"""技能注册中心"""

import os
import importlib.util
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

from .. import config
from ..logging_config import get_logger

log = get_logger("skills")


@dataclass
class Skill:
    id: str = ""
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    handler: Optional[Callable] = None


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._register_builtin()
        self._load_external()

    def register(self, skill: Skill):
        self._skills[skill.id] = skill

    def list_all(self) -> List[Skill]:
        return list(self._skills.values())

    def to_openai_tools(self, enabled_ids: List[str] = None) -> List[dict]:
        tools = []
        for s in self._skills.values():
            if enabled_ids is None or s.id in enabled_ids:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": s.id,
                        "description": s.description,
                        "parameters": s.parameters,
                    },
                })
        return tools

    async def execute(self, skill_id: str, arguments: dict, agent_config: dict = None) -> dict:
        skill = self._skills.get(skill_id)
        if not skill or not skill.handler:
            return {"error": f"未知技能: {skill_id}"}
        try:
            # 仅当 handler 接受 agent_config 参数时才传递（向后兼容自定义技能）
            import inspect
            try:
                params = inspect.signature(skill.handler).parameters
            except (ValueError, TypeError):
                params = {}
            if 'agent_config' in params:
                result = await skill.handler(arguments, agent_config=agent_config)
            else:
                result = await skill.handler(arguments)
            if isinstance(result, dict):
                return result
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    async def _skill_generate_image(self, arguments: dict, agent_config: dict = None) -> dict:
        from ..routes.providers_cfg import resolve_provider

        prompt = str(arguments.get("prompt") or "").strip()
        if not prompt:
            return {"error": "prompt 不能为空"}

        provider_id = str(arguments.get("provider_id") or "openai")
        model = str(arguments.get("model") or "")
        size = str(arguments.get("size") or "1024x1024")
        reference_images = arguments.get("reference_images") or []

        prov = resolve_provider(provider_id)
        if not prov:
            return {"error": f"未找到 API 平台: {provider_id}"}

        result = await prov.generate_image(
            prompt=prompt,
            size=size,
            model=model,
            reference_images=reference_images,
        )
        return {"url": result.url, "size": size, "model": model or ""}

    async def _skill_search_knowledge(self, arguments: dict, agent_config: dict = None) -> dict:
        from ..routes.knowledge import _load_index, search_kb_chunks

        query = str(arguments.get("query") or "").strip()
        top_k = int(arguments.get("top_k") or 3)
        kb_ids = arguments.get("kb_ids") or list(_load_index().keys())
        if not query:
            return {"results": []}
        return {"results": search_kb_chunks(kb_ids, query, top_k)}

    async def _skill_web_search(self, arguments: dict, agent_config: dict = None) -> dict:
        """联网搜索：使用 DuckDuckGo 或 Google 搜索。"""
        query = str(arguments.get("query") or "").strip()
        num = int(arguments.get("num_results") or 5)
        if not query:
            return {"error": "query 不能为空"}

        try:
            import httpx
            # 使用 DuckDuckGo Instant Answer API（免费，无需 Key）
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as cli:
                resp = await cli.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                    headers={"User-Agent": "Canvas571/1.0"}
                )
                data = resp.json()
                results = []
                # Abstract
                if data.get("AbstractText"):
                    results.append({"title": data.get("AbstractSource", "Wikipedia"), "snippet": data["AbstractText"], "url": data.get("AbstractURL", "")})
                # Related topics
                for topic in (data.get("RelatedTopics") or [])[:num]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append({"title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "), "snippet": topic["Text"], "url": topic.get("FirstURL", "")})
                if not results:
                    return {"results": [], "message": f"未找到关于 '{query}' 的搜索结果"}
                return {"results": results[:num], "query": query}
        except ImportError:
            return {"error": "httpx 未安装"}
        except Exception as e:
            return {"error": f"搜索失败: {e}", "results": []}

    async def _skill_chat(self, arguments: dict, agent_config: dict = None) -> dict:
        from ..routes.providers_cfg import resolve_provider

        message = str(arguments.get("message") or "").strip()
        if not message:
            return {"error": "message 不能为空"}

        # 默认用 Agent 配置的平台和模型
        agent_cfg = agent_config or {}
        provider_id = str(arguments.get("provider_id") or agent_cfg.get("provider_id") or "openai")
        model = str(arguments.get("model") or agent_cfg.get("model") or "gpt-4o-mini")
        system_prompt = str(arguments.get("system_prompt") or "")

        prov = resolve_provider(provider_id)
        if not prov:
            return {"error": f"未找到 API 平台: {provider_id}"}

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        result = await prov.chat(messages=messages, model=model)
        return {"reply": result.content, "model": result.model, "usage": result.usage}

    # ——— 内置技能 ———
    def _register_builtin(self):
        # 文生图
        self.register(Skill(
            id="generate_image",
            name="文生图",
            description="根据文本提示词生成一张图片。调用前务必确认画面构图、风格、尺寸。",
            handler=self._skill_generate_image,
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "图片生成提示词，需详细描述画面内容"},
                    "size": {"type": "string", "enum": ["1024x1024", "1536x1024", "1024x1536"], "description": "图片尺寸"},
                    "model": {"type": "string", "description": "可选模型名"},
                    "provider_id": {"type": "string", "description": "可选 API 平台 ID，默认 openai"},
                    "reference_images": {"type": "array", "items": {"type": "string"}, "description": "可选参考图片 URL"},
                },
                "required": ["prompt"],
            },
        ))
        # 知识库搜索
        self.register(Skill(
            id="search_knowledge",
            name="知识库搜索",
            description="在知识库中搜索相关内容。明确想查什么信息时使用。",
            handler=self._skill_search_knowledge,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "top_k": {"type": "integer", "description": "返回结果数，默认 3"},
                    "kb_ids": {"type": "array", "items": {"type": "string"}, "description": "可选知识库 ID 列表"},
                },
                "required": ["query"],
            },
        ))
        # 联网搜索
        self.register(Skill(
            id="web_search",
            name="联网搜索",
            description="在互联网上搜索最新信息。需要查实时数据、新闻、文档时使用。",
            handler=self._skill_web_search,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或问题"},
                    "num_results": {"type": "integer", "description": "返回结果数，默认 5"},
                },
                "required": ["query"],
            },
        ))
        # LLM 对话
        self.register(Skill(
            id="chat",
            name="LLM 对话",
            description="调用大语言模型进行推理、写作、分析等文本任务。不可用于生成图片。",
            handler=self._skill_chat,
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "发给 LLM 的消息"},
                    "system_prompt": {"type": "string", "description": "可选系统提示词"},
                    "model": {"type": "string", "description": "可选模型名"},
                    "provider_id": {"type": "string", "description": "可选 API 平台 ID，默认 openai"},
                },
                "required": ["message"],
            },
        ))

    # ——— 外部技能热加载 ———
    def _load_external(self, fingerprint: str = ""):
        # 1. 旧的 skills/ 全局目录（永不明文加密）
        if os.path.isdir(config.SKILLS_DIR):
            self._scan_skills_dir(config.SKILLS_DIR)

        # 2. 每个 Agent 自己的 agents/{id}/skills/ 目录
        if os.path.isdir(config.AGENTS_ROOT):
            for name in sorted(os.listdir(config.AGENTS_ROOT)):
                if name.startswith("_") or name.startswith("."):
                    continue
                agent_skills = os.path.join(config.AGENTS_ROOT, name, "skills")
                if os.path.isdir(agent_skills):
                    self._scan_skills_dir(agent_skills, prefix=f"{name}/", fingerprint=fingerprint)

    def _scan_skills_dir(self, directory: str, prefix: str = "", fingerprint: str = ""):
        # 安全校验：目录必须在授权白名单内
        from .. import config as _cfg
        dir_real = os.path.realpath(directory)
        authorized = any(
            dir_real == os.path.realpath(d) or
            dir_real.startswith(os.path.realpath(d) + os.sep)
            for d in _cfg.SKILL_AUTHORIZED_DIRS
        )
        if not authorized:
            log.warning(f"技能目录未授权，跳过: {directory}")
            return

        import tempfile
        for fn in sorted(os.listdir(directory)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            path = os.path.join(directory, fn)
            # 防止符号链接逃逸
            if not os.path.realpath(path).startswith(dir_real + os.sep):
                log.warning(f"技能文件路径异常（符号链接攻击？），跳过: {path}")
                continue

            import_path = path  # 默认直接加载
            tmp_file = None

            # 检测加密文件：AGP1 魔数
            try:
                with open(path, "rb") as f:
                    header = f.read(4)
                if header == b"AGP1":
                    if not fingerprint:
                        log.warning(f"加密技能缺少指纹，跳过: {fn}")
                        continue
                    from ..security.agent_crypto import decrypt_bytes
                    import hashlib as _hashlib
                    fkey = _hashlib.sha256(("agent_fingerprint:" + fingerprint).encode()).digest()
                    with open(path, "rb") as f:
                        raw = f.read()
                    plain = decrypt_bytes(raw, fkey)
                    tmp_file = tempfile.NamedTemporaryFile(
                        mode="wb", suffix=".py", prefix="dec_skill_", delete=False
                    )
                    tmp_file.write(plain)
                    tmp_file.close()
                    # v2.5.51：限制临时文件权限，仅当前用户可读写
                    os.chmod(tmp_file.name, 0o600)
                    import_path = tmp_file.name
            except Exception as e:
                log.warning(f"检测加密状态失败 {fn}: {e}")
                continue

            try:
                mod_name = f"skill_{prefix}{fn[:-3]}".replace("/", "_").replace("\\", "_")
                spec = importlib.util.spec_from_file_location(mod_name, import_path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                sid = getattr(mod, "SKILL_ID", "").strip()
                if not sid:
                    continue
                handler = getattr(mod, "execute", None)
                if not callable(handler):
                    continue
                self.register(Skill(
                    id=sid,
                    name=getattr(mod, "SKILL_NAME", sid),
                    description=getattr(mod, "SKILL_DESCRIPTION", ""),
                    parameters=getattr(mod, "SKILL_PARAMETERS", {}),
                    handler=handler,
                ))
                log.info(f"已加载: {sid} ({fn})")
            except Exception as e:
                log.warning(f"加载 {fn} 失败: {e}")
            finally:
                # 清理临时解密文件
                if tmp_file:
                    try:
                        os.unlink(import_path)
                    except Exception:
                        pass


_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def reload_external_skills():
    global _registry
    _registry = SkillRegistry()
