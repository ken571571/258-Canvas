"""纯配置常量（不依赖环境变量，不依赖目录结构）"""

# 应用配置
APP_VERSION = "1.0.0"
APP_HOST = "0.0.0.0"
APP_PORT = 3571

# ——— 上传限制 ———
LOCAL_IMAGE_IMPORT_MAX_BYTES = 50 * 1024 * 1024   # 50MB（可通过环境变量覆盖）
LOCAL_IMAGE_IMPORT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
