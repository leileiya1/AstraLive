"""Non-publishing preflight. Never put targets in subprocess args or output."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

from .config import RTMPSettings


def existing_publishers(settings):
    """Check visible FFmpeg processes for RTMP output. No argv is returned.

    Fail closed on unreadable cmdline; hidepid still restricts visibility.
    Deployment must additionally use a single publisher user and service lock.
    """
    proc = Path('/proc')
    if not proc.is_dir():
        raise RuntimeError('Publisher inspection requires Linux procfs')
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:
            continue
        except PermissionError:
            raise RuntimeError('Publisher inspection incomplete') from None
        if args and Path(os.fsdecode(args[0])).name == Path(settings.ffmpeg_binary).name:
            if any(arg.startswith((b'rtmp://', b'rtmps://')) for arg in args[1:]):
                return True
    return False


def _ffmpeg_listing(binary, flag):
    result = subprocess.run([binary, '-hide_banner', flag], capture_output=True,
                            text=True, timeout=10, check=True)
    return result.stdout + result.stderr


def preflight(settings, resolver=socket.getaddrinfo, publisher_check=existing_publishers):
    checks = {}
    def check(name, operation):
        try:
            checks[name] = bool(operation())
        except Exception:
            # DNS/library/FFmpeg exceptions may include supplied credentials.
            checks[name] = False
    check('enabled', lambda: settings.enabled)
    check('targetConfigured', lambda: bool(settings.publish_url or (settings.url and settings.stream_key)))
    check('credentialConfigured', lambda: bool(settings.publish_url or settings.stream_key))
    check('targetValid', lambda: bool(settings.parsed_target))
    check('settingsValid', lambda: settings.__post_init__() is None)
    check('ffmpegAvailable', lambda: shutil.which(settings.ffmpeg_binary) is not None)
    def codecs():
        encoders = _ffmpeg_listing(settings.ffmpeg_binary, '-encoders')
        pixels = _ffmpeg_listing(settings.ffmpeg_binary, '-pix_fmts')
        formats = _ffmpeg_listing(settings.ffmpeg_binary, '-muxers')
        return all(name in encoders.split() for name in ('libx264', 'aac')) and 'yuv420p' in pixels.split() and 'flv' in formats.split()
    check('codecsAvailable', codecs)
    def protocol():
        listing = _ffmpeg_listing(settings.ffmpeg_binary, '-protocols')
        return settings.parsed_target.scheme in listing.split('Output:', 1)[1].split()
    check('outputProtocolAvailable', protocol)
    check('dnsResolved', lambda: bool(resolver(settings.parsed_target.hostname,
          settings.parsed_target.port or (443 if settings.parsed_target.scheme == 'rtmps' else 1935),
          type=socket.SOCK_STREAM)))
    check('secretRedaction', lambda: settings.target not in settings.redact(settings.target)
          and settings.target not in repr(settings))
    check('noExistingPublisher', lambda: not publisher_check(settings))
    return {'ok': all(checks.values()), 'checks': checks,
            'publishes': False, 'connectionVerified': False}


def main():
    try:
        result = preflight(RTMPSettings.from_env())
    except Exception:
        result = {'ok': False, 'checks': {'configuration': False}, 'publishes': False}
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
