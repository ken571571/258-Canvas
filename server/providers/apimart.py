"""APIMart Provider —— OpenAI 兼容协议变体。

APIMart 是第三方 AI API 聚合平台（如 comfly.chat），
协议与 OpenAI 高度兼容，但有以下差异：
- Base URL 不自动追加 /v1
- 生图使用异步任务模式（提交 → 轮询）
- 视频生成有 image_with_roles 等扩展字段
"""

import os
import json
import time
import base64
import hashlib
import re
from typing import List, Dict, Any, Optional
import httpx
from ..security.network import async_validate_safe_url

from .base import BaseProvider, ImageResult, VideoResult, ChatResult
from .. import config
from ..logging_config import get_logger

log = get_logger("apimart")


class APIMartProvider(BaseProvider):
    """APIMart / ComflyAI 协议。

    读取环境变量：
    - APIMART_API_KEY 或 COMFLY_API_KEY
    - APIMART_BASE_URL 或 COMFLY_BASE_URL
    """

    _DEFAULT_BASE = "https://api.apimart.ai"
    _DEFAULT_IMAGE_MODEL = "nano-banana-pro"
    _DEFAULT_CHAT_MODEL = "gpt-4o-mini"

    @property
    def provider_id(self) -> str:
        return "apimart"

    @property
    def provider_name(self) -> str:
        return "APIMart"

    @property
    def protocol(self) -> str:
        return "apimart"

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("APIMART_API_KEY")
        if temp: return temp
        for key in ("APIMART_API_KEY", "COMFLY_API_KEY"):
            val = os.getenv(key, "")
            if val:
                return val.strip().strip('"').strip("'")
        return ""

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        for key in ("APIMART_BASE_URL", "COMFLY_BASE_URL"):
            val = os.getenv(key, "")
            if val:
                return val.rstrip("/")
        return self._DEFAULT_BASE

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

    def list_image_models(self) -> List[str]:
        return self._model_list_from_env("APIMART_IMAGE_MODELS", [self._DEFAULT_IMAGE_MODEL, "gpt-image-2"])

    def list_chat_models(self) -> List[str]:
        return self._model_list_from_env("APIMART_CHAT_MODELS", [
            self._DEFAULT_CHAT_MODEL, "gpt-4o", "gemini-3.1-flash-image-preview-2k"
        ])

    def list_video_models(self) -> List[str]:
        return self._model_list_from_env("APIMART_VIDEO_MODELS", [
            "veo3-fast", "veo3.1-fast", "veo2", "sora-2",
            "wan2.6-t2v", "doubao-seedance-2-0-260128",
        ])

    # ——— 生图（APIMart 是异步模式） ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        import asyncio
        model = model or self._DEFAULT_IMAGE_MODEL
        refs = reference_images or []

        body: dict = {
            "model": model,
            "prompt": prompt,
            "n": 1,
        }
        # Flux 系列模型不支持 size 参数；空尺寸也不传
        if size and size.strip() and not model.lower().startswith("flux"):
            body["size"] = size

        if refs:
            # APIMart 图生图使用 images/generations 端点（非 images/edits）
            # 通过 image_urls 传 base64 图片数组
            image_urls = []
            for r in refs[:16]:
                b64 = await self._load_image_b64(r)
                if b64:
                    image_urls.append(b64)
            if image_urls:
                body["image_urls"] = image_urls

        url = self.build_url("images/generations")

        # 提交任务
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                err = resp.text[:500]
                log.warning(f"HTTP {resp.status_code}: {err}")
                raise RuntimeError(f"APIMart 生图失败 ({resp.status_code}): {err}")
            data = resp.json()

        # APIMart 异步模式：返回 task_id
        task_items = data.get("data") if data.get("data") is not None else None
        if task_items is None:
            raise RuntimeError("APIMart 返回无任务数据")
        task = task_items[0] if isinstance(task_items, list) else task_items
        task_id = task.get("task_id", "") or task.get("id", "")

        if not task_id:
            # 同步模式回退：直接解析图片
            # APIMart 同步响应可能是 data: [{url, b64_json}] 或 data: {url, b64_json}
            items = data.get("data") if data.get("data") is not None else []
            if isinstance(items, dict):
                items = [items]
            if isinstance(items, list) and items:
                item = items[0]
                if item.get("b64_json"):
                    raw = base64.b64decode(item["b64_json"])
                    path = self._save_image(raw, "apimart_")
                    return ImageResult(url=path, raw=data)
                if item.get("url"):
                    img_url = item["url"]
                    if isinstance(img_url, list):
                        img_url = img_url[0] if img_url else ""
                    if img_url and img_url.startswith("http"):
                        if not await async_validate_safe_url(img_url):
                            log.warning(f"SSRF 拦截 — 上游返回了不安全的图片地址: {img_url[:80]}")
                            raise RuntimeError(f"APIMart 返回了不安全的图片地址（内网/云metadata），已拦截")
                        try:
                            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as dl_cli:
                                dl = await dl_cli.get(img_url)
                                if dl.status_code == 200:
                                    path = self._save_image(dl.content, "apimart_")
                                    return ImageResult(url=path, raw=data)
                        except Exception:
                            pass
                    return ImageResult(url=img_url, raw=data)
            log.warning(f"同步响应无法解析，原始数据: {json.dumps(data, ensure_ascii=False)[:500]}")
            raise RuntimeError(f"APIMart 同步生图返回格式异常，无法提取图片")

        # 轮询任务直到完成
        status_url = self.build_url(f"tasks/{task_id}")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            for i in range(120):  # 最多等 4 分钟
                await asyncio.sleep(2)
                try:
                    s_resp = await cli.get(status_url, headers=self.build_headers())
                    if s_resp.status_code != 200:
                        continue
                    s_data = s_resp.json()
                except Exception:
                    continue

                d = s_data.get("data")
                result = d if isinstance(d, dict) else (d[0] if isinstance(d, list) and d else s_data)
                status = str(result.get("status") or "").lower()

                if status in ("succeeded", "completed", "done", "success"):
                    # 多种可能的图片位置
                    img_url = ""

                    # 1. result.result.images[0].url[0] (APIMart async)
                    inner = result.get("result") or {}
                    if isinstance(inner, dict):
                        imgs = inner.get("images") or []
                        if imgs:
                            u = imgs[0].get("url", "")
                            if isinstance(u, list) and u:
                                img_url = u[0]
                            elif isinstance(u, str):
                                img_url = u

                    # 2. result.b64_json
                    if not img_url and result.get("b64_json"):
                        raw = base64.b64decode(result["b64_json"])
                        path = self._save_image(raw, "apimart_")
                        return ImageResult(url=path, raw=s_data)

                    # 3. result.url
                    if not img_url:
                        u = result.get("url", "")
                        if isinstance(u, list) and u: img_url = u[0]
                        elif isinstance(u, str): img_url = u

                    # 4. result.output / outputs
                    if not img_url:
                        outputs = result.get("output") or result.get("outputs") or {}
                        if isinstance(outputs, dict):
                            for node_out in outputs.values():
                                images = node_out.get("images") or []
                                if images:
                                    u = images[0].get("url", "")
                                    if isinstance(u, list) and u: img_url = u[0]
                                    elif isinstance(u, str): img_url = u
                                    if img_url: break

                    if not img_url:
                        # output[].url might be list
                        for node_out in outputs.values():
                            u = node_out.get("url", "")
                            if isinstance(u, list) and u: img_url = u[0]
                            elif isinstance(u, str): img_url = u
                            if img_url: break

                    if img_url:
                        # 下载到本地
                        if img_url.startswith("http"):
                            from ..security.network import async_validate_safe_url
                            if not await async_validate_safe_url(img_url):
                                raise RuntimeError(f"APIMart 返回了不安全的图片地址（内网/云metadata），已拦截")
                            try:
                                dl = await cli.get(img_url, follow_redirects=False)
                                # v2.5.50：手动处理重定向，每跳做 SSRF 校验
                                redirect_count = 0
                                while dl.is_redirect and redirect_count < 5:
                                    redirect_count += 1
                                    next_url = dl.headers.get("location", "")
                                    if not next_url:
                                        break
                                    if next_url.startswith("/"):
                                        from urllib.parse import urljoin
                                        next_url = urljoin(img_url, next_url)
                                    if not await async_validate_safe_url(next_url):
                                        raise RuntimeError(f"APIMart 重定向到不安全地址，已拦截")
                                    dl = await cli.get(next_url, follow_redirects=False)
                                if dl.status_code == 200:
                                    path = self._save_image(dl.content, "apimart_")
                                    return ImageResult(url=path, raw=s_data)
                            except Exception:
                                pass
                        return ImageResult(url=img_url, raw=s_data)

                    # 所有提取路径都失败 → 打印原始数据辅助排查
                    log.warning(f"任务 {task_id} 已完成，但无法提取图片。原始响应: {json.dumps(s_data, ensure_ascii=False)[:800]}")
                    raise RuntimeError("APIMart 任务完成但无图片输出，请查看服务端日志")

                elif status in ("failed", "error", "cancelled"):
                    err_obj = result.get("error") or {}
                    err_msg = (err_obj.get("message", "") if isinstance(err_obj, dict) else str(err_obj)) or result.get("message", "") or status
                    raise RuntimeError(f"APIMart 生图失败: {err_msg}")

        raise RuntimeError("APIMart 生图任务超时（4 分钟）")

    async def edit_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        return await self.generate_image(prompt, size, model, reference_images, **kwargs)

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
                raise RuntimeError(f"APIMart 对话失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})

        # 解析 tool_calls
        tool_calls = self._parse_tool_calls(msg)

        return ChatResult(
            content=msg.get("content", ""),
            model=data.get("model", model),
            usage=data.get("usage"),
            tool_calls=tool_calls,
        )

    # ——— 视频生成 ———

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        model = model or "veo3-fast"
        # API 参数映射：aspect_ratio → size, resolution → quality
        size = str(kwargs.get("size", "") or aspect_ratio)
        quality = str(kwargs.get("quality", "") or resolution)
        body: dict = {
            "model": model,
            "prompt": prompt,
            "seconds": str(duration),  # AIHubMix 要求字符串格式
            "size": size,
        }
        if quality and quality.lower() != "auto":
            body["quality"] = quality
        refs = reference_images or []
        if refs:
            # API 要求公网可访问的 URL，不支持 base64
            image_urls = []
            for r in refs[:3]:
                url = str(r or "").strip()
                if url.startswith("http://") or url.startswith("https://"):
                    image_urls.append(url)
                elif url.startswith("/"):
                    # 本地路径 → 用 PUBLIC_BASE_URL 拼接公网地址
                    base = config.PUBLIC_BASE_URL
                    if base:
                        image_urls.append(base + url)
                    # 无公网地址则跳过（API 无法访问本地文件）
            if image_urls:
                body["image_urls"] = image_urls

        url = self.build_url("videos/generations")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT * 2, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"APIMart 视频生成失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        # APIMart 响应结构：{"data": {"task_id": "..."}} 或 {"task_id": "..."}
        result = data.get("data") if data.get("data") is not None else data
        if isinstance(result, list):
            result = result[0] if result else {}
        task_id = result.get("task_id") or result.get("id", "")
        return VideoResult(url="", task_id=task_id, raw=data)

    async def query_video_task(self, task_id: str) -> VideoResult:
        """查询 APIMart 视频任务状态。"""
        url = self.build_url(f"tasks/{task_id}")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            resp = await cli.get(url, headers=self.build_headers())
            if resp.status_code != 200:
                raise RuntimeError(f"APIMart 查询视频任务失败 ({resp.status_code}): {resp.text[:300]}")
            data = resp.json()

        # APIMart 响应结构：{"data": {"status": "...", "output": {...}}} 或顶层直接
        result = data.get("data") if data.get("data") is not None else data
        if isinstance(result, list):
            result = result[0] if result else {}

        status = str(result.get("status") or "").upper()
        if status in ("SUCCEED", "SUCCESS", "COMPLETED", "DONE", "SUCCEEDED"):
            # 提取视频 URL（多种可能的响应结构）
            video_url = ""
            outputs = result.get("output") or result.get("outputs") or {}
            if isinstance(outputs, dict):
                video_url = outputs.get("video_url") or outputs.get("url") or ""
                if not video_url:
                    for node_out in outputs.values():
                        if isinstance(node_out, dict):
                            videos = node_out.get("videos") or []
                            if videos:
                                video_url = videos[0].get("url", "")
                                if video_url:
                                    break
            if not video_url:
                inner = result.get("result") or {}
                if isinstance(inner, dict):
                    video_url = inner.get("url") or inner.get("video_url") or ""
            if not video_url:
                video_url = result.get("url") or result.get("video_url") or ""
            # v2.5.52：校验返回的视频 URL 非内网地址
            if video_url:
                from ..security.network import async_validate_safe_url
                if not await async_validate_safe_url(video_url):
                    log.warning(f"SSRF 拦截 — APIMart 视频 URL 指向内网: {video_url[:80]}")
                    video_url = ""
            return VideoResult(url=video_url, task_id=task_id, raw=data)
        elif status in ("FAILED", "FAIL", "ERROR", "CANCELED", "CANCELLED"):
            raise RuntimeError(f"APIMart 视频任务失败: {result.get('error') or result.get('message') or status}")
        # 仍在处理中
        return VideoResult(url="", task_id=task_id, raw=data)

    # ——— 拉取模型 ———

    async def fetch_models(self) -> tuple:
        """APIMart 的 /v1/models 端点可能受限，尝试拉取，失败则返回默认列表。返回 (models, live)。"""
        from .base import ModelInfo
        models = []
        try:
            url = self.build_url("models")
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
                resp = await cli.get(url, headers=self.build_headers())
            if resp.status_code == 200:
                data = resp.json()
                for item in (data.get("data") or data.get("models") or []):
                    m_id = item.get("id", "")
                    m_type = "chat"
                    mid_lower = m_id.lower()
                    if any(k in mid_lower for k in ("image", "dall-e", "flux", "sd", "seedream", "banana")):
                        m_type = "image"
                    elif any(k in mid_lower for k in ("video", "veo", "sora", "seedance", "wan")):
                        m_type = "video"
                    models.append(ModelInfo(id=m_id, name=m_id, type=m_type))
                return models, True
        except Exception:
            pass
        # 回退：返回当前配置的默认模型
        for m in self.list_image_models():
            models.append(ModelInfo(id=m, name=m, type="image"))
        for m in self.list_chat_models():
            models.append(ModelInfo(id=m, name=m, type="chat"))
        for m in self.list_video_models():
            models.append(ModelInfo(id=m, name=m, type="video"))
        return models, False

    # ——— 测试连接 ———

    async def test_connection(self) -> dict:
        """测试连接：发一个最小的聊天请求验证 Key 是否有效。"""
        import time as _time
        started = _time.time()
        try:
            url = self.build_url("chat/completions")
            body = {
                "model": self._DEFAULT_CHAT_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as cli:
                resp = await cli.post(url, headers=self.build_headers(), json=body)
            elapsed = int((_time.time() - started) * 1000)
            if resp.status_code == 200:
                return {"ok": True, "latency_ms": elapsed, "status_code": resp.status_code}
            # 解析错误
            detail = ""
            try:
                err = resp.json()
                detail = err.get("error", {}).get("message", "") or err.get("message", "") or str(err)[:300]
            except Exception:
                detail = resp.text[:300]
            return {"ok": False, "latency_ms": elapsed, "error": f"HTTP {resp.status_code}: {detail}"}
        except Exception as e:
            elapsed = int((_time.time() - started) * 1000)
            return {"ok": False, "latency_ms": elapsed, "error": str(e)}
