"""应用入口"""

import uvicorn
from .app import app
from . import config
from .logging_config import setup_logging, get_logger

# 导入并注册路由
from .routes.generation import router as gen_router
from .routes.chat import router as chat_router
from .routes.canvas import router as canvas_router
from .routes.agent_routes import router as agent_router
from .routes.knowledge import router as kb_router
from .routes.comfyui import router as comfy_router
from .routes.assets import router as assets_router
from .routes.providers_cfg import router as cfg_router
from .routes.tasks import router as tasks_router
from .routes.video import router as video_router
from .routes.workflows import router as workflows_router
from .routes.asset_library import router as asset_library_router
from .routes.prompt_library import router as prompt_library_router
from .routes.update import router as update_router
from .routes.avatar import router as avatar_router
from .routes.shared_folders import router as shared_folders_router

app.include_router(gen_router)
app.include_router(chat_router)
app.include_router(canvas_router)
app.include_router(agent_router)
app.include_router(kb_router)
app.include_router(comfy_router)
app.include_router(assets_router)
app.include_router(cfg_router)
app.include_router(tasks_router)
app.include_router(video_router)
app.include_router(workflows_router)
app.include_router(asset_library_router)
app.include_router(prompt_library_router)
app.include_router(update_router)
app.include_router(avatar_router)
app.include_router(shared_folders_router)

# WebSocket
from .websocket.manager import manager
from fastapi import WebSocket, WebSocketDisconnect


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, client_id: str = ""):
    await manager.connect(ws, client_id)
    try:
        while True:
            data = await ws.receive_text()
            if data == "hb.ping":
                await ws.send_text('{"type":"hb.pong"}')
            elif data == "hb.pong":
                manager._record_pong(ws)
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:
        await manager.disconnect(ws)


@app.get("/health")
async def health():
    """健康检查端点（无需鉴权）。"""
    return {"status": "ok", "version": config.APP_VERSION}


@app.get("/")
async def index():
    import os
    # 缓存 HTML 内容，避免每次请求都读文件
    if not hasattr(index, "_cached_html"):
        path = os.path.join(config.STATIC_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            index._cached_html = f.read()
    from fastapi.responses import Response
    return Response(index._cached_html, media_type="text/html; charset=utf-8")


def main():
    setup_logging()
    log = get_logger("main")
    log.info(f"启动 无限画布 v{config.APP_VERSION}")
    print(f"\n  本机访问: http://127.0.0.1:{config.APP_PORT}/")
    print(f"  按 Ctrl+C 停止\n")
    # 自动获取局域网 IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        print(f"  局域网访问: http://{lan_ip}:{config.APP_PORT}/\n")
    except Exception as e:
        log.debug(f"无法获取局域网 IP: {e}")
    uvicorn.run(app, host=config.APP_HOST, port=config.APP_PORT, log_level="info")


if __name__ == "__main__":
    main()
