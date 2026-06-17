"""API 路由：ComfyUI 本地"""

import json
import os
import re
import time
import asyncio
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import config
from ..logging_config import get_logger

log = get_logger("comfyui")

router = APIRouter(prefix="/api", tags=["comfyui"])


class ComfyGenerateReq(BaseModel):
    workflow: dict = {}
    client_id: str = ""


# 多后端负载跟踪
_backend_load: dict = {}
_load_lock = asyncio.Lock()


async def _get_best_backend() -> str:
    """选择任务数最少的在线实例。"""
    async with _load_lock:
        for addr in list(_backend_load):
            if addr not in config.COMFYUI_INSTANCES:
                _backend_load.pop(addr, None)

    # 先选出在线实例
    online = []
    async with httpx.AsyncClient(timeout=3) as cli:
        for addr in config.COMFYUI_INSTANCES:
            try:
                await cli.get(f"http://{addr}/system_stats")
                online.append(addr)
            except Exception:
                continue

    if not online:
        raise HTTPException(status_code=502, detail="无可用 ComfyUI 实例")

    # 选负载最轻的
    async with _load_lock:
        for addr in online:
            if addr not in _backend_load:
                _backend_load[addr] = 0
        best = min(online, key=lambda a: _backend_load.get(a, 0))
        _backend_load[best] = _backend_load.get(best, 0) + 1
        return best


async def _release_backend(addr: str):
    async with _load_lock:
        if addr in _backend_load and _backend_load[addr] > 0:
            _backend_load[addr] -= 1


# ——— 实例管理 ———


@router.get("/comfyui/instances")
def get_instances():
    """获取所有 ComfyUI 实例地址。"""
    return {"instances": config.COMFYUI_INSTANCES}


@router.put("/comfyui/instances")
async def save_instances(payload: dict):
    """保存 ComfyUI 实例列表。

    payload: { instances: ["127.0.0.1:8188", "192.168.1.100:8188"] }
    """
    cleaned = []
    for item in (payload.get("instances") or []):
        s = str(item).strip()
        if not s:
            continue
        # 去除协议前缀
        s = re.sub(r"^https?://", "", s).rstrip("/")
        if ":" not in s:
            raise HTTPException(status_code=400, detail=f"地址缺少端口号: {item}")
        host, _, port = s.rpartition(":")
        if not host or not port.isdigit():
            raise HTTPException(status_code=400, detail=f"地址不合法: {item}")
        if s not in cleaned:
            cleaned.append(s)

    if not cleaned:
        raise HTTPException(status_code=400, detail="至少保留一个 ComfyUI 后端地址")

    # 写入 .env（现在用 threading.Lock，异步调用也安全）
    from ..routes.providers_cfg import _write_env
    await _write_env({"COMFYUI_INSTANCES": ",".join(cleaned)})

    # 更新运行时配置
    config.COMFYUI_INSTANCES = cleaned
    return {"instances": cleaned}


@router.get("/comfyui/status")
async def comfyui_status():
    """查询所有 ComfyUI 实例状态（含负载信息）。"""
    results = []
    async with httpx.AsyncClient(timeout=5) as cli:
        for addr in config.COMFYUI_INSTANCES:
            try:
                resp = await cli.get(f"http://{addr}/system_stats")
                data = resp.json()
                gpu = data.get("system", {}).get("device", "")
                results.append({
                    "address": addr,
                    "online": True,
                    "device": gpu,
                    "load": _backend_load.get(addr, 0),
                })
            except Exception:
                results.append({"address": addr, "online": False, "load": 0})
    return {"instances": results}


@router.get("/comfyui/queue")
def get_queue_status():
    """获取各后端的任务队列状态。"""
    return {addr: _backend_load.get(addr, 0) for addr in config.COMFYUI_INSTANCES}


# ——— ComfyUI 任务提交与轮询（共享函数） ———


async def _submit_comfyui(addr: str, workflow: dict, client_id: str = "canvas571") -> str:
    """提交工作流到 ComfyUI，返回 prompt_id。"""
    async with httpx.AsyncClient(timeout=10) as cli:
        body = {"prompt": workflow, "client_id": client_id}
        try:
            resp = await cli.post(f"http://{addr}/prompt", json=body)
            resp.raise_for_status()
            return resp.json()["prompt_id"]
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300] if e.response else str(e)
            raise HTTPException(status_code=502, detail=f"ComfyUI 错误: {detail}")


async def _poll_comfyui_task(addr: str, prompt_id: str, timeout_seconds: int = 300) -> dict:
    """轮询 ComfyUI 任务直到完成。

    返回: {"images": [...], "videos": [...], "prompt_id": "...", "backend": "..."}
    超时抛出 HTTPException(504)。
    视频/GIF 会下载到本地 output/videos/ 目录。
    """
    import asyncio as _asyncio
    async with httpx.AsyncClient(timeout=5) as cli:
        for _ in range(timeout_seconds):
            try:
                resp = await cli.get(f"http://{addr}/history/{prompt_id}")
                hist = resp.json()
                if prompt_id in hist:
                    outputs = hist[prompt_id].get("outputs", {})
                    images = []
                    videos = []
                    for node_id, node_out in outputs.items():
                        # 图片输出 —— 但部分节点（LTX等）会把视频放在 images 里，需按扩展名分流
                        img_items = node_out.get("images") or []
                        for item in img_items:
                            fn = item.get("filename", "")
                            sub = item.get("subfolder", "")
                            ext = os.path.splitext(fn)[1].lower()
                            # 视频扩展名 → 走视频下载
                            if ext in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
                                video_url = f"http://{addr}/view?filename={fn}&type=output&subfolder={sub}" if sub else f"http://{addr}/view?filename={fn}&type=output"
                                local_url = await _download_comfyui_media(addr, fn, sub or "video")
                                videos.append(local_url or video_url)
                            elif ext in (".gif",):
                                local_url = await _download_comfyui_media(addr, fn, sub or "gifs")
                                videos.append(local_url or f"http://{addr}/view?filename={fn}&type=output&subfolder={sub}" if sub else f"http://{addr}/view?filename={fn}&type=output")
                            else:
                                images.append(f"http://{addr}/view?filename={fn}&type=output")
                        # 视频输出 —— 兼容多种 key（videos / gifs / animated）
                        for video_key in ("videos", "gifs"):
                            for item in (node_out.get(video_key) or []):
                                fn = item.get("filename", "")
                                if not fn: continue
                                sub = item.get("subfolder", "") or video_key
                                video_url = f"http://{addr}/view?filename={fn}&type=output&subfolder={sub}"
                                local_url = await _download_comfyui_media(addr, fn, sub)
                                videos.append(local_url or video_url)
                    log.info(f"ComfyUI 轮询完成: {len(images)} 图片, {len(videos)} 视频")
                    return {"images": images, "videos": videos, "prompt_id": prompt_id, "backend": addr}
            except Exception:
                pass
            await _asyncio.sleep(1)

    raise HTTPException(status_code=504, detail="ComfyUI 渲染超时")


async def _download_comfyui_media(addr: str, filename: str, subfolder: str) -> str:
    """从 ComfyUI 下载视频/GIF 到本地 output/videos/，返回本地 URL。"""
    import os as _os
    import hashlib as _hashlib
    from .. import config
    try:
        dl_url = f"http://{addr}/view?filename={filename}&type=output&subfolder={subfolder}"
        log.info(f"下载 ComfyUI 媒体: {dl_url}")
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as cli:
            dl = await cli.get(dl_url)
            log.info(f"ComfyUI 下载响应: HTTP {dl.status_code}, size={len(dl.content)}")
            if dl.status_code == 200 and len(dl.content) > 1000:
                h = _hashlib.md5(dl.content).hexdigest()[:12]
                ts = int(time.time())
                ext = _os.path.splitext(filename)[1] or ".mp4"
                out_name = f"comfy_{ts}_{h}{ext}"
                path = _os.path.join(config.OUTPUT_VIDEOS_DIR, out_name)
                _os.makedirs(_os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(dl.content)
                log.info(f"ComfyUI 媒体已保存: {out_name} ({len(dl.content)} bytes)")
                return f"/output/videos/{out_name}"
            else:
                log.warning(f"ComfyUI 下载异常: HTTP {dl.status_code}, size={len(dl.content)}")
    except Exception as e:
        log.warning(f"下载 ComfyUI 媒体失败 {filename}: {e}")
    return ""


# ——— 工作流提交 ———


@router.post("/comfyui/generate")
async def comfyui_generate(req: ComfyGenerateReq):
    """提交 ComfyUI 工作流并轮询等待完成（负载均衡）。"""
    if not config.COMFYUI_INSTANCES:
        raise HTTPException(status_code=400, detail="未配置 ComfyUI 地址")

    addr = await _get_best_backend()

    try:
        prompt_id = await _submit_comfyui(addr, req.workflow, req.client_id or "canvas571")
        return await _poll_comfyui_task(addr, prompt_id)
    finally:
        await _release_backend(addr)
