"""服务层 —— 业务逻辑，独立于 HTTP 路由层。

薄路由 + 服务层 架构：
- routes/ 只负责 HTTP 参数校验、状态码、响应格式
- services/ 负责业务逻辑、Provider 解析、数据归一化
"""
