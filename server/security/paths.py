"""路径安全工具 —— 防止目录穿越攻击。

所有涉及用户输入路径的接口必须使用 safe_join() 做边界校验。
"""

import os


def safe_join(root: str, *parts: str) -> str:
    """安全拼接路径，确保最终路径仍位于 root 内。

    用户输入路径必须是相对路径，不能包含盘符或绝对路径。
    调用方可捕获 ValueError 并转换为 HTTP 400。

    Args:
        root: 安全根目录（绝对路径）
        *parts: 用户提供的相对路径片段

    Returns:
        拼接后的绝对路径（保证在 root 内）

    Raises:
        ValueError: 路径包含盘符/绝对路径/..逃逸到 root 外
    """
    root_abs = os.path.abspath(root)
    clean_parts = []
    for part in parts:
        value = str(part or "")
        if not value:
            continue
        value = value.replace("\\", os.sep).replace("/", os.sep)
        drive, _ = os.path.splitdrive(value)
        if drive or os.path.isabs(value):
            raise ValueError("absolute path is not allowed")
        clean_parts.append(value)

    path = os.path.abspath(os.path.join(root_abs, *clean_parts))
    try:
        common = os.path.commonpath([root_abs, path])
    except ValueError as exc:
        raise ValueError("path is outside root") from exc
    if common != root_abs:
        raise ValueError("path is outside root")
    return path
