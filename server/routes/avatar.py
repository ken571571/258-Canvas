"""API 路由：角色一致性（Avatar）

通过注册多角度角色照片，在后续生成中保持角色外观一致。
"""

import os
import json
import uuid
import time
import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File
from .. import config

router = APIRouter(prefix="/api", tags=["avatar"])

AVATAR_FILE = os.path.join(config.DATA_DIR, "avatars.json")
AVATAR_IMAGE_DIR = os.path.join(config.ASSETS_DIR, "avatars")
_write_lock = asyncio.Lock()


def _now():
    return int(time.time() * 1000)


def _load() -> dict:
    if not os.path.exists(AVATAR_FILE):
        return {"avatars": []}
    with open(AVATAR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def _save(data: dict):
    async with _write_lock:
        tmp = AVATAR_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, AVATAR_FILE)


# ——— Avatar CRUD ———


@router.get("/avatars")
def list_avatars():
    """列出所有已注册的角色。"""
    return {"avatars": _load().get("avatars", [])}


@router.post("/avatars")
async def create_avatar(payload: dict):
    """注册新角色。

    payload: {
        name: "小A",
        description: "一个可爱的女孩角色",
        images: ["/assets/output/xxx.png", "/assets/output/yyy.png"],
        prompt_prefix: "a cute girl with long black hair"
    }
    """
    data = _load()
    avatar = {
        "id": f"avatar_{uuid.uuid4().hex[:12]}",
        "name": str(payload.get("name", "未命名角色"))[:80],
        "description": str(payload.get("description", ""))[:500],
        "images": payload.get("images") or [],
        "prompt_prefix": str(payload.get("prompt_prefix", "")),
        "created_at": _now(),
        "updated_at": _now(),
    }
    data.setdefault("avatars", []).append(avatar)
    await _save(data)
    return {"avatar": avatar}


@router.get("/avatars/{avatar_id}")
def get_avatar(avatar_id: str):
    """获取角色详情。"""
    data = _load()
    for avatar in data.get("avatars", []):
        if avatar["id"] == avatar_id:
            return {"avatar": avatar}
    raise HTTPException(status_code=404, detail="角色不存在")


@router.put("/avatars/{avatar_id}")
async def update_avatar(avatar_id: str, payload: dict):
    """更新角色信息。"""
    data = _load()
    for avatar in data.get("avatars", []):
        if avatar["id"] == avatar_id:
            for field in ("name", "description", "prompt_prefix"):
                if field in payload:
                    avatar[field] = str(payload[field])[:500 if field == "description" else 80]
            if "images" in payload:
                avatar["images"] = payload["images"]
            avatar["updated_at"] = _now()
            await _save(data)
            return {"avatar": avatar}
    raise HTTPException(status_code=404, detail="角色不存在")


@router.delete("/avatars/{avatar_id}")
async def delete_avatar(avatar_id: str):
    """删除角色。"""
    data = _load()
    before = len(data.get("avatars", []))
    data["avatars"] = [a for a in data.get("avatars", []) if a["id"] != avatar_id]
    if len(data["avatars"]) == before:
        raise HTTPException(status_code=404, detail="角色不存在")
    await _save(data)
    return {"ok": True}


# ——— 图片上传 ———


@router.post("/avatars/{avatar_id}/images")
async def upload_avatar_image(avatar_id: str, file: UploadFile = File(...)):
    """上传角色参考照片。"""
    data = _load()
    avatar = next((a for a in data.get("avatars", []) if a["id"] == avatar_id), None)
    if not avatar:
        raise HTTPException(status_code=404, detail="角色不存在")

    raw = await file.read()
    ext = os.path.splitext(file.filename or ".png")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="不支持的图片格式")

    os.makedirs(AVATAR_IMAGE_DIR, exist_ok=True)
    filename = f"{avatar_id}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(AVATAR_IMAGE_DIR, filename)
    with open(path, "wb") as f:
        f.write(raw)

    url = f"/assets/avatars/{filename}"
    avatar.setdefault("images", []).append(url)
    avatar["updated_at"] = _now()
    await _save(data)

    return {"url": url, "avatar": avatar}


@router.delete("/avatars/{avatar_id}/images")
async def remove_avatar_image(avatar_id: str, payload: dict):
    """删除角色参考照片（不删除物理文件）。"""
    url = str(payload.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")

    data = _load()
    avatar = next((a for a in data.get("avatars", []) if a["id"] == avatar_id), None)
    if not avatar:
        raise HTTPException(status_code=404, detail="角色不存在")

    before = len(avatar.get("images", []))
    avatar["images"] = [i for i in avatar.get("images", []) if i != url]
    if len(avatar["images"]) == before:
        raise HTTPException(status_code=404, detail="图片不在角色中")

    avatar["updated_at"] = _now()
    await _save(data)
    return {"ok": True, "avatar": avatar}
