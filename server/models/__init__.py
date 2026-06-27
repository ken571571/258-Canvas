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


# —— 视频生成 ——
class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    provider_id: str = "openai"
    model: str = ""
    duration: int = Field(default=5, ge=1, le=30)  # v2.5.50：添加上下界约束
    aspect_ratio: str = Field(default="16:9", min_length=1)
    resolution: str = Field(default="720p", min_length=1)
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


# —— Agent ——
class AgentCreateRequest(BaseModel):
    name: str = "新智能体"


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    provider_id: Optional[str] = None
    skills: Optional[List[str]] = None
    knowledge_bases: Optional[List[str]] = None
    max_steps: Optional[int] = None


class AgentRunRequest(BaseModel):
    user_input: str = Field(default="", max_length=50000)  # v2.5.50：添加长度约束
    input_images: List[str] = Field(default_factory=list)
    prompt_vars: Optional[dict] = None


# —— 提示词库 ——
class PromptLibraryCreate(BaseModel):
    name: str = Field(default="新建提示词库", max_length=80)
    type: str = "prompt"


class PromptItemCreate(BaseModel):
    name: str = Field(default="", max_length=100)
    positive: str = Field(default="", max_length=20000)
    negative: str = ""
    scene: str = ""
    tags: List[str] = Field(default_factory=list)


class PromptItemUpdate(BaseModel):
    name: Optional[str] = None
    positive: Optional[str] = None
    negative: Optional[str] = None
    scene: Optional[str] = None
    tags: Optional[List[str]] = None


# —— 资产库 ——
class AssetItemCreate(BaseModel):
    name: str = Field(default="", max_length=100)
    url: str = ""
    type: str = "image"
    category_id: str = ""


class AssetCategoryCreate(BaseModel):
    name: str = Field(default="新分类", max_length=50)


