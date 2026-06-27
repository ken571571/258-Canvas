"""API 路由：Agent 智能体

新结构: agents/{agent_id}/
  ├── agent.json      ← 配置
  ├── skills/         ← 自定义技能 .py
  ├── knowledge/      ← 知识库文档
  └── docs/           ← 参考 .MD
"""

import os
import uuid
import asyncio
import time
import json
import re
import shutil
import base64 as b64
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from .. import config
from ..utils import KeyedLockManager, safe_join, read_upload_safely
from ..storage.json_store import store
from ..models import AgentCreateRequest, AgentUpdateRequest, AgentRunRequest
from ..logging_config import get_logger
from ..security.agent_crypto import (
    collect_machine_fingerprint, fingerprint_hash,
    encrypt_with_fingerprint, decrypt_with_fingerprint,
    encrypt_file as crypto_encrypt_file, decrypt_file_to_memory,
    is_encrypted, export_bundle, import_bundle, extract_slots_from_agent_file,
)
from ..exceptions import CryptoError

log = get_logger("agent_routes")
from ..agent.engine import run_agent
from ..agent.skills import get_skill_registry, reload_external_skills
from ..routes.providers_cfg import resolve_provider

router = APIRouter(prefix="/api", tags=["agent"])

_locks = KeyedLockManager()

# 进程级指纹缓存
_fingerprint_cache = None


def _get_fingerprint() -> str:
    """惰性采集机器指纹（进程级缓存）。"""
    global _fingerprint_cache
    if not _fingerprint_cache:
        _fingerprint_cache = collect_machine_fingerprint()
    return _fingerprint_cache


def _is_protected(agent: dict) -> bool:
    return bool(agent.get("protected", False))


def _strip_protected_fields(agent: dict) -> dict:
    """剥离加密字段，返回安全的副本。"""
    agent.pop("_enc", None)
    agent.pop("_trial", None)
    return agent


def _protect_agent_dict(agent: dict, fingerprint: str) -> dict:
    """加密 agent 敏感字段，放入 _enc（在原始 dict 上就地修改）。"""
    agent["protected"] = True
    agent["fingerprint_hash"] = fingerprint_hash(fingerprint)
    enc = {}
    if agent.get("system_prompt"):
        enc["system_prompt"] = encrypt_with_fingerprint(agent["system_prompt"], fingerprint)
    enc["skills"] = encrypt_with_fingerprint(json.dumps(agent.get("skills") or [], ensure_ascii=False), fingerprint)
    enc["knowledge_bases"] = encrypt_with_fingerprint(json.dumps(agent.get("knowledge_bases") or [], ensure_ascii=False), fingerprint)
    # 试用计数器（导出导入后前端传入）
    trial = agent.pop("_trial", None)
    if trial:
        enc["_trial"] = encrypt_with_fingerprint(json.dumps(trial, ensure_ascii=False), fingerprint)
    agent["_enc"] = enc
    # 清除明文
    agent["system_prompt"] = "[Encrypted]"
    agent["skills"] = []
    agent["knowledge_bases"] = []
    return agent


def _unprotect_agent_dict(agent: dict, fingerprint: str) -> dict:
    """解密 _enc 字段，恢复明文（在原始 dict 上就地修改，仅内存）。"""
    enc = agent.pop("_enc", None)
    if not enc:
        return agent
    try:
        if enc.get("system_prompt"):
            agent["system_prompt"] = decrypt_with_fingerprint(enc["system_prompt"], fingerprint)
        if enc.get("skills"):
            agent["skills"] = json.loads(decrypt_with_fingerprint(enc["skills"], fingerprint))
        if enc.get("knowledge_bases"):
            agent["knowledge_bases"] = json.loads(decrypt_with_fingerprint(enc["knowledge_bases"], fingerprint))
        if enc.get("_trial"):
            agent["_trial"] = json.loads(decrypt_with_fingerprint(enc["_trial"], fingerprint))
    except Exception as e:
        raise CryptoError(f"解密 Agent 失败（指纹不匹配或数据损坏）: {e}")
    agent["protected"] = True  # 标记仍在保护模式
    return agent


def _protect_agent_files(agent_dir: str, fingerprint: str) -> None:
    """加密 agent 目录下所有文件（skills/knowledge/docs + _kb_snapshot）。
    幂等：跳过已加密文件（AGP1 魔数），防止双重加密导致数据损坏。"""
    for sub in ["skills", "knowledge", "docs"]:
        sub_dir = os.path.join(agent_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        for fn in os.listdir(sub_dir):
            if fn.startswith("."):
                continue
            fpath = os.path.join(sub_dir, fn)
            if not os.path.isfile(fpath):
                continue
            try:
                # 跳过已加密文件（幂等保护）
                with open(fpath, "rb") as _f:
                    if _f.read(4) == b"AGP1":
                        continue
                crypto_encrypt_file(fpath, fingerprint)
            except Exception as e:
                log.warning(f"加密文件失败 {fpath}: {e}")
    # 加密知识库快照
    snapshot = os.path.join(agent_dir, "_kb_snapshot.json")
    if os.path.exists(snapshot):
        try:
            with open(snapshot, "rb") as _f:
                if _f.read(4) != b"AGP1":
                    crypto_encrypt_file(snapshot, fingerprint)
        except Exception as e:
            log.warning(f"加密快照失败: {e}")


def _verify_fingerprint_match(agent: dict) -> bool:
    """检查当前机器指纹是否与 agent 存储的匹配。"""
    stored = agent.get("fingerprint_hash", "")
    if not stored:
        return False
    try:
        return stored == fingerprint_hash(_get_fingerprint())
    except Exception:
        return False


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


def _load_agent(agent_id: str, fingerprint: str = None) -> dict | None:
    """加载 agent，可选解密 protected agent。"""
    path = _agent_config_path(agent_id)
    if not os.path.exists(path):
        # 兼容旧路径
        old_path = os.path.join(config.AGENTS_DIR, f"{re.sub(r'[^a-zA-Z0-9_-]', '_', agent_id)}.json")
        if os.path.exists(old_path):
            with open(old_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    with open(path, "r", encoding="utf-8") as f:
        agent = json.load(f)
    if _is_protected(agent):
        if fingerprint:
            agent = _unprotect_agent_dict(agent, fingerprint)
        else:
            _strip_protected_fields(agent)
    return agent


async def _write_agent_locked(agent_id: str, agent: dict) -> None:
    """原子写入 agent.json（调用方必须持有 _locks.get(agent_id) 锁）。

    不获取锁、不调 _sync_kb_snapshot。用于锁内读-改-写事务。
    """
    agent["updated_at"] = int(time.time() * 1000)
    d = _agent_dir(agent_id)
    os.makedirs(d, exist_ok=True)
    for sub in ["skills", "knowledge", "docs"]:
        os.makedirs(os.path.join(d, sub), exist_ok=True)

    write_data = agent
    if _is_protected(agent) and "_enc" not in agent:
        # 防御：如果字段已是占位符，说明 _enc 被误剥离，拒绝覆盖
        if agent.get("system_prompt") == "[Encrypted]" and not agent.get("skills"):
            raise RuntimeError("Refusing to encrypt placeholder data — _enc was accidentally stripped")
        _protect_agent_dict(write_data, _get_fingerprint())
    tmp = _agent_config_path(agent_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(write_data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())  # v2.5.50：确保持久化到磁盘后再原子替换
    os.replace(tmp, _agent_config_path(agent_id))


async def _sync_kb_snapshot(agent: dict):
    """将 agent 引用的知识库文档分片同步到 agent 目录下的 _kb_snapshot.json。

    快照使 agent 目录自包含 —— 拷贝到另一台机器后，知识库内容随 agent 一起走，
    不再依赖实例绑定的知识库 ID。
    """
    snapshot_path = os.path.join(_agent_dir(agent["id"]), "_kb_snapshot.json")
    kb_ids = agent.get("knowledge_bases") or []
    if not kb_ids:
        # 知识库引用已清空 → 删除旧快照
        if os.path.exists(snapshot_path):
            os.remove(snapshot_path)
        return
    try:
        from ..routes.knowledge import _load_index
        idx = _load_index()
        snapshot = {}
        for kbid in kb_ids:
            kb_data = idx.get(kbid)
            if isinstance(kb_data, dict):
                # 浅拷贝文档列表（chunks 不可变，浅拷贝足够）
                snapshot[kbid] = {
                    "name": kb_data.get("name", kbid),
                    "documents": kb_data.get("documents", []),
                }
        if snapshot:
            # v2.5.50：使用 store.write() 替代手动 open+os.replace（自动 fsync + 原子替换 + 锁）
            await store.write(snapshot_path, snapshot)
        elif os.path.exists(snapshot_path):
            os.remove(snapshot_path)
    except Exception as e:
        log.warning(f"同步知识库快照失败（不影响 agent 保存）: {e}")


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
                a["_dir"] = name
                if _is_protected(a):
                    _strip_protected_fields(a)
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
                        if _is_protected(a):
                            _strip_protected_fields(a)
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
async def create_agent(payload: AgentCreateRequest):
    name = (payload.name or "新智能体").strip()[:80]
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
    a.setdefault("id", agent_id)
    # 文件列表 — protected agent 标记加密状态
    files = {
        "skills": _list_agent_files(agent_id, "skills", (".py",)),
        "knowledge": _list_agent_files(agent_id, "knowledge", (".md", ".txt", ".pdf")),
        "docs": _list_agent_files(agent_id, "docs", (".md", ".txt")),
    }
    if _is_protected(a):
        # 解密到内存（仅本机可查看）
        try:
            a = _unprotect_agent_dict(a, _get_fingerprint())
        except CryptoError:
            pass  # 指纹不匹配，返回元数据
        a["locked"] = not _verify_fingerprint_match(a)
        for cat in files:
            for fi in files[cat]:
                fi["encrypted"] = True
    a["_files"] = files
    return {"agent": a}


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, payload: AgentUpdateRequest):
    # 锁外预读 + 快速验证（避免不必要地持有锁）
    a = _load_agent(agent_id, fingerprint=_get_fingerprint())
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    old_dir = _agent_dir(agent_id)
    old_name = a.get("name", "")
    is_protected = _is_protected(a)

    update_fields = payload.model_dump(exclude_unset=True)
    if is_protected:
        allowed = {"name", "model", "provider_id", "max_steps", "_trial"}
        unsafe = [k for k in update_fields if k not in allowed]
        if unsafe:
            raise HTTPException(status_code=400, detail=f"Protected agent 不允许修改: {', '.join(unsafe)}")

    # 锁内：原子化读-改-写事务
    lock = await _locks.get(agent_id)
    async with lock:
        a = _load_agent(agent_id, fingerprint=_get_fingerprint())
        if not a:
            raise HTTPException(status_code=404, detail="Agent 不存在")

        # 双重检查：agent 可能在锁外验证后变为 protected
        if _is_protected(a):
            allowed = {"name", "model", "provider_id", "max_steps", "_trial"}
            unsafe = [k for k in update_fields if k not in allowed]
            if unsafe:
                raise HTTPException(status_code=400, detail=f"Protected agent 不允许修改: {', '.join(unsafe)}")
            if "_trial" in update_fields:
                a["_trial"] = update_fields.pop("_trial")
        else:
            for field, value in update_fields.items():
                a[field] = value

        for field, value in update_fields.items():
            if field in ("system_prompt", "skills", "knowledge_bases") and _is_protected(a):
                continue
            a[field] = value

        await _write_agent_locked(agent_id, a)
        # 快照同步移入锁内（v2.5.40：防止并发 update_agent 导致快照与 agent.json 不一致）
        if not _is_protected(a):
            await _sync_kb_snapshot(a)

    # 锁外：目录重命名

    new_name = a.get("name", "")
    if new_name != old_name and os.path.isdir(old_dir):
        new_dir = os.path.join(config.AGENTS_ROOT, f"{_safe_name(new_name)}_{agent_id[:8]}")
        if os.path.normpath(new_dir) != os.path.normpath(old_dir) and not os.path.exists(new_dir):
            try:
                os.rename(old_dir, new_dir)
            except Exception:
                log.warning(f"Agent 目录重命名失败: {old_dir} → {new_dir}")

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

    raw = await read_upload_safely(file, 50 * 1024 * 1024)  # v2.5.40：流式读取防 OOM
    filename = file.filename or "未命名"
    # 安全处理文件名
    safe_name = re.sub(r"[\\/:*?\"<>|]", "_", filename)
    try:
        path = safe_join(target_dir, safe_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")
    # protected agent: 加密后存储（_fingerprint_key 与 agent_crypto 一致）
    if _is_protected(a):
        import hashlib
        fkey = hashlib.sha256(("agent_fingerprint:" + _get_fingerprint()).encode()).digest()
        from ..security.agent_crypto import encrypt_bytes
        raw = encrypt_bytes(raw, fkey)

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
    """读取 agent 文件的原始内容。protected agent 拒绝返回明文。"""
    if sub not in ("skills", "knowledge", "docs"):
        raise HTTPException(status_code=400, detail="sub 必须是 skills / knowledge / docs")
    try:
        base_dir = safe_join(_agent_dir(agent_id), sub)
        path = safe_join(base_dir, filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径不合法")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")

    # 检查是否为 protected agent
    a = _load_agent(agent_id)
    if a and _is_protected(a):
        raise HTTPException(status_code=403, detail="Protected agent — 文件内容不可查看")

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

    # 构建设计器 Agent 的 system prompt（防御 null 值导致的 TypeError）
    skills_raw = agent_cfg.get("skills") or []
    kb_raw = agent_cfg.get("knowledge_bases") or []
    skills_info = ", ".join([s for s in skills_raw]) or "无"
    kb_info = ", ".join([k for k in kb_raw]) or "无"
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
        agent_dir="",  # 设计器 Agent 无实体目录
    )
    return result


# ——— 图片 URL 解析 ———

# 本地路径前缀 → 对应磁盘目录
_IMAGE_ROOT_MAP = {
    "/canvases/": config.CANVASES_ROOT,
    "/assets/":   config.ASSETS_DIR,
    "/output/":   config.OUTPUT_DIR,
    "/input/":    config.INPUT_DIR,
}

_MIME_MAP = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp"}


def _file_to_data_url(local_path: str) -> str:
    """读取本地文件 → data:{mime};base64,...。文件不存在返回空字符串。"""
    if not os.path.exists(local_path):
        return ""
    with open(local_path, "rb") as f:
        raw = f.read()
    ext = os.path.splitext(local_path)[1].lower().lstrip(".")
    mime = _MIME_MAP.get(ext, "image/png")
    return f"data:{mime};base64,{b64.b64encode(raw).decode('ascii')}"


def _resolve_image(url: str) -> str | None:
    """将图片 URL/路径 解析为可直接发给 LLM 的格式。

    规则：
    1. data: 协议 → 原样返回
    2. 本地绝对路径 (/canvases/, /assets/, /output/, /input/) → 读文件转 base64
    3. 本机 HTTP URL (127.0.0.1 / localhost) → 提取路径，读文件转 base64
    4. 外部 http(s) URL → 原样返回（由 AI 平台的下载能力处理）
    5. tag:: 前缀（画布管线字段映射）→ 剥离后按上述规则解析
    6. 其他 → 返回 None，丢弃
    """
    url = str(url or "").strip()
    if not url:
        return None

    # 剥离画布管线的 tag:: 前缀（字段映射用，Agent 不需要）
    if "::" in url and not url.startswith(("http://", "https://", "data:")):
        _tag, sep, rest = url.partition("::")
        if rest:
            url = rest

    # data: 已编码，直接通过
    if url.startswith("data:"):
        return url

    # 外部 HTTP(S) URL → 原样保留
    if url.startswith(("https://", "http://")):
        if _is_local_origin(url):
            return _local_origin_to_data_url(url)
        return url

    # 本地绝对路径 → 读文件转 base64
    if url.startswith("/"):
        for prefix, root in _IMAGE_ROOT_MAP.items():
            if url.startswith(prefix):
                try:
                    rel = url[len(prefix):].lstrip("/")
                    local = safe_join(root, rel)
                    data_url = _file_to_data_url(local)
                    if data_url:
                        return data_url
                except ValueError:
                    pass
                return None  # 匹配了前缀但文件不存在/不安全 → 丢弃

    # 无法识别的格式 → 丢弃
    return None


def _is_local_origin(url: str) -> bool:
    """检查 URL 是否指向本机服务。"""
    port = str(config.APP_PORT)
    return (
        url.startswith(f"http://127.0.0.1:{port}/")
        or url.startswith(f"http://localhost:{port}/")
    )


def _local_origin_to_data_url(url: str) -> str | None:
    """将本机 HTTP URL 转换为 base64 data URL。"""
    port = str(config.APP_PORT)
    path = None
    if url.startswith(f"http://127.0.0.1:{port}/"):
        path = url[len(f"http://127.0.0.1:{port}"):]
    elif url.startswith(f"http://localhost:{port}/"):
        path = url[len(f"http://localhost:{port}"):]
    if not path or not path.startswith("/"):
        return None
    return _resolve_image(path)


# ===== Agent 执行 =====

@router.post("/agents/{agent_id}/run")
async def run_agent_endpoint(agent_id: str, payload: AgentRunRequest):
    fp = _get_fingerprint()
    a = _load_agent(agent_id, fingerprint=fp)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    # v2.5.52：试用计数器在锁内检查+递增，防止并发突破限制
    trial = a.get("_trial")
    trial_ok = True
    if trial and isinstance(trial, dict) and trial.get("type") == "trial":
        lock = await _locks.get(agent_id)
        async with lock:
            a2 = _load_agent(agent_id, fingerprint=fp)
            if a2 and a2.get("_trial"):
                used = a2["_trial"].get("used", 0)
                limit = a2["_trial"].get("limit", 5)
                if used >= limit:
                    return {"success": False, "error": f"Agent 试用次数已用尽（{used}/{limit}）"}
                a2["_trial"]["used"] = used + 1
                await _write_agent_locked(agent_id, a2)
                trial_ok = False  # 已递增，下方不再重复递增

    pid = a.get("provider_id", "openai")
    prov = resolve_provider(pid)
    if not prov:
        return {"success": False, "error": f"未找到 API 平台: {pid}"}

    input_images = []
    for url in (payload.input_images or []):
        data_url = _resolve_image(url)
        if data_url:
            input_images.append(data_url)

    # v2.5.52：仅加载当前 Agent 的技能，避免全局 _load_external 扫描所有 Agent 导致技能互相覆盖
    skills_dir = _agent_skills_dir(agent_id)
    if os.path.isdir(skills_dir):
        reg = get_skill_registry()
        reg._scan_skills_dir(skills_dir, fingerprint=fp)

    user_input = str(payload.user_input or "")

    try:
        result = await asyncio.wait_for(
            run_agent(
                agent_config=a,
                user_input=user_input,
                input_images=input_images,
                provider=prov,
                docs_dir=_agent_docs_dir(agent_id),
                agent_dir=_agent_dir(agent_id),
                fingerprint=fp,
            ),
            timeout=600,  # v2.5.52：全局超时 600s（max_steps×单次超时的两倍）
        )
    except asyncio.TimeoutError:
        return {"success": False, "error": "Agent 执行超时（600s）", "steps": [], "final_output": ""}

    # v2.5.52：已在前置锁内递增；失败时退还试用次数
    if trial and not trial_ok:
        if not result.get("success"):
            lock = await _locks.get(agent_id)
            async with lock:
                a3 = _load_agent(agent_id, fingerprint=fp)
                if a3 and a3.get("_trial"):
                    a3["_trial"]["used"] = max(0, a3["_trial"].get("used", 0) - 1)
                    await _write_agent_locked(agent_id, a3)

    return result


# ===== Agent 保护 / 导出 / 导入 =====

@router.post("/agents/{agent_id}/protect")
async def protect_agent(agent_id: str):
    """将明文 Agent 转为受保护模式（不可逆）。"""
    # 锁外预读 + 快速验证
    a = _load_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if _is_protected(a):
        raise HTTPException(status_code=400, detail="Agent 已是受保护模式")

    fp = _get_fingerprint()
    if not fp:
        raise HTTPException(status_code=500, detail="无法采集机器指纹")

    agent_dir = _agent_dir(agent_id)

    # 锁内：原子化保护操作（文件加密 + agent.json 加密写入在同一锁内完成）
    lock = await _locks.get(agent_id)
    async with lock:
        a = _load_agent(agent_id)
        if not a:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if _is_protected(a):
            raise HTTPException(status_code=400, detail="Agent 已是受保护模式")

        # 加密 skills/knowledge/docs 文件 + 知识库快照
        _protect_agent_files(agent_dir, fp)

        # 加密 agent.json 敏感字段并原子写入
        _protect_agent_dict(a, fp)
        await _write_agent_locked(agent_id, a)

    return {"ok": True, "agent": {"id": agent_id, "protected": True}}


@router.post("/agents/{agent_id}/export")
async def export_agent(agent_id: str, payload: dict):
    """导出受保护的 Agent 为 .agent 文件。

    payload: {
        permanent_password: str (≥8字符),
        trial_password: str (可选，≥4字符),
        trial_limit: int (默认 5)
    }
    """
    a = _load_agent(agent_id, fingerprint=_get_fingerprint())
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not _is_protected(a):
        raise HTTPException(status_code=400, detail="仅受保护 Agent 可导出")
    if a.get("imported"):
        raise HTTPException(status_code=403, detail="导入的 Agent 不可再次导出（仅原始创作者可导出）")

    perm_pw = str(payload.get("permanent_password", "")).strip()
    if len(perm_pw) < 8:
        raise HTTPException(status_code=400, detail="永久密码至少 8 个字符")

    trial_pw = str(payload.get("trial_password", "")).strip()
    if trial_pw and len(trial_pw) < 8:
        raise HTTPException(status_code=400, detail="试用密码至少 8 个字符")  # v2.5.50
    trial_limit = int(payload.get("trial_limit", 5))
    expires_hours = int(payload.get("expires_hours", 24))  # 0=永不过期

    # 收集所有文件（解密到内存）
    agent_dir = _agent_dir(agent_id)
    files = {}
    for sub in ["skills", "knowledge", "docs"]:
        sub_dir = os.path.join(agent_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        for fn in os.listdir(sub_dir):
            if fn.startswith("."):
                continue
            fpath = os.path.join(sub_dir, fn)
            if not os.path.isfile(fpath):
                continue
            rel = f"{sub}/{fn}"
            try:
                plain = decrypt_file_to_memory(fpath, _get_fingerprint())
                files[rel] = plain.decode("utf-8", errors="replace")
            except Exception as e:
                log.warning(f"解密文件失败 {fpath}: {e}")

    # 知识库快照
    kb_snapshot = {}
    snapshot_path = os.path.join(agent_dir, "_kb_snapshot.json")
    if os.path.exists(snapshot_path):
        try:
            kb_raw = decrypt_file_to_memory(snapshot_path, _get_fingerprint())
            kb_snapshot = json.loads(kb_raw.decode("utf-8"))
        except Exception as e:
            log.warning(f"解密快照失败: {e}")

    # 清除内部字段
    a.pop("fingerprint_hash", None)
    a.pop("_enc", None)
    a.pop("_dir", None)
    a.pop("_files", None)

    # 构建导出包
    bundle_bytes = export_bundle(
        agent_config=a,
        files=files,
        kb_snapshot=kb_snapshot,
        permanent_password=perm_pw,
        trial_password=trial_pw,
        trial_limit=trial_limit,
        expires_hours=expires_hours,
    )

    from fastapi.responses import Response
    import urllib.parse
    safe_fn = _safe_name(a.get("name", "agent"))
    filename = f"{safe_fn}_{a['id'][:8]}.agent"
    # RFC 5987: ASCII fallback + UTF-8 encoded filename（HTTP 头仅支持 ASCII）
    ascii_fn = f"agent_{a['id'][:8]}.agent"
    encoded_fn = urllib.parse.quote(filename)
    return Response(
        content=bundle_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{ascii_fn}"; filename*=UTF-8\'\'{encoded_fn}'}
    )


@router.post("/agents/import")
async def import_agent(file: UploadFile = File(...), password: str = Form("")):
    """导入 .agent 文件。密码自动匹配永久/试用slot。"""
    password = str(password or "").strip()
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")

    if file.size and file.size > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（最大 100MB）")
    raw = await read_upload_safely(file, 100 * 1024 * 1024)  # v2.5.40：流式读取防 OOM

    try:
        bundle = import_bundle(raw, password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"导入失败: {e}")

    agent_config = bundle.get("agent_config", {})
    files = bundle.get("files", {})
    kb_snapshot = bundle.get("kb_snapshot", {})
    slot_type = bundle.get("slot_type", "permanent")
    trial_limit = bundle.get("trial_limit")

    # 生成新 ID 避免冲突，标记为导入（禁止二次导出）
    aid = uuid.uuid4().hex[:16]
    agent_config["imported"] = True
    slug = _safe_name(agent_config.get("name", "imported"))
    dir_name = f"{slug}_{aid[:8]}"
    d = os.path.join(config.AGENTS_ROOT, dir_name)
    os.makedirs(d, exist_ok=True)
    success = False

    try:
        for sub in ["skills", "knowledge", "docs"]:
            os.makedirs(os.path.join(d, sub), exist_ok=True)

        fp = _get_fingerprint()

        # 写入文件（加密）
        import hashlib as _hashlib
        fkey = _hashlib.sha256(("agent_fingerprint:" + fp).encode()).digest()
        from ..security.agent_crypto import encrypt_bytes
        for rel_path, content in files.items():
            target = safe_join(d, rel_path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fout:
                fout.write(encrypt_bytes(content.encode("utf-8", errors="replace"), fkey))

        # 写入知识库快照（加密）
        if kb_snapshot:
            snap_data = json.dumps(kb_snapshot, ensure_ascii=False).encode("utf-8")
            with open(os.path.join(d, "_kb_snapshot.json"), "wb") as fout:
                fout.write(encrypt_bytes(snap_data, fkey))

        # 构建 agent 配置
        agent_config["id"] = aid
        agent_config["protected"] = True
        agent_config["fingerprint_hash"] = fingerprint_hash(fp)
        agent_config["_enc"] = {
            "system_prompt": encrypt_with_fingerprint(agent_config.get("system_prompt", ""), fp),
            "skills": encrypt_with_fingerprint(json.dumps(agent_config.get("skills") or [], ensure_ascii=False), fp),
            "knowledge_bases": encrypt_with_fingerprint(json.dumps(agent_config.get("knowledge_bases") or [], ensure_ascii=False), fp),
        }
        # 试用信息存入 _trial
        if slot_type == "trial" and trial_limit:
            agent_config["_trial"] = {"type": "trial", "limit": trial_limit, "used": 0}
            agent_config["_enc"]["_trial"] = encrypt_with_fingerprint(json.dumps(agent_config["_trial"], ensure_ascii=False), fp)

        # 清除明文
        agent_config["system_prompt"] = "[Encrypted]"

        now = int(time.time() * 1000)
        agent_config["created_at"] = now
        agent_config["updated_at"] = now

        config_path = os.path.join(d, "agent.json")
        await store.write_with_timestamp(config_path, agent_config)

        success = True
        return {"ok": True, "agent": {"id": aid, "name": agent_config.get("name"), "protected": True}, "dir": dir_name,
                "slot_type": slot_type, "trial_limit": trial_limit}
    except Exception:
        raise  # 保留原始异常信息
    finally:
        # 导入失败 → 清理已创建的目录，不留残留（v2.5.40：从 except 移入 finally）
        if not success and os.path.isdir(d):
            try:
                shutil.rmtree(d)
                log.info(f"Agent 导入失败，已清理目录: {dir_name}")
            except Exception as cleanup_err:
                log.warning(f"Agent 导入回滚：清理目录失败 {d}: {cleanup_err}")


@router.post("/agents/{agent_id}/verify-fingerprint")
def verify_agent_fingerprint(agent_id: str):
    """验证当前机器是否可以解密此 Agent。"""
    a = _load_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if not _is_protected(a):
        return {"matched": False, "reason": "Agent 不是受保护模式"}

    matched = _verify_fingerprint_match(a)
    if matched:
        return {"matched": True}
    return {"matched": False, "reason": "机器指纹不匹配 — Agent 绑定到其他机器"}
