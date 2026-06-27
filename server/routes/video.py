"""API 路由：视频生成 —— 薄路由层，业务逻辑委托给 services/video_service.py"""

from fastapi import APIRouter, HTTPException
from ..models import VideoGenerateRequest
from ..providers.registry import get_provider_registry
from ..routes.providers_cfg import resolve_provider
from ..tasks.manager import task_manager
from .. import config
from ..utils import launch_background_task
from ..services.video_service import (
    build_video_result_meta,
    run_video_task,
    query_video_status,
)

router = APIRouter(prefix="/api", tags=["video"])


# ——— 同步视频生成（仅适用于同步 Provider） ———


@router.post("/video/generate")
async def generate_video(req: VideoGenerateRequest):
    """同步视频生成（向后兼容，可能超时）。推荐使用 /api/video/generate/async。"""
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")

    try:
        result = await prov.generate_video(
            prompt=req.prompt,
            duration=req.duration,
            aspect_ratio=req.aspect_ratio,
            model=req.model,
            reference_images=req.reference_images,
            resolution=req.resolution,
            generate_audio=req.generate_audio,
        )
    except NotImplementedError:
        raise HTTPException(status_code=400, detail=f"{prov.provider_name} 不支持视频生成")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"视频生成失败: {e}")

    return {
        "url": result.url,
        "task_id": result.task_id,
        "model": req.model,
    }


# ——— 异步视频生成（推荐） ———


@router.post("/video/generate/async")
async def generate_video_async(req: VideoGenerateRequest):
    """异步视频生成：创建任务后立即返回 task_id，前端轮询结果。"""
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")

    # 模型名校验：确保请求的 model 在 provider 支持的视频模型列表中
    if req.model:
        valid_models = prov.list_video_models()
        if valid_models and not any(m.lower() == req.model.lower() for m in valid_models):
            raise HTTPException(
                status_code=400,
                detail=f"平台 {prov.provider_name} 不支持视频模型: {req.model}。支持的视频模型: {', '.join(valid_models)}"
            )

    # 创建任务，写入初始元数据
    tid = task_manager.create_task("video_generation")

    # 后台执行（委托给 service 层）
    # 注意：update_task("running") 放在后台任务内部，避免启动失败时任务永久卡在 running
    launch_background_task(run_video_task(
        tid=tid,
        prov=prov,
        provider_id=req.provider_id,
        prompt=req.prompt,
        model=req.model,
        duration=req.duration,
        aspect_ratio=req.aspect_ratio,
        reference_images=req.reference_images,
        resolution=req.resolution,
        generate_audio=req.generate_audio,
    ))
    return {"task_id": tid, "status": "queued"}


# ——— 视频任务状态查询 ———


@router.get("/video/status/{task_id}")
async def get_video_status(task_id: str):
    """查询视频任务状态（通过 Provider 续查上游状态）。

    这是专属的视频任务轮询端点，比通用 /api/tasks/{id} 更精确。
    """
    task = task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    # 如果任务已完成，直接返回
    if task.get("status") in ("succeeded", "failed"):
        return task

    # 委托给 service 层进行 Provider 状态续查
    updated = await query_video_status(task_id)
    return updated if updated is not None else task


# ——— 视频 Provider 列表 ———


@router.get("/video/providers")
def list_video_providers():
    """列出支持视频生成的所有 Provider。"""
    provs = get_provider_registry().list_all()
    video_providers = []
    for p in provs:
        models = p.list_video_models()
        if models:
            video_providers.append({
                "id": p.provider_id,
                "name": p.provider_name,
                "video_models": models,
            })
    return {"providers": video_providers}


# ——— 视频模型参数（供前端下拉菜单使用） ———

from ..data.video_model_params import VIDEO_MODEL_DURATIONS, VIDEO_MODEL_RESOLUTIONS


@router.get("/video/model-params")
async def get_video_model_params():
    """返回视频模型参数和轮询配置（供前端下拉菜单和轮询逻辑使用）。"""
    return {
        "durations": VIDEO_MODEL_DURATIONS,
        "resolutions": VIDEO_MODEL_RESOLUTIONS,
        "poll_timeout": config.VIDEO_POLL_TIMEOUT,
        "poll_interval": config.VIDEO_POLL_INTERVAL,
    }
