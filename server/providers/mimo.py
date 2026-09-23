"""MiMo (小米 AI) Provider —— OpenAI 兼容协议，认证头使用 api-key 而非 Authorization: Bearer"""

import os
from typing import List

from .openai import OpenAIProvider, ChatResult


class MiMoProvider(OpenAIProvider):

    _DEFAULT_BASE = "https://api.xiaomimimo.com/v1"
    _DEFAULT_CHAT_MODEL = "mimo-v2.5-pro"

    @property
    def provider_id(self) -> str:
        return "xmmimo"

    @property
    def provider_name(self) -> str:
        return "MiMo"

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("MIMO_API_KEY")
        if temp:
            return temp
        # v2.5.55：MIMO_API_KEY 优先（与 env.py get_provider_api_key 顺序一致，避免两 env 值不同时注册校验与实际请求用不同 Key）
        for key in ("MIMO_API_KEY", "XMMIMO_API_KEY", "API_PROVIDER_XMMIMO_KEY"):
            val = os.getenv(key, "").strip().strip('"').strip("'")
            if val:
                return val
        return ""

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE:
            return temp.rstrip("/")
        for key in ("XMMIMO_BASE_URL", "MIMO_BASE_URL"):
            val = os.getenv(key, "").strip()
            if val:
                return val.rstrip("/")
        return self._DEFAULT_BASE

    def build_headers(self) -> dict:
        """MiMo 使用 api-key 而非 Authorization: Bearer。"""
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json",
        }

    def build_url(self, endpoint: str) -> str:
        """MiMo 的 Base URL 已包含 /v1，不需要父类那样 strip 再拼接。"""
        endpoint = endpoint.lstrip("/")
        base = self._base_url.rstrip("/")
        # v2.5.55：兜底——自定义 base_url 若漏写 /v1，自动补全，避免拼出 .../chat/completions 404
        if not base.endswith("/v1"):
            base = base + "/v1"
        return f"{base}/{endpoint}"

    def list_chat_models(self):
        # XMMIMO_CHAT_MODELS 优先（settings 页面写入的命名），MIMO_CHAT_MODELS 作为备选
        # 默认含 mimo-v2.5-pro（chat）与 mimo-v2.5（视觉），后者用于图像识别 Agent
        models = self._model_list_from_env("XMMIMO_CHAT_MODELS", [])
        if models:
            return models
        return self._model_list_from_env("MIMO_CHAT_MODELS", [self._DEFAULT_CHAT_MODEL, "mimo-v2.5"])

    def list_image_models(self):
        return []

    def list_video_models(self):
        return []

    # v2.5.57：mimo-v2.5 是带 reasoning 的模型，默认 max_tokens=4096 会被推理 token 占用，
    # 导致 6 段 H3 提示词 JSON（需 3000-4000 输出 token）时好时坏——推理多时内容被截断。
    # 覆写 chat，将默认输出上限提升到 8192，保证长 JSON 完整输出。
    async def chat(self, messages: List[dict], model: str = "", **kwargs) -> ChatResult:
        if "max_tokens" not in kwargs or not kwargs.get("max_tokens"):
            kwargs["max_tokens"] = 8192
        return await super().chat(messages=messages, model=model, **kwargs)

    # v2.5.55：MiMo 不支持图片/视频生成，显式拒绝，避免继承的 OpenAI 实现向 MiMo 发 /images/generations 404
    async def generate_image(self, *args, **kwargs):
        raise NotImplementedError("MiMo 不支持图片生成")

    async def generate_video(self, *args, **kwargs):
        raise NotImplementedError("MiMo 不支持视频生成")
