"""画布业务逻辑层 —— 所有画布 CRUD + 文件同步逻辑。

从 routes/canvas.py 抽取，保持与原路由层完全兼容的公共 API。
路由层只保留 HTTP 参数校验、状态码转换和 WebSocket 广播。
"""

import os
import json
import re
import shutil
import asyncio
import time
from contextlib import asynccontextmanager
from .. import config
from ..storage.json_store import store
from ..utils import KeyedLockManager
from ..exceptions import NotFoundError, ConflictError, ValidationError


# v2.5.51：画布线写锁，防止同一画布的并发保存互相覆盖
_canvas_write_lock = KeyedLockManager()


@asynccontextmanager
async def lock_canvas(canvas_id: str):
    """画布写锁上下文管理器 —— 保护 load → merge → save 全事务。

    用法:
        async with lock_canvas(canvas_id):
            existing = load(canvas_id)
            canvas = merge_from_payload(existing, payload)
            await save(canvas)
    """
    async with await _canvas_write_lock.get(canvas_id):
        yield


_CANVAS_ID_RE = re.compile(r'^[a-f0-9]{12,64}$')


# ——— 目录路径工具 ———


def _safe_name(name: str) -> str:
    """把画布标题转为安全的文件夹名（保留中英文数字）。"""
    safe = re.sub(r"[^\w一-鿿-]", "_", name)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:60] if safe else "canvas"


def _find_canvas_dir(canvas_id: str) -> str | None:
    """扫描 canvases/ 下所有子目录的 canvas.json，按 id 匹配目录。"""
    if not os.path.isdir(config.CANVASES_ROOT):
        return None
    for name in os.listdir(config.CANVASES_ROOT):
        d = os.path.join(config.CANVASES_ROOT, name)
        if not os.path.isdir(d):
            continue
        cfg = os.path.join(d, "canvas.json")
        if os.path.exists(cfg):
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("id") == canvas_id:
                    return d
            except Exception:
                pass
    return None


def _canvas_dir(canvas_id: str) -> str:
    """获取画布目录路径。

    查找顺序：
    1. 扫描 canvases/ 下所有 canvas.json，按 id 精确匹配
    2. 匹配目录名中的 _{id[:8]} 后缀（处理 canvas.json 尚未写入的新目录）
    3. 回退到纯 ID 目录名
    """
    existing = _find_canvas_dir(canvas_id)
    if existing:
        return existing
    # 新创建的画布目录可能尚未写入 canvas.json，按 id[:8] 后缀匹配
    short_id = canvas_id[:8]
    if os.path.isdir(config.CANVASES_ROOT):
        for name in os.listdir(config.CANVASES_ROOT):
            if name.endswith(f"_{short_id}") and os.path.isdir(os.path.join(config.CANVASES_ROOT, name)):
                return os.path.join(config.CANVASES_ROOT, name)
    return os.path.join(config.CANVASES_ROOT, canvas_id)


def _canvas_dir_name(canvas_id: str) -> str:
    """获取画布目录名（不含路径）。"""
    return os.path.basename(_canvas_dir(canvas_id))


def _canvas_path(canvas_id: str) -> str:
    return os.path.join(_canvas_dir(canvas_id), "canvas.json")


def _canvas_files_dir(canvas_id: str) -> str:
    return os.path.join(_canvas_dir(canvas_id), "files")


def _validate_canvas_id(canvas_id: str):
    """校验画布 ID 格式，防止路径穿越。"""
    if not _CANVAS_ID_RE.match(canvas_id):
        raise ValidationError("无效的画布 ID 格式")


def _now():
    return int(time.time() * 1000)


# ——— 读 / 写 ———


def load(canvas_id: str) -> dict:
    """读取画布完整数据。画布不存在时抛出 NotFoundError。"""
    _validate_canvas_id(canvas_id)
    path = _canvas_path(canvas_id)
    if not os.path.exists(path):
        raise NotFoundError("画布不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def save(canvas: dict):
    """写入 canvas.json 并同步媒体文件到画布目录。

    1. 确保画布目录和 files/ 子目录存在
    2. 将节点引用的本地媒体文件复制到 files/
    3. 原子写入 canvas.json（临时文件 + os.replace）
    """
    cid = canvas["id"]
    d = _canvas_dir(cid)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "files"), exist_ok=True)

    # 同步媒体文件到画布目录（自包含）
    await _sync_canvas_files(canvas)

    # 原子写入
    await store.write_with_timestamp(_canvas_path(cid), canvas)


async def _sync_canvas_files(canvas: dict):
    """将画布节点中引用的本地媒体文件复制到画布目录并重写 URL。

    处理所有节点类型中的本地文件引用：
    - url 字段（图片节点、输出节点等）
    - images[] 数组（输出节点生成结果）
    - videos[] 数组（输出节点视频结果）

    复制完成后，将节点中的 URL 替换为画布内部路径：
    /output/images/xxx.png → /canvases/{dir}/files/xxx.png
    /input/xxx.jpg          → /canvases/{dir}/files/xxx.jpg
    """
    cid = canvas["id"]
    files_dir = _canvas_files_dir(cid)
    dir_name = _canvas_dir_name(cid)

    # 收集所有本地文件引用及其来源路径
    refs: dict[str, str] = {}  # source_abs_path → original_url
    for node in canvas.get("nodes", []):
        # 单值 url 字段
        for field in ["url"]:
            val = str(node.get(field, "")).strip()
            src = _resolve_file_source(val)
            if src:
                refs[src] = val
        # 数组字段
        for arr_key in ["images", "videos"]:
            for item in (node.get(arr_key) or []):
                if isinstance(item, dict):
                    val = str(item.get("url", "")).strip()
                elif isinstance(item, str):
                    val = item.strip()
                else:
                    continue
                src = _resolve_file_source(val)
                if src:
                    refs[src] = val

    if not refs:
        return

    # 复制文件并构建 URL 映射
    url_map: dict[str, str] = {}  # old_url → new_url
    for src_path, old_url in refs.items():
        if not os.path.isfile(src_path):
            continue
        filename = os.path.basename(old_url)
        dst_path = os.path.join(files_dir, filename)
        if not os.path.exists(dst_path):
            # v2.5.50：线程池执行避免阻塞事件循环
            await asyncio.to_thread(shutil.copy2, src_path, dst_path)
        new_url = f"/canvases/{dir_name}/files/{filename}"
        url_map[old_url] = new_url

    if not url_map:
        return

    # 替换节点中的 URL
    for node in canvas.get("nodes", []):
        for field in ["url"]:
            val = str(node.get(field, "")).strip()
            if val in url_map:
                node[field] = url_map[val]
        for arr_key in ["images", "videos"]:
            arr = node.get(arr_key) or []
            for i in range(len(arr)):
                item = arr[i]
                if isinstance(item, dict):
                    val = str(item.get("url", "")).strip()
                    if val in url_map:
                        arr[i]["url"] = url_map[val]
                elif isinstance(item, str):
                    if item in url_map:
                        arr[i] = url_map[item]


def _resolve_file_source(url: str) -> str:
    """将项目本地 URL 解析为绝对文件路径。非本地 URL 返回空字符串。"""
    url = str(url or "").strip()
    from ..security.paths import safe_join
    if url.startswith("/output/"):
        try:
            return safe_join(config.OUTPUT_DIR, url[len("/output/"):].lstrip("/"))
        except ValueError:
            return ""
    if url.startswith("/input/"):
        try:
            return safe_join(config.INPUT_DIR, url[len("/input/"):].lstrip("/"))
        except ValueError:
            return ""
    if url.startswith("/assets/"):
        try:
            return safe_join(config.ASSETS_DIR, url[len("/assets/"):].lstrip("/"))
        except ValueError:
            return ""
    return ""


# ——— 列表 ———


def list_all() -> list[dict]:
    """列出所有画布（扫描 canvases/ 目录）。"""
    items: list[dict] = []
    if not os.path.isdir(config.CANVASES_ROOT):
        return items

    for name in sorted(os.listdir(config.CANVASES_ROOT)):
        if name.startswith("_") or name.startswith("."):
            continue
        d = os.path.join(config.CANVASES_ROOT, name)
        if not os.path.isdir(d):
            continue
        cfg = os.path.join(d, "canvas.json")
        if not os.path.exists(cfg):
            continue
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                c = json.load(f)
        except Exception:
            continue
        if c.get("deleted_at"):
            continue
        items.append({
            "id": c["id"],
            "title": c.get("title", ""),
            "created_at": c.get("created_at", 0),
            "updated_at": c.get("updated_at", 0),
            "icon": c.get("icon", "layers"),
            "kind": c.get("kind", "default"),
            "node_count": len(c.get("nodes", [])),
            "_dir": name,
        })

    items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return items


# ——— 复合操作 ———


def create(title: str) -> tuple[dict, str]:
    """创建新画布，返回 (canvas_dict, dir_name)。"""
    import uuid as _uuid
    cid = _uuid.uuid4().hex[:16]
    now_ts = _now()
    canvas = {
        "id": cid,
        "title": title or "未命名画布",
        "created_at": now_ts,
        "updated_at": now_ts,
        "nodes": [],
        "connections": [],
        "groups": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    slug = _safe_name(title)
    d = os.path.join(config.CANVASES_ROOT, f"{slug}_{cid[:8]}")
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "files"), exist_ok=True)
    return canvas, os.path.basename(d)


def merge_from_payload(existing: dict, payload: dict) -> dict:
    """将前端 payload 合并到已有画布数据中，返回合并后的画布 dict。

    乐观并发控制：比对 base_updated_at，冲突时抛出 ConflictError。
    """
    cid = existing["id"]

    # 乐观并发控制
    base_updated_at = payload.get("base_updated_at")
    current_updated_at = existing.get("updated_at", 0)
    if base_updated_at and current_updated_at and int(base_updated_at) < current_updated_at:
        raise ConflictError(
            message="画布已被其他页面更新，已拒绝旧版本覆盖。请刷新页面获取最新数据。",
        )

    return {
        "id": cid,
        "title": payload.get("title", existing.get("title", "未命名画布")),
        "created_at": existing.get("created_at", _now()),
        "updated_at": _now(),
        "nodes": payload.get("nodes", existing.get("nodes", [])),
        "connections": payload.get("connections", existing.get("connections", [])),
        "groups": payload.get("groups", existing.get("groups", [])),
        "viewport": payload.get("viewport", existing.get("viewport", {"x": 0, "y": 0, "scale": 1})),
        "icon": payload.get("icon", existing.get("icon", "layers")),
        "kind": payload.get("kind", existing.get("kind", "default")),
        "logs": payload.get("logs", existing.get("logs", [])),
        "settings": payload.get("settings", existing.get("settings", {})),
    }


def duplicate(existing: dict) -> tuple[dict, str]:
    """创建画布副本，返回 (new_canvas_dict, dir_name)。"""
    import copy
    import uuid as _uuid
    new_id = _uuid.uuid4().hex[:16]
    now_ts = _now()

    new_canvas = {
        "id": new_id,
        "title": f"{existing.get('title', '未命名画布')} - 副本",
        "created_at": now_ts,
        "updated_at": now_ts,
        "nodes": copy.deepcopy(existing.get("nodes", [])),
        "connections": copy.deepcopy(existing.get("connections", [])),
        "groups": copy.deepcopy(existing.get("groups", [])),
        "viewport": copy.deepcopy(existing.get("viewport", {"x": 0, "y": 0, "scale": 1})),
        "icon": existing.get("icon", "layers"),
        "kind": existing.get("kind", "default"),
        "logs": copy.deepcopy(existing.get("logs", [])),
        "settings": copy.deepcopy(existing.get("settings", {})),
    }

    slug = _safe_name(new_canvas["title"])
    d = os.path.join(config.CANVASES_ROOT, f"{slug}_{new_id[:8]}")
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "files"), exist_ok=True)

    return new_canvas, os.path.basename(d)


def update_meta(existing: dict, payload) -> dict:
    """更新画布元数据（就地修改 existing，返回 existing）。"""
    if payload.title is not None:
        existing["title"] = (payload.title or existing.get("title") or "未命名画布")[:80]
    if payload.icon is not None:
        existing["icon"] = payload.icon[:32]
    if payload.color is not None:
        existing["color"] = payload.color[:20]
    if payload.owner is not None:
        existing["owner"] = payload.owner.strip()[:40]
    if payload.pinned is not None:
        existing["pinned"] = payload.pinned
    if payload.kind is not None:
        existing["kind"] = payload.kind[:20]
    return existing


def soft_delete(existing: dict) -> dict:
    """软删除画布（设置 deleted_at 时间戳），返回 updated canvas。"""
    existing["deleted_at"] = _now()
    return existing


def hard_delete(existing: dict) -> None:
    """永久删除画布目录（不可恢复）。

    目录名不合法时拒绝操作，防止误删。
    """
    cid = existing.get("id", "")
    _validate_canvas_id(cid)
    d = _canvas_dir(cid)
    if not os.path.isdir(d):
        raise NotFoundError("画布目录不存在")
    # 安全检查：确保目录名包含画布 ID（防止误删其他目录）
    dir_name = os.path.basename(d)
    if cid[:8] not in dir_name and cid not in dir_name:
        raise ValidationError("画布目录名不匹配，拒绝删除")
    shutil.rmtree(d)
