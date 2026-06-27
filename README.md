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

## 🚀 快速启动

### Windows
```bat
.\启动服务.bat
```

### macOS / Linux
```bash
./python/python run.py
```

启动后访问：**http://127.0.0.1:3571/**

- 本机免密访问
- 局域网输入预设密码（默认 `571`）

## 📁 项目结构

```
├── server/         # Python FastAPI 后端（59 文件 / ~11,000 行）
├── static/         # 前端（18 JS 模块 / 9 HTML 页面）
├── tests/          # 测试（241 用例）
├── workflows/      # ComfyUI 工作流模板
├── scripts/        # 测试脚本
├── python/         # 嵌入式 Python 运行时（需自行下载）
└── 项目.MD          # 完整技术文档（中文）
```

## 🔧 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+ / FastAPI / uvicorn / httpx / Pydantic |
| 前端 | 原生 JavaScript (ES6+) / CSS Custom Properties |
| 安全 | AES-256-GCM / PBKDF2 / SSRF 防护 / XSS 防御 |
| 存储 | 文件系统 / JSON Store（TTL 缓存） |

## 📖 文档

完整的技术文档、API 路由表、开发约定和 BUG 模式库请参阅 [项目.MD](项目.MD)。

## ⚠️ 许可

本项目采用**源码可用**（Source Available）许可证。允许免费商业使用、学习研究和内部使用，**禁止**将源码封装为商业产品出售。

详见 [LICENSE](LICENSE)。

---

*Made with ❤️ by ken571571*
