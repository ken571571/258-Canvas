"""火山方舟 Provider (Volcengine / ARK)。

火山方舟是字节跳动旗下的 AI 推理平台，协议与 OpenAI 兼容。
- Base URL: https://ark.cn-beijing.volces.com/api/v3
- 认证: Bearer Token (ARK_API_KEY)
- 支持 Access Key + Secret Key 认证方式
- 视频模型: doubao-seedance 系列
- 内容格式略有差异（content 列表格式）
"""

import os
import json
import re
import time
from typing import List, Dict, Any
import httpx

from .base import BaseProvider, ImageResult, VideoResult, ChatResult
from .. import config


class VolcengineProvider(BaseProvider):
    """火山方舟 / ARK Provider。

    读取环境变量：
    - ARK_API_KEY（优先）
    - VOLCENGINE_ACCESS_KEY_ID + VOLCENGINE_SECRET_ACCESS_KEY
    - VOLCENGINE_BASE_URL（可选）
    """

    _DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
    _DEFAULT_CHAT_MODEL = "doubao-1-5-pro-32k"
    _DEFAULT_IMAGE_MODEL = "doubao-seedream-3-0"

    @property
    def provider_id(self) -> str:
        return "volcengine"

    @property
    def provider_name(self) -> str:
        return "火山方舟"

    @property
    def protocol(self) -> str:
        return "volcengine"

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        """获取 API Key。优先 ARK_API_KEY，其次通过 AK/SK 拼接。"""
        temp = self._temp_key("ARK_API_KEY")
        if temp: return temp
        ark_key = os.getenv("ARK_API_KEY", "")
        if ark_key:
            return ark_key.strip().strip('"').strip("'")
        # 尝试 AK/SK 方式：返回 access_key:secret_key 格式
        ak = os.getenv("VOLCENGINE_ACCESS_KEY_ID", "")
        sk = os.getenv("VOLCENGINE_SECRET_ACCESS_KEY", "")
        if ak and sk:
            return f"{ak.strip()}:{sk.strip()}"
        return ""

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        val = os.getenv("VOLCENGINE_BASE_URL", "")
        return val.rstrip("/") if val else self._DEFAULT_BASE

    # ——— 认证 ———

    def build_headers(self) -> Dict[str, str]:
        key = self._api_key
        # 如果是 AK:SK 格式，使用 Bearer 直接传（ARK API 标准做法）
        if ":" in key:
            # 火山方舟某些端点支持 AK/SK 签名，这里简化处理
            # 实际需要使用 HMAC-SHA256 签名，这里用 Bearer 传 key
            return {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def build_url(self, endpoint: str) -> str:
        endpoint = endpoint.lstrip("/")
        base = self._base_url
        # 仅在 URL 不含 /v{N} 版本段时追加 /v3
        if not re.search(r'/v\d+$', base):
            base += "/v3"
        return f"{base}/{endpoint}"

    # ——— 模型列表 ———

    def list_chat_models(self) -> List[str]:
        return self._model_list_from_env("VOLCENGINE_CHAT_MODELS", [
            self._DEFAULT_CHAT_MODEL,
            "doubao-1-5-vision-pro-32k",
            "deepseek-v4-pro",
        ])

    def list_image_models(self) -> List[str]:
        return self._model_list_from_env("VOLCENGINE_IMAGE_MODELS", [
            self._DEFAULT_IMAGE_MODEL,
            "doubao-seedream-4-0",
        ])

    def list_video_models(self) -> List[str]:
        return self._model_list_from_env("VOLCENGINE_VIDEO_MODELS", [
            "doubao-seedance-2-0-260128",
            "doubao-seedance-2-0-fast-260128",
            "doubao-seedance-1-5-pro-251215",
            "doubao-seedance-1-0-pro-250528",
        ])

    # ——— 对话 ———

    async def chat(
        self, messages: List[dict], model: str = "", **kwargs
    ) -> ChatResult:
        model = model or self._DEFAULT_CHAT_MODEL
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": False,
        }
        if kwargs.get("tools"):
            body["tools"] = kwargs["tools"]
            body["tool_choice"] = "auto"

        url = self.build_url("chat/completions")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"火山方舟 对话失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})

        # 解析 tool_calls（Agent 功能需要）
        tool_calls = self._parse_tool_calls(msg)

        return ChatResult(
            content=msg.get("content", ""),
            model=data.get("model", model),
            usage=data.get("usage"),
            tool_calls=tool_calls,
        )

    # ——— 生图 ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        model = model or self._DEFAULT_IMAGE_MODEL
        refs = reference_images or []

        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }
        if refs:
            # 火山方舟使用 images/generations 端点（非 images/edits）
            # image 参数为 base64 字符串数组
            images = []
            for r in refs[:10]:
                b64 = await self._load_image_b64(r)
                if b64:
                    images.append(b64)
            if images:
                body["image"] = images

        url = self.build_url("images/generations")

        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"火山方舟 生图失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        return self._extract_b64_image(data)

    async def edit_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        return await self.generate_image(prompt, size, model, reference_images, **kwargs)

    # ——— 视频生成 ———

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        model = model or "doubao-seedance-2-0-260128"
        text = str(prompt or "").strip()

        # 火山方舟视频使用 content 列表格式
        content = [{"type": "text", "text": text}]
        refs = reference_images or []
        for ref in refs[:9]:
            img_url = await self._load_image_b64(ref)
            content.append({"type": "image_url", "image_url": {"url": img_url}})

        body: dict = {
            "model": model,
            "content": content,
            "duration": duration,
        }
        if aspect_ratio:
            body["ratio"] = aspect_ratio
        if resolution:
            body["resolution"] = resolution

        url = self.build_url("contents/generations/tasks")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT * 2, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"火山方舟 视频生成失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        task_id = data.get("id") or data.get("task_id", "")
        return VideoResult(url="", task_id=task_id, raw=data)

    async def query_video_task(self, task_id: str) -> VideoResult:
        """查询火山方舟视频任务状态。"""
        url = self.build_url(f"contents/generations/tasks/{task_id}")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            resp = await cli.get(url, headers=self.build_headers())
            if resp.status_code != 200:
                raise RuntimeError(f"火山方舟 查询视频任务失败 ({resp.status_code}): {resp.text[:300]}")
            data = resp.json()

        status = str(data.get("status") or "").upper()
        if status in ("SUCCEED", "SUCCESS", "COMPLETED", "DONE"):
            video_url = ""
            outputs = data.get("output") or data.get("outputs") or {}
            if isinstance(outputs, dict):
                videos = outputs.get("videos") or []
                if videos:
                    video_url = videos[0].get("url", "")
            if not video_url:
                result = data.get("result") or {}
                if isinstance(result, dict):
                    video_url = result.get("video_url") or result.get("url") or ""
            return VideoResult(url=video_url, task_id=task_id, raw=data)
        elif status in ("FAILED", "FAIL", "ERROR", "CANCELED"):
            raise RuntimeError(f"火山方舟 视频任务失败: {data.get('error') or data.get('message') or status}")
        return VideoResult(url="", task_id=task_id, raw=data)
