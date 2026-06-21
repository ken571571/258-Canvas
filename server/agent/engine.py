"""Agent 执行引擎：ReAct 循环（完整实现）"""

import json
import logging
import os
import time
from typing import List, Dict, Any
from .skills import get_skill_registry
from .. import config
from ..providers.base import BaseProvider

_log = logging.getLogger("canvas571")


async def run_agent(
    agent_config: dict,
    user_input: str,
    input_images: List[str],
    provider: BaseProvider,
    docs_dir: str = "",
    agent_dir: str = "",
    fingerprint: str = "",
) -> dict:
    """执行 Agent 任务，返回 {success, steps, final_output, output_images, error}"""
    started = time.time()
    steps: List[dict] = []

    system_prompt = agent_config.get("system_prompt", "")
    model = agent_config.get("model", "gpt-4o-mini")
    max_steps = agent_config.get("max_steps", 10)
    skill_ids = [s.get("id", s) if isinstance(s, dict) else s for s in agent_config.get("skills", [])]
    kb_ids = agent_config.get("knowledge_bases", [])

    skill_reg = get_skill_registry()
    skill_reg._agent_config = agent_config  # 注入 Agent 配置，技能可读取
    tools = skill_reg.to_openai_tools(skill_ids)

    # 如果用 Gemini 且启用了 tools，打印警告（Gemini 原生协议未适配 Function Calling）
    if tools and provider and provider.provider_id == "gemini":
        import logging
        logging.getLogger("agent").warning(
            f"[agent] Agent '{agent_config.get('name', agent_config.get('id'))}' "
            f"配置了技能但使用 Gemini Provider，Function Calling 将静默失效。"
            f"建议改用 openai/apimart 协议的平台。"
        )

    # 构建 system prompt
    sys_content = system_prompt or "你是一个 AI 助手。可以使用工具完成任务。完成后请用中文总结。"
    if tools:
        sys_content += "\n\n你可以使用提供的工具函数来完成任务。调用工具后等待结果再继续。"

    # 自动加载 docs/ 下的 .md 参考文档（异步，不阻塞事件循环）
    if docs_dir:
        docs_ctx = await _load_docs(docs_dir, fingerprint)
        if docs_ctx:
            sys_content += f"\n\n## 参考文档\n{docs_ctx}"

    # 注入知识库上下文
    if kb_ids and user_input:
        kb_ctx = await _search_kb(kb_ids, user_input, agent_dir, fingerprint)
        if kb_ctx:
            sys_content += f"\n\n## 知识库参考\n{kb_ctx}"

    messages: List[dict] = [{"role": "system", "content": sys_content}]

    # 用户输入（可能带图片）
    user_content = user_input or "请执行任务"
    if input_images:
        parts = [{"type": "text", "text": user_content}]
        for url in input_images:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_content})

    final_output = ""
    try:
        for step_idx in range(max_steps):
            # 调用 LLM
            try:
                chat_result = await provider.chat(
                    messages=messages,
                    model=model,
                    tools=tools if tools else None,
                )
            except Exception as e:
                steps.append({"step": step_idx + 1, "status": "error", "error": str(e)})
                break

            # 如果有 tool_calls，执行工具
            if chat_result.tool_calls and tools:
                tool_calls = chat_result.tool_calls
                # 记录 assistant 消息（含 tool_calls）
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": chat_result.content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(assistant_msg)

                # 执行每个工具调用
                for tc in tool_calls:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("arguments", {})
                    call_id = tc.get("id", "")

                    result = await skill_reg.execute(tool_name, tool_args)
                    result_str = json.dumps(result, ensure_ascii=False)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_str,
                    })

                    steps.append({
                        "step": step_idx + 1,
                        "status": "tool_call",
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": result,
                    })

                # 继续循环，让 LLM 处理工具结果
                continue

            # 无 tool_calls → 任务完成
            final_output = chat_result.content or ""
            steps.append({"step": step_idx + 1, "status": "done", "output": final_output})
            break

        # 循环结束仍未完成
        if not final_output:
            # 尝试让 LLM 做最终总结
            messages.append({"role": "user", "content": "请基于以上工具执行结果，给出最终总结。"})
            try:
                final = await provider.chat(messages=messages, model=model)
                if final.content:
                    final_output = final.content
                    steps.append({"step": "final", "status": "done", "output": final_output})
            except Exception as e:
                _log.warning("Agent final summary failed: %s", e)

        if not final_output:
            final_output = "任务已执行但未获得最终输出。"

        elapsed = int((time.time() - started) * 1000)
        return {
            "success": True,
            "steps": steps,
            "final_output": final_output,
            "output_images": [],
            "total_elapsed_ms": elapsed,
            "model_used": model,              # Agent 配置的模型
            "provider_used": agent_config.get("provider_id", "openai"),
        }

    except (ConnectionError, OSError):
        elapsed = int((time.time() - started) * 1000)
        return {"success": False, "steps": steps, "final_output": "", "error": "无法连接 API 服务器", "total_elapsed_ms": elapsed,
                "model_used": model, "provider_used": agent_config.get("provider_id", "openai")}
    except Exception as e:
        elapsed = int((time.time() - started) * 1000)
        return {"success": False, "steps": steps, "final_output": final_output, "error": f"{type(e).__name__}: {e}", "total_elapsed_ms": elapsed,
                "model_used": model, "provider_used": agent_config.get("provider_id", "openai")}


def _load_docs_sync(docs_dir: str, fingerprint: str = "") -> str:
    """扫描 docs/ 目录下所有 .md 和 .txt 文件，拼接为上下文（同步实现）。

    protected agent 的文件已加密，需要 fingerprint 解密到内存。
    """
    import os as _os
    if not _os.path.isdir(docs_dir):
        return ""
    parts = []
    for fn in sorted(_os.listdir(docs_dir)):
        if fn.startswith("."):
            continue
        path = _os.path.join(docs_dir, fn)
        if not _os.path.isfile(path):
            continue
        ext = _os.path.splitext(fn)[1].lower()
        if ext not in (".md", ".txt", ".markdown"):
            continue
        try:
            with open(path, "rb") as f:
                raw = f.read()
            # 检测加密文件
            from ..security.agent_crypto import is_encrypted, decrypt_bytes
            import hashlib as _hashlib
            if is_encrypted(raw):
                if not fingerprint:
                    continue  # 无指纹，跳过加密文件
                fkey = _hashlib.sha256(("agent_fingerprint:" + fingerprint).encode()).digest()
                content = decrypt_bytes(raw, fkey).decode("utf-8", errors="replace")
            else:
                content = raw.decode("utf-8")
            if content.strip():
                parts.append(f"### {fn}\n{content}")
        except Exception:
            pass
    return "\n\n---\n\n".join(parts) if parts else ""


async def _load_docs(docs_dir: str, fingerprint: str = "") -> str:
    """异步版 _load_docs：在线程池中执行同步 I/O，不阻塞事件循环。"""
    import asyncio
    return await asyncio.get_running_loop().run_in_executor(None, _load_docs_sync, docs_dir, fingerprint)


async def _search_kb(kb_ids: List[str], query: str, agent_dir: str = "", fingerprint: str = "") -> str:
    """从知识库中检索相关片段。

    优先级：
    1. Agent 自带的 _kb_snapshot.json（跨实例拷贝后仍可用）
    2. 实时知识库索引（当前实例的 data/knowledge_bases/_index.json）
    """
    # 优先：从 agent 目录的快照中检索（跨实例可移植）
    if agent_dir:
        snapshot_path = os.path.join(agent_dir, "_kb_snapshot.json")
        if os.path.exists(snapshot_path):
            try:
                with open(snapshot_path, "rb") as f:
                    raw = f.read()
                from ..security.agent_crypto import is_encrypted, decrypt_bytes
                import hashlib as _hashlib
                if is_encrypted(raw):
                    if not fingerprint:
                        raw = b"{}"  # 不能解密，跳过
                    else:
                        fkey = _hashlib.sha256(("agent_fingerprint:" + fingerprint).encode()).digest()
                        raw = decrypt_bytes(raw, fkey)
                snapshot = json.loads(raw if not is_encrypted(raw) else "{}")
                from ..services.knowledge_service import search_from_snapshot
                top = search_from_snapshot(snapshot, kb_ids, query, 3)
                if top:
                    return "\n---\n".join(f"【{c['filename']}】\n{c['text']}" for c in top)
            except Exception:
                pass  # 快照损坏时回退到实时检索

    # 回退：实时知识库检索（向后兼容）
    from ..routes.knowledge import search_kb_chunks
    top = search_kb_chunks(kb_ids, query, 3)
    if not top:
        return ""
    return "\n---\n".join(f"【{c['filename']}】\n{c['text']}" for c in top)
