"""Guardian owns the publishing socket and controls RTMP terminal teardown.

FFmpeg closes its muxer to flush the final interleaved A/V packets. Forwarding
FCUnpublish/deleteStream immediately lets the server discard queued tail media.
This transparent chunk relay withholds ONLY those terminal commands, keeps the
real server socket open until trusted full-range decode, then closes it. It adds
no media, timestamp offset, silence, fixed delay, reconnect or Worker behavior.
"""

import asyncio

from .model import Closed


class PublishingSocket:
    def __init__(self, check, host, port):
        self.check, self.host, self.port = check, host, port
        self.listener = None
        self.tasks, self.writers = set(), set()
        self.closed = asyncio.Event()
        self.accepted = False

    async def start(self):
        self.listener = await asyncio.start_server(self.accept, "127.0.0.1", 0)
        return self.listener.sockets[0].getsockname()[1]

    async def accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        server = relay = None
        terminal = False
        try:
            self.check()
            if self.accepted:
                raise Closed()
            self.accepted = True
            remote, server = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), 0.2
            )
            self.writers.add(server)

            async def back():
                while True:
                    data = await remote.read(65536)
                    if not data:
                        return
                    writer.write(data)
                    await writer.drain()

            relay = asyncio.create_task(back())
            handshake = await reader.readexactly(1537)
            if handshake[0] != 3:
                raise Closed()
            self.check()
            server.write(handshake)
            await server.drain()
            reply = await reader.readexactly(1536)
            self.check()
            server.write(reply)
            await server.drain()
            chunks, chunk_size = {}, 128
            while True:
                basic = await reader.readexactly(1)
                fmt, csid = basic[0] >> 6, basic[0] & 63
                if csid == 0:
                    extra = await reader.readexactly(1)
                    csid, basic = 64 + extra[0], basic + extra
                elif csid == 1:
                    extra = await reader.readexactly(2)
                    csid, basic = 64 + int.from_bytes(extra, "little"), basic + extra
                size = (11, 7, 3, 0)[fmt]
                header = await reader.readexactly(size)
                previous = chunks.get(csid)
                if fmt and previous is None:
                    raise Closed()
                if fmt == 0:
                    current = {
                        "length": int.from_bytes(header[3:6], "big"),
                        "type": header[6],
                        "received": 0,
                        "drop": False,
                        "extended": header[:3] == b"\xff\xff\xff",
                    }
                elif fmt == 1:
                    current = {
                        "length": int.from_bytes(header[3:6], "big"),
                        "type": header[6],
                        "received": 0,
                        "drop": False,
                        "extended": header[:3] == b"\xff\xff\xff",
                    }
                elif fmt == 2:
                    current = previous.copy()
                    current.update(
                        received=0, drop=False, extended=header == b"\xff\xff\xff"
                    )
                else:
                    current = previous.copy()
                    if current["received"] == current["length"]:
                        current.update(received=0, drop=False)
                if current["length"] > 8 * 1024 * 1024:
                    raise Closed()
                extended = await reader.readexactly(4) if current["extended"] else b""
                count = min(chunk_size, current["length"] - current["received"])
                payload = await reader.readexactly(count)
                first = current["received"] == 0
                if first and current["type"] in {17, 20}:
                    command = payload[1:] if current["type"] == 17 else payload
                    if len(command) < 3 or command[0] != 2:
                        raise Closed()
                    length = int.from_bytes(command[1:3], "big")
                    if len(command) < 3 + length:
                        raise Closed()  # Unproven terminal framing is closed.
                    name = command[3 : 3 + length]
                    current["drop"] = name in {
                        b"FCUnpublish",
                        b"deleteStream",
                        b"closeStream",
                    }
                    terminal |= current["drop"]
                if terminal and not current["drop"] and current["type"] > 6:
                    # No media or fresh stream commands after terminal flush.
                    raise Closed()
                current["received"] += count
                chunks[csid] = current
                if current["type"] == 1 and first:
                    if current["length"] != 4 or len(payload) != 4:
                        raise Closed()
                    chunk_size = int.from_bytes(payload, "big")
                    if not 128 <= chunk_size <= 65536:
                        raise Closed()
                self.check()  # Final socket handoff, independently of SQL/Runtime.
                if not current["drop"]:
                    server.write(basic + header + extended + payload)
                    await asyncio.wait_for(server.drain(), 0.1)
        except asyncio.IncompleteReadError:
            if terminal and not self.closed.is_set():
                # Event driven trusted drain barrier, bounded by local Permit.
                await self.closed.wait()
        except (Exception, asyncio.CancelledError):
            pass  # Caller has no authority to interpret EOF as a fence proof.
        finally:
            if relay:
                relay.cancel()
                await asyncio.gather(relay, return_exceptions=True)
            for stream in (writer, server):
                if stream:
                    stream.close()
                    self.writers.discard(stream)
            self.tasks.discard(task)

    async def close(self):
        self.closed.set()
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()
        for writer in tuple(self.writers):
            writer.close()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
