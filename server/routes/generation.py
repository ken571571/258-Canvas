"""API 路由：生图 —— 薄路由层，业务逻辑委托给 services/image_service.py"""

import asyncio
from fastapi import APIRouter, HTTPException
from ..models import GenerateRequest
from ..providers.registry import get_provider_registry
from ..routes.providers_cfg import resolve_provider
from ..tasks.manager import task_manager
from .. import config
from ..logging_config import get_logger
from ..utils import launch_background_task
from ..services.image_service import (
    auto_detect_provider,
    prepare_image_size,
    build_image_response,
)

log = get_logger("generation")

router = APIRouter(prefix="/api", tags=["generation"])


@router.post("/generate")
async def generate_image(req: GenerateRequest):
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")
    prov = auto_detect_provider(prov, req.model)

    # 模型名校验：确保请求的 model 在 provider 支持的模型列表中
    if req.model:
        valid_models = prov.list_image_models() + prov.list_video_models()
        if valid_models and not any(m.lower() == req.model.lower() for m in valid_models):
            raise HTTPException(
                status_code=400,
                detail=f"平台 {prov.provider_name} 不支持模型: {req.model}。支持的模型: {', '.join(valid_models)}"
            )

    log.info(f"provider={req.provider_id} model={req.model} refs={req.reference_images}")
    try:
        resolved_size = prepare_image_size(req.size, req.reference_images)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await prov.generate_image(
            prompt=req.prompt,
            size=resolved_size,
            model=req.model,
            reference_images=req.reference_images,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="该平台不支持此功能")

    return build_image_response(result.url, req.size, resolved_size, req.model)


# ——— 异步生图（推荐，避免超时） ———


@router.post("/generate/async")
async def generate_image_async(req: GenerateRequest):
    """异步生图：创建任务后立即返回 task_id，前端轮询结果。"""

    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")
    prov = auto_detect_provider(prov, req.model)

    tid = task_manager.create_task("image_generation")
    task_manager.update_task(tid, status="running", progress=10, progress_message="正在提交生图请求…")

    # 后台执行生图
    async def _run():
        try:
            resolved_size = prepare_image_size(req.size, req.reference_images)
            result = await prov.generate_image(
                prompt=req.prompt,
                size=resolved_size,
                model=req.model,
                reference_images=req.reference_images,
            )
            task_manager.update_task(
                tid,
                status="succeeded",
                progress=100,
                progress_message="生图完成",
                result=build_image_response(result.url, req.size, resolved_size, req.model),
            )
        except Exception as e:
            task_manager.update_task(
                tid,
                status="failed",
                progress=0,
                progress_message="生图失败",
                error=str(e),
            )

    launch_background_task(_run())
    return {"task_id": tid, "status": "queued"}


# ——— ComfyUI 异步生成 ———


@router.post("/comfyui/generate/async")
async def comfyui_generate_async(payload: dict):
    """异步 ComfyUI 生图：创建任务后立即返回 task_id。"""

    if not config.COMFYUI_INSTANCES:
        raise HTTPException(status_code=400, detail="未配置 ComfyUI 地址")

    tid = task_manager.create_task("comfyui")
    task_manager.update_task(tid, status="running", progress=5, progress_message="正在连接 ComfyUI…")

    async def _run():
        import httpx
        try:
            # 选择在线实例
            addr = config.COMFYUI_INSTANCES[0]
            async with httpx.AsyncClient(timeout=10) as cli:
                for candidate in config.COMFYUI_INSTANCES:
                    try:
                        await cli.get(f"http://{candidate}/system_stats")
                        addr = candidate
                        break
                    except Exception:
                        continue  # 实例健康检查失败，尝试下一个

            workflow = payload.get("workflow", {})
            client_id = payload.get("client_id", "canvas571")

            body = {"prompt": workflow, "client_id": client_id}
            async with httpx.AsyncClient(timeout=10) as cli:
                resp = await cli.post(f"http://{addr}/prompt", json=body)
                resp.raise_for_status()
                prompt_id = resp.json()["prompt_id"]

            task_manager.update_task(tid, progress=20, progress_message=f"ComfyUI 任务 {prompt_id} 已提交，等待渲染…")

            # 轮询等待完成（基于实际时间，避免 HTTP 超时累加导致远超预期）
            import time as _time
            poll_started = _time.time()
            MAX_WAIT_SEC = 300  # 5分钟硬上限
            async with httpx.AsyncClient(timeout=3) as cli:
                while True:
                    elapsed = _time.time() - poll_started
                    if elapsed > MAX_WAIT_SEC:
                        break
                    await asyncio.sleep(1)
                    try:
                        resp = await cli.get(f"http://{addr}/history/{prompt_id}")
                        hist = resp.json()
                        if prompt_id in hist:
                            outputs = hist[prompt_id].get("outputs", {})
                            images = []
                            for node_out in outputs.values():
                                for item in (node_out.get("images") or []):
                                    fn = item.get("filename", "")
                                    images.append(f"http://{addr}/view?filename={fn}&type=output")
                            task_manager.update_task(
                                tid,
                                status="succeeded",
                                progress=100,
                                progress_message="ComfyUI 渲染完成",
                                result={"images": images, "prompt_id": prompt_id, "backend": addr},
                            )
                            return
                    except Exception:
                        pass  # ComfyUI 轮询瞬态错误，下一轮继续
                    if int(elapsed) % 10 == 0:
                        progress = min(20 + int(elapsed / MAX_WAIT_SEC * 75), 95)
                        task_manager.update_task(tid, progress=progress,
                            progress_message=f"ComfyUI 渲染中 ({int(elapsed)}s)…")

            task_manager.update_task(tid, status="failed", error="ComfyUI 渲染超时")

        except Exception as e:
            task_manager.update_task(tid, status="failed", error=str(e))

    launch_background_task(_run())
    return {"task_id": tid, "status": "queued"}


# ——— Provider 列表 ———


def _discover_custom_providers_from_env():
    """扫描 .env 发现自定义平台（无 Python Provider 类但配置了 Key 的平台，如 aihubmix）。

    返回 {provider_id: {id, name, protocol, image_models, chat_models, video_models}} 字典。
    """
    import os as _os
    from ..routes.providers_cfg import _read_env, _parse_env, _detect_protocol_from_url

    env = _parse_env(_read_env())
    registry_ids = {p.provider_id for p in get_provider_registry().list_all()}

    custom = {}
    for key, value in env.items():
        if not value or not value.strip():
            continue
        upper = key.upper()
        pid = ""
        # 匹配 API_PROVIDER_{X}_KEY 模式
        if upper.startswith("API_PROVIDER_") and upper.endswith("_KEY"):
            pid = upper[len("API_PROVIDER_"):-len("_KEY")].lower()
        # 匹配 {X}_API_KEY 模式（排除已知非 provider 键）
        elif upper.endswith("_API_KEY"):
            pid = upper[:-len("_API_KEY")].lower()
            # 过滤掉一些非 provider 的环境变量
            if pid in ("app",):
                continue
        if not pid or pid in registry_ids or pid in custom:
            continue
        # 查找 Base URL
        base_url = env.get(f"{pid}_BASE_URL", "") or env.get(f"API_PROVIDER_{pid.upper()}_BASE_URL", "")
        # 查找模型列表（大小写不敏感——.env 中的键可能是大写或小写）
        def _get_env_val(key_suffix: str) -> str:
            target = f"{pid}_{key_suffix}".upper()
            for k, v in env.items():
                if k.upper() == target:
                    return v
            return ""
        image_models = [s.strip() for s in _get_env_val("IMAGE_MODELS").split(",") if s.strip()]
        chat_models = [s.strip() for s in _get_env_val("CHAT_MODELS").split(",") if s.strip()]
        video_models = [s.strip() for s in _get_env_val("VIDEO_MODELS").split(",") if s.strip()]
        # 检测协议
        protocol = _detect_protocol_from_url(base_url) or "openai"
        # 名称：尝试从 PID 推导
        name_map = {
            "aihubmix": "AIHubMix", "ds": "DeepSeek", "tl": "TL",
            "su": "SU", "al": "AL",
        }
        custom[pid] = {
            "id": pid,
            "name": name_map.get(pid, pid.upper()),
            "protocol": protocol,
            "image_models": image_models,
            "chat_models": chat_models,
            "video_models": video_models,
        }
    return custom


@router.get("/providers")
def list_providers():
    provs = get_provider_registry().list_all()
    # 已注册（Python 类）平台——仅返回已配置 API Key 的
    result = {}
    for p in provs:
        # 检查是否有可用的 API Key（无 Key 的平台不应出现在下拉列表中）
        api_key = config.get_provider_api_key(p.provider_id)
        if not api_key:
            continue
        result[p.provider_id] = {
            "id": p.provider_id,
            "name": p.provider_name,
            "protocol": p.protocol,
            "image_models": p.list_image_models(),
            "chat_models": p.list_chat_models(),
            "video_models": p.list_video_models(),
        }
    # 合并 .env 中发现的自定义平台（无 Python 类但配置了 Key 的平台）
    custom = _discover_custom_providers_from_env()
    for pid, entry in custom.items():
        if pid not in result:
            result[pid] = entry
    return {"providers": list(result.values())}
