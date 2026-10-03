import asyncio
import contextlib
import json
import os
import signal
import sys
import uuid

from . import config


def emit(event, **data):
    print(json.dumps({"type": event, **data}, ensure_ascii=False), flush=True)


async def serve():
    from .collector import Collector
    from .engine import Engine
    from .protocol import Arrival
    from .voice import Voice
    settings = config.load()
    voice = Voice(emit)
    engine = Engine(settings, voice, emit)
    collector = Collector(emit, engine.add)
    engine.start()
    stopped = asyncio.Event()
    task = None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)

    def devices():
        try:
            emit("devices", devices=voice.devices())
        except Exception as error:
            emit("log", level="error", message="音频设备读取失败：" + str(error))

    async def connect(room):
        try:
            engine.seen.clear()
            engine.events.clear()
            await collector.connect(room)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            emit("log", level="error", message="连接失败：" + str(error)[:400])

    reader = asyncio.StreamReader(limit=256 * 1024)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    emit("ready", settings=settings)
    devices()
    engine.status()
    line_task = asyncio.create_task(reader.readline())
    stop_task = asyncio.create_task(stopped.wait())
    try:
        while not stopped.is_set():
            done, _ = await asyncio.wait([line_task, stop_task], return_when=asyncio.FIRST_COMPLETED)
            if stop_task in done:
                break
            line = line_task.result()
            if not line:
                break
            line_task = asyncio.create_task(reader.readline())
            try:
                message = json.loads(line)
                command = message.get("command")
                if command == "save":
                    new_settings = config.validate(message["settings"])
                    config.save(new_settings)
                    settings.clear()
                    settings.update(new_settings)
                    emit("saved")
                elif command == "connect":
                    config.room_url(settings["room"])
                    if task:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                    await engine.stop(pause=False)
                    task = asyncio.create_task(connect(settings["room"]))
                elif command == "disconnect":
                    if task:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                        task = None
                    await collector.close()
                    await engine.stop(pause=False)
                elif command == "preview":
                    if engine.paused:
                        raise ValueError("播报已暂停，请先恢复播报")
                    engine.add(Arrival("preview-" + uuid.uuid4().hex, message.get("name", "新朋友")), preview=True)
                elif command == "simulate":
                    engine.add(Arrival("simulation-" + message.get("name", "新朋友"), message.get("name", "新朋友")))
                elif command == "stop":
                    await engine.stop()
                elif command == "resume":
                    engine.resume()
                elif command == "devices":
                    devices()
                elif command == "shutdown":
                    break
                else:
                    raise ValueError("未知命令")
            except Exception as error:
                emit("log", level="error", message=str(error))
    finally:
        line_task.cancel()
        stop_task.cancel()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await collector.close()
        await engine.close()
        transport.close()
        for path in (config.APP_DIR / "audio-cache").glob("*.wav"):
            path.unlink(missing_ok=True)
        emit("stopped")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "voice-worker":
        from .voice_worker import run
        run()
    else:
        # Own only our descendants, allowing bounded cleanup when the UI quits.
        with contextlib.suppress(OSError):
            os.setsid()
        asyncio.run(serve())
