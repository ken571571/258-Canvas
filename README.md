<details open>
<summary><b>🇺🇸 English</b> (click to switch language)</summary>

# ∞ 258 Canvas

> AI-powered infinite canvas — aggregate multiple AI platforms for image & video generation, LLM chat, and ComfyUI workflow execution. Built-in Agent system with knowledge bases, custom Python skills, and encrypted distribution. Connect your local ComfyUI backend for seamless workflow automation. Zero-config LAN collaboration with bilingual UI.

[![Version](https://img.shields.io/badge/version-2.5.54-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Source%20Available-orange)](LICENSE)

## ✨ Features

- 🎨 **Infinite Canvas** — visual node editor, drag-and-drop AI workflows
- 🤖 **Multi-Platform** — OpenAI / DeepSeek / Gemini / Volcengine / ModelScope / RunningHub / APIMart
- 🖼️ **Image Generation** — text-to-image, image-to-image, Loop batch pipelines
- 🎬 **Video Generation** — Veo3 and other video models
- 💬 **LLM Chat** — streaming/non-streaming, multi-conversation
- 🧠 **Agent System** — ReAct execution engine, knowledge bases, custom Python skills
- ⚡ **ComfyUI Integration** — workflow management + async execution, local backend support
- 🔒 **Encrypted Agent** — AES-256-GCM, machine-bound, export/distribution ready
- 🌐 **LAN Collaboration** — zero-config multi-device, optimistic locking
- 🌍 **Bilingual UI** — 483 translation keys, 100% Chinese/English coverage

---

## 📦 Requirements

- **Python 3.10+**
- Windows / macOS / Linux
- No database or external services required

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/ken571571/258-Canvas.git
cd 258-Canvas

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Configure API keys
cp API/.env.example API/.env
# Edit API/.env with your keys

# 4. Run
python run.py        # macOS / Linux
# or double-click 启动服务.bat on Windows

# 5. Open browser → http://127.0.0.1:3571
```

- Localhost access: no password required
- LAN access: enter preset password (default `258`)

---

## 📖 Project Structure

```
├── server/         # Python FastAPI backend
├── static/         # Frontend (18 JS modules, 9 pages)
├── tests/          # Tests (241 cases)
├── workflows/      # ComfyUI workflow templates
├── agents/         # Agent data
├── canvases/       # Canvas data
├── skills/         # Custom skills
└── scripts/        # Test scripts
```

## 🧪 Run Tests

```bash
RATE_LIMIT_ENABLED=0 python -m unittest discover -s tests
```

## ⚠️ License

**Source Available** — free for commercial use, study, and internal use. Redistribution as a commercial product is prohibited unless explicitly authorized.

See [LICENSE](LICENSE).

</details>

<details>
<summary><b>🇨🇳 中文</b>（点击切换语言）</summary>

# ∞ 258 无限画布

> AI 驱动的无限创作平台 — 聚合多 AI 平台的画布式创作工具。内置 Agent 智能体系统，支持知识库、自定义 Python 技能和加密分发。可对接本地 ComfyUI 后端实现无缝工作流自动化。零配置局域网协作，中英双语界面。

[![Version](https://img.shields.io/badge/版本-2.5.54-blue)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/许可-Source%20Available-orange)](LICENSE)

## ✨ 功能

- 🎨 **无限画布** — 可视化节点编辑器，拖拽连线构建 AI 工作流
- 🤖 **多平台聚合** — OpenAI / DeepSeek / Gemini / 火山方舟 / ModelScope / RunningHub / APIMart
- 🖼️ **文生图 / 图生图** — 多模型图片生成，支持 Loop 批量管线
- 🎬 **视频生成** — 支持 Veo3 等视频模型
- 💬 **LLM 对话** — 流式/非流式聊天，多对话管理
- 🧠 **Agent 智能体** — ReAct 执行引擎，支持知识库和自定义 Python 技能
- ⚡ **ComfyUI 集成** — 工作流管理 + 异步执行，支持对接本地 ComfyUI
- 🔒 **加密 Agent** — AES-256-GCM 加密，机器绑定，支持付费分发
- 🌐 **局域网协作** — 零配置多端使用，乐观锁防冲突
- 🌍 **中英双语** — 483 个翻译键，100% 覆盖

---

## 📦 环境要求

- **Python 3.10+**
- Windows / macOS / Linux
- 无需数据库，无需额外服务

---

## 🚀 快速启动

```bash
# 1. 克隆
git clone https://github.com/ken571571/258-Canvas.git
cd 258-Canvas

# 2. 安装依赖
pip install -r requirements.txt

# 3. （可选）配置 API Key
cp API/.env.example API/.env
# 编辑 API/.env，填入你的密钥

# 4. 运行
python run.py        # macOS / Linux
# Windows 双击 启动服务.bat

# 5. 打开浏览器 → http://127.0.0.1:3571
```

- 本机免密访问
- 局域网输入预设密码（默认 `258`）

---

## 📖 项目结构

```
├── server/         # Python FastAPI 后端
├── static/         # 前端（18 个 JS 模块 / 9 个页面）
├── tests/          # 测试（241 个用例）
├── workflows/      # ComfyUI 工作流模板
├── agents/         # Agent 数据
├── canvases/       # 画布数据
├── skills/         # 自定义技能
└── scripts/        # 测试脚本
```

## 🧪 运行测试

```bash
RATE_LIMIT_ENABLED=0 python -m unittest discover -s tests
```

## ⚠️ 许可

**源码可用（Source Available）** — 允许免费商用、学习研究和内部使用。禁止将源码封装为商业产品出售，除非获得明确授权。

详见 [LICENSE](LICENSE)。

</details>

---

*Made with ❤️ by ken571571*
