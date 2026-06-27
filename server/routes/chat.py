"""API 路由：GPT 对话（含流式 SSE 和历史持久化）

路由层职责：HTTP 参数校验、SSE 流式传输。
业务逻辑全部委托给 services/chat_service.py。
"""

import os
import json
import base64
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..models import ChatRequest
from ..routes.providers_cfg import resolve_provider
from .. import config
from ..security.paths import safe_join  # 用于 canvas_llm 本地文件路径安全拼接
from ..services import chat_service

_log = logging.getLogger("canvas571")

router = APIRouter(prefix="/api", tags=["chat"])


def _build_user_content(message: str, reference_images: list):
    """构建用户消息内容，支持图片的多模态格式。"""
    if not reference_images:
        return message or ""
    content = []
    if message:
        content.append({"type": "text", "text": message})
    for img in reference_images:
        content.append({"type": "image_url", "image_url": {"url": img}})
    return content


# ——— 非流式对话（向后兼容） ———


@router.post("/llm")
async def chat(req: ChatRequest):
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")

    # 加载或创建历史
    conv_id = req.conversation_id or chat_service.generate_id()

    async with chat_service.lock_conversation(conv_id):
        messages = chat_service.load_history(conv_id)

        # 构建用户消息（支持图片）
        user_content = _build_user_content(req.message, req.reference_images)

        if not messages:
            if req.system_prompt:
                messages.append({"role": "system", "content": req.system_prompt})
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_content})

        # 限制历史长度
        messages = chat_service.trim_history(messages, config.MAX_HISTORY_MESSAGES)

        result = await prov.chat(messages=messages, model=req.model or "gpt-4o-mini")

        # 保存历史
        messages.append({"role": "assistant", "content": result.content})
        title = chat_service.auto_title(req.message) if len(messages) <= 3 else ""
        await chat_service.save_history(conv_id, messages, title)

    return {
        "reply": result.content,
        "model": result.model,
        "usage": result.usage,
        "conversation_id": conv_id,
    }


# ——— 流式对话（SSE） ———


@router.post("/llm/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式对话端点。

    使用 Server-Sent Events 协议逐 token 返回。
    前端使用 EventSource 或 fetch + ReadableStream 消费。
    """
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")

    conv_id = req.conversation_id or chat_service.generate_id()

    # 在锁内加载历史并追加用户消息（保证事务完整性）
    async with chat_service.lock_conversation(conv_id):
        messages = chat_service.load_history(conv_id)

        user_content = _build_user_content(req.message, req.reference_images)
        if not messages:
            if req.system_prompt:
                messages.append({"role": "system", "content": req.system_prompt})
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_content})

        messages = chat_service.trim_history(messages, config.MAX_HISTORY_MESSAGES)

    async def event_stream():
        full_content = ""
        seq = 0
        stream_error = None
        # SSE 重连间隔（毫秒）
        yield "retry: 3000\n\n"
        try:
            async for token in prov.chat_stream(
                messages=messages,
                model=req.model or "gpt-4o-mini",
                temperature=0.7,
                max_tokens=4096,
            ):
                seq += 1
                full_content += token
                yield f"id: {seq}\n"
                yield f"data: {json.dumps({'content': token})}\n\n"
        except Exception as e:
            stream_error = e
            seq += 1
            yield f"id: {seq}\n"
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        # 仅在流式成功时保存历史（避免保存损坏的部分内容）
        if not stream_error:
            try:
                # 重新获取写锁，并从磁盘重载最新历史（避免覆盖流式期间的并发写入）
                async with chat_service.lock_conversation(conv_id):
                    latest = chat_service.load_history(conv_id)
                    latest.append({"role": "assistant", "content": full_content})
                    title = chat_service.auto_title(req.message) if len(latest) <= 3 else ""
                    await chat_service.save_history(conv_id, latest, title)
            except Exception as save_err:
                _log.error("Failed to save chat history conv=%s: %s", conv_id, save_err)
        else:
            _log.warning("Stream error for conv=%s, history NOT saved: %s", conv_id, stream_error)

        # 始终发送完成信号（含 conversation_id）
        seq += 1
        yield f"id: {seq}\n"
        yield f"data: {json.dumps({'done': True, 'conversation_id': conv_id, 'model': req.model or 'gpt-4o-mini'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


# ——— Canvas 多模态对话 ———


@router.post("/boards/llm")
async def canvas_llm(req: ChatRequest):
    """画布多模态对话端点。

    支持图片和视频输入，自动将本地文件转为 base64 data URL，
    构建多模态 messages 发送给 LLM。
    """
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")

    system_prompt = (req.system_prompt or "").strip()
    model = req.model or "gpt-4o-mini"

    # 构建 messages
    upstream_messages: list = []
    if system_prompt:
        upstream_messages.append({"role": "system", "content": system_prompt})

    # 用户消息：纯文本或多模态
    refs = req.reference_images or []
    if refs:
        # 多模态格式
        content_parts = [{"type": "text", "text": req.message}]
        for ref_url in refs[:8]:
            url = str(ref_url or "").strip()
            if not url:
                continue
            # 转换本地路径为 base64 data URL
            if url.startswith(("http://", "https://", "data:")):
                data_url = url
            elif url.startswith(("/assets/", "/output/")):
                local = safe_join(config.BASE_DIR, url.lstrip("/"))
                if os.path.exists(local):
                    with open(local, "rb") as f:
                        raw = f.read()
                    ext = os.path.splitext(local)[1].lower()
                    mime = {
                        ".png": "image/png", ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg", ".webp": "image/webp",
                        ".gif": "image/gif", ".mp4": "video/mp4",
                        ".webm": "video/webm",
                    }.get(ext, "image/png")
                    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
                else:
                    continue
            else:
                data_url = url
            content_parts.append({"type": "image_url", "image_url": {"url": data_url}})
        upstream_messages.append({"role": "user", "content": content_parts})
    else:
        upstream_messages.append({"role": "user", "content": req.message})

    # 调用 Provider
    result = await prov.chat(messages=upstream_messages, model=model)

    return {
        "text": result.content,
        "model": result.model or model,
        "usage": result.usage,
    }


# ——— 对话管理 ———


@router.get("/threads")
def list_conversations():
    """列出所有对话历史（从元数据索引读取，O(1) 避免遍历全部文件）。"""
    return {"conversations": chat_service.list_conversations()}


@router.get("/threads/{thread_id}")
def get_conversation(thread_id: str):
    """获取指定对话的完整历史。"""
    messages = chat_service.load_history(thread_id)
    if not messages:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"conversation_id": thread_id, "messages": messages}


@router.delete("/threads/{thread_id}")
async def delete_conversation(thread_id: str):
    """删除对话历史（同时清理元数据索引）。"""
    await chat_service.delete_conversation(thread_id)
    return {"ok": True}
