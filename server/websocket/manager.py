"""WebSocket 连接管理器（含心跳超时检测 + 死连接自动清理）"""

import json
import asyncio
import time
from typing import List, Dict
from fastapi import WebSocket


from .. import config

HEARTBEAT_INTERVAL = config.HEARTBEAT_INTERVAL
HEARTBEAT_TIMEOUT = config.HEARTBEAT_TIMEOUT


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.user_map: Dict[str, WebSocket] = {}
        self.client_map: Dict[WebSocket, str] = {}
        self._last_pong: Dict[WebSocket, float] = {}  # 最近 pong 时间戳
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket, client_id: str = ""):
        await ws.accept()
        self.active.append(ws)
        cid = client_id or f"anon-{id(ws)}"
        self.client_map[ws] = cid
        self._last_pong[ws] = time.time()
        if client_id:
            self.user_map[client_id] = ws
        await self._broadcast_count()
        # 启动心跳循环（如尚未运行）
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        cid = self.client_map.pop(ws, "")
        self._last_pong.pop(ws, None)
        if cid and self.user_map.get(cid) is ws:
            del self.user_map[cid]
        await self._broadcast_count()

    async def _heartbeat_loop(self):
        """定期 ping 所有连接，清理超时未响应 pong 的死连接。"""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            now = time.time()
            dead: List[WebSocket] = []
            for ws in self.active[:]:
                try:
                    await ws.send_text('{"type":"hb.ping"}')
                except Exception:
                    dead.append(ws)
                    continue
                last = self._last_pong.get(ws, now)
                if now - last > HEARTBEAT_TIMEOUT:
                    dead.append(ws)
            for ws in dead:
                await self.disconnect(ws)

    def _record_pong(self, ws: WebSocket):
        """客户端响应了 pong，更新心跳时间戳。"""
        self._last_pong[ws] = time.time()

    @property
    def online_count(self) -> int:
        return len({c for c in self.client_map.values() if not str(c).startswith("canvas_")})

    async def _broadcast_count(self):
        await self.broadcast({"type": "presence", "peers": self.online_count})

    async def broadcast(self, data: dict):
        payload = json.dumps(data, ensure_ascii=False)
        dead = []
        for ws in self.active[:]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    async def send_to(self, client_id: str, data: dict):
        ws = self.user_map.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                # 发送失败 → 清理死连接（不再静默忽略）
                await self.disconnect(ws)

    async def broadcast_board_synced(self, canvas_id: str, updated_at: int, client_id: str = ""):
        await self.broadcast({
            "type": "board.synced",
            "board": canvas_id,
            "version": updated_at,
            "origin": client_id,
        })


manager = ConnectionManager()
