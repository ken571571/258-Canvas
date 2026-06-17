"""视频生成服务 —— 从 routes/video.py 抽取的业务逻辑层。

职责：
- 视频任务提交与元数据写入
- 异步视频生成与轮询
- 任务状态恢复与续查

路由层应只保留 HTTP 参数校验、状态码转换和对本服务的调用。
"""

import asyncio
from ..providers.base import BaseProvider, VideoResult
from ..tasks.manager import task_manager
from ..logging_config import get_logger

log = get_logger("video_service")

VIDEO_POLL_TIMEOUT = 600   # 视频轮询总超时（秒）
VIDEO_POLL_INTERVAL = 8    # 轮询间隔（秒）


def build_video_result_meta(
    provider_id: str,
    model: str = "",
    video_url: str = "",
    upstream_task_id: str = "",
) -> dict:
    """构建视频任务结果的标准 metadata。

    本地 task_id 和上游 task_id 必须分开命名：
    - task_id: 本系统内部的 task_id
    - upstream_task_id: 远程 Provider 返回的任务 ID
    """
    return {
        "provider_id": provider_id,
        "model": model,
        "task_id": upstream_task_id,
        "upstream_task_id": upstream_task_id,
        "video_url": video_url,
    }


async def run_video_task(
    tid: str,
    prov: BaseProvider,
    provider_id: str,
    prompt: str,
    model: str = "",
    duration: int = 5,
    aspect_ratio: str = "16:9",
    reference_images: list = None,
    resolution: str = "720p",
    generate_audio: bool = True,
):
    """后台执行视频生成任务（由路由层的 asyncio.create_task 调用）。

    流程：
    1. 提交视频生成请求到 Provider
    2. 如果 Provider 同步返回 URL → 直接完成
    3. 否则轮询 Provider 的 query_video_task 直到完成或超时
    """
    try:
        # 1. 提交视频任务
        try:
            result = await prov.generate_video(
                prompt=prompt,
                duration=duration,
                aspect_ratio=aspect_ratio,
                model=model,
                reference_images=reference_images or [],
                resolution=resolution,
                generate_audio=generate_audio,
            )
        except NotImplementedError:
            task_manager.update_task(tid, status="failed", error=f"{prov.provider_name} 不支持视频生成")
            return

        # 2. 如果返回了 URL，直接完成
        if result.url:
            task_manager.update_task(
                tid, status="succeeded", progress=100,
                progress_message="视频生成完成",
                result=build_video_result_meta(
                    provider_id, model, result.url, result.task_id,
                ),
            )
            return

        # 3. 否则需要轮询异步任务
        if result.task_id:
            task_manager.update_task(
                tid, progress=20,
                progress_message=f"视频任务 {result.task_id} 已提交，等待生成…",
                result=build_video_result_meta(provider_id, model, upstream_task_id=result.task_id),
            )

            for i in range(VIDEO_POLL_TIMEOUT // VIDEO_POLL_INTERVAL):
                await asyncio.sleep(VIDEO_POLL_INTERVAL)
                try:
                    poll_result = await prov.query_video_task(result.task_id)
                except NotImplementedError:
                    task_manager.update_task(tid, status="failed", error="Provider 不支持视频任务轮询")
                    return
                except Exception as e:
                    task_manager.update_task(tid, status="failed", error=str(e))
                    return

                if poll_result.url:
                    task_manager.update_task(
                        tid, status="succeeded", progress=100,
                        progress_message="视频生成完成",
                        result=build_video_result_meta(
                            provider_id, model, poll_result.url, result.task_id,
                        ),
                    )
                    return

                progress = min(20 + int(i / (VIDEO_POLL_TIMEOUT // VIDEO_POLL_INTERVAL) * 75), 95)
                if i % 5 == 0:
                    task_manager.update_task(
                        tid, progress=progress,
                        progress_message=f"视频生成中 ({i * VIDEO_POLL_INTERVAL}s)…",
                    )

            task_manager.update_task(tid, status="failed", error="视频生成超时")
        else:
            task_manager.update_task(tid, status="failed", error="Provider 未返回视频 URL 或 task_id")

    except Exception as e:
        task_manager.update_task(tid, status="failed", error=f"{type(e).__name__}: {e}")


async def query_video_status(task_id: str, prov: BaseProvider = None) -> dict | None:
    """通过 Provider 查询上游视频任务状态并更新本地任务。

    如果 Provider 未提供或查询失败，返回 None（调用方回退到本地 task 数据）。
    """
    task = task_manager.get_task(task_id)
    if task is None:
        return None

    if task.get("status") in ("succeeded", "failed"):
        return task

    meta = task.get("result") or {}
    provider_id = meta.get("provider_id", "")
    upstream_task_id = meta.get("upstream_task_id") or meta.get("task_id") or ""

    if not provider_id or not upstream_task_id:
        return task

    if prov is None:
        from ..routes.providers_cfg import resolve_provider
        prov = resolve_provider(provider_id)

    if not prov:
        return task

    try:
        poll_result = await prov.query_video_task(upstream_task_id)
        if poll_result.url:
            task_manager.update_task(
                task_id, status="succeeded", progress=100,
                progress_message="视频生成完成",
                result={
                    **meta,
                    "video_url": poll_result.url,
                    "provider_id": provider_id,
                    "task_id": upstream_task_id,
                    "upstream_task_id": upstream_task_id,
                },
            )
            return task_manager.get_task(task_id)
    except (NotImplementedError, Exception):
        pass

    return task
