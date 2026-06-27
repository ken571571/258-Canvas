"""OpenAI 兼容协议 Provider"""

import os
import json
from json import JSONDecodeError
import time
import base64
import hashlib
from typing import List, Dict, Any, Optional
import httpx

from .base import BaseProvider, ImageResult, VideoResult, ChatResult
from .. import config
from ..logging_config import get_logger
from ..security.network import async_validate_safe_url

log = get_logger("openai")


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容协议。

    支持所有遵循 OpenAI API 格式的第三方中转站。
    读取 API/.env 中的 API_PROVIDER_OPENAI_KEY。
    """

    _DEFAULT_BASE = "https://api.openai.com/v1"
    _DEFAULT_IMAGE_MODEL = "dall-e-3"
    _DEFAULT_CHAT_MODEL = "gpt-4o-mini"

    @property
    def provider_id(self) -> str:
        return "openai"

    @property
    def provider_name(self) -> str:
        return "OpenAI 兼容"

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("OPENAI_API_KEY")
        if temp: return temp
        for key in ("API_PROVIDER_OPENAI_KEY", "OPENAI_API_KEY"):
            val = os.getenv(key, "")
            if val:
                return val.strip().strip('"').strip("'")
        return ""

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        return os.getenv("OPENAI_BASE_URL", self._DEFAULT_BASE).rstrip("/")

    # ——— 认证 ———

    def build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def build_url(self, endpoint: str) -> str:
        endpoint = endpoint.lstrip("/")
        base = self._base_url.rstrip("/")
        # 规范化：先移除已有的 /v1 后缀，再统一追加，防止双 /v1 级联
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/v1/{endpoint}"

    # ——— 模型列表 ———

    def _model_list_from_env(self, key: str, fallback: List[str]) -> List[str]:
        raw = os.getenv(key, "")
        items = [s.strip() for s in raw.split(",") if s.strip()]
        return items or fallback

    def list_image_models(self) -> List[str]:
        return self._model_list_from_env("OPENAI_IMAGE_MODELS", [self._DEFAULT_IMAGE_MODEL, "gpt-image-2"])

    def list_chat_models(self) -> List[str]:
        return self._model_list_from_env("OPENAI_CHAT_MODELS", [self._DEFAULT_CHAT_MODEL, "gpt-4o", "deepseek-v4-flash"])

    def list_video_models(self) -> List[str]:
        return self._model_list_from_env("OPENAI_VIDEO_MODELS", ["veo3-fast"])

    # ——— 生图 ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        model = model or self._DEFAULT_IMAGE_MODEL
        refs = reference_images or []

        # 构建请求体
        if refs:
            url = self.build_url("images/edits")
            body: dict = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
                "image": await self._load_image_b64(refs[0]),
            }
            if len(refs) > 1:
                body["mask"] = await self._load_image_b64(refs[1])
        else:
            url = self.build_url("images/generations")
            body = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            }

        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            try:
                data = resp.json()
            except JSONDecodeError:
                raise RuntimeError(f"OpenAI 返回非 JSON 响应 ({resp.status_code}): {resp.text[:500]}")

            # 自动降级重试（最多 2 轮），逐步适配第三方中转 API 的参数差异
            for _retry in range(2):
                if resp.status_code != 400:
                    break
                err_text = resp.text.lower()
                changed = False

                # 降级 1: response_format 参数不支持
                if ("response_format" in err_text or "unknown_parameter" in err_text) and "response_format" in body:
                    log.info("response_format 不被支持，自动降级重试")
                    body.pop("response_format", None)
                    changed = True

                # 降级 2: 图生图 JSON → multipart/form-data（AIHubMix 格式）
                if ("image" in err_text or "images" in err_text) and "image" in body:
                    log.info("切换到 multipart/form-data 文件上传模式")
                    import io as _io
                    # 文本字段用 data，文件用 files（httpx 混合模式）
                    # 优先用 body 中已计算好的 size（如倍率 x2→880x400）
                    # 如果为空才从图片文件读取
                    form_fields = {}
                    for key in ("model", "prompt", "size"):
                        if key in body:
                            val = str(body[key] or "")
                            form_fields[key] = val
                    # size 为空时从图片读尺寸，否则沿用已算好的值
                    img_size_from_file = ""
                    form_files = {}
                    # 图片：从 data URL 解码为二进制
                    ref_data = body.get("image", "")
                    mask_data = body.get("mask", "")
                    if ref_data and ref_data.startswith("data:"):
                        header, b64 = ref_data.split(",", 1)
                        mime = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
                        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(mime, "png")
                        img_bytes = base64.b64decode(b64)
                        form_files["image"] = (f"image.{ext}", _io.BytesIO(img_bytes), mime)
                        if not form_fields.get("size"):
                            try:
                                from PIL import Image as PILImage
                                w, h = PILImage.open(_io.BytesIO(img_bytes)).size
                                w = max(64, ((w + 8) // 16) * 16)
                                h = max(64, ((h + 8) // 16) * 16)
                                img_size_from_file = f"{w}x{h}"
                            except Exception:
                                pass
                        if mask_data and mask_data.startswith("data:"):
                            _, b64_m = mask_data.split(",", 1)
                            form_files["mask"] = (f"mask.{ext}", _io.BytesIO(base64.b64decode(b64_m)), mime)
                    else:
                        # 从本地路径读取
                        try:
                            from ..security.paths import safe_join
                            local = safe_join(config.BASE_DIR, ref_data.lstrip("/"))
                        except ValueError:
                            local = None
                        if local and os.path.isfile(local):
                            ext = os.path.splitext(local)[1].lower()
                            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")
                            with open(local, "rb") as _fref:
                                form_files["image"] = (os.path.basename(local), _io.BytesIO(_fref.read()), mime)
                            if not form_fields.get("size"):
                                try:
                                    from PIL import Image as PILImage
                                    w, h = PILImage.open(local).size
                                    w = max(64, ((w + 8) // 16) * 16)
                                    h = max(64, ((h + 8) // 16) * 16)
                                    img_size_from_file = f"{w}x{h}"
                                except Exception:
                                    pass
                    # 若 JSON 路径未算出 size，回退到文件尺寸
                    if not form_fields.get("size") and img_size_from_file:
                        form_fields["size"] = img_size_from_file
                    elif not form_fields.get("size"):
                        form_fields["size"] = "1024x1024"
                    # 用 multipart 重发
                    resp = await cli.post(
                        url,
                        headers={"Authorization": self.build_headers().get("Authorization", "")},
                        data=form_fields,
                        files=form_files,
                    )
                    if resp.status_code != 200:
                        raise RuntimeError(f"OpenAI 生图失败 ({resp.status_code}): {resp.text[:500]}")
                    data = resp.json()
                    break  # 成功后跳出循环

                if not changed:
                    break

                resp = await cli.post(url, headers=self.build_headers(), json=body)
                data = resp.json()

            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI 生图失败 ({resp.status_code}): {resp.text[:500]}")

            # 降级后的响应（没有 response_format），手动解析图片数据
            if "response_format" not in body:
                log.debug(f"降级后响应: {json.dumps(data, ensure_ascii=False)[:600]}")
                img_url = ""
                d = data.get("data")
                if isinstance(d, list) and d:
                    img_url = d[0].get("url", "")
                    b64 = d[0].get("b64_json", "")
                    if b64:
                        raw = base64.b64decode(b64)
                        path = self._save_image(raw, "openai_")
                        return ImageResult(url=path, raw=data)
                elif isinstance(d, dict):
                    img_url = d.get("url", "") or d.get("b64_json", "")
                elif isinstance(d, str):
                    img_url = d
                if not img_url:
                    img_url = data.get("url", "") or data.get("image_url", "")
                    imgs = data.get("images") or data.get("output") or []
                    if isinstance(imgs, list) and imgs:
                        img_url = imgs[0].get("url", "") if isinstance(imgs[0], dict) else str(imgs[0])
                    elif isinstance(imgs, dict):
                        img_url = imgs.get("url", "")
                if img_url:
                    if img_url.startswith("http"):
                        if await async_validate_safe_url(img_url):
                            try:
                                dl = await cli.get(img_url)
                                if dl.status_code == 200:
                                    path = self._save_image(dl.content, "openai_")
                                    return ImageResult(url=path, raw=data)
                            except Exception:
                                pass
                        else:
                            log.warning(f"SSRF 拦截 — 降级图片 URL: {img_url[:80]}")
                    return ImageResult(url=img_url, raw=data)
                raise RuntimeError(f"OpenAI 生图失败：降级后无图片 URL")

        return self._extract_b64_image(data)

    async def edit_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        # 编辑图片 = 带参考图的生成
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
                raise RuntimeError(f"OpenAI 对话失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})

        # 解析 tool_calls
        tool_calls: List[dict] = []
        raw_tool_calls = msg.get("tool_calls") or []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "arguments": arguments,
            })

        return ChatResult(
            content=msg.get("content", ""),
            model=data.get("model", model),
            usage=data.get("usage"),
            tool_calls=tool_calls,
        )

    # ——— 流式对话 ———

    async def chat_stream(
        self, messages: List[dict], model: str = "", **kwargs
    ):
        """OpenAI 协议 SSE 流式对话，逐 token yield。"""
        import json as _json
        model = model or self._DEFAULT_CHAT_MODEL
        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }
        if kwargs.get("tools"):
            body["tools"] = kwargs["tools"]
            body["tool_choice"] = "auto"

        url = self.build_url("chat/completions")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            async with cli.stream("POST", url, headers=self.build_headers(), json=body) as resp:
                if resp.status_code != 200:
                    error_text = await resp.aread()
                    raise RuntimeError(
                        f"OpenAI 流式对话失败 ({resp.status_code}): {error_text.decode()[:200]}"
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = _json.loads(data_str)
                            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except _json.JSONDecodeError:
                            continue

    # ——— 视频生成 ———

    # 分辨率标签 → 像素尺寸映射
    _RESOLUTION_TO_PX = {
        "480p": "854x480",
        "720p": "1280x720",
        "1080p": "1920x1080",
        "2k": "2560x1440",
        "4k": "3840x2160",
    }

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        model = model or (self.list_video_models() or ["veo3-fast"])[0]
        body: dict = {
            "model": model,
            "prompt": prompt,
        }
        # 优先用 seconds（AIHubMix / Sora 格式），回退 duration
        seconds = str(kwargs.get("seconds", "") or duration)
        if seconds:
            body["seconds"] = seconds
        # size 参数：优先用 kwargs["size"]（前端传入），其次 resolution
        size = str(kwargs.get("size", "") or resolution)
        refs = reference_images or []
        ref_b64 = ""
        ref_url = ""
        if refs:
            ref_b64 = await self._load_image_b64(refs[0])
            ref_url = refs[0]  # 保留原始 URL，用于不支持 base64 的平台
            body["input_reference"] = ref_b64
            if not size or size.lower() == "auto":
                try:
                    if ref_b64.startswith("data:"):
                        _, b64 = ref_b64.split(",", 1)
                        img_bytes = base64.b64decode(b64)
                    else:
                        try:
                            from ..security.paths import safe_join
                            local = safe_join(config.BASE_DIR, ref_b64.lstrip("/"))
                        except ValueError:
                            local = None
                        if local and os.path.isfile(local):
                            with open(local, "rb") as f:
                                img_bytes = f.read()
                    from PIL import Image as PILImage
                    import io as _io2
                    w, h = PILImage.open(_io2.BytesIO(img_bytes)).size
                    size = f"{w}x{h}"
                    log.info(f"视频自动分辨率: 参考图 {w}x{h}")
                except Exception:
                    pass
        if size and size.lower() != "auto":
            body["size"] = size
        # 有声/无声（豆包 Seedance 等模型支持）
        generate_audio = kwargs.get("generate_audio", True)
        if not generate_audio:
            body["generate_audio"] = False

        url = self.build_url("videos")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT * 2, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            try:
                data = resp.json()
            except JSONDecodeError:
                raise RuntimeError(f"OpenAI 返回非 JSON 响应 ({resp.status_code}): {resp.text[:500]}")

            # 自动降级重试（适配不同平台的参数差异）
            for _retry in range(2):
                if resp.status_code != 400:
                    break
                err_text = resp.text.lower()
                changed = False

                # 降级 1: image_urls 参数名（APIMart 格式，只接受 http URL）
                if ("image_urls" in err_text) and "input_reference" in body:
                    log.info("视频: 降级为 image_urls 参数格式")
                    body.pop("input_reference", None)
                    if ref_url and (ref_url.startswith("http://") or ref_url.startswith("https://")):
                        body["image_urls"] = [ref_url]
                    elif ref_url and ref_url.startswith("/"):
                        # 本地文件转 base64 data URL 尝试（APIMart 可能不支持）
                        body["image_urls"] = [ref_b64]
                    else:
                        body["image_urls"] = [ref_b64]
                    changed = True

                # 降级 2: 不支持 input_reference / image_urls，去掉参考图
                if ("input_reference" in err_text or "image_urls" in err_text) and ("input_reference" in body or "image_urls" in body):
                    log.info("视频: 去掉参考图重试")
                    body.pop("input_reference", None)
                    body.pop("image_urls", None)
                    changed = True

                if not changed:
                    break

                resp = await cli.post(url, headers=self.build_headers(), json=body)
                data = resp.json()

            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI 视频生成失败 ({resp.status_code}): {resp.text[:500]}")

        # 提取 task_id：AIHubMix 用 "id"，其他平台可能用 "task_id"
        task_id = data.get("id", "") or data.get("task_id", "")
        # 如果响应里已经有 URL（同步模式），直接返回
        video_url = data.get("url", "")
        return VideoResult(url=video_url, task_id=task_id, raw=data)

    async def query_video_task(self, task_id: str) -> VideoResult:
        """查询 OpenAI 兼容协议的视频任务状态（支持 AIHubMix 等异步视频 API）。

        异步流程: POST /v1/videos → 轮询 GET /v1/videos/{id} → 下载 /v1/videos/{id}/content
        """
        url = self.build_url(f"videos/{task_id}")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            resp = await cli.get(url, headers=self.build_headers())
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI 查询视频任务失败 ({resp.status_code}): {resp.text[:300]}")
            data = resp.json()

        status = str(data.get("status") or "").lower()
        log.debug(f"视频任务状态: {status} keys={list(data.keys())}")

        # 即使状态不是 completed，如果已有 url 就直接下载
        video_url = data.get("url", "") or data.get("video_url", "") or data.get("output_url", "")
        if video_url:
            log.info(f"视频 URL 已就绪 (status={status})")

        if status in ("completed", "succeeded", "success", "done", "ready", "finished", "generated", "processed"):
            import asyncio as _asyncio, hashlib as _hashlib

            # 策略列表：(等待秒数, headers, 说明)
            auth = self.build_headers().get("Authorization", "")
            strategies = [
                (5,  {"Authorization": auth},                       "auth header"),
                (8,  {"Authorization": auth, "User-Agent": "Mozilla/5.0"}, "auth + UA"),
                (12, {"Authorization": auth},                       "auth header (重试)"),
            ]
            # 尝试各平台的下载地址
            download_urls = []
            # 首选 content 端点（AIHubMix / OpenAI 标准）
            content_url = self.build_url(f"videos/{task_id}/content")
            if content_url not in download_urls:
                download_urls.append(content_url)
            # 备选 url 字段（部分平台直接给直链）
            if video_url and video_url != content_url:
                download_urls.append(video_url)

            last_err = ""
            for dl_url in download_urls:
                if not await async_validate_safe_url(dl_url):
                    log.warning(f"SSRF 拦截 — 视频下载 URL: {dl_url[:120]}")
                    last_err = f"SSRF blocked: {dl_url[:80]}"
                    continue
                log.info(f"尝试下载视频: {dl_url[:120]}")
                for attempt_i, (wait_s, headers, desc) in enumerate(strategies):
                    try:
                        if attempt_i == 0:
                            log.info(f"等待 CDN 就绪 {wait_s}s...")
                        await _asyncio.sleep(2 if attempt_i == 0 else wait_s)  # v2.5.52：首次尝试仅 2s，避免无意义等待
                        async with httpx.AsyncClient(timeout=180, follow_redirects=False) as cli:
                            dl = await cli.get(dl_url, headers=headers)
                            # 手动处理重定向，每跳做 SSRF 校验
                            redirect_count = 0
                            while dl.is_redirect and redirect_count < 5:
                                redirect_count += 1
                                next_url = dl.headers.get("location", "")
                                if not next_url:
                                    break
                                if next_url.startswith("/"):
                                    from urllib.parse import urljoin
                                    next_url = urljoin(dl_url, next_url)
                                if not await async_validate_safe_url(next_url):
                                    log.warning(f"SSRF 拦截（视频 CDN 重定向）: {next_url[:120]}")
                                    last_err = f"SSRF blocked (redirect): {next_url[:80]}"
                                    break
                                dl = await cli.get(next_url, headers=headers)
                            if last_err and last_err.startswith("SSRF"):
                                break  # v2.5.50：退出策略循环 → 外层 for 跳到下一个 dl_url
                            if isinstance(dl, httpx.Response) and dl.status_code == 200 and len(dl.content) > 1000:
                                h = _hashlib.md5(dl.content).hexdigest()[:12]
                                ts = int(time.time())
                                filename = f"video_{ts}_{h}.mp4"
                                path = os.path.join(config.OUTPUT_VIDEOS_DIR, filename)
                                os.makedirs(os.path.dirname(path), exist_ok=True)
                                with open(path, "wb") as f:
                                    f.write(dl.content)
                                log.info(f"视频下载成功 [{desc}]: {filename} ({len(dl.content)} bytes)")
                                return VideoResult(url=f"/output/videos/{filename}", task_id=task_id, raw=data)
                            else:
                                last_err = f"HTTP {dl.status_code}"
                                log.warning(f"下载尝试 [{desc}]: {last_err} size={len(dl.content)}")
                    except Exception as e:
                        last_err = f"{type(e).__name__}: {e}"
                        log.warning(f"下载失败 [{desc}]: {last_err}")

            log.error(f"所有下载策略均失败: {last_err}，返回远程 URL")
            # 最后兜底：返回远程 URL，让前端至少能访问原始链接
            return VideoResult(url=video_url or content_url, task_id=task_id, raw=data)
        elif status in ("failed", "fail", "error", "cancelled"):
            err = data.get("error") or {}
            err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"视频生成失败: {err_msg or status}")
        # 仍在处理中
        return VideoResult(url="", task_id=task_id, raw=data)

