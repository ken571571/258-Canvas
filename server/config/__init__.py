"""配置包 —— 聚合所有子模块，保持与原有 config.py 完全兼容的公共 API。"""

# ——— 1. 目录路径 ———
from .paths import (
    BASE_DIR, STATIC_DIR, DATA_DIR, WORKFLOW_DIR, SKILLS_DIR, ASSETS_DIR,
    API_ENV_FILE, CANVAS_DIR, AGENTS_DIR, KB_DIR, HISTORY_DIR,
    INPUT_DIR, OUTPUT_DIR, OUTPUT_IMAGES_DIR, OUTPUT_VIDEOS_DIR,
    AGENTS_ROOT, CANVASES_ROOT,
    ensure_directories,
)

# ——— 2. 纯常量 ———
from .constants import (
    APP_VERSION, APP_HOST, APP_PORT,
    LOCAL_IMAGE_IMPORT_EXTS,
    VIDEO_POLL_TIMEOUT, VIDEO_POLL_INTERVAL,
    HEARTBEAT_INTERVAL, HEARTBEAT_TIMEOUT,
    TASK_EXPIRE_SECONDS, JSON_CACHE_TTL,
    KB_CHUNK_SIZE, KB_CHUNK_OVERLAP,
)

# ——— 3. 环境变量 ———
from .env import (
    load_env,
    get_app_api_key, get_cors_origins,
    get_ai_request_timeout, get_image_poll_interval, get_max_history_messages,
    get_comfyui_instances, get_public_base_url,
    get_rate_limit_enabled, get_rate_limit_requests, get_rate_limit_window,
    get_local_image_import_max_bytes, get_skill_authorized_dirs,
    get_provider_api_key, get_provider_base_url,
)

# ——— 4. 运行时配置 ———
from .runtime import (
    RuntimeConfig, _build_runtime_config,
    runtime as _runtime_base,       # 非公开，下面重新导出
)

# ——— 5. 初始化（导入时触发，与原 config.py 行为一致） ———
ensure_directories()
load_env()


# ——— 6. 导出模块级变量（兼容原 config.X 的访问方式） ———
def _refresh_module_levels():
    """刷新模块级全局变量（被 refresh_runtime_config 和 import 时调用）。"""
    global APP_API_KEY, CORS_ORIGINS, AI_REQUEST_TIMEOUT, IMAGE_POLL_INTERVAL
    global MAX_HISTORY_MESSAGES, COMFYUI_INSTANCES, PUBLIC_BASE_URL
    global RATE_LIMIT_ENABLED, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW
    global LOCAL_IMAGE_IMPORT_MAX_BYTES, SKILL_AUTHORIZED_DIRS, runtime

    APP_API_KEY = get_app_api_key()
    CORS_ORIGINS = get_cors_origins()
    AI_REQUEST_TIMEOUT = get_ai_request_timeout()
    IMAGE_POLL_INTERVAL = get_image_poll_interval()
    MAX_HISTORY_MESSAGES = get_max_history_messages()
    COMFYUI_INSTANCES = get_comfyui_instances()
    LOCAL_IMAGE_IMPORT_MAX_BYTES = get_local_image_import_max_bytes()
    PUBLIC_BASE_URL = get_public_base_url()
    RATE_LIMIT_ENABLED = get_rate_limit_enabled()
    RATE_LIMIT_REQUESTS = get_rate_limit_requests()
    RATE_LIMIT_WINDOW = get_rate_limit_window()
    SKILL_AUTHORIZED_DIRS = get_skill_authorized_dirs()
    runtime = _build_runtime_config()

    # 确保 skill 目录存在
    import os as _os
    for _d in SKILL_AUTHORIZED_DIRS:
        _os.makedirs(_d, exist_ok=True)


# import 时初始化
_refresh_module_levels()


def refresh_runtime_config():
    """刷新模块级全局变量 + 运行时配置单例。与原 config.py 行为完全一致。"""
    # 重新加载环境变量（覆盖已有值）
    load_env(override=True)
    _refresh_module_levels()
