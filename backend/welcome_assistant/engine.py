import asyncio
import contextlib
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass

from .protocol import Arrival


def clean_name(value: str, blocked: str = "") -> str:
    name = unicodedata.normalize("NFKC", value)
    words = [w.strip().casefold() for w in re.split(r"[,，\n]", blocked) if w.strip()]
    if any(w in name.casefold() for w in words):
        return ""
    name = re.sub(r"https?://\S+|www\.\S+", "", name, flags=re.I)
    name = re.sub(r"\d{5,}", "", name)
    name = "".join(c for c in name if c.isalnum() or c in " ·_-" )
    name = re.sub(r"\s+", " ", name).strip(" ·_-")[:12]
    return name


@dataclass
class Pending:
    name: str
    arrived: float
    preview: bool = False


class Engine:
    def __init__(self, config, voice, emit, clock=time.monotonic):
        self.config, self.voice, self.emit, self.clock = config, voice, emit, clock
        self.queue = deque()
        self.seen = {}
        self.events = {}
        self.paused = False
        self.active = None
        self.loop = None
        self.wake = asyncio.Event()
        self.next_allowed = 0
        self.received = self.spoken = self.skipped = 0
        self.phase = "idle"
        self.current_text = ""

    def status(self, phase=None, text=None):
        if phase is not None:
            self.phase = phase
        if text is not None:
            self.current_text = text
        self.emit("queue", pending=len(self.queue), paused=self.paused, phase=self.phase, text=self.current_text,
                  received=self.received, spoken=self.spoken, skipped=self.skipped)

    def add(self, arrival: Arrival, preview=False):
        now = self.clock()
        name = clean_name(arrival.nickname, self.config["blocked_words"])
        if not preview:
            self.received += 1
        self.seen = {k: v for k, v in self.seen.items() if now - v < self.config["dedup_seconds"]}
        self.events = {k: v for k, v in self.events.items() if now - v < 600}
        event_key = arrival.event_id if arrival.event_id not in ("", "0") else None
        duplicate = arrival.user_id in self.seen or (event_key and event_key in self.events)
        if not name or self.paused or (duplicate and not preview):
            self.skipped += 1
            self.status()
            return False
        if not preview:
            self.seen[arrival.user_id] = now
            if event_key:
                self.events[event_key] = now
        while len(self.queue) >= self.config["max_queue"]:
            self.queue.popleft()
            self.skipped += 1
        self.queue.append(Pending(name, now, preview))
        self.emit("arrival", nickname=name, preview=preview)
        self.status()
        self.wake.set()
        return True

    def start(self):
        self.loop = asyncio.create_task(self._run())

    async def _run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while self.queue and not self.paused:
                if self.clock() < self.next_allowed:
                    await asyncio.sleep(min(0.1, self.next_allowed - self.clock()))
                    continue
                batch = []
                while self.queue and len(batch) < 3:
                    item = self.queue.popleft()
                    if self.clock() - item.arrived > self.config["max_age"]:
                        self.skipped += 1
                    else:
                        batch.append(item)
                    if batch and batch[-1].preview:
                        break
                if not batch:
                    self.status()
                    continue
                settings = self.config.copy()
                text = settings["template"].replace("{name}", "、".join(x.name for x in batch))
                self.active = asyncio.create_task(self._speak(text, settings, batch))
                try:
                    await self.active
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    self.active = None
                self.next_allowed = self.clock() + settings["interval"]
                self.status("idle", "")

    async def _speak(self, text, settings, batch):
        output = None
        try:
            self.status("synthesizing", text)
            output = await self.voice.synthesize(text, settings)
            # Do not play stale welcomes after a long first-time model download.
            if not any(x.preview for x in batch) and self.clock() - max(x.arrived for x in batch) > settings["max_age"]:
                self.skipped += len(batch)
                self.emit("log", level="warning", message="合成完成时欢迎语已过期，已跳过。建议开播前先试听预热模型。")
                return
            self.status("playing", text)
            await self.voice.play(output, settings)
            self.spoken += len(batch)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.emit("log", level="error", message=str(error))
            await self.voice.stop()
        finally:
            if output:
                output.unlink(missing_ok=True)

    async def stop(self, pause=True):
        self.paused = pause
        self.queue.clear()
        if self.active:
            self.active.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.active
        await self.voice.stop()
        self.next_allowed = 0
        self.status("idle", "")

    def resume(self):
        self.paused = False
        self.status()
        self.wake.set()

    async def close(self):
        await self.stop()
        if self.loop:
            self.loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.loop
