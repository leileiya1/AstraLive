"""Opt-in test receiver: decoded RTMP frames, bounded evidence, local authenticated clock exchange."""
import argparse
import collections
import hmac
import http.server
import json
from pathlib import Path
import threading
import time


def decode_marker(rgb):
    """Read the existing diagnostic marker after centered square scale/pad."""
    h, w = rgb.shape[:2]
    size = min(h, w)
    x, y = (w-size)//2, (h-size)//2
    def bits(row, count):
        return sum(1 << b for b in range(count) if
                   int(rgb[y+round((row+4)*size/512), x+round((b*8+4)*size/512), 0]) >
                   int(rgb[y+round((row+4)*size/512), x+round((b*8+4)*size/512), 1]))
    return bits(0, 16), bits(16, 16), bits(8, 24)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', required=True)
    p.add_argument('--token-file', required=True)
    p.add_argument('--port', type=int, default=26836)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    import av
    import numpy as np
    origin = time.monotonic()
    token = Path(a.token_file).read_text().strip()
    lock = threading.Lock()
    rows = collections.deque(maxlen=6000)
    counts = dict(audio=0, video=0, nonzeroAudio=0, markedVideo=0)
    errors = []
    def snapshot():
        with lock:
            return dict(clockDomain='receiver_monotonic', clockOriginAgeMs=(time.monotonic()-origin)*1000,
                        rows=list(rows), counts=dict(counts), errors=list(errors))
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path != '/snapshot' or not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token):
                self.send_error(401)
                return
            payload = json.dumps(snapshot()).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    container = None
    for _ in range(60):
        try:
            container = av.open(a.url, timeout=(3, 15))
            break
        except Exception:
            time.sleep(.5)
    if container is None:
        errors.append('NO_RTMP_PUBLISHER')
    else:
        try:
            for packet in container.demux():
                for frame in packet.decode():
                    at = (time.monotonic()-origin)*1000
                    pts = float(frame.pts*frame.time_base) if frame.pts is not None else None
                    if isinstance(frame, av.AudioFrame):
                        array = frame.to_ndarray().astype(np.float32)
                        if frame.format.is_planar and frame.format.name.startswith('fl'):
                            peak = float(np.max(np.abs(array)))
                        else:
                            peak = float(np.max(np.abs(array)))/32768
                        row = dict(kind='audio', at=at, pts=pts, peak=peak)
                        with lock:
                            counts['audio'] += 1
                            if peak > .003:
                                counts['nonzeroAudio'] += 1
                                rows.append(row)
                    elif isinstance(frame, av.VideoFrame):
                        rgb = frame.to_ndarray(format='rgb24')
                        # Accepted sink scales/pads a 512-square source centrally.
                        marker, generation, sequence = decode_marker(rgb)
                        with lock:
                            counts['video'] += 1
                            if 0 < marker < 8192:
                                counts['markedVideo'] += 1
                                rows.append(dict(kind='video', at=at, pts=pts, marker=marker, generation=generation,sequence=sequence))
                    if time.monotonic()-origin > 600:
                        raise TimeoutError
        except Exception as exc:
            errors.append('RECEIVER_ENDED_'+type(exc).__name__)
        finally:
            container.close()
    Path(a.output).write_text(json.dumps(snapshot(), indent=2)+'\n')
    # Keep the final observation queryable briefly after normal Session Stop.
    time.sleep(5)
    server.shutdown()


if __name__ == '__main__':
    main()
