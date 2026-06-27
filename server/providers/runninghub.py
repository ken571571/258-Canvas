"""RunningHub Provider —— AI 应用/工作流平台。

RunningHub 是国内的 AI 工作流平台，通过 API 提交 AI 应用或工作流任务。
- Base URL: https://www.runninghub.cn (国内) / https://www.runninghub.ai (国外)
- 认证: Bearer Token
- 双 Key 体系:
  - RUNNINGHUB_API_KEY: RH币 Key（必填，积分/免费额度）
  - RUNNINGHUB_WALLET_API_KEY: 余额 Key（可选，账户余额付费）
- 协议: 自有 REST API（非 OpenAI 兼容）
"""

import os
import json
import time
from typing import List, Dict
import httpx

from .base import BaseProvider, ImageResult, VideoResult, ChatResult
from .. import config
from ..security.network import async_validate_safe_url


class RunningHubProvider(BaseProvider):
    """RunningHub AI 平台。

    读取环境变量：
    - RUNNINGHUB_API_KEY (RH币，必填)
    - RUNNINGHUB_WALLET_API_KEY (余额，可选)
    - RUNNINGHUB_BASE_URL（可选，默认 https://www.runninghub.cn）
    """

    _DEFAULT_BASE = "https://www.runninghub.cn"
    _DEFAULT_IMAGE_MODELS = [
        "seedream-v5-lite/text-to-image",
        "seedream-v5-lite/image-to-image",
    ]

    @property
    def provider_id(self) -> str:
        return "runninghub"

    @property
    def provider_name(self) -> str:
        return "RunningHub"

    @property
    def protocol(self) -> str:
        return "runninghub"

    # ——— 配置 ———

    @property
    def _api_key(self) -> str:
        """RH币 Key（必填）。"""
        temp = self._temp_key("RUNNINGHUB_API_KEY")
        if temp: return temp
        val = os.getenv("RUNNINGHUB_API_KEY", "")
        return val.strip().strip('"').strip("'")

    @property
    def _wallet_key(self) -> str:
        """余额 Key（可选）。为空时回退到 RH币 Key。"""
        val = os.getenv("RUNNINGHUB_WALLET_API_KEY", "")
        return val.strip().strip('"').strip("'")

    def _resolve_key(self, use_wallet: bool = False) -> str:
        """根据 use_wallet 选择 Key：余额优先，回退 RH币。"""
        if use_wallet and self._wallet_key:
            return self._wallet_key
        return self._api_key or self._wallet_key

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        val = os.getenv("RUNNINGHUB_BASE_URL", "")
        return val.rstrip("/") if val else self._DEFAULT_BASE

    # ——— 认证 ———

    def build_headers(self, use_wallet: bool = False) -> Dict[str, str]:
        key = self._resolve_key(use_wallet)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        }
        if "runninghub.cn" in self._base_url:
            headers["Host"] = "www.runninghub.cn"
        elif "runninghub.ai" in self._base_url:
            headers["Host"] = "www.runninghub.ai"
        return headers

    def build_url(self, endpoint: str) -> str:
        endpoint = endpoint.lstrip("/")
        return f"{self._base_url}/{endpoint}"

    # ——— 模型列表 ———

    def list_image_models(self) -> List[str]:
        return self._model_list_from_env("RUNNINGHUB_IMAGE_MODELS", self._DEFAULT_IMAGE_MODELS)

    def list_chat_models(self) -> List[str]:
        return []  # RunningHub 不直接提供 LLM 对话

    def list_video_models(self) -> List[str]:
        return []  # 视频生成通过工作流间接支持

    # ——— 对话（不支持） ———

    async def chat(self, messages: list, model: str = "", **kwargs) -> ChatResult:
        raise NotImplementedError("RunningHub 不支持 LLM 对话")

    # ——— 生图（通过 AI 应用提交） ———

    async def generate_image(
        self, prompt: str, size: str = "1024x1024", model: str = "",
        reference_images: List[str] = None, use_wallet: bool = False, **kwargs
    ) -> ImageResult:
        refs = reference_images or []
        webapp_id = model or "2058517022748798977"  # 默认 seedream-v5-lite
        api_key = self._resolve_key(use_wallet)

        node_info_list = [{
            "nodeId": "100",
            "fieldName": "prompt",
            "fieldValue": prompt,
        }]
        if refs:
            for i, ref in enumerate(refs[:3]):
                img_data = await self._load_image_b64(ref)
                node_info_list.append({
                    "nodeId": "101" if i > 0 else "100",
                    "fieldName": "image",
                    "fieldValue": img_data,
                })

        body = {
            "apiKey": api_key,
            "webappId": webapp_id,
            "nodeInfoList": node_info_list,
        }

        url = self.build_url("/task/openapi/ai-app/run")
        async with httpx.AsyncClient(timeout=config.AI_REQUEST_TIMEOUT, follow_redirects=False) as cli:
            resp = await cli.post(url, headers=self.build_headers(use_wallet), json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"RunningHub 生图失败 ({resp.status_code}): {resp.text[:500]}")
            data = resp.json()

        if not isinstance(data, dict) or data.get("code") not in (0, "0"):
            raise RuntimeError(f"RunningHub 提交失败: {data.get('msg', str(data))}")

        task_id = data.get("data", {}).get("taskId", "") if isinstance(data.get("data"), dict) else ""
        if not task_id:
            raise RuntimeError(f"RunningHub 未返回 taskId: {data}")

        return await self._poll_task(task_id, use_wallet)

    async def _poll_task(self, task_id: str, use_wallet: bool = False, max_wait: int = 300) -> ImageResult:
        import asyncio
        url = self.build_url("/task/openapi/task-status")
        api_key = self._resolve_key(use_wallet)
        body = {"apiKey": api_key, "taskId": task_id}

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as cli:
            for _ in range(max_wait // 3):
                await asyncio.sleep(3)
                resp = await cli.post(url, headers=self.build_headers(use_wallet), json=body)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not isinstance(data, dict):
                    continue

                status = str(data.get("data", {}).get("status") if isinstance(data.get("data"), dict) else data.get("status", ""))
                if status.upper() in ("SUCCESS", "SUCCEED", "COMPLETED"):
                    outputs = (data.get("data") or {}).get("outputs") or data.get("outputs") or {}
                    if isinstance(outputs, dict):
                        for node_out in outputs.values():
                            images = node_out.get("images") or []
                            if images:
                                img_url = images[0].get("url", "")
                                if img_url:
                                    # SSRF 防护：验证所有 URL 的下载地址安全
                                    if not await async_validate_safe_url(img_url):
                                        raise RuntimeError(f"RunningHub 返回了不安全的图片地址（内网/云metadata），已拦截")
                                    try:
                                        dl_resp = await cli.get(img_url, follow_redirects=False)
                                        # v2.5.50：手动处理重定向，每跳做 SSRF 校验
                                        redirect_count = 0
                                        while dl_resp.is_redirect and redirect_count < 5:
                                            redirect_count += 1
                                            next_url = dl_resp.headers.get("location", "")
                                            if not next_url:
                                                break
                                            if next_url.startswith("/"):
                                                from urllib.parse import urljoin
                                                next_url = urljoin(img_url, next_url)
                                            if not await async_validate_safe_url(next_url):
                                                raise RuntimeError(f"RunningHub 重定向到不安全地址，已拦截")
                                            dl_resp = await cli.get(next_url, follow_redirects=False)
                                        if dl_resp.status_code == 200:
                                            path = self._save_image(dl_resp.content, f"rh_{task_id[:8]}_")
                                            return ImageResult(url=path, raw=data)
                                    except Exception as e:
                                        log.warning(f"RunningHub 图片下载失败: {e}")
                                    return ImageResult(url=img_url, raw=data)
                    raise RuntimeError("RunningHub 任务完成但无图片输出")
                elif status.upper() in ("FAILED", "FAIL", "ERROR", "CANCELED"):
                    raise RuntimeError(f"RunningHub 任务失败: {data}")

        raise RuntimeError("RunningHub 任务轮询超时")

    async def fetch_models(self) -> tuple:
        """RunningHub 不提供模型列表 API，直接返回默认模型。live=False。"""
        from .base import ModelInfo
        models = []
        for m in self.list_image_models():
            models.append(ModelInfo(id=m, name=m, type="image"))
        return models, False

    async def generate_video(
        self, prompt: str, duration: int = 5, aspect_ratio: str = "16:9",
        model: str = "", reference_images: List[str] = None,
        resolution: str = "720p", **kwargs
    ) -> VideoResult:
        raise NotImplementedError("RunningHub 视频生成暂未实现，请使用工作流方式提交")

    async def test_connection(self) -> dict:
        """测试连接：检查 API 可达且 Token 有效。

        RunningHub 即使 token 无效也返回 HTTP 200，错误信息在 JSON body 的 code 字段。
        """
        import time as _time
        started = _time.time()
        try:
            url = self.build_url("/api/user/info")
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as cli:
                resp = await cli.get(url, headers=self.build_headers())
            elapsed = int((_time.time() - started) * 1000)

            if resp.status_code >= 500:
                return {"ok": False, "latency_ms": elapsed, "error": f"服务器错误 HTTP {resp.status_code}"}

            # RunningHub 即使报错也返回 200，需解析 body
            try:
                data = resp.json()
                code = data.get("code") if isinstance(data, dict) else None
                if code not in (0, "0", None, 200):
                    msg = data.get("msg", "") or data.get("message", "") or f"code={code}"
                    return {"ok": False, "latency_ms": elapsed, "error": f"Token 无效: {msg}"}
                # code=0 或没有 code → Token 有效
                return {"ok": True, "latency_ms": elapsed, "status_code": resp.status_code}
            except Exception:
                # 非 JSON 响应
                if 200 <= resp.status_code < 300:
                    return {"ok": True, "latency_ms": elapsed, "status_code": resp.status_code}
                return {"ok": False, "latency_ms": elapsed, "error": f"HTTP {resp.status_code}"}

        except Exception as e:
            elapsed = int((_time.time() - started) * 1000)
            return {"ok": False, "latency_ms": elapsed, "error": str(e)}
