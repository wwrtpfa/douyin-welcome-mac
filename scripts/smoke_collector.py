"""Local WebSocket fixture: real Chrome -> parser -> queue -> graceful close.

No Douyin account or real live room is used. Run with PYTHONPATH=backend .venv/bin/python scripts/smoke_collector.py.
"""
import asyncio
import base64
import gzip
import hashlib
import os
import struct
import tempfile
from pathlib import Path


def vi(n):
    data = bytearray()
    while n > 127:
        data.append((n & 127) | 128)
        n >>= 7
    data.append(n)
    return bytes(data)


def field(k, v):
    if isinstance(v, int):
        return vi(k << 3) + vi(v)
    if isinstance(v, str):
        v = v.encode()
    return vi(k << 3 | 2) + vi(len(v)) + v


async def main():
    with tempfile.TemporaryDirectory(prefix="welcome-smoke-") as temp:
        os.environ["WELCOME_DATA_DIR"] = temp
        import welcome_assistant.collector as module
        from welcome_assistant.config import DEFAULTS
        from welcome_assistant.engine import Engine
        done = asyncio.Event()
        seen = []

        class Voice:
            async def synthesize(self, text, settings):
                seen.append(text)
                target = Path(temp) / "fake.wav"
                target.touch()
                return target

            async def play(self, path, settings):
                done.set()

            async def stop(self):
                pass

        def emit(event, **data):
            if event in ("connection", "log"):
                print(event, data, flush=True)

        engine = Engine(DEFAULTS | {"interval": 0}, Voice(), emit)
        collector = module.Collector(emit, engine.add)
        member = field(2, field(1, 123) + field(3, "联调用户"))
        message = field(1, "WebcastMemberMessage") + field(2, member) + field(3, 567)
        packet = field(8, gzip.compress(field(1, message)))
        writers = set()

        async def handle(reader, writer):
            writers.add(writer)
            try:
                request = (await reader.readuntil(b"\r\n\r\n")).decode()
                if "Upgrade: websocket" in request or "upgrade: websocket" in request:
                    headers = dict(line.split(": ", 1) for line in request.split("\r\n")[1:] if ": " in line)
                    key = next(v for k, v in headers.items() if k.lower() == "sec-websocket-key")
                    accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                    writer.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode())
                    await writer.drain()
                    await asyncio.sleep(.3)
                    header = bytes([130, len(packet)]) if len(packet) < 126 else bytes([130, 126]) + struct.pack("!H", len(packet))
                    writer.write(header + packet)
                    await writer.drain()
                    await reader.read()
                else:
                    html = b'<script>new WebSocket("ws://"+location.host+"/webcast/fixture")</script>'
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: " + str(len(html)).encode() + b"\r\nConnection: close\r\n\r\n" + html)
                    await writer.drain()
            finally:
                writer.close()
                writers.discard(writer)

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        # Only the test replaces validation; production restricts live.douyin.com.
        module.room_url = lambda _: f"http://127.0.0.1:{port}/"
        engine.start()
        try:
            await collector.connect("fixture")
            await asyncio.wait_for(done.wait(), 20)
            assert seen == ["欢迎联调用户，欢迎来到直播间！"], seen
            print("PASS: real Chrome WebSocket frame -> welcome queue", flush=True)
        finally:
            await collector.close()
            await engine.close()
            server.close()
            await server.wait_closed()
            for writer in list(writers):
                writer.close()
                await writer.wait_closed()
        print("PASS: collector browser and server closed", flush=True)


asyncio.run(main())
