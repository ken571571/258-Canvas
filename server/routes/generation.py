"""API 路由：生图 —— 薄路由层，业务逻辑委托给 services/image_service.py"""

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


# ——— Provider 列表 ———


def _discover_custom_providers_from_env():
    """扫描 .env 发现自定义平台（无 Python Provider 类但配置了 Key 的平台，如 aihubmix）。

    返回 {provider_id: {id, name, protocol, image_models, chat_models, video_models}} 字典。
    """
    import os as _os
    from ..routes.providers_cfg import _read_env, _parse_env, _detect_protocol_from_url, _read_env_model_lists

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
        # 查找模型列表（共用 _read_env_model_lists，与 _inject_custom_models 保持一致）
        models = _read_env_model_lists(pid)
        image_models = models["image_models"]
        chat_models = models["chat_models"]
        video_models = models["video_models"]
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
