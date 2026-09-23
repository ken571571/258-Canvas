# 自定义技能目录

此目录存放 Agent 级自定义技能。

## 已安装：h3-prompt-writing（官方）

来源：https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing

MiniMax H3 官方提示词写作 skill，纯 Markdown + 参考文件，无外部 API 调用，适用于 T2VA / I2VA / FL2VA / L2VA / Ref2VA 全模式。

- `SKILL.md`：skill 入口，说明工作流和模式选择。
- `references/base-en.txt`：text/keyframe 模式（含 FL2VA 首尾帧）的权威提示词结构指南，本智能体的核心参考。
- `references/ref-en.txt`：全参考模式（Ref2VA）指南，备用参考。

本智能体使用 FL2VA（首尾帧）模式，严格遵循 base-en.txt 中的字段名、顺序和时间标注格式。
