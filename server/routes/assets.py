"""API 路由：素材/文件"""

import os
import uuid
import time
import hashlib
from fastapi import APIRouter, HTTPException, UploadFile, File
from .. import config

router = APIRouter(prefix="/api", tags=["assets"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    from ..utils import read_upload_safely
    raw = await read_upload_safely(file, config.LOCAL_IMAGE_IMPORT_MAX_BYTES)  # v2.5.40：流式读取防 OOM

    ext = os.path.splitext(file.filename or ".png")[1].lower()
    if ext not in config.LOCAL_IMAGE_IMPORT_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

    h = hashlib.md5(raw).hexdigest()[:12]
    ts = int(time.time())
    filename = f"upload_{ts}_{h}{ext}"
    # 保存到 input/ 目录
    path = os.path.join(config.INPUT_DIR, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)

    # 读取图片尺寸
    w, h = 0, 0
    try:
        from PIL import Image as PILImage
        import io as _io
        w, h = PILImage.open(_io.BytesIO(raw)).size
    except Exception:
        pass
    return {"url": f"/input/{filename}", "name": file.filename, "width": w, "height": h}


@router.get("/assets/list")
def list_assets(dir: str = "input"):
    """列出 input/ 或 output/ 目录下的所有媒体文件。"""
    if dir == "input":
        scan_dir = config.INPUT_DIR
        url_prefix = "/input/"
    elif dir == "output":
        scan_dir = config.OUTPUT_DIR
        url_prefix = "/output/"
    else:
        raise HTTPException(status_code=400, detail="dir 必须是 input 或 output")

    if not os.path.isdir(scan_dir):
        return {"files": []}

    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov"}

    def _scan(directory: str, rel: str = "") -> list:
        items = []
        try:
            for name in sorted(os.listdir(directory), reverse=True):
                if name.startswith("."):
                    continue
                full = os.path.join(directory, name)
                child_rel = os.path.join(rel, name).replace("\\", "/") if rel else name
                if os.path.isfile(full) and os.path.splitext(name)[1].lower() in exts:
                    items.append({
                        "name": name,
                        "url": url_prefix + child_rel,
                        "size": os.path.getsize(full),
                        "updated_at": int(os.path.getmtime(full) * 1000),
                    })
                elif os.path.isdir(full):
                    items.extend(_scan(full, child_rel))
        except Exception:
            pass
        return items

    return {"files": _scan(scan_dir)}


@router.delete("/assets/delete")
def delete_asset(url: str = ""):
    """删除 input/ 或 output/ 下的文件。"""
    url = str(url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")

    # 解析路径
    if url.startswith("/input/"):
        base_dir = config.INPUT_DIR
        rel = url[len("/input/"):]
    elif url.startswith("/output/"):
        base_dir = config.OUTPUT_DIR
        rel = url[len("/output/"):]
    else:
        raise HTTPException(status_code=400, detail="只能删除 input/ 或 output/ 下的文件")

    # 安全：防目录穿越（使用标准路径安全函数）
    rel = rel.replace("\\", "/").split("?")[0]
    try:
        from ..utils import safe_join
        path = safe_join(base_dir, rel)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")

    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")

    os.remove(path)
    return {"ok": True}
