"""统一业务异常层次 — 所有应用层异常由此派生。

所有异常包含 status_code（HTTP 状态码）和 message（用户可读描述）。
路由层统一 catch AppError 并转换为 HTTPException。

用法:
    from server.exceptions import NotFoundError, ConflictError

    if not canvas:
        raise NotFoundError("画布不存在")
    if conflict:
        raise ConflictError("画布已被其他页面更新")
"""


class AppError(Exception):
    """所有应用层异常的基类。

    子类只需设置 status_code 和 default_message，即可被路由层统一处理。
    """
    status_code: int = 500
    default_message: str = "服务器内部错误"

    def __init__(self, message: str = "", status_code: int = 0):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        if status_code:
            self.status_code = status_code

    def to_dict(self) -> dict:
        """返回可序列化给客户端的错误详情。"""
        return {"detail": self.message, "code": type(self).__name__}


class NotFoundError(AppError):
    """资源不存在"""
    status_code = 404
    default_message = "请求的资源不存在"


class ConflictError(AppError):
    """资源冲突（如乐观锁冲突）"""
    status_code = 409
    default_message = "资源冲突，请刷新后重试"


class ValidationError(AppError):
    """输入校验失败"""
    status_code = 400
    default_message = "输入参数无效"


class ProviderError(AppError):
    """上游 AI 平台错误"""
    status_code = 502
    default_message = "AI 平台服务异常"


class AuthError(AppError):
    """认证失败"""
    status_code = 401
    default_message = "未授权：请提供有效的 API Key"


class ForbiddenError(AppError):
    """权限不足"""
    status_code = 403
    default_message = "无权访问此资源"


class RateLimitError(AppError):
    """请求频率超限"""
    status_code = 429
    default_message = "请求过于频繁，请稍后再试"


class SecurityError(AppError):
    """安全拦截（SSRF/路径穿越等）"""
    status_code = 400
    default_message = "请求被安全策略拦截"


class ServiceUnavailableError(AppError):
    """服务不可用"""
    status_code = 503
    default_message = "服务暂时不可用，请稍后再试"


class CryptoError(AppError):
    """加密/解密失败（密码错误、数据损坏、指纹不匹配等）"""
    status_code = 400
    default_message = "加密/解密操作失败"
