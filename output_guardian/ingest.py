"""Trusted dedicated MediaMTX control plane; no Runtime close assertions."""

import asyncio
import base64
from urllib.parse import urlsplit

import aiohttp

from .model import Closed


class Ingest:
    def __init__(self, api_url, path):
        parsed = urlsplit(api_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("dedicated loopback ingest API required")
        self.url, self.path = api_url.rstrip("/"), path
        self.client = None
        self.api_secret = None

    async def start(self):
        if not self.api_secret:
            raise Closed()
        self.client = aiohttp.ClientSession(
            headers={
                "Authorization": "Basic "
                + base64.b64encode(
                    ("guardian-api:" + self.api_secret).encode()
                ).decode()
            },
            timeout=aiohttp.ClientTimeout(total=0.3),
            trust_env=False,
        )

    async def request(self, method, path):
        try:
            async with self.client.request(method, self.url + path) as response:
                if response.status == 404 and method == "POST":
                    return None
                if response.status != 200:
                    raise Closed()
                return await response.json() if method == "GET" else None
        except Exception:
            raise Closed() from None

    async def publishers(self):
        # Enumerate all pages. A huge/unbounded list cannot establish a barrier.
        items = []
        for page in range(100):
            data = await self.request(
                "GET", f"/v3/rtmpconns/list?page={page}&itemsPerPage=100"
            )
            items.extend(
                c
                for c in data["items"]
                if c.get("state") == "publish" and c.get("path") == self.path
            )
            if page + 1 >= data["pageCount"]:
                return items
        raise Closed()

    async def ready(self):
        state = await self.request("GET", "/v3/paths/get/" + self.path)
        return state.get("ready") is True

    async def isolate(self):
        # Caller first disables HTTP auth and kills its encoder. This also
        # revokes retained FFmpeg processes: old secrets can never reconnect.
        for connection in await self.publishers():
            await self.request("POST", "/v3/rtmpconns/kick/" + connection["id"])
        for _ in range(30):
            if not await self.publishers():
                return
            await asyncio.sleep(0.01)
        raise Closed()

    async def exclusive(self, expected_id):
        publishers = await self.publishers()
        if len(publishers) != 1 or publishers[0]["id"] != expected_id:
            raise Closed()

    async def close(self):
        if self.client:
            await self.client.close()
