"""API 路由：LLM 对话（非流式）

注意：独立的「Chat 对话」页面功能（chat.html 页面、多会话历史管理页）已移除。
本端点 /api/llm 仅保留给 Agent 设计器（agents.html 的 Prompt Engineer 助手）
等内部调用方使用，通过 conversation_id 维护多轮历史。
历史持久化逻辑委托给 services/chat_service.py。
"""

import logging
from fastapi import APIRouter, HTTPException
from ..models import ChatRequest
from ..routes.providers_cfg import resolve_provider
from .. import config
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


# ——— LLM 对话（非流式，供 Agent 设计器等内部调用） ———


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
