"""环境变量加载和查找"""

import os
import warnings
from .paths import API_ENV_FILE, SKILLS_DIR, AGENTS_ROOT
from .constants import LOCAL_IMAGE_IMPORT_MAX_BYTES, LOCAL_IMAGE_IMPORT_EXTS


# ——— 安全类型转换（防环境变量坏值导致启动崩溃） ———

def _safe_float(env_key: str, default: float) -> float:
    raw = os.getenv(env_key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        warnings.warn(f"Invalid value for {env_key}='{raw}', using default {default}")
        return default


def _safe_int(env_key: str, default: int) -> int:
    raw = os.getenv(env_key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        warnings.warn(f"Invalid value for {env_key}='{raw}', using default {default}")
        return default


def load_env(override: bool = False):
    """加载 API/.env 文件中的配置到 os.environ。"""
    if not os.path.exists(API_ENV_FILE):
        return
    with open(API_ENV_FILE, "r", encoding="utf-8-sig") as f:
        for line in f.read().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if override:
                os.environ[key] = val
            else:
                os.environ.setdefault(key, val)


# ——— 从环境变量读取的配置（在 load_env 之后才能正确取值） ———

def get_app_api_key() -> str:
    return os.getenv("APP_API_KEY", "").strip().strip('"').strip("'")


def get_cors_origins() -> list:
    return [s.strip() for s in os.getenv("CORS_ORIGINS", "").split(",") if s.strip()]


def get_ai_request_timeout() -> float:
    return _safe_float("AI_REQUEST_TIMEOUT", 300.0)


def get_image_poll_interval() -> float:
    return _safe_float("IMAGE_POLL_INTERVAL", 3.0)


def get_max_history_messages() -> int:
    return _safe_int("MAX_HISTORY_MESSAGES", 30)


def get_comfyui_instances() -> list:
    return [s.strip() for s in os.getenv("COMFYUI_INSTANCES", "127.0.0.1:8188").split(",") if s.strip()]


def get_public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")


def get_rate_limit_enabled() -> bool:
    # 自动检测测试环境：unittest discover 运行时默认关闭限流
    import sys as _sys
    if any("unittest" in a for a in _sys.argv):
        return os.getenv("RATE_LIMIT_ENABLED", "0").lower() in ("1", "true", "yes")
    return os.getenv("RATE_LIMIT_ENABLED", "1").lower() in ("1", "true", "yes")


def get_rate_limit_requests() -> int:
    return _safe_int("RATE_LIMIT_REQUESTS", 60)


def get_rate_limit_window() -> int:
    return _safe_int("RATE_LIMIT_WINDOW", 60)


def get_canvas_env() -> str:
    """运行环境: development | production。控制日志级别、CORS、调试开关。"""
    env = os.getenv("CANVAS_ENV", "production").lower().strip()
    return env if env in ("development", "production") else "production"


def is_development() -> bool:
    return get_canvas_env() == "development"


def get_local_image_import_max_bytes() -> int:
    return _safe_int("LOCAL_IMAGE_IMPORT_MAX_BYTES", LOCAL_IMAGE_IMPORT_MAX_BYTES)


def get_skill_authorized_dirs() -> list:
    return [s.strip() for s in os.getenv("SKILL_AUTHORIZED_DIRS", "").split(",") if s.strip()] or [SKILLS_DIR, AGENTS_ROOT]


def get_provider_api_key(provider_id: str) -> str:
    """根据 provider_id 从环境变量按优先级查找 API Key。"""
    key_map = {
        "openai": ["API_PROVIDER_OPENAI_KEY", "OPENAI_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "apimart": ["APIMART_API_KEY", "COMFLY_API_KEY"],
        "gemini": ["GEMINI_API_KEY"],
        "volcengine": ["ARK_API_KEY"],
        "modelscope": ["MODELSCOPE_API_KEY"],
        "runninghub": ["RUNNINGHUB_API_KEY"],
        "runninghub_wallet": ["RUNNINGHUB_WALLET_API_KEY"],
    }
    for key in key_map.get(provider_id, []):
        val = os.getenv(key, "")
        if val:
            return val.strip().strip('"').strip("'")
    # 回退：通用命名格式
    generic = f"API_PROVIDER_{provider_id.upper().replace('-', '_')}_KEY"
    val = os.getenv(generic, "")
    return val.strip().strip('"').strip("'") if val else ""


def get_provider_base_url(provider_id: str) -> str:
    """根据 provider_id 从环境变量按优先级查找 Base URL。"""
    pid_upper = provider_id.upper().replace("-", "_")
    candidates = [
        f"{pid_upper}_BASE_URL",
        f"API_PROVIDER_{pid_upper}_BASE_URL",
    ]
    # 内置平台默认 URL 映射
    defaults = {
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "apimart": "https://api.apimart.ai",
        "gemini": "https://generativelanguage.googleapis.com/v1beta",
        "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
        "modelscope": "https://api-inference.modelscope.cn/v1",
        "runninghub": "https://www.runninghub.cn",
    }
    for key in candidates:
        val = os.getenv(key, "")
        if val:
            return val.strip().strip('"').strip("'").rstrip("/")
    return defaults.get(provider_id, "")
