"""Serve the existing React dist and proxy Control API/SSE on one origin for local QA."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import http.client
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / "frontend/dist"
BACKEND = urlsplit(os.getenv("ASTRALIVE_BASE_URL", "http://127.0.0.1:18080"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.startswith(("/api/", "/health/")):
            return self.proxy()
        if not (ROOT / self.path.lstrip("/")).exists():
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        return self.proxy()

    def do_PUT(self):
        return self.proxy()

    def do_DELETE(self):
        return self.proxy()

    def proxy(self):
        conn = http.client.HTTPConnection(BACKEND.hostname, BACKEND.port, timeout=60)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection", "content-length"}}
        if body:
            headers["Content-Length"] = str(len(body))
        conn.request(self.command, self.path, body=body, headers=headers)
        response = conn.getresponse()
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                self.send_header(key, value)
        self.end_headers()
        try:
            while chunk := response.read1(4096):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("FRONTEND_PORT", "18081"))), Handler).serve_forever()
