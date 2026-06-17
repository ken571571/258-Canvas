"""DeepSeek Provider —— 标准 OpenAI 兼容协议。

DeepSeek 完全遵循 OpenAI API 格式，无需特殊处理。
- Base URL: https://api.deepseek.com
- 文档: https://platform.deepseek.com/api-docs
"""

import os
from typing import List
from .openai import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek API —— 标准 OpenAI 兼容协议。"""

    _DEFAULT_BASE = "https://api.deepseek.com"
    _DEFAULT_CHAT_MODEL = "deepseek-chat"

    @property
    def provider_id(self) -> str:
        return "deepseek"

    @property
    def provider_name(self) -> str:
        return "DeepSeek"

    @property
    def _api_key(self) -> str:
        val = os.getenv("DEEPSEEK_API_KEY", "")
        return val.strip().strip('"').strip("'")

    @property
    def _base_url(self) -> str:
        return os.getenv("DEEPSEEK_BASE_URL", self._DEFAULT_BASE).rstrip("/")

    def list_chat_models(self) -> List[str]:
        return self._model_list_from_env("DEEPSEEK_CHAT_MODELS", [
            self._DEFAULT_CHAT_MODEL, "deepseek-reasoner"
        ])

    def list_image_models(self) -> List[str]:
        return []  # DeepSeek 当前不原生支持生图

    def list_video_models(self) -> List[str]:
        return []
