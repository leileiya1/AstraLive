"""Opt-in, short Linux localhost smoke; no real platform or secrets."""
import asyncio
import json
from pathlib import Path
import socket
import tempfile

from app.config import RTMPSettings
from app.providers import AudioChunk, VideoFrame
from app.rtmp_media import FFmpegRTMPMediaOutput
from app.rtmp_preflight import preflight


async def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    settings = RTMPSettings(enabled=True, publish_url=f'rtmp://127.0.0.1:{port}/live/fake-smoke')
    # Run before listener; fake ingest credentials only, no publish in preflight.
    result = preflight(settings)
    assert result['ok'], result
    output = FFmpegRTMPMediaOutput(settings)
    with tempfile.TemporaryDirectory(prefix='astralive-hardening-smoke-') as directory:
        capture = Path(directory) / 'capture.flv'
        receiver = await asyncio.create_subprocess_exec('ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-listen', '1', '-i', settings.target, '-c', 'copy', '-y', str(capture),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            await asyncio.sleep(.5)
            await output.start()
            await output.push_audio(AudioChunk(1, 0, b'\0\0' * 16000, 16000, 1))
            await output.push_video(VideoFrame(1, 0, 8, 8, bytes([60,120,180])*64))
            await output.drain(1)
            await asyncio.sleep(4)
            before = output.diagnostics()
            await output.interrupt(2)
            await asyncio.sleep(.2)
            assert output.diagnostics()['ffmpegPid'] == before['ffmpegPid']
            await output.stop()
            await asyncio.wait_for(receiver.communicate(), 10)
            probe = await asyncio.create_subprocess_exec('ffprobe', '-v','error','-show_streams',
                '-of','json', str(capture), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            raw, error = await asyncio.wait_for(probe.communicate(), 10)
            assert probe.returncode == 0, error
            streams = {s['codec_type']:s for s in json.loads(raw)['streams']}
            v,a=streams['video'],streams['audio']
            assert (v['codec_name'],v['pix_fmt'],v['width'],v['height'],v['avg_frame_rate']) == ('h264','yuv420p',720,1280,'25/1')
            assert (a['codec_name'],a['sample_rate'],a['channels']) == ('aac','48000',2)
            assert before['processStarts'] == 1 and before['writeFailures'] == 0 and before['reconnectCount'] == 0
            assert output._process.returncode == 0
            print(json.dumps({'ok':True, 'preflight':result, 'video':'h264/yuv420p 720x1280 25/1',
                'audio':'aac 48000 stereo','normalStop':True,'interruptPidStable':True,
                'processStarts':before['processStarts'],'reconnectCount':before['reconnectCount'],
                'writeFailures':before['writeFailures'],'realPlatformConnected':False}))
        finally:
            await output.stop()
            if receiver.returncode is None:
                receiver.terminate()
                await receiver.communicate()


if __name__ == '__main__':
    asyncio.run(main())
