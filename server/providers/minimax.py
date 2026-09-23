"""MiniMax Provider —— MiniMax H3 视频生成（V2 接口）

API 文档:
- 创建: https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create
- 查询: https://platform.minimaxi.com/docs/api-reference/video-generation-v2-query

端点:
- 创建任务: POST https://api.minimax.cn/v2/video_generation
- 查询任务: GET  https://api.minimax.cn/v2/query/video_generation/{task_id}
- 认证:     Authorization: Bearer <API_KEY>

模型:
- MiniMax-H3      : 文生视频 / 图生视频(首尾帧) / 多模态参考, 768P/2K, 4~15s
- MiniMax-H3-Max  : 文生视频 / 图生视频(首帧/尾帧), 480P/768P, 5~15s (极速版)
"""

import os
import time
import hashlib
from typing import List, Dict, Any
import httpx

from .base import BaseProvider, _safe_error_text, VideoResult
from .. import config
from ..logging_config import get_logger
from ..security.network import async_validate_safe_url

log = get_logger("minimax")


class MiniMaxProvider(BaseProvider):
    """MiniMax H3 视频生成 Provider。

    读取环境变量:
    - MINIMAX_API_KEY（优先）/ API_PROVIDER_MINIMAX_KEY
    - MINIMAX_BASE_URL（可选，默认 https://api.minimax.cn）
    - MINIMAX_VIDEO_MODELS（可选，逗号分隔的自定义模型列表）
    """

    _DEFAULT_BASE = "https://api.minimax.cn"
    _DEFAULT_VIDEO_MODEL = "MiniMax-H3"

    @property
    def provider_id(self) -> str:
        return "minimax"

    @property
    def provider_name(self) -> str:
        return "MiniMax"

    @property
    def protocol(self) -> str:
        return "minimax"

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("MINIMAX_API_KEY")
        if temp:
            return temp
        for key in ("MINIMAX_API_KEY", "API_PROVIDER_MINIMAX_KEY"):
            val = os.getenv(key, "")
            if val:
                return val.strip().strip('"').strip("'")
        return ""

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE:
            return temp.rstrip("/")
        val = os.getenv("MINIMAX_BASE_URL", "")
        return val.rstrip("/") if val else self._DEFAULT_BASE

    # ——— 认证 ———

    def build_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def build_url(self, endpoint: str) -> str:
        """构建 URL。MiniMax V2 接口统一在 /v2/ 下。"""
        endpoint = endpoint.lstrip("/")
        base = self._base_url.rstrip("/")
        # 规范化：移除已有的 /v2 后缀再统一追加，防止双 /v2
        if base.endswith("/v2"):
            base = base[:-3]
        return f"{base}/v2/{endpoint}"

    # ——— 模型列表 ———

    def list_video_models(self) -> List[str]:
        return self._model_list_from_env("MINIMAX_VIDEO_MODELS", [
            "MiniMax-H3",
            "MiniMax-H3-Max",
        ])

    def list_chat_models(self) -> List[str]:
        return []

    def list_image_models(self) -> List[str]:
        return []

    # ——— 参数映射 ———

    # 系统分辨率 → MiniMax 分辨率档位
    _RESOLUTION_MAP = {
        "480p": "480P",
        "720p": "768P",
        "768p": "768P",
        "1080p": "2K",
        "2k": "2K",
        "4k": "2K",
        "480P": "480P",
        "768P": "768P",
        "2K": "2K",
    }

    def _map_resolution(self, resolution: str, model: str) -> str:
        """将系统分辨率映射到 MiniMax 支持的档位。"""
        r = (resolution or "").strip()
        mapped = self._RESOLUTION_MAP.get(r, self._RESOLUTION_MAP.get(r.lower(), "768P"))
        # H3-Max 不支持 2K，降级到 768P
        if model.endswith("-Max") and mapped == "2K":
            return "768P"
        return mapped

    def _clamp_duration(self, duration: int, model: str) -> int:
        """时长限制：H3 4~15s，H3-Max 5~15s。"""
        try:
            d = int(duration)
        except (ValueError, TypeError):
            d = 5
        min_d = 5 if model.endswith("-Max") else 4
        return max(min_d, min(15, d))

    # ——— 视频生成 ———

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", reference_audio: List[str] = None,
        **kwargs
    ) -> VideoResult:
        model = model or self._DEFAULT_VIDEO_MODEL
        text = str(prompt or "").strip()
        if not text:
            raise RuntimeError("MiniMax 视频生成需要非空 prompt")

        # 构建 content 多模态数组
        content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
        refs = reference_images or []
        audios = reference_audio or []

        # 音频参考（r2va 多模态参考）：仅 MiniMax-H3 支持，H3-Max 不支持
        if audios:
            if model.endswith("-Max"):
                raise RuntimeError("MiniMax-H3-Max 不支持音频参考，请选择 MiniMax-H3")
            # MiniMax 音频限制：WAV/MP3，单文件 ≤15MB，个数 ≤3
            if len(audios) > 3:
                raise RuntimeError(f"MiniMax 音频参考最多支持 3 个，当前 {len(audios)} 个")
            for au in audios[:3]:
                au_ext = os.path.splitext(str(au).split("?")[0])[1].lower()
                if au_ext not in (".wav", ".mp3"):
                    raise RuntimeError(f"MiniMax 音频参考仅支持 WAV/MP3 格式，当前: {au_ext or '未知格式'}")
                try:
                    au_data = await self._load_audio_b64(au)
                except Exception as e:
                    raise RuntimeError(f"音频参考加载失败: {e}")
                # base64 后体积膨胀约 1.33 倍，反推原始大小做 15MB 校验
                import base64 as _b64
                if au_data.startswith("data:") and "base64," in au_data:
                    raw_size = len(au_data.split("base64,", 1)[1]) * 3 // 4
                    if raw_size > 15 * 1024 * 1024:
                        raise RuntimeError(f"MiniMax 音频参考单文件不能超过 15MB，当前约 {raw_size // (1024*1024)}MB")
                content.append({
                    "type": "audio_url",
                    "audio_url": {"url": au_data},
                    "role": "reference_audio",
                })

        if refs:
            # 1张→首帧；2张→首尾帧；>2张→多模态参考图（前9张）
            # 注意：first_frame/last_frame 与 reference_image 互斥，不可混用
            # 关键：当存在 reference_audio（r2va 全参考模式）时，已进入 reference 场景，
            #       图片必须全部用 reference_image，不能用 first_frame/last_frame，否则 H3 报 (2013) 混用错误
            if audios:
                # r2va 全参考模式：音频参考已触发 reference 场景，图片全部用 reference_image
                for ref in refs[:9]:
                    img_url = await self._load_image_b64(ref)
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url},
                        "role": "reference_image",
                    })
            elif len(refs) == 1:
                img_url = await self._load_image_b64(refs[0])
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url},
                    "role": "first_frame",
                })
            elif len(refs) == 2:
                for i, ref in enumerate(refs):
                    img_url = await self._load_image_b64(ref)
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url},
                        "role": "first_frame" if i == 0 else "last_frame",
                    })
            else:
                for ref in refs[:9]:
                    img_url = await self._load_image_b64(ref)
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img_url},
                        "role": "reference_image",
                    })

        body: Dict[str, Any] = {
            "model": model,
            "content": content,
            "resolution": self._map_resolution(resolution, model),
            "duration": self._clamp_duration(duration, model),
        }

        # 文生视频：ratio 必填且不能为 adaptive
        # 图生视频：ratio 恒为 adaptive（由输入图片决定）
        # 音频参考（r2va）：ratio 可选，默认 adaptive，用户指定则生效
        if refs:
            body["ratio"] = "adaptive"
        else:
            ratio = (aspect_ratio or "16:9").strip()
            if audios:
                body["ratio"] = ratio if ratio and ratio.lower() != "adaptive" else "adaptive"
            else:
                body["ratio"] = ratio if ratio and ratio.lower() != "adaptive" else "16:9"

        # AIGC 水印默认关闭
        body["aigc_watermark"] = bool(kwargs.get("aigc_watermark", False))

        url = self.build_url("video_generation")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT * 2, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(), json=body)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"MiniMax 视频生成失败 ({resp.status_code}): {_safe_error_text(resp.text)}"
                )
            data = resp.json()

        task_id = data.get("task_id", "")
        if not task_id:
            raise RuntimeError(f"MiniMax 视频生成未返回 task_id: {data}")
        return VideoResult(url="", task_id=task_id, raw=data)

    # ——— 视频任务查询 ———

    async def query_video_task(self, task_id: str) -> VideoResult:
        """查询 MiniMax 视频任务状态。成功时主动下载视频到本地（避免 CDN 签名链接过期）。"""
        url = self.build_url(f"query/video_generation/{task_id}")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            resp = await cli.get(url, headers=self.build_headers())
            if resp.status_code != 200:
                raise RuntimeError(
                    f"MiniMax 查询视频任务失败 ({resp.status_code}): {_safe_error_text(resp.text)}"
                )
            data = resp.json()

        # 响应格式: {task: {id, status, content: {url}, ...}}
        task = data.get("task") or data
        status = str(task.get("status") or "").lower()
        log.debug(f"MiniMax 视频任务状态: {status}")

        if status in ("succeeded", "success", "completed", "done", "finished"):
            video_url = ""
            content_obj = task.get("content") or {}
            if isinstance(content_obj, dict):
                video_url = content_obj.get("url", "")
            if not video_url:
                video_url = task.get("video_url") or task.get("url") or ""

            if video_url:
                local_path = await self._download_video(video_url)
                if local_path:
                    return VideoResult(url=local_path, task_id=task_id, raw=data)
                # 下载失败，回退返回远程 URL
                return VideoResult(url=video_url, task_id=task_id, raw=data)
            return VideoResult(url="", task_id=task_id, raw=data)

        if status in ("failed", "fail", "error", "cancelled", "canceled"):
            err = task.get("error") or {}
            err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"MiniMax 视频任务失败: {err_msg or status}")

        # queued / running / 其他 → 仍在处理中
        return VideoResult(url="", task_id=task_id, raw=data)

    async def _download_video(self, video_url: str) -> str:
        """下载视频到 output/videos/，返回本地路径。失败返回空字符串。"""
        if not await async_validate_safe_url(video_url):
            log.warning(f"SSRF 拦截 — MiniMax 视频 URL: {video_url[:80]}")
            return ""
        try:
            async with httpx.AsyncClient(timeout=180, follow_redirects=False) as cli:
                dl = await cli.get(video_url)
                # 手动处理重定向（CDN 可能 302，每跳做 SSRF 校验）
                redirect_count = 0
                while dl.is_redirect and redirect_count < 5:
                    redirect_count += 1
                    next_url = dl.headers.get("location", "")
                    if not next_url:
                        break
                    if next_url.startswith("/"):
                        from urllib.parse import urljoin
                        next_url = urljoin(video_url, next_url)
                    if not await async_validate_safe_url(next_url):
                        log.warning(f"SSRF 拦截（重定向）: {next_url[:80]}")
                        return ""
                    dl = await cli.get(next_url)
                if dl.status_code == 200 and len(dl.content) > 1000:
                    h = hashlib.md5(dl.content).hexdigest()[:12]
                    ts = int(time.time())
                    filename = f"minimax_{ts}_{h}.mp4"
                    path = os.path.join(config.OUTPUT_VIDEOS_DIR, filename)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(dl.content)
                    log.info(f"MiniMax 视频下载成功: {filename} ({len(dl.content)} bytes)")
                    return f"/output/videos/{filename}"
                log.warning(f"MiniMax 视频下载失败: HTTP {dl.status_code}, size={len(dl.content)}")
        except Exception as e:
            log.warning(f"MiniMax 视频下载异常: {e}")
        return ""

    # ——— 连接测试 ———

    async def test_connection(self) -> dict:
        """测试 MiniMax API 连接。

        MiniMax 没有标准 /models 端点，用查询接口探测：
        - 401 → API Key 无效
        - 其他状态码（400/404 等）→ 认证通过，连接正常（只是 task_id 不存在）
        """
        import time as _time
        started = _time.time()
        try:
            url = self.build_url("query/video_generation/_conn_test_")
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as cli:
                resp = await cli.get(url, headers=self.build_headers())
            elapsed = int((_time.time() - started) * 1000)
            if resp.status_code == 401:
                return {
                    "ok": False, "latency_ms": elapsed,
                    "error": "API Key 无效 (401 Unauthorized)",
                    "status_code": 401,
                }
            return {
                "ok": True, "latency_ms": elapsed,
                "status_code": resp.status_code, "protocol": self.protocol,
            }
        except Exception as e:
            elapsed = int((_time.time() - started) * 1000)
            return {"ok": False, "latency_ms": elapsed, "error": str(e)}

    # ——— 不支持的能力（显式拒绝，避免继承基类的 NotImplementedError 消息不明确）———

    async def generate_image(self, *args, **kwargs):
        raise NotImplementedError("MiniMax 当前仅接入视频生成，不支持图片生成")

    async def chat(self, *args, **kwargs):
        raise NotImplementedError("MiniMax 当前仅接入视频生成，不支持对话")
