"""生图服务 —— 从 routes/generation.py 抽取的业务逻辑层。

职责：
- Provider 解析与协议自动切换
- 生图尺寸倍率解析（x2/x3/custom:N）
- 结果 URL 归一化（旧路径迁移）
- 响应 payload 组装

路由层应只保留 HTTP 参数校验、状态码转换和对本服务的调用。
"""

import os
import shutil
from .. import config
from ..providers.base import BaseProvider
from ..logging_config import get_logger
from ..utils import resolve_gen_size

log = get_logger("image_service")


def auto_detect_provider(prov: BaseProvider, model: str) -> BaseProvider:
    """根据模型名自动切换协议：gemini 模型 → GeminiProvider。

    避免 OpenAI 格式请求被错误发到 Google API。
    """
    model_lower = (model or "").lower()
    if "gemini" in model_lower and getattr(prov, 'protocol', '') != 'gemini':
        from ..providers.gemini import GeminiProvider
        alt = GeminiProvider()
        if hasattr(prov, '_injected_key') and prov._injected_key:
            alt._injected_key = prov._injected_key
        if hasattr(prov, '_injected_url') and prov._injected_url:
            alt._injected_url = prov._injected_url
        return alt
    return prov


def prepare_image_size(size: str, reference_images: list) -> str:
    """统一解析生图尺寸，供同步/异步接口共用。"""
    return resolve_gen_size(size, reference_images)


def normalize_image_url(url: str) -> str:
    """兼容旧输出路径，将 /assets/output/* 迁移到 /output/images/*。"""
    if "/assets/output/" not in (url or ""):
        return url

    old_path = os.path.join(config.ASSETS_DIR, "output", os.path.basename(url))
    if not os.path.exists(old_path):
        return url

    new_path = os.path.join(config.OUTPUT_IMAGES_DIR, os.path.basename(url))
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    if not os.path.exists(new_path):
        shutil.copy2(old_path, new_path)
    return "/output/images/" + os.path.basename(url)


def build_image_response(url: str, request_size: str, resolved_size: str, model: str) -> dict:
    """组装生图响应的标准 payload。"""
    return {
        "url": normalize_image_url(url),
        "size": request_size,
        "resolved_size": resolved_size,
        "model": model,
    }
