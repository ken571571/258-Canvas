"""Provider 注册中心 —— 自动发现并注册所有协议插件"""

import os
import importlib
from typing import Dict, List, Optional
from .base import BaseProvider
from ..logging_config import get_logger

log = get_logger("registry")


class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}
        self._discover()

    def _discover(self):
        """扫描 providers/ 目录，自动加载所有 Provider"""
        prov_dir = os.path.dirname(os.path.abspath(__file__))
        for fn in sorted(os.listdir(prov_dir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            if fn in ("base.py", "registry.py", "__init__.py"):
                continue
            mod_name = fn[:-3]
            try:
                mod = importlib.import_module(f"{__package__}.{mod_name}")
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if (isinstance(obj, type) and issubclass(obj, BaseProvider)
                            and obj is not BaseProvider
                            and obj.__module__ == mod.__name__):   # 跳过从其他模块 import 的类
                        inst = obj()
                        if inst.provider_id:
                            self._providers[inst.provider_id] = inst
                            log.info(f"已注册: {inst.provider_id} ({inst.provider_name})")
            except Exception as e:
                log.warning(f"加载 {fn} 失败: {e}")

    def get(self, provider_id: str) -> Optional[BaseProvider]:
        return self._providers.get(provider_id)

    def list_all(self) -> List[BaseProvider]:
        return list(self._providers.values())


# 全局单例
_registry: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
