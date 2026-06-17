"""运行时配置数据类（可从环境变量热刷新）"""

from dataclasses import dataclass, field
from typing import List as _List

from .env import (
    get_app_api_key, get_cors_origins, get_ai_request_timeout,
    get_image_poll_interval, get_max_history_messages, get_comfyui_instances,
    get_public_base_url, get_rate_limit_enabled, get_rate_limit_requests,
    get_rate_limit_window,
)
from .constants import LOCAL_IMAGE_IMPORT_EXTS
from .env import get_local_image_import_max_bytes, get_skill_authorized_dirs


@dataclass
class RuntimeConfig:
    """运行时可刷新的配置单例。"""
    app_api_key: str = ""
    cors_origins: _List[str] = field(default_factory=list)
    ai_request_timeout: float = 300.0
    image_poll_interval: float = 3.0
    max_history_messages: int = 30
    comfyui_instances: _List[str] = field(default_factory=list)
    public_base_url: str = ""
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 30
    rate_limit_window: int = 60


def _build_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        app_api_key=get_app_api_key(),
        cors_origins=get_cors_origins(),
        ai_request_timeout=get_ai_request_timeout(),
        image_poll_interval=get_image_poll_interval(),
        max_history_messages=get_max_history_messages(),
        comfyui_instances=get_comfyui_instances(),
        public_base_url=get_public_base_url(),
        rate_limit_enabled=get_rate_limit_enabled(),
        rate_limit_requests=get_rate_limit_requests(),
        rate_limit_window=get_rate_limit_window(),
    )


# 全局单例
runtime = _build_runtime_config()


def refresh_runtime_config():
    """刷新会被路由和中间件直接读取的运行期配置。"""
    global runtime
    runtime = _build_runtime_config()
