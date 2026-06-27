"""API 路由：API 平台配置"""

import os
import asyncio
from fastapi import APIRouter, HTTPException
from .. import config
from ..providers.base import BaseProvider
from ..providers.registry import get_provider_registry
from ..providers.openai import OpenAIProvider
from ..providers.gemini import GeminiProvider
from ..providers.volcengine import VolcengineProvider
from ..providers.apimart import APIMartProvider
from ..providers.runninghub import RunningHubProvider

router = APIRouter(prefix="/api", tags=["providers"])

# 写锁（asyncio.Lock：不阻塞事件循环，与 async 路由配合更优）
_env_lock = asyncio.Lock()


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
    """增量更新 .env 文件：保留原有注释和格式，只修改/追加键值。

    锁内完成「写盘 → os.environ 同步 → config 重载」全周期，
    防止并发 save_api_keys 时环境变量状态不一致（v2.5.40 修复）。
    """
    async with _env_lock:
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
                # 跳过已有空值行和本次要清空的行
                if k in updated_keys:
                    if current[k]:
                        new_lines.append(f"{k}={current[k]}")
                    seen_keys.add(k)
                    continue
                seen_keys.add(k)
                # 已有空值行 → 删除
                v = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                if not v:
                    continue
            new_lines.append(line)

        # 追加新键（跳过空值）
        for k, v in current.items():
            if k not in seen_keys and v:
                new_lines.append(f"{k}={v}")

        with open(_env_path(), "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")

        # 同步到 os.environ
        for k, v in updates.items():
            os.environ[k] = str(v or "")

        # 重载配置（锁内，确保并发写入的一致性）
        config.load_env(override=True)
        config.refresh_runtime_config()


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


# 允许写入 .env 的键名前缀白名单（防止环境变量注入攻击）
_ALLOWED_KEY_PREFIXES = (
    "APP_API_KEY",
    "API_PROVIDER_",      # API_PROVIDER_OPENAI_KEY 等
    "PROVIDER_",          # PROVIDER_OPENAI_BASE_URL 等
    "AI_REQUEST_TIMEOUT",
    "IMAGE_POLL_INTERVAL",
    "REQUEST_TIMEOUT",
    "CORS_ORIGINS",
    # UPDATE_REPO_URL 不在白名单 —— 仅允许通过 .env 文件直接修改，防止 API 接口被利用进行供应链攻击
)

# 允许写入的键名后缀白名单（针对 {PID}_IMAGE_MODELS 等自定义平台配置）
_ALLOWED_KEY_SUFFIXES = (
    "_API_KEY",
    "_BASE_URL",
    "_IMAGE_MODELS",
    "_CHAT_MODELS",
    "_VIDEO_MODELS",
    "_WALLET_API_KEY",
)


def _is_allowed_env_key(key: str) -> bool:
    """校验键名是否在白名单内（前缀匹配 + 后缀匹配）。"""
    upper = key.upper().strip()
    # 前缀匹配
    for prefix in _ALLOWED_KEY_PREFIXES:
        if upper.startswith(prefix):
            return True
    # 后缀匹配（自定义平台配置如 AIHUBMIX_IMAGE_MODELS）
    for suffix in _ALLOWED_KEY_SUFFIXES:
        if upper.endswith(suffix):
            return True
    return False


@router.post("/settings/api-keys")
async def save_api_keys(payload: dict):
    """保存 API Key 或 Base URL 等配置项。

    仅允许白名单内的键名前缀，防止系统环境变量注入攻击。
    键名会自动转为大写。
    """
    updates = {}
    rejected = []
    for k, v in payload.items():
        k = str(k).strip().upper()
        if not k:
            continue
        if not _is_allowed_env_key(k):
            rejected.append(k)
            continue
        updates[k] = str(v or "").strip()
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"不允许写入的键名: {', '.join(rejected)}"
        )
    await _write_env(updates)
    # load_env + refresh_runtime_config 已在 _write_env 锁内完成（v2.5.40）
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
    """获取 Provider 实例（测试连接/拉取模型专用）。

    与 resolve_provider 的隔离策略：
    - 内置平台从注册表获取 CLASS 后**克隆新实例**，绝不修改全局单例
    - 自定义平台动态创建新实例
    - _injected_key/_injected_url 只存在于克隆实例上，请求结束即 GC 回收
    - 并发请求各自持有独立实例，不共享可变状态

    v2.5.51 修复：之前直接修改单例的 _injected_key，导致：
    1. 测试注入的 Key 残留到后续请求（你遇到的 BUG）
    2. 并发请求互相覆盖注入 Key
    3. resolve_provider 返回的单例被"污染"，正常 Chat/生图 误用测试 Key
    """
    registry_prov = get_provider_registry().get(provider_id)
    if registry_prov is not None:
        # 内置平台：克隆新实例，不碰全局单例
        prov = registry_prov.__class__()
    else:
        # 自定义平台：新建实例 + 注入模型列表
        protocol_map = {
            "openai": OpenAIProvider,
            "apimart": APIMartProvider,
            "gemini": GeminiProvider,
            "volcengine": VolcengineProvider,
            "runninghub": RunningHubProvider,
        }
        cls = protocol_map.get(protocol, OpenAIProvider)
        prov = cls()
        _inject_custom_models(prov, provider_id)

    # 注入临时 Key / URL（仅影响当前克隆实例，不影响单例）
    if api_key:
        prov._injected_key = api_key
    if base_url:
        prov._injected_url = base_url
    return prov


def _read_env_model_lists(provider_id: str) -> dict:
    """从环境变量读取 {PID}_IMAGE_MODELS / _CHAT_MODELS / _VIDEO_MODELS。

    返回 {"image_models": [...], "chat_models": [...], "video_models": [...]}
    供 _inject_custom_models 和 _discover_custom_providers_from_env 共用。
    """
    import os as _os
    pid_upper = provider_id.upper()
    result = {}
    for suffix, key in [("image_models", "IMAGE_MODELS"),
                         ("chat_models", "CHAT_MODELS"),
                         ("video_models", "VIDEO_MODELS")]:
        raw = _os.getenv(f"{pid_upper}_{key}", "")
        result[suffix] = [s.strip() for s in raw.split(",") if s.strip()]
    return result


def _inject_custom_models(prov, provider_id: str):
    """将自定义平台的环境变量模型列表注入到 Provider 实例。"""
    models = _read_env_model_lists(provider_id)
    if models["image_models"]:
        prov.list_image_models = lambda m=models["image_models"]: m
    if models["chat_models"]:
        prov.list_chat_models = lambda m=models["chat_models"]: m
    if models["video_models"]:
        prov.list_video_models = lambda m=models["video_models"]: m


def resolve_provider(provider_id: str) -> BaseProvider | None:
    """解析 Provider（供 Chat/生图/Agent 等实际调用端点使用）。

    与 _get_or_create_provider 不同，此函数不接收显式的 key/url 参数，
    而是从环境变量（.env 文件）中自动读取配置。

    查找顺序:
    1. 内置平台 → 从 ProviderRegistry 获取（检查禁用状态）
    2. 自定义平台 → 根据 .env 中的 Key + Base URL 动态创建 OpenAIProvider
    """
    reg = get_provider_registry()

    # 1. 先查注册表——需要同时验证 Key 存在
    prov = reg.get(provider_id)
    if prov:
        api_key = config.get_provider_api_key(provider_id)
        if api_key:
            return prov
        return None  # 注册平台存在但未配置 Key

    # 2. 尝试从环境变量解析自定义平台
    api_key = config.get_provider_api_key(provider_id)
    if not api_key:
        return None

    base_url = config.get_provider_base_url(provider_id)

    # 3. 默认按 OpenAI 协议创建（绝大多数自定义平台兼容 OpenAI 格式）
    prov = OpenAIProvider()
    prov._injected_key = api_key
    if base_url:
        prov._injected_url = base_url

    # 注入自定义平台的模型列表（读取 {PID}_IMAGE_MODELS 等 env 变量）
    _inject_custom_models(prov, provider_id)

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

    # SSRF 防护：拒绝内网地址
    if temp_url:
        from ..security.network import async_validate_safe_url
        if not await async_validate_safe_url(temp_url):
            raise HTTPException(status_code=400, detail="禁止连接内网地址或云 metadata 服务")
    prov = _get_or_create_provider(provider_id, protocol, temp_key, temp_url)

    # URL 协议检测：URL 域名匹配 协议名 或 平台ID 就不报错
    # 因为 _URL_PROTOCOL_MAP 混用了协议名(modelscope)和平台名(openai)，都算合法
    url_protocol = _detect_protocol_from_url(temp_url)
    actual_protocol = prov.protocol
    if url_protocol and url_protocol != actual_protocol and url_protocol != provider_id:
        return {
            "ok": False,
            "latency_ms": 0,
            "status_code": 0,
            "error": f"URL 疑似 {url_protocol} 平台的地址，但当前选中了 {provider_id} 平台。请确认平台匹配。",
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

    # SSRF 防护：拒绝内网地址
    if temp_url:
        from ..security.network import async_validate_safe_url
        if not await async_validate_safe_url(temp_url):
            raise HTTPException(status_code=400, detail="禁止连接内网地址或云 metadata 服务")
    prov = _get_or_create_provider(provider_id, protocol, temp_key, temp_url)
    models, live = await prov.fetch_models()

    # 按类型分类
    image_models = [m.id for m in models if m.type == "image"]
    chat_models = [m.id for m in models if m.type == "chat"]
    video_models = [m.id for m in models if m.type == "video"]
    all_ids = [m.id for m in models]

    return {
        "total": len(models),
        "live": live,  # v2.5.51：前端用此字段区分"API实时拉取"和"本地默认模型"
        "all": all_ids,
        "image_models": image_models,
        "chat_models": chat_models,
        "video_models": video_models,
        "models": [{"id": m.id, "name": m.name, "type": m.type} for m in models],
    }


# ——— 平台启用 / 禁用 ———


def _is_sensitive_key(key: str) -> bool:
    """判断是否为敏感配置项（需要在 UI 上脱敏显示）。"""
    upper = key.upper()
    return any(kw in upper for kw in ("KEY", "SECRET", "TOKEN", "PASSWORD"))


def _mask(val):
    if not val:
        return ""
    return "****" + val[-4:] if len(val) > 4 else "****"
