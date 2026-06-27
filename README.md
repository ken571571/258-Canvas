# ∞ 无限画布 (Infinite Canvas)

> AI 驱动的无限创作平台 — 聚合多 AI 平台的画布式创作工具

[![Version](https://img.shields.io/badge/version-2.5.54-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Source%20Available-orange)](LICENSE)

## ✨ 功能

- 🎨 **无限画布** — 可视化节点编辑器，拖拽连线构建 AI 工作流
- 🤖 **多 AI 平台聚合** — OpenAI / DeepSeek / Gemini / 火山方舟 / ModelScope / RunningHub / APIMart
- 🖼️ **文生图 / 图生图** — 多模型图片生成，支持 Loop 批量管线
- 🎬 **视频生成** — 支持 Veo3 等视频模型
- 💬 **LLM 对话** — 流式/非流式聊天，多对话管理
- 🧠 **Agent 智能体** — ReAct 执行引擎，支持知识库和自定义技能
- ⚡ **ComfyUI 集成** — 工作流管理 + 异步执行
- 🔒 **加密 Agent** — AES-256-GCM 加密，支持付费分发
- 🌐 **局域网协作** — 零配置多端使用，乐观锁防冲突
- 🌍 **中英双语** — 483 个翻译键，100% 覆盖

---

## 📦 环境要求

- **Python 3.10+**（推荐 3.10）
- Windows / macOS / Linux
- 无需数据库，无需额外服务

---

## 🚀 安装与启动

### 1. 克隆仓库

```bash
git clone <你的仓库地址>
cd <仓库目录>
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key（可选，启动后也能配置）

```bash
cp API/.env.example API/.env
# 编辑 API/.env，填入你的 API Key
```

支持平台：OpenAI / DeepSeek / Gemini / 火山方舟 / ModelScope / RunningHub / APIMart / 自定义 OpenAI 兼容接口。

### 4. 启动服务

**Windows：**
```bat
启动服务.bat
```

**macOS / Linux：**
```bash
python run.py
```

### 5. 打开浏览器

访问 **http://127.0.0.1:3571/**

- 本机免密访问
- 局域网其他设备输入预设密码（默认 `571`，可在设置页修改）

---

## 🔧 配置 API 平台

1. 打开设置页 → **API 设置**
2. 点击平台 → 填入 API Key → 保存
3. 保存即生效，无需重启

详细配置说明见 `API/.env.example`。

---

## 📖 使用文档

| 页面 | 功能 |
|------|------|
| 画布入口 | 创建/管理画布 |
| 画布编辑器 | 节点编辑、连线、生图/视频/Agent 管线 |
| AI 对话 | 多对话 LLM 聊天 |
| Agent 管理 | 创建/配置/加密/导出智能体 |
| ComfyUI | 工作流管理与异步执行 |
| 生图/视频 | 独立 API 调用页面 |
| 设置 | API Key、密码、模型管理 |

---

## 📁 项目结构

```
├── server/         # Python FastAPI 后端
│   ├── routes/     # API 路由（16 模块）
│   ├── services/   # 业务逻辑
│   ├── providers/  # AI 平台适配（7 平台）
│   ├── agent/      # Agent 执行引擎
│   ├── security/   # 安全模块（加密/SSRF/路径）
│   └── storage/    # JSON 持久化
├── static/         # 前端
│   ├── js/         # 18 个 JS 模块
│   ├── css/        # 样式
│   └── locales/    # 中英文翻译（483 键）
├── tests/          # 测试（241 用例）
├── workflows/      # ComfyUI 工作流模板
├── agents/         # Agent 数据（每个 Agent 一个目录）
├── canvases/       # 画布数据（每个画布一个目录）
├── skills/         # 自定义技能
└── scripts/        # 测试脚本
```

---

## 🧪 运行测试

```bash
# 关闭限流（避免测试被 429 拦截）
RATE_LIMIT_ENABLED=0 python -m unittest discover -s tests

# 或使用脚本
.\scripts\test_all.bat    # Windows
./scripts/test_all.sh     # Linux/macOS
```

---

## ⚠️ 许可

本项目采用**源码可用**（Source Available）许可证。

- ✅ 免费商用、学习研究、内部使用
- ❌ 禁止将源码封装为商业产品出售
- 个人创作的 Agent 和工作流不受此限制

详见 [LICENSE](LICENSE)。

---

*Made with ❤️ by ken571571*
