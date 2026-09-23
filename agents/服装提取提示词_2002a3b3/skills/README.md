# 技能目录说明

只有当你需要 Agent 在 ReAct 循环中调用可执行函数时，才把 Python 技能放到这里。

每个技能文件必须暴露：

```python
SKILL_ID = "skill_id"
SKILL_NAME = "技能名"
SKILL_DESCRIPTION = "给 LLM 看的用途说明"
SKILL_PARAMETERS = {"type": "object", "properties": {}, "required": []}

async def execute(arguments, agent_config=None):
    return {"result": "..."}
```

可参考 `../../skills-library/` 里的示例。
