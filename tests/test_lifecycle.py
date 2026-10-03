import asyncio
import json
import os
import sys
from pathlib import Path


async def test_backend_ready_and_shutdown(tmp_path):
    env = os.environ | {"WELCOME_DATA_DIR": str(tmp_path), "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
    process = await asyncio.create_subprocess_exec(sys.executable, "-u", "-m", "welcome_assistant", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        ready = json.loads(await asyncio.wait_for(process.stdout.readline(), 15))
        assert ready["type"] == "ready"
        process.stdin.write(b'{"command":"shutdown"}\n')
        await process.stdin.drain()
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode == 0, stderr.decode()
        assert any(json.loads(line).get("type") == "stopped" for line in stdout.splitlines())
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
