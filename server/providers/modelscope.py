"""ModelScope Provider —— 魔搭社区 API。

ModelScope 遵循 OpenAI 兼容协议，额外支持：
- LoRA 插件
- 异步图片生成（提交 → 轮询 task）
- 图片编辑（Image Edit）
"""

import asyncio
import os
import json
import re
import time
import base64
from typing import List, Dict, Any
import httpx
from ..security.network import validate_safe_url

from .base import BaseProvider, ImageResult, VideoResult, ChatResult
from .. import config


class ModelScopeProvider(BaseProvider):
    """ModelScope / 魔搭社区。

    读取环境变量：
    - MODELSCOPE_API_KEY
    """

    _DEFAULT_BASE = "https://api-inference.modelscope.cn/v1"
    _DEFAULT_CHAT_MODEL = "Qwen/Qwen3-235B-A22B"
    _DEFAULT_IMAGE_MODEL = "Tongyi-MAI/Z-Image-Turbo"

    @property
    def provider_id(self) -> str:
        return "modelscope"

    @property
    def provider_name(self) -> str:
        return "ModelScope"

    @property
    def protocol(self) -> str:
        return "openai"  # OpenAI 兼容协议

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("MODELSCOPE_API_KEY")
        if temp: return temp
        val = os.getenv("MODELSCOPE_API_KEY", "")
        return val.strip().strip('"').strip("'")

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        val = os.getenv("MODELSCOPE_BASE_URL", "")
        return val.rstrip("/") if val else self._DEFAULT_BASE

    # ——— 认证 ———

    def build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def build_url(self, endpoint: str) -> str:
        endpoint = endpoint.lstrip("/")
        base = self._base_url
        # 仅在 URL 不含 /v{N} 版本段时追加 /v1
        if not re.search(r'/v\d+$', base):
            base += "/v1"
        return f"{base}/{endpoint}"

    # ——— 模型列表 ———

    def list_chat_models(self) -> List[str]:
        return self._model_list_from_env("MODELSCOPE_CHAT_MODELS", [
            self._DEFAULT_CHAT_MODEL,
            "Qwen/Qwen3-VL-235B-A22B-Instruct",
            "MiniMax/MiniMax-M2.7:MiniMax",
        ])

    def list_image_models(self) -> List[str]:
        return self._model_list_from_env("MODELSCOPE_IMAGE_MODELS", [
            self._DEFAULT_IMAGE_MODEL,
            "Qwen/Qwen-Image-2512",
            "Qwen/Qwen-Image-Edit-2511",
            "black-forest-labs/FLUX.2-klein-9B",
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

        url = self.build_url("chat/completions")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"ModelScope 对话失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})

        return ChatResult(
            content=msg.get("content", ""),
            model=data.get("model", model),
            usage=data.get("usage"),
        )

    # ——— 生图（ModelScope 异步模式） ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        model = model or self._DEFAULT_IMAGE_MODEL
        refs = reference_images or []
        loras = kwargs.get("loras") or []

        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        if refs:
            image_urls = []
            for r in refs[:3]:
                image_urls.append(await self._load_image_b64(r))
            body["image_url"] = image_urls
        if loras:
            body["loras"] = loras

        # 使用异步模式
        headers = {**self.build_headers(), "X-ModelScope-Async-Mode": "true"}
        url = self.build_url("images/generations")

        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"ModelScope 生图失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        # ModelScope 异步模式返回 task_id
        task_id = data.get("task_id", "")
        if task_id:
            # 轮询等待任务完成
            return await self._poll_image_task(task_id, headers)
        # 同步模式直接返回
        return self._extract_b64_image(data)

    async def _poll_image_task(self, task_id: str, headers: dict, max_wait: int = 300) -> ImageResult:
        """轮询 ModelScope 异步图片任务。"""
        url = self.build_url(f"tasks/{task_id}")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            for i in range(max_wait):
                await asyncio.sleep(2)
                resp = await cli.get(
                    url,
                    headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                status = str(data.get("task_status") or "").upper()

                if status == "SUCCEED":
                    img_url = (data.get("output_images") or [""])[0]
                    if img_url:
                        if img_url.startswith("http"):
                            # SSRF 防护：验证下载地址安全
                            if not validate_safe_url(img_url):
                                raise RuntimeError(f"ModelScope 返回了不安全的图片地址（内网/云metadata），已拦截")
                            # 下载远程图片到本地
                            dl_resp = await cli.get(img_url, follow_redirects=False)
                            if dl_resp.status_code == 200:
                                path = self._save_image(dl_resp.content, f"ms_{task_id[:8]}_")
                                return ImageResult(url=path, raw=data)
                        return ImageResult(url=img_url, raw=data)
                    raise RuntimeError("ModelScope 任务完成但无图片输出")

                elif status in ("FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED", "TIMEOUT"):
                    raise RuntimeError(f"ModelScope 生图任务失败: {data}")

        raise RuntimeError("ModelScope 生图任务超时")

    async def edit_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        # ModelScope Image Edit 使用 /api/v1/images/edits 或 Qwen-Image-Edit 模型
        model = model or "Qwen/Qwen-Image-Edit-2511"
        return await self.generate_image(prompt, size, model, reference_images, **kwargs)

    # ——— 视频生成 ———

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        # ModelScope 当前不直接支持视频生成 API
        # 可通过 RunningHub 工作流间接实现
        raise NotImplementedError("ModelScope 原生 API 不支持视频生成")

    # ——— 测试连接 ———

    async def test_connection(self) -> dict:
        import time as _time
        started = _time.time()
        try:
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
