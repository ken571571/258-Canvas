"""Provider 抽象基类 —— 所有 API 平台必须实现此接口"""

import os
import time
import hashlib
import base64
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
import httpx
from ..logging_config import get_logger
from ..security.network import async_validate_safe_url

log = get_logger("provider")


@dataclass
class ImageResult:
    url: str = ""                # 图片本地路径 /assets/output/xxx.png
    width: int = 0
    height: int = 0
    raw: Any = None              # 上游原始响应


@dataclass
class VideoResult:
    url: str = ""
    raw: Any = None
    task_id: str = ""            # 异步任务 ID，用于后续轮询


@dataclass
class ChatResult:
    content: str = ""
    model: str = ""
    usage: Optional[dict] = None
    tool_calls: List[dict] = field(default_factory=list)


@dataclass
class ModelInfo:
    """模型信息（用于 fetch_models 返回）。"""
    id: str = ""
    name: str = ""
    type: str = ""               # chat / image / video / embedding


class BaseProvider(ABC):
    """API 平台基类。

    子类放在 providers/ 目录下，文件名 = provider_id，
    会被 ProviderRegistry 自动发现和注册。
    """

    # ——— 必须实现的属性/方法 ———

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """唯一标识，如 'openai', 'gemini', 'apimart'"""
        ...

    @property
    def provider_name(self) -> str:
        return self.provider_id

    @property
    def protocol(self) -> str:
        """协议类型标识，用于前端区分处理逻辑。"""
        return "openai"

    @abstractmethod
    def build_headers(self) -> Dict[str, str]:
        """构建请求头（含认证）"""
        ...

    @abstractmethod
    def build_url(self, endpoint: str) -> str:
        """构建完整请求 URL"""
        ...

    # ——— 模型列表 ———

    def list_image_models(self) -> List[str]:
        return []

    def list_chat_models(self) -> List[str]:
        return []

    def list_video_models(self) -> List[str]:
        return []

    # ——— 生图 ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        raise NotImplementedError

    async def edit_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, **kwargs
    ) -> ImageResult:
        raise NotImplementedError

    # ——— 生视频 ———

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        raise NotImplementedError

    async def query_video_task(self, task_id: str) -> VideoResult:
        """查询异步视频任务状态。返回 VideoResult，url 为空表示仍在处理中。"""
        raise NotImplementedError

    # ——— 对话 ———

    async def chat(
        self, messages: List[dict], model: str = "", **kwargs
    ) -> ChatResult:
        raise NotImplementedError

    # ——— 流式对话 ———

    async def chat_stream(
        self, messages: List[dict], model: str = "", **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式对话，逐 token yield。默认回退到非流式 chat()。

        子类可覆盖此方法实现真正的 SSE 流式传输。
        """
        result = await self.chat(messages=messages, model=model, **kwargs)
        yield result.content

    # ——— 工具方法 ———

    async def test_connection(self) -> dict:
        """测试 API 连接是否正常。返回 {ok, latency_ms, error}。"""
        import time as _time
        started = _time.time()
        try:
            # 默认发一个简单的 models 请求
            url = self.build_url("models")
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as cli:
                resp = await cli.get(url, headers=self.build_headers())
            elapsed = int((_time.time() - started) * 1000)
            if 200 <= resp.status_code < 300:
                return {"ok": True, "latency_ms": elapsed, "status_code": resp.status_code, "protocol": self.protocol}
            return {"ok": False, "latency_ms": elapsed, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            elapsed = int((_time.time() - started) * 1000)
            return {"ok": False, "latency_ms": elapsed, "error": str(e)}

    async def fetch_models(self) -> tuple:
        """从上游 API 拉取可用模型列表。

        返回 (models, live)：
        - live=True: 模型来自上游 API 实时拉取
        - live=False: API 不可达，返回的是本地默认/配置模型

        如果拉取失败，回退到返回当前配置的模型列表。
        """
        models = []
        fetched = False
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
                    if any(k in mid_lower for k in ("image", "dall-e", "flux", "sd", "seedream", "banana", "imagen", "midjourney", "playground", "ideogram", "recraft", "sdxl", "stable-diffusion", "kolors", "hunyuan", "ernie-vilg", "cogview")):
                        m_type = "image"
                    elif any(k in mid_lower for k in ("video", "veo", "sora", "seedance", "wanx", "t2v", "i2v", "cogvideo", "cogvideox", "videox", "vidu", "kling", "hailuo", "pika", "runway", "gen", "luma", "morph", "stable-video")):
                        m_type = "video"
                    elif any(k in mid_lower for k in ("embedding", "text-embedding")):
                        m_type = "embedding"
                    models.append(ModelInfo(id=m_id, name=m_id, type=m_type))
                if models:
                    fetched = True
        except Exception as e:
            log.debug(f"从上游 API 拉取模型列表失败（将使用本地配置）: {e}")

        # 回退：返回当前配置的模型列表
        if not fetched:
            for m in self.list_image_models():
                if not any(x.id == m for x in models):
                    models.append(ModelInfo(id=m, name=m, type="image"))
            for m in self.list_chat_models():
                if not any(x.id == m for x in models):
                    models.append(ModelInfo(id=m, name=m, type="chat"))
            for m in self.list_video_models():
                if not any(x.id == m for x in models):
                    models.append(ModelInfo(id=m, name=m, type="video"))
        return models, fetched

    # ——— 通用辅助方法 ———

    async def _load_image_b64(self, url: str, download_remote: bool = True) -> str:
        """将本地路径或 http URL 转为 base64 data URL（异步）。

        Args:
            url: 图片路径或 URL
            download_remote: 是否下载远程 URL 并转 base64（默认 True）。
                           设为 False 时直接返回原 URL（部分 API 接受原始 URL）。
        """
        if url.startswith("data:"):
            return url
        if url.startswith("http://") or url.startswith("https://"):
            if not download_remote:
                return url
            # SSRF 防护：检查目标主机是否安全
            if not await async_validate_safe_url(url):
                log.warning(f"SSRF 拦截 — 禁止访问内网地址: {url[:80]}")
                raise ValueError(f"安全拦截：禁止访问内网地址")
            # 下载远程图片并转为 base64（异步，不阻塞事件循环）
            # SSRF 纵深防御：禁用自动重定向跟随，手动校验每一跳
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=30, follow_redirects=False) as _cli:
                    r = await _cli.get(url)
                    # 手动处理重定向，每跳都做 SSRF 校验
                    redirect_count = 0
                    while r.is_redirect and redirect_count < 5:
                        redirect_count += 1
                        next_url = r.headers.get("location", "")
                        if not next_url:
                            break
                        if next_url.startswith("/"):
                            from urllib.parse import urljoin
                            next_url = urljoin(url, next_url)
                        if not await async_validate_safe_url(next_url):
                            log.warning(f"SSRF 拦截（重定向目标）: {next_url[:80]}")
                            raise ValueError(f"安全拦截：重定向目标指向内网地址")
                        r = await _cli.get(next_url)
                    r.raise_for_status()
                    raw = r.content
                    mime = r.headers.get("content-type", "image/png")
                b64 = base64.b64encode(raw).decode("ascii")
                log.debug(f"图片转 base64: {url[:80]} ({len(raw)} bytes)")
                return f"data:{mime};base64,{b64}"
            except Exception as e:
                log.debug(f"下载远程图片失败: {url[:80]} — {e}")
                return url  # 回退：返回原始 URL
        # 本地路径
        from .. import config
        from ..security.paths import safe_join
        if url.startswith("/output/"):
            local = safe_join(config.OUTPUT_DIR, url[len("/output/"):].lstrip("/"))
        elif url.startswith("/input/"):
            local = safe_join(config.INPUT_DIR, url[len("/input/"):].lstrip("/"))
        elif url.startswith("/assets/"):
            local = safe_join(config.ASSETS_DIR, url[len("/assets/"):].lstrip("/"))
        else:
            local = safe_join(config.BASE_DIR, url.lstrip("/"))
        if os.path.isfile(local) and local.startswith(str(config.BASE_DIR)):
            with open(local, "rb") as f:
                raw = f.read()
            ext = os.path.splitext(local)[1].lower()
            mime = {
                ".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(ext, "image/png")
            log.debug(f"图片转 base64: {url[:80]} ({len(raw)} bytes)")
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        log.debug(f"图片文件未找到: {url} -> {local}")
        return url

    def _save_image(self, raw: bytes, prefix: str = "gen_") -> str:
        """将二进制图片保存到 output/images/ 目录，返回路径。"""
        from .. import config
        h = hashlib.md5(raw).hexdigest()[:12]
        ts = int(time.time())
        filename = f"{prefix}{ts}_{h}.png"
        # 优先新路径 output/images/
        path = os.path.join(config.OUTPUT_IMAGES_DIR, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(raw)
        return f"/output/images/{filename}"

    def _extract_b64_image(self, data: dict, key: str = "b64_json") -> ImageResult:
        """从 API 响应中提取 base64 图片并保存到本地。"""
        items = data.get("data") or []
        if isinstance(items, dict):
            items = [items]  # 兼容部分 API 返回 dict 而非 list
        if not items:
            raise RuntimeError(f"{self.provider_name} 返回无图片数据")
        item = items[0]
        if item.get("url"):
            return ImageResult(url=item["url"], raw=data)
        if item.get(key):
            raw = base64.b64decode(item[key])
            path = self._save_image(raw, f"{self.provider_id}_")
            return ImageResult(url=path, raw=data)
        raise RuntimeError(f"无法解析 {self.provider_name} 返回的图片")

    def _temp_key(self, env_key: str) -> str:
        """检查是否有前端传入的临时 Key（验证/拉取时使用）。"""
        # 优先：实例属性（_get_or_create_provider 注入）
        if hasattr(self, '_injected_key') and self._injected_key:
            return self._injected_key
        # 其次：临时环境变量
        import os as _os
        temp = _os.getenv(f"_TEMP_{self.provider_id.upper()}_KEY", "")
        return temp if temp else _os.getenv(env_key, "")

    def _temp_url(self, default: str) -> str:
        """检查是否有前端传入的临时 URL。"""
        # 优先：实例属性（_get_or_create_provider 注入）
        if hasattr(self, '_injected_url') and self._injected_url:
            return self._injected_url
        # 其次：临时环境变量
        import os as _os
        temp = _os.getenv(f"_TEMP_{self.provider_id.upper()}_URL", "")
        return temp if temp else default

    def _model_list_from_env(self, key: str, fallback: List[str]) -> List[str]:
        """从环境变量读取逗号分隔的模型列表。"""
        import os as _os
        raw = _os.getenv(key, "")
        items = [s.strip() for s in raw.split(",") if s.strip()]
        return items or fallback

    @staticmethod
    def _parse_tool_calls(msg: dict) -> List[dict]:
        """从 OpenAI 协议的 Chat Completion 消息中解析 tool_calls。

        所有 OpenAI 兼容协议的子类共享此逻辑，避免重复实现。
        """
        import json as _json
        tool_calls: List[dict] = []
        for tc in (msg.get("tool_calls") or []):
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                arguments = _json.loads(args_str) if isinstance(args_str, str) else args_str
            except _json.JSONDecodeError:
                arguments = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "arguments": arguments,
            })
        return tool_calls
