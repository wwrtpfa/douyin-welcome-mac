import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path(os.environ.get("WELCOME_DATA_DIR", str(Path.home() / "Library/Application Support/DouyinWelcome")))
MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"
DEFAULTS = {
    "room": "", "mode": "system", "reference_audio": "", "reference_text": "",
    "template": "欢迎{name}，欢迎来到直播间！", "interval": 8,
    "dedup_seconds": 600, "max_age": 30, "max_queue": 5, "volume": 0.7,
    "output_device": "", "blocked_words": "", "model": MODEL,
}


def room_url(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[0-9]{5,24}", value):
        return "https://live.douyin.com/" + value
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname == "live.douyin.com" and re.fullmatch(r"/[0-9]{5,24}/?", parsed.path) and parsed.port in (None, 443) and not parsed.username:
        return "https://live.douyin.com/" + parsed.path.strip("/")
    raise ValueError("请填写电脑网页版直播间链接，例如 https://live.douyin.com/123456789；不支持短分享链接。")


def validate(data: dict) -> dict:
    result = DEFAULTS | {k: v for k, v in data.items() if k in DEFAULTS}
    for key in ("room", "mode", "reference_audio", "reference_text", "template", "output_device", "blocked_words", "model"):
        if not isinstance(result[key], str):
            raise ValueError(f"设置字段 {key} 必须是文字")
    if result["mode"] not in ("system", "clone"):
        raise ValueError("未知声音模式")
    if "{name}" not in result["template"] or len(result["template"]) > 100:
        raise ValueError("欢迎语必须包含 {name}，且不超过 100 字")
    for key, low, high in (("interval", 0, 120), ("dedup_seconds", 10, 86400), ("max_age", 5, 120), ("max_queue", 1, 20)):
        result[key] = int(result[key])
        if not low <= result[key] <= high:
            raise ValueError(f"{key} 超出允许范围 {low}–{high}")
    result["volume"] = float(result["volume"])
    if not 0 <= result["volume"] <= 1:
        raise ValueError("音量应在 0 到 1 之间")
    if result["model"] != MODEL:
        raise ValueError("此版本使用已经适配的 Qwen3-TTS 0.6B Base 4bit 模型")
    if len(result["reference_text"]) > 2000 or len(result["blocked_words"]) > 2000:
        raise ValueError("录音文字或屏蔽词过长")
    return result


def load() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        return validate(json.loads((APP_DIR / "settings.json").read_text()))
    except (OSError, ValueError, TypeError):
        return DEFAULTS.copy()


def save(config: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = APP_DIR / "settings.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(validate(config), ensure_ascii=False, indent=2))
    temp.chmod(0o600)
    temp.replace(target)

