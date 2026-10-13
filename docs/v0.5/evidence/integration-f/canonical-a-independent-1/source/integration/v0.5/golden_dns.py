#!/usr/bin/env python3
"""Opt-in owned DNS wire relay for the real Golden process only.

Queries use actual authenticated HTTPS Cloudflare DNS responses. No invented
addresses, provider substitution, OS DNS changes or relaxed Go SSRF rules.
"""
import argparse
import json
from pathlib import Path
import socketserver
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            wire, socket = self.request
            try:
                request = urllib.request.Request(
                    "https://cloudflare-dns.com/dns-query", data=wire,
                    headers={"Content-Type": "application/dns-message", "Accept": "application/dns-message"})
                with client.open(request, timeout=8) as response:
                    actual = response.read(65536)
                    if (response.status != 200 or response.geturl() != "https://cloudflare-dns.com/dns-query"
                            or response.headers.get_content_type() != "application/dns-message"
                            or len(actual) < 12 or len(actual) > 65535 or actual[:2] != wire[:2]):
                        raise ValueError("invalid real DNS response")
                socket.sendto(actual, self.client_address)
            except Exception:
                # Preserve failure rather than synthesizing successful answers.
                print("real DNS relay request failed", flush=True)

    with socketserver.ThreadingUDPServer(("127.0.0.1", 0), Relay) as server:
        server.daemon_threads = True
        args.ready_file.write_text(json.dumps({"address": f"127.0.0.1:{server.server_address[1]}",
            "upstream": "https://cloudflare-dns.com/dns-query", "scope": "OWNED_REAL_GOLDEN_PROCESS_ONLY"})+"\n")
        server.serve_forever()


if __name__ == "__main__":
    main()
