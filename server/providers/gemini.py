"""Gemini Provider —— Google Gemini API。

Gemini 使用与 OpenAI 不同的原生协议：
- Auth: URL 查询参数 ?key=API_KEY
- Base URL: https://generativelanguage.googleapis.com/v1beta
- 消息格式: contents/parts 结构
- 生图: 通过 gemini-2.x-flash-image-preview 等模型对话式生成
"""

import os
import json
import time
import base64
import hashlib
from typing import List, Dict, Any
import httpx

from .base import BaseProvider, ImageResult, VideoResult, ChatResult
from .. import config
from ..logging_config import get_logger

log = get_logger("gemini")


class GeminiProvider(BaseProvider):
    """Google Gemini 原生协议。

    读取环境变量：
    - GEMINI_API_KEY
    - GEMINI_BASE_URL（可选）
    """

    _DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
    _DEFAULT_CHAT_MODEL = "gemini-2.5-flash"
    _DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image-preview"

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def provider_name(self) -> str:
        return "Gemini"

    @property
    def protocol(self) -> str:
        return "gemini"

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("GEMINI_API_KEY")
        if temp: return temp
        val = os.getenv("GEMINI_API_KEY", "")
        return val.strip().strip('"').strip("'")

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        val = os.getenv("GEMINI_BASE_URL", "")
        return val.rstrip("/") if val else self._DEFAULT_BASE

    # ——— 认证 ———

    def build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,  # Gemini 推荐方式，避免 Key 出现在 URL 日志中
        }

    def build_url(self, endpoint: str) -> str:
        endpoint = endpoint.lstrip("/")
        return f"{self._base_url}/{endpoint}"

    # ——— 模型列表 ———

    def list_chat_models(self) -> List[str]:
        return self._model_list_from_env("GEMINI_CHAT_MODELS", [
            self._DEFAULT_CHAT_MODEL,
            "gemini-2.5-pro",
            "gemini-2.5-flash-image-preview",
            "gemini-2.0-flash",
        ])

    def list_image_models(self) -> List[str]:
        return self._model_list_from_env("GEMINI_IMAGE_MODELS", [
            "gemini-2.5-flash-image-preview",
        ])

    # ——— 对话（核心） ———

    def _convert_messages(self, messages: List[dict]) -> List[dict]:
        """将 OpenAI 格式的 messages 转换为 Gemini contents 格式。"""
        contents = []
        system_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append({"text": content})
                continue

            # Gemini roles: user / model (assistant → model)
            gemini_role = "model" if role == "assistant" else "user"

            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list):
                # OpenAI 多模态格式 [{"type":"text","text":"..."}, {"type":"image_url",...}]
                parts = []
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"text": item["text"]})
                    elif item.get("type") == "image_url":
                        img_url = item.get("image_url", {}).get("url", "")
                        if img_url.startswith("data:"):
                            # data:image/png;base64,xxxxx
                            header, b64_data = img_url.split(",", 1)
                            mime_type = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64_data,
                                }
                            })
                        else:
                            parts.append({
                                "file_data": {
                                    "mime_type": "image/jpeg",
                                    "file_uri": img_url,
                                }
                            })
            else:
                parts = [{"text": str(content)}]

            contents.append({"role": gemini_role, "parts": parts})

        return contents, system_parts

    async def chat(
        self, messages: List[dict], model: str = "", **kwargs
    ) -> ChatResult:
        model = model or self._DEFAULT_CHAT_MODEL
        contents, system_parts = self._convert_messages(messages)

        body: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.7),
                "maxOutputTokens": kwargs.get("max_tokens", 4096),
            },
        }
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}

        url = self.build_url(f"models/{model}:generateContent")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini 对话失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        # 解析 Gemini 响应
        candidates = data.get("candidates") or []
        text_parts = []
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in (content.get("parts") or []):
                if "text" in part:
                    text_parts.append(part["text"])

        usage = data.get("usageMetadata") or {}
        return ChatResult(
            content="\n".join(text_parts),
            model=model,
            usage={
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            },
        )

    # ——— 生图（通过 Gemini 多模态模型对话实现） ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        model = model or self._DEFAULT_IMAGE_MODEL
        refs = reference_images or []

        # 构建多模态消息
        parts = [{"text": f"Generate an image based on this description: {prompt}"}]
        if refs:
            for ref in refs[:3]:
                b64_url = await self._load_image_b64(ref)
                if b64_url.startswith("data:"):
                    header, b64_data = b64_url.split(",", 1)
                    mime_type = header.split(":")[1].split(";")[0]
                    parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})

        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.9,
                "responseModalities": ["IMAGE", "TEXT"],
            },
        }

        url = self.build_url(f"models/{model}:generateContent")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini 生图失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        # 提取图片
        candidates = data.get("candidates") or []
        for candidate in candidates:
            for part in (candidate.get("content", {}).get("parts") or []):
                if "inlineData" in part:
                    inline = part["inlineData"]
                    raw = base64.b64decode(inline.get("data", ""))
                    path = self._save_image(raw, "gemini_")
                    return ImageResult(url=path, raw=data)

        raise RuntimeError("Gemini 生图未返回图片数据")

    # ——— 视频生成 ———

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        # Gemini 原生 API 不直接支持视频生成，返回未实现
        raise NotImplementedError("Gemini 原生 API 不支持视频生成，请使用 Veo 通过 APIMart Provider")

    # ——— 测试连接 ———

    async def test_connection(self) -> dict:
        import time as _time
        started = _time.time()
        try:
            # Gemini 用 models 列表检测连通性
            url = self.build_url("models")
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as cli:
                resp = await cli.get(url, headers=self.build_headers())
            elapsed = int((_time.time() - started) * 1000)
            if 200 <= resp.status_code < 300:
                return {"ok": True, "latency_ms": elapsed, "status_code": resp.status_code}
            return {"ok": False, "latency_ms": elapsed, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            elapsed = int((_time.time() - started) * 1000)
            return {"ok": False, "latency_ms": elapsed, "error": str(e)}

    async def fetch_models(self) -> tuple:
        """Gemini models 列表格式不同，覆盖默认实现。返回 (models, live)。"""
        try:
            url = self.build_url("models")
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
                resp = await cli.get(url, headers=self.build_headers())
            if resp.status_code != 200:
                return [], False
            data = resp.json()
            models = []
            from .base import ModelInfo
            for item in (data.get("models") or []):
                name = item.get("name", "").replace("models/", "")
                # 只返回 Gemini 生成模型
                if "gemini" in name.lower():
                    m_type = "chat"
                    if "image" in name.lower():
                        m_type = "image"
                    models.append(ModelInfo(id=name, name=item.get("displayName", name), type=m_type))
            return models, True
        except Exception as e:
            log.debug(f"从 Gemini API 拉取模型列表失败（将使用本地配置）: {e}")
            return [], False
