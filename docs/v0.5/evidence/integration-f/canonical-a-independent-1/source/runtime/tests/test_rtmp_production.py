import asyncio
import json
import os
import unittest
from unittest.mock import patch

from app.config import RTMPSettings
from app.drop_rate import DropRateMonitor
from app.rtmp_media import FFmpegRTMPMediaOutput
from app.rtmp_preflight import preflight
from app.media_fanout import FanoutMediaOutput
from app.providers import VideoFrame


class ProductionSettingsTests(unittest.TestCase):
    def test_full_url_preserved_and_redacted(self):
        s = RTMPSettings(enabled=True, publish_url='rtmps://example.invalid:443/live/key%2Fpart?token=query-secret&sign=signature')
        self.assertEqual(s.target, s.publish_url)
        self.assertEqual(s.parsed_target.hostname, 'example.invalid')
        redacted = s.redact(s.target + ' key/part query-secret signature')
        for secret in (s.target, 'key/part', 'query-secret', 'signature'):
            self.assertNotIn(secret, redacted)
            self.assertNotIn(secret, repr(s))
        self.assertEqual(s.redacted_target, 'rtmps://example.invalid:443/***')

    def test_invalid_targets_never_echo_credentials(self):
        for target in ('https://host/live/private-key', 'rtmp://user:private-key@host/live',
                       'rtmp:///private-key', 'rtmp://host:private-key/live',
                       'rtmp://host/live/private-key#fragment', 'rtmp://host/live/private-key\n',
                       'rtmp://host/', 'rtmp://host:0/live/private-key'):
            with self.subTest(target=target), self.assertRaises(ValueError) as cm:
                RTMPSettings(enabled=True, publish_url=target)
            self.assertNotIn('private-key', str(cm.exception))
        with self.assertRaises(ValueError):
            RTMPSettings(enabled=True, publish_url='rtmp://host/live/key', url='rtmp://host/live', stream_key='key')

    def test_pair_url_query_rejected(self):
        with self.assertRaises(ValueError):
            RTMPSettings(enabled=True, url='rtmp://host/live?token=secret', stream_key='key')

    def test_generic_defaults_and_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            s = RTMPSettings.from_env()
            self.assertEqual((s.platform, s.width, s.height, s.fps, s.audio_sample_rate, s.gop_frames),
                             ('generic', 720, 1280, 25, 48000, 50))
        with patch.dict(os.environ, {'RTMP_FPS': '30', 'RTMP_VIDEO_BITRATE':'4000k', 'RTMP_GOP':'60'}, clear=True):
            s = RTMPSettings.from_env()
            self.assertEqual((s.fps, s.video_bitrate, s.gop_frames), (30, '4000k', 60))
        with patch.dict(os.environ, {'RTMP_PLATFORM':'douyin'}, clear=True):
            with self.assertRaises(ValueError): RTMPSettings.from_env()

    def test_codec_settings_rejected(self):
        for fields in ({'width':719}, {'height':0}, {'fps':0}, {'gop':0},
                       {'audio_sample_rate':12345}, {'preset':'invented'}, {'video_bitrate':'3M -foo'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                RTMPSettings(**fields)

    def test_command_keeps_accepted_codecs_and_explicit_gop(self):
        s = RTMPSettings(enabled=True, url='rtmp://localhost/live', stream_key='fake', gop=60)
        command = FFmpegRTMPMediaOutput(s)._command(3,4)
        for flag,value in (('-c:v','libx264'),('-pix_fmt','yuv420p'),('-c:a','aac'),('-g','60')):
            self.assertIn([flag,value], [command[i:i+2] for i in range(len(command)-1)])
        self.assertEqual(command[-1],s.target)

    def test_diagnostics_defense_in_depth(self):
        s = RTMPSettings(enabled=True, publish_url='rtmp://host/live/key-secret?token=query-secret')
        output = FFmpegRTMPMediaOutput(s)
        output.stderr_lines.append(s.target+' key-secret query-secret')
        diagnostic = output.diagnostics()
        text = json.dumps(diagnostic)
        self.assertNotIn('key-secret', text)
        self.assertNotIn('query-secret', text)
        for name in ('enabled','running','connected','ffmpegPid','processStarts','reconnectCount',
                     'writeFailures','targetFps','resolution','audioQueueMs','videoQueueMs',
                     'audioDropped','videoDropped','lastError'):
            self.assertIn(name, diagnostic)
        self.assertIsNone(diagnostic['connected'])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.s=RTMPSettings(enabled=True, publish_url='rtmps://host/live/fake-secret')

    def run_check(self, resolver=lambda *a,**kw:[object()], publisher=lambda s:False, listing=None):
        with patch('app.rtmp_preflight.shutil.which', return_value='/usr/bin/ffmpeg'), \
             patch('app.rtmp_preflight._ffmpeg_listing', side_effect=listing or (lambda b,f: {
                '-encoders':'libx264 aac', '-pix_fmts':'yuv420p', '-muxers':'flv',
                '-protocols':'Input:\nrtmps\nOutput:\nrtmp\nrtmps'}[f])):
            return preflight(self.s, resolver=resolver, publisher_check=publisher)

    def test_success_without_publishing(self):
        result=self.run_check()
        self.assertTrue(result['ok'])
        self.assertFalse(result['publishes'])
        self.assertFalse(result['connectionVerified'])
        self.assertNotIn('fake-secret', json.dumps(result))

    def test_dns_failure_and_existing_publisher_block(self):
        def fail(*a,**kw): raise OSError('fake-secret')
        result=self.run_check(resolver=fail, publisher=lambda s:True)
        self.assertFalse(result['ok'])
        self.assertFalse(result['checks']['dnsResolved'])
        self.assertFalse(result['checks']['noExistingPublisher'])
        self.assertNotIn('fake-secret', json.dumps(result))

    def test_rtmps_input_support_is_not_output_support(self):
        result=self.run_check(listing=lambda b,f: 'Input:\nrtmps\nOutput:\nrtmp' if f=='-protocols' else 'libx264 aac yuv420p flv')
        self.assertFalse(result['checks']['outputProtocolAvailable'])

    def test_incomplete_inspection_fails_closed(self):
        def fail(s): raise PermissionError('fake-secret')
        self.assertFalse(self.run_check(publisher=fail)['checks']['noExistingPublisher'])


class DropRateTests(unittest.TestCase):
    def test_sustained_threshold_cooldown_and_recovery(self):
        now=[0.0]
        monitor=DropRateMonitor(clock=lambda:now[0])
        def window(drops):
            for i in range(100):
                monitor.offer()
                if i < drops: monitor.drop()
            now[0]+=10
            return monitor.offer()
        self.assertIsNone(window(10))  # exactly 10% does not exceed threshold
        self.assertIsNone(window(30))
        self.assertIsNone(window(30))
        warning=window(30)
        self.assertIsNotNone(warning)
        self.assertGreater(warning['drop_rate'],.1)
        self.assertIsNone(window(30))  # cooldown
        self.assertIsNone(window(0))
        self.assertEqual(monitor.high_windows,0)

    def test_idle_and_sparse_windows_do_not_warn(self):
        now=[0.0]; monitor=DropRateMonitor(clock=lambda:now[0])
        for _ in range(10):
            monitor.offer(); monitor.drop(); now[0]+=30
            self.assertIsNone(monitor.offer())
        self.assertEqual(monitor.high_windows,0)


class DropDeliveryRegression(unittest.IsolatedAsyncioTestCase):
    async def test_small_drop_preserves_metric_and_latest_frame_without_warning(self):
        from test_media_fanout import FakeSink
        output=FanoutMediaOutput([('rtmp',FakeSink())])
        channel=output.channels[0]
        for i in range(channel.video.maxsize):
            channel.video.put_nowait(VideoFrame(1,i,2,2,b'\0'*12))
        frame=VideoFrame(1,99,2,2,b'\0'*12)
        output._drop_and_offer(channel,channel.video,frame,'video')
        self.assertEqual(channel.video_dropped,1)
        self.assertEqual(channel.video.qsize(),channel.video.maxsize)
        self.assertIn(frame,list(channel.video._queue))
        self.assertEqual(output.pop_warnings(),[])


class ProductionDiagnosticsRegression(unittest.IsolatedAsyncioTestCase):
    async def test_production_interval_emits_info_and_cleans_up(self):
        from app.main import create_app
        from app.config import Settings
        with patch.dict(os.environ, {'RUNTIME_MEDIA_METRICS_INTERVAL_SECONDS':'0.01'}):
            app = create_app(Settings())
            with self.assertLogs('app', level='INFO') as logs:
                async with app.router.lifespan_context(app):
                    await asyncio.sleep(.025)
            self.assertTrue(any('runtime_media_metrics' in line for line in logs.output))
            self.assertFalse(any('WARNING' in line for line in logs.output))


class ProductionLauncherTests(unittest.TestCase):
    def test_preflight_failure_never_starts_runtime(self):
        from app import production_launcher
        with patch.object(production_launcher.os,'open',return_value=10), \
             patch.object(production_launcher.os,'close') as close, \
             patch.object(production_launcher.fcntl,'flock'), \
             patch.object(production_launcher,'preflight_main',return_value=1), \
             patch.object(production_launcher.os,'execv') as launch:
            self.assertEqual(production_launcher.main(),1)
            launch.assert_not_called()
            close.assert_called_once_with(10)

    def test_second_publisher_is_blocked(self):
        from app import production_launcher
        with patch.object(production_launcher.os,'open',return_value=10), \
             patch.object(production_launcher.os,'close'), \
             patch.object(production_launcher.fcntl,'flock',side_effect=BlockingIOError), \
             patch.object(production_launcher,'preflight_main') as preflight_check, \
             patch.object(production_launcher.os,'execv') as launch:
            self.assertEqual(production_launcher.main(),1)
            preflight_check.assert_not_called()
            launch.assert_not_called()
