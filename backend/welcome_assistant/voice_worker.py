"""Dedicated MLX process. Stopping synthesis releases the entire model process."""
import contextlib
import json
import sys
from pathlib import Path


def run():
    transport = sys.stdout

    def send(**event):
        transport.write(json.dumps(event, ensure_ascii=False) + "\n")
        transport.flush()

    model = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                import numpy as np
                import soundfile as sf
                try:
                    info = sf.info(request["reference_audio"])
                except RuntimeError as error:
                    raise ValueError("参考录音不是 WAV/AIFF PCM 格式。请回到‘我的声音’重新选择录音，应用会自动转换为 WAV。") from error
                if info.duration < 3 or info.duration > 30:
                    raise ValueError("参考录音应为 3～30 秒，推荐 10～20 秒")
                if model is None:
                    from .model_store import model_path
                    path = model_path(lambda message: send(type="progress", message=message))
                    from mlx_audio.tts.utils import load_model
                    send(type="progress", message="正在把声音模型加载到内存")
                    model = load_model(path)
                    send(type="progress", message="本地声音模型已加载")
                output = []
                sample_rate = 24000
                for result in model.generate(
                    text=request["text"], ref_audio=request["reference_audio"],
                    ref_text=request["reference_text"], lang_code="Chinese",
                    max_tokens=900, verbose=False,
                ):
                    output.append(np.asarray(result.audio, dtype=np.float32))
                    sample_rate = result.sample_rate
                if not output:
                    raise ValueError("模型没有生成音频")
                sf.write(request["output"], np.concatenate(output), sample_rate)
            send(type="result", path=request["output"])
        except Exception as error:
            send(type="error", message=str(error))
