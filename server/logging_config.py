"""集中式日志配置 — 整个项目统一使用此模块。

用法:
    from server.logging_config import get_logger
    log = get_logger("generation")
    log.info("开始生图", extra={"provider": "openai"})
"""

import os
import logging
import sys
import contextvars
from logging.handlers import RotatingFileHandler

_log_format = "%(asctime)s [%(levelname)-5s] [%(request_id)-12s] %(name)s: %(message)s"
_date_format = "%H:%M:%S"

# 请求 ID 上下文变量（线程安全，替代全局 logRecordFactory）
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIDFilter(logging.Filter):
    """从 contextvars 读取 request_id，注入到每条日志记录。

    并发安全：每个 asyncio task 有独立的 contextvars 上下文，
    不会像全局 logRecordFactory 那样出现竞态。
    """
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


_initialized = False


def setup_logging(level: int = logging.INFO, log_dir: str = ""):
    """配置根 Logger。在 main.py 启动时调用一次即可。

    Args:
        level: 日志级别（默认 INFO，调试时可用 DEBUG）
        log_dir: 日志文件目录（默认项目根目录下的 logs/）
    """
    global _initialized
    if _initialized:
        return

    root = logging.getLogger("canvas571")
    root.setLevel(level)

    # 通过 contextvars 注入 request_id（并发安全）
    root.addFilter(_RequestIDFilter())

    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_log_format, _date_format))
    console.setLevel(level)
    console.addFilter(_RequestIDFilter())  # handler 级过滤：确保外部库日志也有 request_id
    root.addHandler(console)

    # 文件输出（滚动日志，最多 5MB × 3 个文件）
    if not log_dir:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app.log")
    file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    ))
    file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别，包括 DEBUG
    file_handler.addFilter(_RequestIDFilter())  # handler 级过滤
    root.addHandler(file_handler)

    root.propagate = False
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取 "canvas571.<name>" 命名空间下的子 Logger。"""
    return logging.getLogger(f"canvas571.{name}")
