"""API 路由：ComfyUI 工作流管理"""

import os
import json
import uuid
import re
import asyncio
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import httpx

from .. import config
from ..logging_config import get_logger
from ..security.paths import safe_join

log = get_logger("workflows")

router = APIRouter(prefix="/api", tags=["workflows"])

# 内置工作流（不可删除）
BUILTIN_WORKFLOWS = {"Z-Image.json", "Z-Image-Enhance.json"}
CUSTOM_FOLDER = "custom"
WORKFLOW_NAME_RE = re.compile(
    rf"^(?:(?:{CUSTOM_FOLDER})/)?[a-zA-Z0-9_一-鿿.\-]+\.json$"
)


def _workflow_path(name: str) -> str:
    """获取工作流文件的完整路径（含安全校验）。"""
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="工作流名称不合法，请使用中文/英文/数字/_-.")
    # 安全校验：使用 safe_join 防止目录穿越
    from ..utils import safe_join
    try:
        return safe_join(config.WORKFLOW_DIR, *name.split("/"))
    except ValueError:
        raise HTTPException(status_code=400, detail="工作流路径不合法")


def _config_path(name: str) -> str:
    """工作流配置文件路径（与工作流同名 + .config.json）。"""
    import re as _re
    return _re.sub(r'\.json$', '.config.json', _workflow_path(name))


def _is_builtin(name: str) -> bool:
    return "/" not in name and os.path.basename(name) in BUILTIN_WORKFLOWS


# ——— 工作流列表 ———


@router.get("/comfyui/workflows")
def list_workflows():
    """列出所有工作流（内置 + 自定义）。"""
    if not os.path.isdir(config.WORKFLOW_DIR):
        return {"workflows": []}

    items = []
    # 内置工作流
    for name in sorted(BUILTIN_WORKFLOWS):
        path = os.path.join(config.WORKFLOW_DIR, name)
        if os.path.exists(path):
            cfg = {}
            cfg_path = _config_path(name)
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f) or {}
                except Exception:
                    cfg = {}
            items.append({
                "name": name,
                "title": cfg.get("title") or name.replace(".json", ""),
                "builtin": True,
                "field_count": len(cfg.get("fields") or []),
            })

    # 自定义工作流（custom/ 目录下）
    custom_dir = os.path.join(config.WORKFLOW_DIR, CUSTOM_FOLDER)
    if os.path.isdir(custom_dir):
        for fn in sorted(os.listdir(custom_dir)):
            if not fn.endswith(".json") or fn.endswith(".config.json"):
                continue
            rel = f"{CUSTOM_FOLDER}/{fn}"
            cfg = {}
            cfg_path = _config_path(rel)
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f) or {}
                except Exception:
                    cfg = {}
            items.append({
                "name": rel,
                "title": cfg.get("title") or fn.replace(".json", ""),
                "builtin": False,
                "field_count": len(cfg.get("fields") or []),
            })

    return {"workflows": items}


# ——— 获取/上传/删除工作流 ———


@router.get("/comfyui/workflows/{name:path}")
def get_workflow(name: str):
    """获取工作流 JSON 内容 + 配置。"""
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="工作流名称不合法")

    path = _workflow_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="工作流不存在")

    with open(path, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    cfg = {"title": os.path.basename(name).replace(".json", ""), "fields": []}
    cfg_path = _config_path(name)
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f) or cfg
        except Exception:
            pass

    return {"name": name, "workflow": workflow, "config": cfg, "builtin": _is_builtin(name)}


@router.post("/comfyui/workflows")
def upload_workflow(payload: dict):
    """上传自定义工作流 JSON。"""
    raw_name = str(payload.get("name", "")).strip()
    workflow_data = payload.get("workflow", payload.get("workflow_json", {}))

    if not raw_name:
        raise HTTPException(status_code=400, detail="工作流名称不能为空")
    if not isinstance(workflow_data, dict) or not workflow_data:
        raise HTTPException(status_code=400, detail="工作流 JSON 不能为空")

    # 统一存入 custom/ 目录
    name = os.path.basename(raw_name)
    if not name.endswith(".json"):
        name += ".json"
    safe_name = f"{CUSTOM_FOLDER}/{name}"

    if not WORKFLOW_NAME_RE.match(safe_name):
        raise HTTPException(status_code=400, detail="工作流名称不合法")

    os.makedirs(os.path.join(config.WORKFLOW_DIR, CUSTOM_FOLDER), exist_ok=True)
    path = _workflow_path(safe_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow_data, f, ensure_ascii=False, indent=2)

    return {"name": safe_name, "message": "工作流上传成功"}


@router.put("/comfyui/workflows/{name:path}/config")
def save_workflow_config(name: str, payload: dict):
    """保存工作流的 UI 配置（字段定义等）。"""
    if _is_builtin(name):
        raise HTTPException(status_code=400, detail="内置工作流不可修改配置")

    path = _workflow_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="工作流不存在")

    cfg_path = _config_path(name)
    cfg = {
        "title": str(payload.get("title") or os.path.basename(name).replace(".json", "")),
        "fields": payload.get("fields") or [],
        "mini_cards": payload.get("mini_cards") or {},
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    return {"name": name, "config": cfg}


@router.delete("/comfyui/workflows/{name:path}")
def delete_workflow(name: str):
    """删除自定义工作流。"""
    if _is_builtin(name):
        raise HTTPException(status_code=400, detail="内置工作流不可删除")

    path = _workflow_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="工作流不存在")

    os.remove(path)
    # 同时删除配置文件
    cfg_path = _config_path(name)
    if os.path.exists(cfg_path):
        os.remove(cfg_path)

    return {"ok": True}


# ——— 运行工作流 ———


@router.post("/comfyui/workflows/{name:path}/run")
async def run_workflow(name: str, payload: dict):
    """运行工作流：注入字段值 → 提交 ComfyUI → 轮询结果。

    payload:
    {
        "fields": {"23::text": "a cat", ...},  # 用户填写的字段值
        "client_id": ""                          # 可选 WebSocket 客户端 ID
    }
    """
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="工作流名称不合法")

    path = _workflow_path(name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="工作流不存在")

    if not config.COMFYUI_INSTANCES:
        raise HTTPException(status_code=400, detail="未配置 ComfyUI 地址")

    # 加载工作流
    with open(path, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    # 注入字段值到工作流节点
    fields = payload.get("fields") or {}
    for field_ref, value in fields.items():
        parts = str(field_ref).split("::")
        node_id = parts[0]
        input_name = parts[1] if len(parts) > 1 else "text"
        if node_id in workflow:
            if "inputs" not in workflow[node_id]:
                workflow[node_id]["inputs"] = {}
            workflow[node_id]["inputs"][input_name] = value

    # 注入随机种子
    import random
    seed = random.randint(1, 10 ** 15)
    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue
        inputs = node_data.get("inputs") or {}
        if "seed" in inputs:
            inputs["seed"] = seed
        if "noise_seed" in inputs:
            inputs["noise_seed"] = seed

    client_id = payload.get("client_id", "canvas571")

    # 选择在线实例（复用 comfyui 的负载均衡）
    from .comfyui import _get_best_backend, _release_backend, _submit_comfyui, _poll_comfyui_task
    addr = await _get_best_backend()

    try:
        # —— 上传参考图到 ComfyUI ——
        # 遍历工作流节点，找到所有图片类型的输入值，
        # 将其上传到 ComfyUI 的 input 目录，并替换为 ComfyUI 可识别的文件名。
        # 支持三种来源：本地路径、远程 URL、Data URL。
        IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        async with httpx.AsyncClient(timeout=30) as cli:
            for node_id, node_data in workflow.items():
                if not isinstance(node_data, dict):
                    continue
                inputs = node_data.get("inputs") or {}
                for input_name, input_value in list(inputs.items()):
                    val = str(input_value) if input_value else ""
                    ext = os.path.splitext(val.split("?")[0])[1].lower()
                    # 跳过明确是文本的值（如提示词）
                    if not (val.startswith("/") or val.startswith("\\") or
                            val.startswith("http://") or val.startswith("https://") or
                            val.startswith("data:") or ext in IMAGE_EXTENSIONS):
                        continue
                    file_data = None
                    filename = "image.png"

                    # 1) Data URL
                    if val.startswith("data:"):
                        try:
                            header, b64_data = val.split(",", 1)
                            mime = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
                            ext2 = {"image/png":".png","image/jpeg":".jpg","image/webp":".webp","image/gif":".gif"}.get(mime, ".png")
                            file_data = __import__("base64").b64decode(b64_data)
                            filename = f"ref_{node_id}_{input_name}{ext2}"
                        except Exception as e:
                            log.warning(f"Data URL 解码失败: {e}")
                            continue

                    # 2) 远程 URL（SSRF 防护：检查目标主机）
                    elif val.startswith("http://") or val.startswith("https://"):
                        from ..security.network import validate_safe_url
                        if not validate_safe_url(val):
                            log.warning(f"SSRF 拦截 — 禁止访问内网地址: {val[:80]}")
                            continue
                        try:
                            r = await cli.get(val, follow_redirects=False)
                            r.raise_for_status()
                            file_data = r.content
                            mime = r.headers.get("content-type", "image/png").split(";")[0]
                            ext2 = {"image/png":".png","image/jpeg":".jpg","image/webp":".webp","image/gif":".gif"}.get(mime, ".png")
                            filename = f"ref_{node_id}_{input_name}{ext2}"
                        except Exception as e:
                            log.warning(f"下载远程图片失败 {val[:80]}: {e}")
                            continue

                    # 3) 本地服务器路径
                    else:
                        local_path = safe_join(config.BASE_DIR, val.lstrip("/"))
                        # 也尝试子目录
                        if not os.path.isfile(local_path):
                            for sub in ["output/images", "output/videos", "input"]:
                                alt = os.path.join(config.BASE_DIR, sub, os.path.basename(val))
                                if os.path.isfile(alt):
                                    local_path = alt
                                    break
                            else:
                                log.warning(f"图片不存在，跳过上传: {val}")
                                continue
                        try:
                            with open(local_path, "rb") as f:
                                file_data = f.read()
                            filename = os.path.basename(local_path)
                        except Exception as e:
                            log.warning(f"读取本地图片失败 {local_path}: {e}")
                            continue

                    if not file_data:
                        continue

                    # 上传到 ComfyUI
                    try:
                        upload_resp = await cli.post(
                            f"http://{addr}/upload/image",
                            files={"image": (filename, file_data)},
                        )
                        if upload_resp.status_code == 200:
                            comfy_name = upload_resp.json().get("name", filename)
                            workflow[node_id]["inputs"][input_name] = comfy_name
                            log.info(f"图片已上传到 ComfyUI: {val[:60]} -> {comfy_name}")
                        else:
                            log.error(f"ComfyUI 上传失败 ({upload_resp.status_code}): {upload_resp.text[:200]}")
                    except Exception as e:
                        log.warning(f"上传图片到 ComfyUI 失败: {e}")

            # 提交
            prompt_id = await _submit_comfyui(addr, workflow, client_id)

            # 轮询
            result = await _poll_comfyui_task(addr, prompt_id)
            result["seed"] = seed
            return result

    finally:
        await _release_backend(addr)
