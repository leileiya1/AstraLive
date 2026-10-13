"""Test-only HTTP forwarding proxy. Records request/response metadata without credentials."""
import argparse
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request


def serve(listen, upstream, evidence):
    target = upstream.rstrip('/')
    output = Path(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def forward(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection', 'content-length')}
            req = urllib.request.Request(target + self.path, body if self.command != 'GET' else None, headers, method=self.command)
            fault_file = os.getenv('ASTRALIVE_FAULT_FILE')
            fault = json.loads(Path(fault_file).read_text()) if fault_file and Path(fault_file).exists() else {}
            if fault and self.path.startswith(fault.get('path', '#')):
                mode = fault['mode']
                if mode == 'timeout':
                    time.sleep(32)
                status = 500 if mode == '500' else 503
                result = json.dumps({'code': 'INTERNAL_ERROR' if mode == '500' else 'RUNTIME_UNAVAILABLE',
                                     'message': 'injected integration fault', 'details': {}}).encode()
                response_headers = {}
            else:
                try:
                    with urllib.request.urlopen(req, timeout=40) as response:
                        status, result, response_headers = response.status, response.read(), response.headers
                except urllib.error.HTTPError as exc:
                    status, result, response_headers = exc.code, exc.read(), exc.headers
                except Exception as exc:
                    status, result, response_headers = 503, json.dumps({'code': 'RUNTIME_UNAVAILABLE', 'message': str(exc)}).encode(), {}
            record = {'at': datetime.now(timezone.utc).isoformat(), 'method': self.command,
                      'path': self.path, 'status': status}
            if body:
                try:
                    record['request'] = json.loads(body)
                except ValueError:
                    record['requestBytes'] = len(body)
            if '/tools/products/' in self.path:
                try:
                    record['response'] = json.loads(result)
                except ValueError:
                    pass
            with lock, output.open('a') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
            self.send_response(status)
            self.send_header('Content-Type', response_headers.get('Content-Type', 'application/json'))
            self.send_header('Content-Length', str(len(result)))
            self.end_headers()
            self.wfile.write(result)

        do_GET = do_POST = do_PUT = do_DELETE = forward

        def log_message(self, *_):
            pass

    ThreadingHTTPServer(('127.0.0.1', listen), Handler).serve_forever()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--listen', type=int, required=True)
    p.add_argument('--upstream', required=True)
    p.add_argument('--evidence', required=True)
    args = p.parse_args()
    serve(args.listen, args.upstream, args.evidence)
