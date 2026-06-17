"""API 路由：API 平台配置"""

import os
import asyncio
import threading
from fastapi import APIRouter, HTTPException
from .. import config
from ..providers.base import BaseProvider
from ..providers.registry import get_provider_registry

router = APIRouter(prefix="/api", tags=["providers"])

# 写锁（threading.Lock：跨路由同步调用也安全，不会因为不同事件循环而失效）
_env_lock = threading.Lock()


def _env_path():
    return config.API_ENV_FILE


def _read_env():
    """读取 .env 文件，保留注释和空行。"""
    if not os.path.exists(_env_path()):
        return []
    lines = []
    with open(_env_path(), "r", encoding="utf-8-sig") as f:
        for line in f.read().splitlines():
            lines.append(line)
    return lines


def _parse_env(lines: list) -> dict:
    """将 env 行列表解析为键值对字典。"""
    result = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        result[k.strip()] = v.strip().strip('"').strip("'")
    return result


async def _write_env(updates: dict):
    """增量更新 .env 文件：保留原有注释和格式，只修改/追加键值。"""
    with _env_lock:
        os.makedirs(os.path.dirname(_env_path()), exist_ok=True)

        lines = _read_env()
        current = _parse_env(lines)
        current.update(updates)
        updated_keys = set(updates.keys())

        # 更新已有行
        new_lines = []
        seen_keys = set()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in updated_keys:
                    new_lines.append(f"{k}={current[k]}")
                    seen_keys.add(k)
                    continue
                seen_keys.add(k)
            new_lines.append(line)

        # 追加新键
        for k, v in current.items():
            if k not in seen_keys:
                new_lines.append(f"{k}={v}")

        with open(_env_path(), "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")

        # 同步到 os.environ
        for k, v in updates.items():
            os.environ[k] = str(v or "")


@router.get("/settings/api-keys")
def get_api_keys():
    """返回所有已配置的环境变量（敏感 Key 脱敏显示）。"""
    lines = _read_env()
    env = _parse_env(lines)
    result = {}
    for k, v in env.items():
        if _is_sensitive_key(k):
            result[k] = _mask(v)
        else:
            result[k] = v
    return {"keys": result}


@router.post("/settings/api-keys")
async def save_api_keys(payload: dict):
    """保存 API Key 或 Base URL 等配置项。

    接受任意键值对，不仅限于 KEY/SECRET/TOKEN。
    键名会自动转为大写。
    """
    updates = {}
    for k, v in payload.items():
        k = str(k).strip().upper()
        if k:
            updates[k] = str(v or "").strip()
    await _write_env(updates)
    # 重新加载环境变量以使 provider 和运行期配置生效
    config.load_env(override=True)
    config.refresh_runtime_config()
    return {"ok": True, "saved": list(updates.keys())}


# ——— URL → 协议 自动检测 ———

_URL_PROTOCOL_MAP = [
    ("api.apimart.ai", "apimart"),
    ("ai.comfly.chat", "apimart"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("ark.cn-beijing.volces.com", "volcengine"),
    ("modelscope.cn", "modelscope"),
    ("modelscope.ai", "modelscope"),
    ("runninghub.cn", "runninghub"),
    ("runninghub.ai", "runninghub"),
    ("api.openai.com", "openai"),
    ("openai.com", "openai"),
    ("api.deepseek.com", "deepseek"),
    ("aihubmix.com", "openai"),
]

def _detect_protocol_from_url(url: str) -> str:
    """根据 URL 自动检测协议类型。"""
    if not url:
        return ""
    u = url.lower()
    for keyword, protocol in _URL_PROTOCOL_MAP:
        if keyword in u:
            return protocol
    return ""


def _get_or_create_provider(provider_id: str, protocol: str = "openai", api_key: str = "", base_url: str = ""):
    """获取 Provider 实例。内置平台从注册表获取，自定义平台动态创建。"""
    prov = get_provider_registry().get(provider_id)
    if prov:
        return prov

    # 内置平台找不到 → 尝试用 protocol 匹配
    # 例如 deepseek 的 protocol 是 openai，直接用 OpenAIProvider
    from ..providers.openai import OpenAIProvider
    from ..providers.gemini import GeminiProvider
    from ..providers.volcengine import VolcengineProvider
    from ..providers.apimart import APIMartProvider
    from ..providers.runninghub import RunningHubProvider

    protocol_map = {
        "openai": OpenAIProvider,
        "apimart": APIMartProvider,
        "gemini": GeminiProvider,
        "volcengine": VolcengineProvider,
        "runninghub": RunningHubProvider,
    }
    cls = protocol_map.get(protocol, OpenAIProvider)
    prov = cls()
    # 注入 Key 和 URL 到实例（绕过 env 读取）
    if api_key:
        prov._injected_key = api_key
    if base_url:
        prov._injected_url = base_url
    return prov


def resolve_provider(provider_id: str) -> BaseProvider | None:
    """解析 Provider（供 Chat/生图/Agent 等实际调用端点使用）。

    与 _get_or_create_provider 不同，此函数不接收显式的 key/url 参数，
    而是从环境变量（.env 文件）中自动读取配置。

    查找顺序:
    1. 内置平台 → 从 ProviderRegistry 获取
    2. 自定义平台 → 根据 .env 中的 Key + Base URL 动态创建 OpenAIProvider
    """
    # 1. 先查注册表
    prov = get_provider_registry().get(provider_id)
    if prov:
        return prov

    # 2. 尝试从环境变量解析自定义平台
    api_key = config.get_provider_api_key(provider_id)
    if not api_key:
        return None

    base_url = config.get_provider_base_url(provider_id)

    # 3. 默认按 OpenAI 协议创建（绝大多数自定义平台兼容 OpenAI 格式）
    from ..providers.openai import OpenAIProvider
    prov = OpenAIProvider()
    prov._injected_key = api_key
    if base_url:
        prov._injected_url = base_url

    # 重写 provider_id 使其返回自定义 ID（供日志/错误信息使用）
    # 注意：不能直接修改 property，所以通过 _injected_key 机制传递信息
    # provider_name 保持 "OpenAI 兼容" 即可，前端已知道平台名

    return prov


# ——— Provider 测试连接 & 拉取模型 ———


@router.post("/providers/{provider_id}/test-connection")
async def test_provider_connection(provider_id: str, payload: dict = {}):
    """测试 API 连接是否正常。

    payload 可选: {api_key, base_url, protocol}，传入时临时覆盖环境变量中的配置。
    如果 URL 对应的协议与 provider 不符，会提示正确的协议。
    """
    temp_key = str(payload.get("api_key") or "").strip()
    temp_url = str(payload.get("base_url") or "").strip()
    protocol = str(payload.get("protocol") or "openai").strip()
    prov = _get_or_create_provider(provider_id, protocol, temp_key, temp_url)

    # URL 协议检测
    url_protocol = _detect_protocol_from_url(temp_url)
    # 用 provider_id 做匹配（url_protocol 跟 provider_id 比，不跟 protocol 比）
    # 因为多个 provider 可能共用同一种 protocol（如 deepseek 和 openai 都是 openai 协议）
    if url_protocol and url_protocol != provider_id:
        return {
            "ok": False,
            "latency_ms": 0,
            "status_code": 0,
            "error": f"URL 是 {url_protocol} 平台的地址，但当前选中了 {provider_id} 平台。请在左侧选择正确的平台或修改 URL。",
            "protocol": url_protocol,
            "mismatch": True,
        }

    result = await prov.test_connection()
    result["protocol"] = prov.protocol
    return result


@router.post("/providers/{provider_id}/fetch-models")
async def fetch_provider_models(provider_id: str, payload: dict = {}):
    """从上游 API 拉取可用模型列表。

    payload 可选: {api_key, base_url, protocol}，传入时临时覆盖环境变量。
    """
    temp_key = str(payload.get("api_key") or "").strip()
    temp_url = str(payload.get("base_url") or "").strip()
    protocol = str(payload.get("protocol") or "openai").strip()
    prov = _get_or_create_provider(provider_id, protocol, temp_key, temp_url)
    models = await prov.fetch_models()

    # 按类型分类
    image_models = [m.id for m in models if m.type == "image"]
    chat_models = [m.id for m in models if m.type == "chat"]
    video_models = [m.id for m in models if m.type == "video"]
    all_ids = [m.id for m in models]

    return {
        "total": len(models),
        "all": all_ids,
        "image_models": image_models,
        "chat_models": chat_models,
        "video_models": video_models,
        "models": [{"id": m.id, "name": m.name, "type": m.type} for m in models],
    }


def _is_sensitive_key(key: str) -> bool:
    """判断是否为敏感配置项（需要在 UI 上脱敏显示）。"""
    upper = key.upper()
    return any(kw in upper for kw in ("KEY", "SECRET", "TOKEN", "PASSWORD"))


def _mask(val):
    if not val:
        return ""
    return "****" + val[-4:] if len(val) > 4 else "****"
