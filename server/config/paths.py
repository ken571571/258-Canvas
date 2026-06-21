"""目录路径定义和初始化（迁移逻辑）"""

import os
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
WORKFLOW_DIR = os.path.join(BASE_DIR, "workflows")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
API_ENV_FILE = os.path.join(BASE_DIR, "API", ".env")
CANVAS_DIR = os.path.join(DATA_DIR, "canvases")  # 旧格式（兼容）
CANVASES_ROOT = os.path.join(BASE_DIR, "canvases")  # 新格式：每个画布一个独立目录
AGENTS_DIR = os.path.join(DATA_DIR, "agents")
KB_DIR = os.path.join(DATA_DIR, "knowledge_bases")
HISTORY_DIR = os.path.join(DATA_DIR, "chat_history")

# ——— 新的文件夹结构 ———
INPUT_DIR = os.path.join(BASE_DIR, "input")       # 用户素材输入
OUTPUT_DIR = os.path.join(BASE_DIR, "output")     # AI 生成结果输出
OUTPUT_IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
OUTPUT_VIDEOS_DIR = os.path.join(OUTPUT_DIR, "videos")
AGENTS_ROOT = os.path.join(BASE_DIR, "agents")    # 智能体根目录（可拷贝）


def ensure_directories():
    """确保必要目录存在。"""
    dirs = [STATIC_DIR, DATA_DIR, WORKFLOW_DIR, SKILLS_DIR, ASSETS_DIR,
            CANVAS_DIR, CANVASES_ROOT, KB_DIR, HISTORY_DIR,
            INPUT_DIR, OUTPUT_DIR, OUTPUT_IMAGES_DIR, OUTPUT_VIDEOS_DIR,
            AGENTS_ROOT, os.path.dirname(API_ENV_FILE)]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # 迁移：旧的 agents data 目录 → 新的 agents/ 根目录
    _OLD_AGENTS_DIR = os.path.join(DATA_DIR, "agents")
    if os.path.isdir(_OLD_AGENTS_DIR) and os.path.isdir(AGENTS_ROOT):
        for fn in os.listdir(_OLD_AGENTS_DIR):
            if fn.endswith(".json"):
                old_path = os.path.join(_OLD_AGENTS_DIR, fn)
                agent_id = fn[:-5]
                new_dir = os.path.join(AGENTS_ROOT, agent_id)
                if not os.path.exists(new_dir):
                    os.makedirs(new_dir, exist_ok=True)
                    shutil.copy2(old_path, os.path.join(new_dir, "agent.json"))
        # 不删除旧数据，保持兼容
