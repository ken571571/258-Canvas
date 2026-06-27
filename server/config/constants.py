"""纯配置常量（不依赖环境变量，不依赖目录结构）"""
import os

def _load_app_version() -> str:
    """从项目根目录的 VERSION 文件动态读取版本号，读取失败返回 '0.0.0'"""
    try:
        _version_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "VERSION",
        )
        with open(_version_file, encoding="utf-8") as f:
            v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    return "0.0.0"

# 应用配置
APP_VERSION: str = _load_app_version()
APP_HOST = "0.0.0.0"
APP_PORT = 3571

# ——— 上传限制 ———
LOCAL_IMAGE_IMPORT_MAX_BYTES = 50 * 1024 * 1024   # 50MB（可通过环境变量覆盖）
LOCAL_IMAGE_IMPORT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# ——— 视频轮询 ———
VIDEO_POLL_TIMEOUT = 1200    # 视频轮询总超时（秒）
VIDEO_POLL_INTERVAL = 15     # 轮询间隔（秒）

# ——— WebSocket 心跳 ———
HEARTBEAT_INTERVAL = 30      # 心跳间隔（秒）
HEARTBEAT_TIMEOUT = 90       # 超时未收到 pong 则断连（秒）

# ——— 异步任务 ———
TASK_EXPIRE_SECONDS = 3600   # 任务结果保留时间（秒）

# ——— JSON 缓存 ———
JSON_CACHE_TTL = 30          # 内存缓存 TTL（秒）

# ——— 知识库分片 ———
KB_CHUNK_SIZE = 500          # 文本分片大小（字符）
KB_CHUNK_OVERLAP = 100       # 相邻分片重叠长度（字符）
