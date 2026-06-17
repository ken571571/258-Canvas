"""API 路由：Agent 智能体

新结构: agents/{agent_id}/
  ├── agent.json      ← 配置
  ├── skills/         ← 自定义技能 .py
  ├── knowledge/      ← 知识库文档
  └── docs/           ← 参考 .MD
"""

import os
import uuid
import time
import json
import re
import shutil
import base64 as b64
from fastapi import APIRouter, HTTPException, UploadFile, File
from .. import config
from ..utils import KeyedLockManager, safe_join
from ..storage.json_store import store
from ..logging_config import get_logger

log = get_logger("agent_routes")
from ..agent.engine import run_agent
from ..agent.skills import get_skill_registry, reload_external_skills
from ..providers.registry import get_provider_registry
from ..routes.providers_cfg import resolve_provider

router = APIRouter(prefix="/api", tags=["agent"])

_locks = KeyedLockManager()


# ===== 路径工具 =====

def _safe_name(name: str) -> str:
    """把名称转为安全的文件夹名：保留中英文数字，空格和特殊符号替换为下划线。"""
    # 允许：中文、英文、数字、下划线、连字符
    safe = re.sub(r"[^\w一-鿿-]", "_", name)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:60] if safe else "agent"


def _find_agent_dir(agent_id: str) -> str | None:
    """根据 agent_id 查找文件夹路径（扫描 agents/ 下所有子目录的 agent.json）。"""
    if not os.path.isdir(config.AGENTS_ROOT):
        return None
    for name in os.listdir(config.AGENTS_ROOT):
        d = os.path.join(config.AGENTS_ROOT, name)
        if not os.path.isdir(d):
            continue
        cfg = os.path.join(d, "agent.json")
        if os.path.exists(cfg):
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("id") == agent_id:
                    return d
            except Exception as e:
                log.warning(f"读取 Agent 配置失败 {cfg}: {e}")
    return None


def _agent_dir(agent_id: str) -> str:
    """获取 agent 文件夹路径。先查已有，没有则回退到旧格式。"""
    existing = _find_agent_dir(agent_id)
    if existing:
        return existing
    # 兼容旧 data/agents/{id}.json → 用 id 做文件夹名
    return os.path.join(config.AGENTS_ROOT, re.sub(r"[^\w一-鿿-]", "_", agent_id))


def _agent_config_path(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "agent.json")


def _agent_skills_dir(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "skills")


def _agent_knowledge_dir(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "knowledge")


def _agent_docs_dir(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "docs")


def _load_agent(agent_id: str) -> dict | None:
    path = _agent_config_path(agent_id)
    if not os.path.exists(path):
        # 兼容旧路径
        old_path = os.path.join(config.AGENTS_DIR, f"{re.sub(r'[^a-zA-Z0-9_-]', '_', agent_id)}.json")
        if os.path.exists(old_path):
            with open(old_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def _save_agent(agent: dict):
    agent["updated_at"] = int(time.time() * 1000)
    d = _agent_dir(agent["id"])
    os.makedirs(d, exist_ok=True)
    # 确保子目录存在
    for sub in ["skills", "knowledge", "docs"]:
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    lock = await _locks.get(agent["id"])
    async with lock:
        tmp = _agent_config_path(agent["id"]) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(agent, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _agent_config_path(agent["id"]))


def _scan_agents() -> list[dict]:
    """扫描 agents/ 目录下所有子文件夹，读取 agent.json"""
    agents = []
    if not os.path.isdir(config.AGENTS_ROOT):
        return agents
    for name in sorted(os.listdir(config.AGENTS_ROOT)):
        if name.startswith("_") or name.startswith("."):
            continue
        agent_dir = os.path.join(config.AGENTS_ROOT, name)
        if not os.path.isdir(agent_dir):
            continue
        cfg_path = os.path.join(agent_dir, "agent.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    a = json.load(f)
                a.setdefault("id", name)
                a["_dir"] = name  # 文件夹名
                agents.append(a)
            except Exception as e:
                log.warning(f"读取 Agent 配置失败 {cfg_path}: {e}")
    # 兼容旧 data/agents/*.json
    if os.path.isdir(config.AGENTS_DIR):
        for fn in os.listdir(config.AGENTS_DIR):
            if fn.endswith(".json"):
                agent_id = fn[:-5]
                new_dir = _agent_dir(agent_id)
                if not os.path.exists(new_dir):
                    try:
                        with open(os.path.join(config.AGENTS_DIR, fn), "r", encoding="utf-8") as f:
                            a = json.load(f)
                        a.setdefault("id", agent_id)
                        agents.append(a)
                    except Exception as e:
                        log.warning(f"读取旧 Agent 配置失败 {fn}: {e}")
    agents.sort(key=lambda a: a.get("updated_at", 0), reverse=True)
    return agents


def _list_agent_files(agent_id: str, sub: str, exts: tuple = (".md", ".txt", ".pdf")) -> list[dict]:
    """列出 agent 子目录下的文件。"""
    try:
        d = safe_join(_agent_dir(agent_id), sub)
    except ValueError:
        return []
    if not os.path.isdir(d):
        return []
    files = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("."):
            continue
        path = os.path.join(d, fn)
        if os.path.isfile(path) and fn.lower().endswith(exts):
            files.append({
                "name": fn,
                "size": os.path.getsize(path),
                "ext": os.path.splitext(fn)[1].lower(),
                "updated_at": int(os.path.getmtime(path) * 1000),
            })
    return files


# ===== 技能列表 =====

@router.get("/agents/skills")
def list_skills():
    reg = get_skill_registry()
    return {"skills": [{"id": s.id, "name": s.name, "description": s.description, "parameters": s.parameters} for s in reg.list_all()]}


@router.post("/agents/skills/reload")
def reload_skills():
    reload_external_skills()
    reg = get_skill_registry()
    return {"skills": [{"id": s.id, "name": s.name, "description": s.description} for s in reg.list_all()]}


# ===== Agent CRUD =====

@router.get("/agents")
def list_agents():
    return {"agents": _scan_agents()}


@router.post("/agents")
async def create_agent(payload: dict):
    name = str(payload.get("name") or "新智能体").strip()[:80]
    aid = uuid.uuid4().hex[:16]
    now = int(time.time() * 1000)
    a = {
        "id": aid,
        "name": name,
        "system_prompt": "",
        "skills": [],
        "knowledge_bases": [],
        "model": "gpt-4o-mini",
        "provider_id": "openai",
        "max_steps": 10,
        "created_at": now,
        "updated_at": now,
    }
    # 用名字+短ID 作为文件夹名
    slug = _safe_name(name)
    dir_name = f"{slug}_{aid[:8]}"
    d = os.path.join(config.AGENTS_ROOT, dir_name)
    os.makedirs(d, exist_ok=True)
    for sub in ["skills", "knowledge", "docs"]:
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    # 原子写入（JsonStore：KeyedLockManager 加锁 + tmp+os.replace）
    config_path = os.path.join(d, "agent.json")
    await store.write_with_timestamp(config_path, a)
    return {"agent": a, "dir": dir_name}


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    a = _load_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    # 附加上文件列表
    a.setdefault("id", agent_id)
    a["_files"] = {
        "skills": _list_agent_files(agent_id, "skills", (".py",)),
        "knowledge": _list_agent_files(agent_id, "knowledge", (".md", ".txt", ".pdf")),
        "docs": _list_agent_files(agent_id, "docs", (".md", ".txt")),
    }
    return {"agent": a}


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, payload: dict):
    a = _load_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    old_dir = _agent_dir(agent_id)
    old_name = a.get("name", "")

    for field in ("name", "system_prompt", "model", "provider_id"):
        if field in payload:
            a[field] = payload[field]
    for field in ("skills", "knowledge_bases"):
        if field in payload:
            a[field] = payload[field]
    if "max_steps" in payload:
        a["max_steps"] = int(payload["max_steps"])

    await _save_agent(a)

    # 如果名字变了且文件夹名包含旧名字，则重命名
    new_name = a.get("name", "")
    if new_name != old_name and os.path.isdir(old_dir):
        new_dir = os.path.join(config.AGENTS_ROOT, f"{_safe_name(new_name)}_{agent_id[:8]}")
        # 只有当新路径跟旧路径不同时才重命名
        if os.path.normpath(new_dir) != os.path.normpath(old_dir) and not os.path.exists(new_dir):
            try:
                os.rename(old_dir, new_dir)
            except Exception:
                pass  # 重命名失败不影响保存

    return {"agent": a}


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    d = _agent_dir(agent_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
    # 兼容旧文件
    old = os.path.join(config.AGENTS_DIR, f"{re.sub(r'[^a-zA-Z0-9_-]', '_', agent_id)}.json")
    if os.path.exists(old):
        os.remove(old)
    return {"ok": True}


# ===== Agent 文件管理 =====

@router.get("/agents/{agent_id}/files/{sub}")
def list_agent_files_endpoint(agent_id: str, sub: str):
    """列出 agent 子目录文件。sub: skills | knowledge | docs"""
    if sub not in ("skills", "knowledge", "docs"):
        raise HTTPException(status_code=400, detail="sub 必须是 skills / knowledge / docs")
    return {"files": _list_agent_files(agent_id, sub)}


@router.post("/agents/{agent_id}/files/{sub}")
async def upload_agent_file(agent_id: str, sub: str, file: UploadFile = File(...)):
    """上传文件到 agent 子目录。"""
    if sub not in ("skills", "knowledge", "docs"):
        raise HTTPException(status_code=400, detail="sub 必须是 skills / knowledge / docs")
    a = _load_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    try:
        target_dir = safe_join(_agent_dir(agent_id), sub)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")
    os.makedirs(target_dir, exist_ok=True)

    raw = await file.read()
    filename = file.filename or "未命名"
    # 安全处理文件名
    safe_name = re.sub(r"[\\/:*?\"<>|]", "_", filename)
    try:
        path = safe_join(target_dir, safe_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")
    with open(path, "wb") as f:
        f.write(raw)

    return {"ok": True, "name": safe_name, "size": len(raw)}


@router.delete("/agents/{agent_id}/files/{sub}")
def delete_agent_file(agent_id: str, sub: str, name: str = ""):
    """删除 agent 子目录下的文件。"""
    if sub not in ("skills", "knowledge", "docs"):
        raise HTTPException(status_code=400, detail="sub 必须是 skills / knowledge / docs")
    name = str(name).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    safe_name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    try:
        path = safe_join(_agent_dir(agent_id), sub, safe_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    os.remove(path)
    return {"ok": True}


@router.get("/agents/{agent_id}/files/{sub}/{filename:path}")
def get_agent_file_content(agent_id: str, sub: str, filename: str):
    """读取 agent 文件的原始内容。"""
    if sub not in ("skills", "knowledge", "docs"):
        raise HTTPException(status_code=400, detail="sub 必须是 skills / knowledge / docs")
    try:
        base_dir = safe_join(_agent_dir(agent_id), sub)
        path = safe_join(base_dir, filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(path, "rb") as f:
            import base64
            content = base64.b64encode(f.read()).decode("ascii")
            return {"content": content, "encoding": "base64"}
    return {"content": content, "encoding": "utf-8"}


# ===== Agent 深度设计 =====

@router.post("/agents/design")
async def design_agent_prompt(payload: dict):
    """用 Agent 框架深度设计系统提示词。

    payload: { user_input, agent_config: {name, skills, knowledge_bases, system_prompt}, provider_id, model }
    """
    user_input = str(payload.get("user_input") or "").strip()
    agent_cfg = payload.get("agent_config") or {}
    provider_id = str(payload.get("provider_id") or "openai")
    model = str(payload.get("model") or "gpt-4o-mini")

    if not user_input:
        raise HTTPException(status_code=400, detail="user_input 不能为空")

    prov = resolve_provider(provider_id)
    if not prov:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台: {provider_id}")

    # 构建设计器 Agent 的 system prompt
    skills_info = ", ".join([s for s in agent_cfg.get("skills", [])]) or "无"
    kb_info = ", ".join([k for k in agent_cfg.get("knowledge_bases", [])]) or "无"
    current_prompt = agent_cfg.get("system_prompt", "") or "（空）"

    designer_sys = f"""你是一个专业的 Prompt Engineer，你的任务是为一个 AI Agent 设计高质量的系统提示词。

## 目标 Agent 信息
- 名称: {agent_cfg.get('name', '未命名')}
- 可用技能: {skills_info}
- 知识库: {kb_info}
- 当前系统提示词: {current_prompt}

## 工作流程
1. 先理解用户需求，确认 Agent 的目标场景
2. 分析当前提示词的优缺点（如果有的话）
3. 根据可用技能和知识库，设计合适的角色定位
4. 生成完整的系统提示词，用 ``` 包裹

## 设计原则
- 用中文
- 明确定义角色、能力边界、行为规范
- 如果 Agent 有技能，说明何时该使用哪个技能
- 如果 Agent 有知识库，说明如何利用知识库内容
- 不要过长，聚焦核心要点
- 如果已有提示词，在它的基础上改进而非重写

完成后输出最终的系统提示词。"""

    config = {
        "id": "_designer",
        "name": "Prompt Designer",
        "system_prompt": designer_sys,
        "skills": [],
        "knowledge_bases": [],
        "model": model,
        "provider_id": provider_id,
        "max_steps": 5,
    }

    result = await run_agent(
        agent_config=config,
        user_input=user_input,
        input_images=[],
        provider=prov,
    )
    return result


# ===== Agent 执行 =====

@router.post("/agents/{agent_id}/run")
async def run_agent_endpoint(agent_id: str, payload: dict):
    a = _load_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    pid = a.get("provider_id", "openai")
    prov = resolve_provider(pid)
    if not prov:
        return {"success": False, "error": f"未找到 API 平台: {pid}"}

    input_images = []
    for url in (payload.get("input_images") or []):
        url = str(url or "").strip()
        if not url:
            continue
        if url.startswith(("http://", "https://", "data:")):
            input_images.append(url)
        elif url.startswith(("/assets/", "/output/", "/input/")):
            # 安全：使用 safe_join 防止路径穿越
            try:
                # 提取相对路径（去掉 /assets/ /output/ /input/ 前缀）
                prefix_map = {"/assets/": config.ASSETS_DIR, "/output/": config.OUTPUT_DIR, "/input/": config.INPUT_DIR}
                base = ""
                for prefix, folder in prefix_map.items():
                    if url.startswith(prefix):
                        base = folder
                        rel = url[len(prefix):].lstrip("/")
                        break
                if not base:
                    continue
                local = safe_join(base, rel)
            except ValueError:
                continue
            if os.path.exists(local):
                with open(local, "rb") as f:
                    raw = f.read()
                ext = os.path.splitext(local)[1].lower()
                mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}.get(ext.lstrip("."), "image/png")
                input_images.append(f"data:{mime};base64,{b64.b64encode(raw).decode('ascii')}")
        else:
            input_images.append(url)

    # 加载 agent 自己的 skills 目录
    skills_dir = _agent_skills_dir(agent_id)
    if os.path.isdir(skills_dir):
        reg = get_skill_registry()
        reg._load_external()  # 重新扫描

    user_input = str(payload.get("user_input") or "")

    result = await run_agent(
        agent_config=a,
        user_input=user_input,
        input_images=input_images,
        provider=prov,
        docs_dir=_agent_docs_dir(agent_id),
    )
    return result
