"""API 路由：GPT 对话（含流式 SSE 和历史持久化）"""

import os
import json
import uuid
import time
import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..models import ChatRequest
from ..providers.registry import get_provider_registry
from ..routes.providers_cfg import resolve_provider
from .. import config
from ..storage.json_store import store

router = APIRouter(prefix="/api", tags=["chat"])


import base64 as _base64


def _conv_path(conversation_id: str) -> str:
    # UUID 格式 ID (conv_ + hex) 直接使用，避免碰撞
    if conversation_id.startswith("conv_") and re.match(r"^conv_[a-f0-9]+$", conversation_id):
        safe = conversation_id
    else:
        # 非标准 ID：使用 URL-safe base64 编码防碰撞
        safe = "conv_" + _base64.urlsafe_b64encode(
            conversation_id.encode("utf-8")
        ).decode("ascii").rstrip("=")
    return os.path.join(config.HISTORY_DIR, f"{safe}.json")


def _load_history(conversation_id: str) -> list:
    data = store.read(_conv_path(conversation_id), default={"messages": []})
    return data.get("messages", [])


async def _save_history(conversation_id: str, messages: list, title: str = ""):
    data = {
        "id": conversation_id,
        "title": title or "对话",
        "updated_at": int(time.time() * 1000),
        "messages": messages,
    }
    await store.write_with_timestamp(_conv_path(conversation_id), data)


def _u():
    return uuid.uuid4().hex[:12]


def _auto_title(user_msg: str) -> str:
    """根据用户第一条消息自动生成对话标题。"""
    return (user_msg[:40] + "…") if len(user_msg) > 40 else user_msg


# ——— 非流式对话（向后兼容） ———


@router.post("/llm")
async def chat(req: ChatRequest):
    prov = resolve_provider(req.provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {req.provider_id}")

    # 加载或创建历史
    conv_id = req.conversation_id or f"conv_{_u()}"
    messages = _load_history(conv_id)

    if not messages:
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        messages.append({"role": "user", "content": req.message})
    else:
        messages.append({"role": "user", "content": req.message})

    # 限制历史长度
    if len(messages) > config.MAX_HISTORY_MESSAGES + 2:
        # 保留 system prompt 和最近的消息
        system_msgs = [m for m in messages if m["role"] == "system"]
        other_msgs = [m for m in messages if m["role"] != "system"]
        messages = system_msgs + other_msgs[-(config.MAX_HISTORY_MESSAGES):]

    result = await prov.chat(messages=messages, model=req.model)

    # 保存历史
    messages.append({"role": "assistant", "content": result.content})
    title = _auto_title(req.message) if len(messages) <= 3 else ""
    await _save_history(conv_id, messages, title)

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

    conv_id = req.conversation_id or f"conv_{_u()}"
    messages = _load_history(conv_id)

    if not messages:
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        messages.append({"role": "user", "content": req.message})
    else:
        messages.append({"role": "user", "content": req.message})

    if len(messages) > config.MAX_HISTORY_MESSAGES + 2:
        system_msgs = [m for m in messages if m["role"] == "system"]
        other_msgs = [m for m in messages if m["role"] != "system"]
        messages = system_msgs + other_msgs[-(config.MAX_HISTORY_MESSAGES):]

    async def event_stream():
        full_content = ""
        seq = 0
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
            seq += 1
            yield f"id: {seq}\n"
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        # 保存历史
        messages.append({"role": "assistant", "content": full_content})
        title = _auto_title(req.message) if len(messages) <= 3 else ""
        await _save_history(conv_id, messages, title)

        # 发送完成信号（含 conversation_id）
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
                import base64
                local = os.path.join(config.BASE_DIR, url.lstrip("/").replace("/", os.sep))
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
    """列出所有对话历史。"""
    os.makedirs(config.HISTORY_DIR, exist_ok=True)
    items = []
    for fn in os.listdir(config.HISTORY_DIR):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(config.HISTORY_DIR, fn), "r", encoding="utf-8") as f:
                    data = json.load(f)
                items.append({
                    "id": data.get("id", fn[:-5]),
                    "title": data.get("title", "对话"),
                    "updated_at": data.get("updated_at", 0),
                    "message_count": len(data.get("messages", [])),
                })
            except Exception:
                pass
    items.sort(key=lambda c: c.get("updated_at", 0), reverse=True)
    return {"conversations": items}


@router.get("/threads/{thread_id}")
def get_conversation(thread_id: str):
    """获取指定对话的完整历史。"""
    messages = _load_history(thread_id)
    if not messages:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"conversation_id": thread_id, "messages": messages}


@router.delete("/threads/{thread_id}")
def delete_conversation(thread_id: str):
    """删除对话历史。"""
    p = _conv_path(thread_id)
    if os.path.exists(p):
        os.remove(p)
    return {"ok": True}
