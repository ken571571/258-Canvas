"""API 路由：共享文件夹

注册本地文件夹到素材库，浏览文件树并导入媒体文件。
"""

import os
import uuid
import time
import mimetypes
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .. import config
from ..storage.json_store import store

router = APIRouter(prefix="/api", tags=["shared_folders"])

SHARED_FILE = os.path.join(config.DATA_DIR, "shared_folders.json")
SHARED_MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov"}


def _now():
    return int(time.time() * 1000)


def _load() -> dict:
    return store.read(SHARED_FILE, default={"folders": []})


async def _save(data: dict):
    await store.write(SHARED_FILE, data)


# ——— 系统目录黑名单（防止通过共享文件夹浏览敏感系统路径） ———

_FORBIDDEN_ROOTS = [
    # Windows 系统目录（使用正斜杠，normpath 会统一转换）
    "C:/Windows",
    "C:/Windows/System32",
    "C:/Windows/SysWOW64",
    "C:/Program Files",
    "C:/Program Files (x86)",
    "C:/ProgramData",
    "C:/Users/All Users",
    "C:/$Recycle.Bin",
    # Unix 系统目录
    "/etc",
    "/proc",
    "/sys",
    "/boot",
    "/root",
    "/var/log",
    "/var/run",
]

_FORBIDDEN_PREFIXES = [
    # Windows
    "C:/Windows/",
    "C:/Program Files/",
    "C:/Program Files (x86)/",
    "C:/ProgramData/",
    # Unix
    "/etc/",
    "/proc/",
    "/sys/",
    "/boot/",
    "/root/",
]


def _is_safe_folder_path(abs_path: str) -> bool:
    """检查路径是否安全可注册（不在系统敏感目录内）。"""
    norm = os.path.normpath(os.path.abspath(abs_path)).replace("/", os.sep)
    norm_lower = norm.lower()
    # 精确匹配（大小写不敏感，Windows 下 C:\Windows == c:\windows）
    for forbidden in _FORBIDDEN_ROOTS:
        if os.path.normpath(forbidden).replace("/", os.sep).lower() == norm_lower:
            return False
    # 前缀匹配（后面必须跟分隔符，防止 C:\Windows 误杀 C:\Windows10）
    norm_with_sep = norm_lower + os.sep
    for prefix in _FORBIDDEN_PREFIXES:
        if norm_with_sep.startswith(os.path.normpath(prefix).lower() + os.sep):
            return False
    return True


# ——— 文件夹管理 ———


@router.get("/folders")
def list_folders():
    """列出所有已注册的共享文件夹。"""
    data = _load()
    folders = []
    for entry in data.get("folders", []):
        abs_path = os.path.abspath(entry.get("path", ""))
        folders.append({
            "id": entry.get("id"),
            "name": entry.get("name") or os.path.basename(abs_path),
            "path": abs_path,
            "exists": os.path.isdir(abs_path),
            "created_at": entry.get("created_at"),
        })
    return {"folders": folders}


@router.post("/folders")
async def register_folder(payload: dict):
    """注册新共享文件夹。

    payload: {path: "D:/my_images", name: "我的图片库"}
    """
    raw_path = payload.get("path")
    if raw_path is None or not isinstance(raw_path, str):
        raise HTTPException(status_code=400, detail="缺少文件夹路径")
    abs_path = os.path.abspath(raw_path.strip())
    if not abs_path or not os.path.isdir(abs_path):
        raise HTTPException(status_code=400, detail="文件夹路径不存在或不可访问")
    if not _is_safe_folder_path(abs_path):
        raise HTTPException(status_code=400, detail="不允许注册系统目录，请选择用户数据目录")
    name = str(payload.get("name") or os.path.basename(abs_path))[:100]

    data = _load()
    # 检查是否已注册
    for entry in data.get("folders", []):
        if os.path.normpath(os.path.abspath(entry.get("path", ""))) == os.path.normpath(abs_path):
            entry["name"] = name
            await _save(data)
            return {"folder": {**entry, "path": abs_path, "exists": True}}

    entry = {
        "id": f"shared_{uuid.uuid4().hex[:12]}",
        "name": name,
        "path": abs_path,
        "created_at": _now(),
    }
    data.setdefault("folders", []).append(entry)
    await _save(data)
    return {"folder": {**entry, "exists": True}}


@router.delete("/folders/{folder_id}")
async def unregister_folder(folder_id: str):
    """取消注册共享文件夹（不删除实际文件）。"""
    data = _load()
    before = len(data.get("folders", []))
    data["folders"] = [f for f in data.get("folders", []) if f.get("id") != folder_id]
    if len(data["folders"]) == before:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")
    await _save(data)
    return {"ok": True}


# ——— 文件浏览 ———


def _scan_dir(base: str, rel: str = "", max_depth: int = 5) -> list:
    """扫描目录树，返回文件/文件夹列表（限定深度）。"""
    if max_depth <= 0:
        return []
    abs_dir = os.path.join(base, rel) if rel else base
    if not os.path.isdir(abs_dir):
        return []
    items = []
    try:
        for name in sorted(os.listdir(abs_dir)):
            child_abs = os.path.join(abs_dir, name)
            child_rel = os.path.join(rel, name).replace("\\", "/") if rel else name
            if os.path.isfile(child_abs):
                ext = os.path.splitext(name)[1].lower()
                if ext in SHARED_MEDIA_EXTS:
                    items.append({"name": name, "rel": child_rel, "type": "file", "ext": ext, "size": os.path.getsize(child_abs)})
            elif os.path.isdir(child_abs) and not name.startswith("."):
                children = _scan_dir(base, child_rel, max_depth - 1)
                items.append({"name": name, "rel": child_rel, "type": "folder", "children": children})
    except PermissionError:
        pass
    return items


@router.get("/folders/{folder_id}/tree")
def get_folder_tree(folder_id: str):
    """浏览共享文件夹的文件树（最多 5 层）。"""
    data = _load()
    entry = next((e for e in data.get("folders", []) if e["id"] == folder_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")

    abs_path = os.path.abspath(entry["path"])
    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=404, detail="文件夹已不存在")

    tree = _scan_dir(abs_path)
    return {"folder": {"id": folder_id, "name": entry.get("name"), "path": abs_path}, "tree": tree}


@router.get("/folders/{folder_id}/file")
def get_folder_file(folder_id: str, path: str = ""):
    """读取共享文件夹中的单个文件。"""
    data = _load()
    entry = next((e for e in data.get("folders", []) if e["id"] == folder_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")

    from ..utils import safe_join
    base = os.path.abspath(entry["path"])
    req_path = str(path).strip().lstrip("/").replace("\\", "/")
    try:
        abs_path = safe_join(base, req_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in SHARED_MEDIA_EXTS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    content_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
    return FileResponse(abs_path, media_type=content_type)


# ——— 导入到素材库 ———


@router.post("/folders/import")
async def import_to_library(payload: dict):
    """从共享文件夹导入文件到素材库。

    payload: {
        folder_id: "shared_xxx",
        paths: ["subdir/image1.png", "image2.jpg"],
        category_id: "cat_xxx",
        library_id: "default"
    }
    """
    data = _load()
    entry = next((e for e in data.get("folders", []) if e["id"] == payload.get("folder_id")), None)
    if not entry:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")

    from ..utils import safe_join
    base = os.path.abspath(entry["path"])
    added = []
    for rel in (payload.get("paths") or [])[:200]:
        try:
            abs_path = safe_join(base, str(rel).strip().lstrip("/").replace("\\", "/"))
        except ValueError:
            continue
        if not os.path.isfile(abs_path):
            continue

        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in SHARED_MEDIA_EXTS:
            continue

        # 复制到 input/
        import uuid as _uuid
        filename = f"shared_{_uuid.uuid4().hex[:8]}{ext}"
        dest = os.path.join(config.INPUT_DIR, filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        import shutil
        shutil.copy2(abs_path, dest)

        added.append({
            "url": f"/input/{filename}",
            "name": os.path.basename(abs_path),
            "source": abs_path,
        })

    return {"items": added, "count": len(added)}
