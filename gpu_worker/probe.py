"""Authenticated loopback health probe; no SSH or shell execution."""
import json
from urllib.request import Request, urlopen
from .config import secret


def probe(cfg, path='/readyz'):
    request = Request(f'http://127.0.0.1:{cfg.management_port}{path}', headers={'Authorization': 'Bearer ' + secret(cfg.management_token_file)})
    with urlopen(request, timeout=2) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('oversized health response')
    return json.loads(raw)
