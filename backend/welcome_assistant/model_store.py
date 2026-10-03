"""Explicit local-cache first loading and bounded network connection timeouts."""
import os
from pathlib import Path

from .config import APP_DIR, MODEL


def model_path(progress=lambda message: None):
    local = Path(os.environ.get("WELCOME_MODEL_DIR", str(APP_DIR / "models" / "qwen3-tts-0.6b")))
    if (local / "config.json").is_file() and (local / "model.safetensors").is_file():
        return str(local)
    import httpx
    from huggingface_hub import snapshot_download, set_client_factory
    set_client_factory(lambda: httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, connect=15)))
    try:
        path = snapshot_download(MODEL, local_files_only=True)
        if (Path(path) / "model.safetensors").is_file() and (Path(path) / "speech_tokenizer/model.safetensors").is_file():
            return path
    except Exception:
        pass
    progress("正在下载本地声音模型，首次使用需要联网；可随时点停止取消")
    try:
        return snapshot_download(MODEL, max_workers=3)
    except Exception as error:
        raise ValueError("声音模型尚未下载成功，请检查 Hugging Face 网络连接后重试。也可按 README 的离线模型说明导入；本次未生成克隆声音。") from error

