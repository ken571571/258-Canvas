# MiMo API 文档

> 小米 AI 智能助手 · OpenAI 兼容协议
> 官方文档：https://api.xiaomimimo.com/docs

---

## 一、接入信息

| 计费模式 | Base URL | API Key 格式 |
|----------|----------|:---:|
| 按量付费 | `https://api.xiaomimimo.com/v1` | `sk-xxxxx` |
| Token Plan | `https://token-plan-cn.xiaomimimo.com/v1` | `tp-xxxxx` |

## 二、认证（⚠ 与标准 OpenAI 不同）

```
Header:  api-key: {MIMO_API_KEY}    ← 不是 Authorization: Bearer !
```

## 三、可用模型

| 模型 ID | 类型 | 说明 |
|---------|------|------|
| `mimo-v2.5-pro` | chat | 主力模型，支持思考模式 + 工具调用 |

不支持 image / video / vision。

## 四、reasoning_content 字段（⚠ 关键）

思考模式下 assistant 消息额外携带 `reasoning_content`（推理链文本）。**多轮对话时 messages 数组必须保留所有历史的 `reasoning_content`**，否则模型表现下降。

```json
{
  "role": "assistant",
  "content": "Hello! I am MiMo.",
  "reasoning_content": "Okay, the user just asked me to introduce myself..."
}
```

本项目引擎中 `msg.model_dump()` 已自动序列化该字段，无需额外处理 — 只要不在中间截断 messages 即可。

## 五、环境变量

```bash
MIMO_API_KEY=sk-xxxxx                          # 必填
MIMO_BASE_URL=https://api.xiaomimimo.com/v1    # 可选，Token Plan 用户改为专属 URL
```

## 六、Provider 实现骨架

```python
# server/providers/mimo.py
from .openai import OpenAIProvider

class MiMoProvider(OpenAIProvider):

    _DEFAULT_BASE = "https://api.xiaomimimo.com/v1"
    _DEFAULT_CHAT_MODEL = "mimo-v2.5-pro"

    @property
    def provider_id(self) -> str:
        return "mimo"

    @property
    def provider_name(self) -> str:
        return "MiMo"

    @property
    def _api_key(self) -> str:
        temp = self._temp_key("MIMO_API_KEY")
        if temp: return temp
        return os.getenv("MIMO_API_KEY", "").strip().strip('"').strip("'")

    @property
    def _base_url(self) -> str:
        temp = self._temp_url(self._DEFAULT_BASE)
        if temp != self._DEFAULT_BASE: return temp.rstrip("/")
        return os.getenv("MIMO_BASE_URL", self._DEFAULT_BASE).rstrip("/")

    def build_headers(self) -> dict:
        """MiMo 使用 api-key 而非 Authorization: Bearer。"""
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json"
        }

    def list_chat_models(self):
        return self._model_list_from_env("MIMO_CHAT_MODELS", [self._DEFAULT_CHAT_MODEL])

    def list_image_models(self):
        return []

    def list_video_models(self):
        return []
```

## 七、Python SDK 调用参考

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-xxxxx",                        # 或 tp-xxxxx
    base_url="https://api.xiaomimimo.com/v1"    # Token Plan 用户替换
)

completion = client.chat.completions.create(
    model="mimo-v2.5-pro",
    messages=[{"role": "user", "content": "你好"}],
    max_completion_tokens=1024,
    temperature=1.0,
    top_p=0.95,
    stream=False
)
```

其他参数（`tools`、`tool_choice`、`stop` 等）与标准 OpenAI API 一致，OpenAI SDK 自动处理。
