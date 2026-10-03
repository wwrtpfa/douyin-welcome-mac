import asyncio
from pathlib import Path
import pytest
from welcome_assistant.config import DEFAULTS, room_url, validate
from welcome_assistant.engine import Engine, clean_name
from welcome_assistant.protocol import Arrival


class FakeVoice:
    def __init__(self, tmp_path):
        self.file = tmp_path / "audio.wav"
        self.texts = []
        self.played = []
        self.stopped = False
        self.block = False
        self.started = asyncio.Event()

    async def synthesize(self, text, settings):
        self.texts.append(text)
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        self.file.touch()
        return self.file

    async def play(self, path, settings):
        self.played.append(path)

    async def stop(self):
        self.stopped = True


def make(tmp_path, **settings):
    events = []
    clock = [100.0]
    voice = FakeVoice(tmp_path)
    engine = Engine(DEFAULTS | {"interval": 0} | settings, voice, lambda t, **v: events.append((t, v)), lambda: clock[0])
    return engine, voice, events, clock


def test_dedup_by_id_not_nickname(tmp_path):
    engine, _, _, clock = make(tmp_path)
    assert engine.add(Arrival("1", "小明", "a"))
    assert not engine.add(Arrival("1", "改名字", "b"))
    assert engine.add(Arrival("2", "小明", "c"))
    assert not engine.add(Arrival("3", "另一个", "a"))
    clock[0] += 601
    assert engine.add(Arrival("1", "小明", "d"))


def test_queue_bounded_and_sanitized(tmp_path):
    engine, _, _, _ = make(tmp_path, max_queue=2)
    for i in range(4):
        engine.add(Arrival(str(i), "小明🌟123456789"))
    assert len(engine.queue) == 2
    assert engine.skipped == 2
    assert engine.queue[0].name == "小明"
    assert clean_name("🔥🔥") == ""
    assert clean_name("广告用户", "广告,禁止") == ""
    assert clean_name("小明https://evil.test") == "小明"


async def test_merge_and_audio_cleanup(tmp_path):
    engine, voice, _, _ = make(tmp_path)
    for i, name in enumerate(["小明", "小红", "小李"]):
        engine.add(Arrival(str(i), name))
    engine.start()
    await asyncio.sleep(.05)
    assert voice.texts == ["欢迎小明、小红、小李，欢迎来到直播间！"]
    assert engine.spoken == 3
    assert not voice.file.exists()
    await engine.close()


async def test_expired_never_synthesized(tmp_path):
    engine, voice, _, clock = make(tmp_path)
    engine.add(Arrival("1", "小明"))
    clock[0] += 31
    engine.start()
    await asyncio.sleep(.02)
    assert not voice.texts
    assert engine.skipped == 1
    await engine.close()


async def test_stop_cancels_generation_and_resumes(tmp_path):
    engine, voice, _, _ = make(tmp_path)
    voice.block = True
    engine.start()
    engine.add(Arrival("1", "小明"))
    await asyncio.wait_for(voice.started.wait(), 1)
    await engine.stop()
    assert voice.stopped and engine.paused
    assert not engine.add(Arrival("2", "小红"))
    voice.block = False
    engine.resume()
    engine.add(Arrival("3", "小李"))
    await asyncio.sleep(.05)
    assert engine.spoken == 1
    await engine.close()


async def test_arrival_does_not_hide_synthesis_state(tmp_path):
    engine, voice, events, _ = make(tmp_path)
    voice.block = True
    engine.start()
    engine.add(Arrival("1", "小明"))
    await asyncio.wait_for(voice.started.wait(), 1)
    engine.add(Arrival("2", "小红"))
    assert events[-1][1]["phase"] == "synthesizing"
    await engine.close()


@pytest.mark.parametrize("url", ["https://evil.test/12345", "file:///etc/passwd", "https://live.douyin.com.evil.test/12345", "https://live.douyin.com@evil.test/12345", "https://live.douyin.com:9999/12345"])
def test_only_douyin_rooms(url):
    with pytest.raises(ValueError):
        room_url(url)


def test_settings_validation():
    assert room_url("123456789") == "https://live.douyin.com/123456789"
    with pytest.raises(ValueError):
        validate({"template": "没有昵称变量"})
    with pytest.raises(ValueError):
        validate({"volume": float("nan")})
