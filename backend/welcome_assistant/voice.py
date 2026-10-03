import asyncio
import contextlib
import json
import os
import sys
import uuid
from pathlib import Path

from .config import APP_DIR


class Voice:
    def __init__(self, emit):
        self.emit = emit
        self.worker = None
        self.say = None
        self.stderr_task = None
        self.audio_active = False

    @staticmethod
    def devices():
        import sounddevice as sd
        return [{"name": d["name"], "id": str(i)} for i, d in enumerate(sd.query_devices()) if d["max_output_channels"] > 0]

    async def _errors(self, stream):
        # MLX/progress diagnostics never go to the JSON transport or expose user text.
        while await stream.readline():
            pass

    async def synthesize(self, text, settings):
        directory = APP_DIR / "audio-cache"
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / (uuid.uuid4().hex + ".wav")
        try:
            if settings["mode"] == "system":
                self.say = await asyncio.create_subprocess_exec(
                    "/usr/bin/say", "-v", "Tingting", "-o", str(output), "--file-format=WAVE", "--data-format=LEI16@24000", text,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                )
                _, error = await self.say.communicate()
                if self.say.returncode:
                    raise ValueError("系统声音生成失败：" + error.decode(errors="replace")[:200])
                self.say = None
            else:
                reference = Path(settings["reference_audio"])
                if not reference.is_file() or not settings["reference_text"].strip():
                    raise ValueError("请先导入自己的 WAV 录音，并填写与录音一致的文字")
                if not self.worker or self.worker.returncode is not None:
                    self.worker = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "welcome_assistant", "voice-worker",
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE, env=os.environ.copy(),
                    )
                    self.stderr_task = asyncio.create_task(self._errors(self.worker.stderr))
                request = {**settings, "text": text, "output": str(output)}
                self.worker.stdin.write((json.dumps(request) + "\n").encode())
                await self.worker.stdin.drain()
                while True:
                    line = await asyncio.wait_for(self.worker.stdout.readline(), timeout=900)
                    if not line:
                        raise ValueError("声音模型进程意外退出，请检查可用内存并重试")
                    result = json.loads(line)
                    if result["type"] == "progress":
                        self.emit("log", level="info", message=result["message"])
                    elif result["type"] == "error":
                        raise ValueError(result["message"])
                    elif result["type"] == "result":
                        break
            return output
        except BaseException:
            output.unlink(missing_ok=True)
            raise

    async def play(self, path, settings):
        import sounddevice as sd
        import soundfile as sf
        audio, rate = sf.read(path, dtype="float32", always_2d=True)
        target = settings["output_device"]
        device = None
        if target:
            matches = [int(d["id"]) for d in self.devices() if d["name"] == target]
            if not matches:
                raise ValueError(f"输出设备已断开：{target}；请重新选择，未自动改用扬声器")
            device = matches[0]
        self.audio_active = True
        try:
            sd.play(audio * settings["volume"], rate, device=device)
            while sd.get_stream().active:
                await asyncio.sleep(0.05)
        finally:
            sd.stop()
            self.audio_active = False

    async def stop(self):
        if self.audio_active:
            import sounddevice as sd
            sd.stop()
        for process in (self.say, self.worker):
            if process and process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=4)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
        self.say = self.worker = None
        if self.stderr_task:
            self.stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.stderr_task
            self.stderr_task = None
