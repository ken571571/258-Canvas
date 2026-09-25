"""API 路由：ComfyUI 本地"""

import json
import os
import re
import time
import socket
import ipaddress
import asyncio
import httpx
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import config
from ..logging_config import get_logger
from ..security.network import BLOCKED_NETWORKS, is_blocked_host, async_is_blocked_host

log = get_logger("comfyui")

router = APIRouter(prefix="/api", tags=["comfyui"])

# ——— 本地别名：保持模块内原有引用名兼容 ———
_BLOCKED_NETWORKS = BLOCKED_NETWORKS
_is_blocked_host = is_blocked_host  # 同步版，仅用于非异步上下文
_async_is_blocked_host = async_is_blocked_host  # 异步版，用于 async def 中


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
    async with httpx.AsyncClient(timeout=3, follow_redirects=False) as cli:
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
        # SSRF 防护：检查主机是否在云 metadata 黑名单（允许内网地址用于多机部署）
        if await async_is_blocked_host(host, allow_lan=True):
            raise HTTPException(status_code=400, detail=f"不允许注册受保护地址: {host}")
        if s not in cleaned:
            cleaned.append(s)

    if not cleaned:
        raise HTTPException(status_code=400, detail="至少保留一个 ComfyUI 后端地址")

    # 写入 .env（使用 asyncio.Lock，异步调用安全）
    from ..routes.providers_cfg import _write_env
    await _write_env({"COMFYUI_INSTANCES": ",".join(cleaned)})

    # 更新运行时配置
    config.COMFYUI_INSTANCES = cleaned
    return {"instances": cleaned}


@router.get("/comfyui/status")
async def comfyui_status():
    """查询所有 ComfyUI 实例状态（含负载信息）。"""
    results = []
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as cli:
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


# ——— 局域网自动扫描 ———


def _detect_lan_networks() -> tuple:
    """探测本机所属的局域网 /24 网段（纯标准库，不依赖 psutil）。

    两种来源互为补充：
      1. UDP connect 技巧：socket 不会真正发包，仅让 OS 给出通往外部时
         将使用的源 IP（主网卡，最可靠）。
      2. gethostbyname_ex(主机名)：枚举主机绑定的其余网卡 IP。

    返回: (IPv4Network 列表, 本机 IP 集合)
    """
    local_ips: set = set()

    # 来源 1：UDP connect 技巧
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ips.add(s.getsockname()[0])
    except Exception:
        pass
    finally:
        s.close()

    # 来源 2：主机名解析
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            local_ips.add(ip)
    except Exception:
        pass

    networks: list = []
    valid_ips: set = set()
    for ip in local_ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        # 仅保留 RFC1918 私有 IPv4（排除环回/链路本地/CGNAT）
        if not isinstance(addr, ipaddress.IPv4Address) or not addr.is_private:
            continue
        if addr.is_loopback or addr.is_link_local:
            continue
        net = ipaddress.ip_interface(f"{ip}/24").network
        if net not in networks:
            networks.append(net)
        valid_ips.add(ip)
    return networks, valid_ips


async def _probe_port(ip: str, port: int, timeout: float) -> bool:
    """TCP 半开探测：端口能否在 timeout 内建立连接。"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


class ScanLanReq(BaseModel):
    port: int = 8188


@router.post("/comfyui/scan-lan")
async def scan_lan(req: ScanLanReq):
    """扫描本机所在局域网，返回所有在线 ComfyUI 实例。

    流程：枚举本机网段 → 并发 TCP 探测 8188 → 对开放主机请求
    /system_stats 确认是 ComfyUI 并读取版本/设备信息。
    """
    port = req.port
    if not (1 <= port <= 65535):
        raise HTTPException(status_code=400, detail="端口号不合法")

    networks, local_ips = _detect_lan_networks()
    if not networks:
        raise HTTPException(
            status_code=400,
            detail="未检测到局域网连接（本机无 RFC1918 私有网段 IP）",
        )

    # 收集候选主机（去重、跳过本机地址）
    candidates: set = set()
    for net in networks:
        for host in net.hosts():
            ip = str(host)
            if ip in local_ips:
                continue
            candidates.add(ip)

    # 并发 TCP 探测
    sem = asyncio.Semaphore(128)

    async def _check(ip: str) -> str:
        async with sem:
            return ip if await _probe_port(ip, port, 0.4) else ""

    open_ips = [r for r in await asyncio.gather(*[_check(ip) for ip in candidates]) if r]

    # 对开放端口确认 ComfyUI 身份并读取信息
    existing = set(config.COMFYUI_INSTANCES)
    found = []
    async with httpx.AsyncClient(timeout=3, follow_redirects=False) as cli:
        for ip in open_ips:
            addr = f"{ip}:{port}"
            try:
                resp = await cli.get(f"http://{addr}/system_stats")
                data = resp.json()
                found.append({
                    "address": addr,
                    "ip": ip,
                    "port": port,
                    "version": data.get("system", {}).get("comfyui_version", ""),
                    "device": data.get("system", {}).get("device", ""),
                    "added": addr in existing,
                })
            except Exception:
                # 端口开放但不是 ComfyUI/响应异常 → 不列入
                continue

    log.info(f"局域网扫描: 网段 {[str(n) for n in networks]}, "
             f"探测 {len(candidates)} 主机, 发现 {len(found)} 个 ComfyUI")
    return {
        "networks": [str(n) for n in networks],
        "hosts_scanned": len(candidates),
        "found": found,
    }


# ——— ComfyUI 任务提交与轮询（共享函数） ———


async def _submit_comfyui(addr: str, workflow: dict, client_id: str = "canvas571") -> str:
    """提交工作流到 ComfyUI，返回 prompt_id。"""
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as cli:
        body = {"prompt": workflow, "client_id": client_id}
        try:
            resp = await cli.post(f"http://{addr}/prompt", json=body)
            resp.raise_for_status()
            return resp.json()["prompt_id"]
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300] if e.response else str(e)
            raise HTTPException(status_code=502, detail=f"ComfyUI 错误: {detail}")


async def _poll_comfyui_task(addr: str, prompt_id: str, timeout_seconds: int = 3600, interval_seconds: int = 1) -> dict:
    """轮询 ComfyUI 任务直到完成。

    返回: {"images": [...], "videos": [...], "prompt_id": "...", "backend": "..."}
    超时抛出 HTTPException(504)。
    视频/GIF 会下载到本地 output/videos/ 目录。
    """
    import asyncio as _asyncio
    consecutive_errors = 0
    elapsed = 0
    last_log = 0
    interval_seconds = max(1, min(60, int(interval_seconds)))
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as cli:
        while elapsed < timeout_seconds:
            try:
                resp = await cli.get(f"http://{addr}/history/{prompt_id}")
                hist = resp.json()
                consecutive_errors = 0  # 成功响应后重置
                if prompt_id not in hist:
                    log.info(f"ComfyUI 轮询 pid 未命中: status={resp.status_code}, size={len(resp.content)}, hist_keys={list(hist.keys())[:5]}")
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
                                video_url = f"http://{addr}/view?filename={quote(fn,safe='')}&type=output&subfolder={quote(sub,safe='')}" if sub else f"http://{addr}/view?filename={quote(fn,safe='')}&type=output"
                                local_url = await _download_comfyui_media(addr, fn, sub)
                                videos.append(local_url or video_url)
                            elif ext in (".gif",):
                                local_url = await _download_comfyui_media(addr, fn, sub)
                                videos.append(local_url or f"http://{addr}/view?filename={quote(fn,safe='')}&type=output&subfolder={quote(sub,safe='')}" if sub else f"http://{addr}/view?filename={quote(fn,safe='')}&type=output")
                            else:
                                # 图片也下载到本地，避免局域网客户端无法直连 ComfyUI
                                local_url = await _download_comfyui_media(addr, fn, sub or "", "images")
                                images.append(local_url or f"http://{addr}/view?filename={quote(fn,safe='')}&type=output")
                        # 视频输出 —— 兼容多种 key（videos / gifs / animated）
                        for video_key in ("videos", "gifs"):
                            for item in (node_out.get(video_key) or []):
                                fn = item.get("filename", "")
                                if not fn: continue
                                sub = item.get("subfolder", "")
                                video_url = f"http://{addr}/view?filename={quote(fn,safe='')}&type=output&subfolder={quote(sub,safe='')}"
                                local_url = await _download_comfyui_media(addr, fn, sub)
                                videos.append(local_url or video_url)
                    log.info(f"ComfyUI 轮询完成: {len(images)} 图片, {len(videos)} 视频")
                    return {"images": images, "videos": videos, "prompt_id": prompt_id, "backend": addr}
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors <= 3 or consecutive_errors % 10 == 0:
                    log.warning(f"ComfyUI 轮询瞬断 ({consecutive_errors} 次): {addr} — {e}")
                if consecutive_errors >= 30:
                    raise HTTPException(status_code=502, detail=f"ComfyUI 后端连续 {consecutive_errors} 次无响应: {addr}")
            await _asyncio.sleep(interval_seconds)
            elapsed += interval_seconds
            if elapsed - last_log >= 60:
                last_log = elapsed
                log.info(f"ComfyUI 任务仍在运行中: {prompt_id} 已等待 {elapsed}s / 上限 {timeout_seconds}s")

    raise HTTPException(status_code=504, detail="ComfyUI 渲染超时")


async def _download_comfyui_media(addr: str, filename: str, subfolder: str, output_subdir: str = "videos") -> str:
    """从 ComfyUI 下载媒体文件到本地 output/ 目录，返回本地 URL。

    Args:
        output_subdir: 输出子目录名，如 "videos" 或 "images"
    """
    import os as _os
    import hashlib as _hashlib
    from .. import config
    try:
        dl_url = f"http://{addr}/view?filename={filename}&type=output&subfolder={subfolder}"
        log.info(f"下载 ComfyUI 媒体: {dl_url}")
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as cli:
            dl = await cli.get(dl_url)
            # 手动处理重定向，每跳做 SSRF 校验（防范被入侵的 ComfyUI 实例重定向到 metadata）
            redirect_count = 0
            from urllib.parse import urlparse as _urlparse, urljoin as _urljoin
            original_host = _urlparse(dl_url).hostname
            while dl.is_redirect and redirect_count < 5:
                redirect_count += 1
                next_url = dl.headers.get("location", "")
                if not next_url:
                    break
                if next_url.startswith("/"):
                    next_url = _urljoin(dl_url, next_url)
                next_host = _urlparse(next_url).hostname
                # 仅当重定向到非原始主机时才做额外校验（允许 LAN 内重定向，拦截 metadata）
                if next_host and next_host != original_host:
                    if await _async_is_blocked_host(next_host, allow_lan=True, allow_localhost=False):
                        log.warning(f"SSRF 拦截（ComfyUI 重定向目标）: {next_url[:120]}")
                        return ""
                dl = await cli.get(next_url)
            log.info(f"ComfyUI 下载响应: HTTP {dl.status_code}, size={len(dl.content)}")
            if dl.status_code == 200 and len(dl.content) > 1000:
                h = _hashlib.md5(dl.content).hexdigest()[:12]
                ts = int(time.time())
                ext = _os.path.splitext(filename)[1] or (".mp4" if output_subdir == "videos" else ".png")
                out_name = f"comfy_{ts}_{h}{ext}"
                out_dir = config.OUTPUT_VIDEOS_DIR if output_subdir == "videos" else config.OUTPUT_IMAGES_DIR
                path = _os.path.join(out_dir, out_name)
                _os.makedirs(_os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(dl.content)
                log.info(f"ComfyUI 媒体已保存: {out_name} ({len(dl.content)} bytes)")
                return f"/output/{output_subdir}/{out_name}"
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
        return await _poll_comfyui_task(addr, prompt_id, timeout_seconds=3600)
    finally:
        await _release_backend(addr)
