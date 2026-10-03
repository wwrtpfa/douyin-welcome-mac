import asyncio
import contextlib
import time

from .config import APP_DIR, room_url
from .protocol import decode_frame


class Collector:
    def __init__(self, emit, on_arrival):
        self.emit, self.on_arrival = emit, on_arrival
        self.context = None
        self.playwright = None
        self.monitor = None
        self.last_frame = 0
        self.stopping = False
        self.state = "disconnected"
        self.bad_frames = 0
        self.sockets = set()
        self.frame_serial = 0

    def status(self, state, detail):
        self.state = state
        self.emit("connection", state=state, detail=detail)

    async def connect(self, value):
        url = room_url(value)
        await self.close()
        self.stopping = False
        self.status("connecting", "正在打开专用直播窗口；如遇登录或验证，请在窗口内完成")
        from playwright.async_api import async_playwright
        try:
            self.playwright = await async_playwright().start()
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(APP_DIR / "browser-profile"), channel="chrome", headless=False,
                args=["--mute-audio", "--disable-background-timer-throttling"],
                viewport={"width": 1050, "height": 760},
            )
            self.context.on("close", self._closed)
            page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            page.on("websocket", self._socket)
            self.last_frame = time.monotonic()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as error:
                self.emit("log", level="warning", message=f"页面加载未完成，可在专用窗口检查：{str(error)[:160]}")
            if self.state != "receiving":
                self.status("waiting", "页面已打开，等待直播消息；请确认已开播并完成验证")
            self.monitor = asyncio.create_task(self._watch(page))
        except BaseException:
            await self.close()
            raise

    def _closed(self, *_):
        if not self.stopping:
            self.status("disconnected", "专用直播窗口已关闭，请重新连接")

    def _socket(self, socket):
        if "webcast" not in socket.url.lower():
            return
        self.sockets.add(socket)
        socket.on("framereceived", self._frame)
        socket.on("close", lambda *_: self._socket_closed(socket))

    def _socket_closed(self, socket):
        self.sockets.discard(socket)
        if not self.stopping and not self.sockets:
            self.status("waiting", "消息连接中断，等待网页重连")

    def _frame(self, data):
        if self.stopping or not isinstance(data, bytes):
            return
        self.last_frame = time.monotonic()
        self.frame_serial += 1
        if self.state != "receiving":
            self.status("receiving", "正在接收直播消息；进房事件可能不完整")
        try:
            for arrival in decode_frame(data):
                # Ignore historical backlog on reconnect (server timestamp is seconds).
                stamp = arrival.created_at / 1000 if arrival.created_at > 10**12 else arrival.created_at
                if stamp and time.time() - stamp > 30:
                    continue
                self.on_arrival(arrival)
        except (ValueError, OSError, TypeError, EOFError):
            self.bad_frames += 1
            if self.bad_frames in (1, 10, 100):
                self.emit("log", level="warning", message="部分消息无法解析，可能是平台协议变化；不会把这些消息当作进房事件")

    async def _watch(self, page):
        retries = 0
        observed_serial = self.frame_serial
        try:
            while not self.stopping and not page.is_closed():
                await asyncio.sleep(10)
                if self.frame_serial != observed_serial:
                    observed_serial = self.frame_serial
                    retries = 0
                if time.monotonic() - self.last_frame < 90:
                    continue
                if retries >= 3:
                    self.status("waiting", "仍未收到消息，请检查直播状态、登录或验证后重新连接")
                    return
                retries += 1
                self.status("connecting", f"长时间无消息，尝试重新加载（{retries}/3）")
                self.last_frame = time.monotonic()
                with contextlib.suppress(Exception):
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
        except asyncio.CancelledError:
            pass

    async def close(self):
        self.stopping = True
        if self.monitor:
            self.monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.monitor
            self.monitor = None
        if self.context:
            with contextlib.suppress(Exception):
                await self.context.close()
            self.context = None
        if self.playwright:
            with contextlib.suppress(Exception):
                await self.playwright.stop()
            self.playwright = None
        self.sockets.clear()
        self.status("disconnected", "未连接直播间")
