"""数据模型"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


# —— 生图 ——
class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    provider_id: str = "openai"
    model: str = ""
    size: str = "1024x1024"
    reference_images: List[str] = Field(default_factory=list)


# —— 对话 ——
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    provider_id: str = "openai"
    model: str = ""
    system_prompt: str = ""
    reference_images: List[str] = Field(default_factory=list)
    conversation_id: str = ""


# —— 多模态对话 ——
class CanvasLLMRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    provider_id: str = "openai"
    model: str = ""
    system_prompt: str = ""
    images: List[str] = Field(default_factory=list)
    videos: List[str] = Field(default_factory=list)


# —— 视频生成 ——
class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    provider_id: str = "openai"
    model: str = ""
    duration: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    reference_images: List[str] = Field(default_factory=list)
    generate_audio: bool = True


# —— 画布 ——
class CanvasCreateRequest(BaseModel):
    title: str = "未命名画布"
    icon: str = "layers"
    kind: str = "default"


class CanvasMetaUpdate(BaseModel):
    title: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    owner: Optional[str] = None
    pinned: Optional[bool] = None
    kind: Optional[str] = None


# —— 工作流 ——
class WorkflowField(BaseModel):
    id: str
    node: str = ""
    input: str = ""
    name: str = ""
    type: str = "text"
    default: Any = None
    options: List[str] = Field(default_factory=list)


class WorkflowConfig(BaseModel):
    title: str = ""
    fields: List[WorkflowField] = Field(default_factory=list)


# —— Agent ——
class AgentSkill(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    enabled: bool = True
    parameters: Dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    id: str = ""
    name: str = "新智能体"
    system_prompt: str = ""
    skills: List[AgentSkill] = Field(default_factory=list)
    knowledge_bases: List[str] = Field(default_factory=list)
    model: str = "gpt-4o-mini"
    provider_id: str = "openai"
    max_steps: int = 10


class AgentExecutionRequest(BaseModel):
    agent_id: str = ""
    user_input: str = ""
    input_images: List[str] = Field(default_factory=list)
