"""API 路由：在线更新系统

支持从 GitHub 检测新版本、下载更新、备份与回滚。
"""

import os
import re
import time
import json
import shutil
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException
import httpx

from .. import config

router = APIRouter(prefix="/api", tags=["update"])

# 更新源 URL —— 替换为你自己的仓库地址
# 格式: "https://raw.githubusercontent.com/<user>/<repo>/main"
GITHUB_REPO = os.getenv("UPDATE_REPO_URL", "")
GITHUB_REPO = GITHUB_REPO.rstrip("/") if GITHUB_REPO else ""
BACKUP_DIR = os.path.join(config.DATA_DIR, "update_backups")


def _version_tuple(v: str) -> list:
    return [int(x) for x in re.findall(r"\d+", str(v or ""))]


def _version_gt(a: str, b: str) -> bool:
    ta, tb = _version_tuple(a), _version_tuple(b)
    n = max(len(ta), len(tb))
    ta += [0] * (n - len(ta))
    tb += [0] * (n - len(tb))
    return ta > tb


@router.get("/app-info")
def app_info():
    """返回当前版本和仓库信息。"""
    return {
        "version": config.APP_VERSION,
        "repo_url": GITHUB_REPO,
        "update_sources": ["github"],
    }


@router.get("/check-update")
async def check_update():
    """检测更新源是否有新版本。"""
    if not GITHUB_REPO:
        return {"current": config.APP_VERSION, "update_available": False, "error": "未配置更新源（UPDATE_REPO_URL）"}
    version_url = f"{GITHUB_REPO}/VERSION"
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            resp = await cli.get(
                version_url,
                headers={"User-Agent": "Canvas571-Updater"},
                params={"t": int(time.time())},
            )
        if resp.status_code != 200:
            return {"current": config.APP_VERSION, "update_available": False, "error": f"HTTP {resp.status_code}"}

        remote_ver = resp.text.strip().splitlines()[0].strip()
        # 防御：检查是否像版本号
        if not remote_ver or "<" in remote_ver or "{" in remote_ver:
            return {"current": config.APP_VERSION, "update_available": False, "error": "版本文件格式异常"}

        latest = {"version": remote_ver, "source": "github"}
        update_available = _version_gt(remote_ver, config.APP_VERSION)
        return {
            "current": config.APP_VERSION,
            "latest": latest,
            "update_available": update_available,
        }
    except Exception as e:
        return {"current": config.APP_VERSION, "update_available": False, "error": str(e)}


@router.post("/update")
async def do_update():
    """从更新源下载最新文件并执行更新。"""
    if not GITHUB_REPO:
        raise HTTPException(status_code=400, detail="未配置更新源（UPDATE_REPO_URL）")
    # 1. 确认有更新
    check = await check_update()
    if not check.get("update_available"):
        raise HTTPException(status_code=400, detail="当前已是最新版本")

    # 2. 创建备份
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = os.path.join(BACKUP_DIR, ts)
    os.makedirs(backup_root, exist_ok=True)

    updatable_files = []  # (remote_url, local_rel_path)

    try:
        # 备份 main.py
        main_path = os.path.join(config.BASE_DIR, "main.py")
        if os.path.exists(main_path):
            shutil.copy2(main_path, os.path.join(backup_root, "main.py"))
            updatable_files.append((f"{GITHUB_REPO}/main.py", "main.py"))

        # 备份 VERSION
        ver_path = os.path.join(config.BASE_DIR, "VERSION")
        if os.path.exists(ver_path):
            shutil.copy2(ver_path, os.path.join(backup_root, "VERSION"))
        updatable_files.append((f"{GITHUB_REPO}/VERSION", "VERSION"))

        # 备份 static/ 目录下的文件
        static_backup = os.path.join(backup_root, "static")
        static_dir = config.STATIC_DIR
        if os.path.isdir(static_dir):
            shutil.copytree(static_dir, static_backup, dirs_exist_ok=True)

        # 备份 workflows/ 中的内置工作流
        workflows_backup = os.path.join(backup_root, "workflows_builtin")
        os.makedirs(workflows_backup, exist_ok=True)
        wf_dir = config.WORKFLOW_DIR
        if os.path.isdir(wf_dir):
            for fn in os.listdir(wf_dir):
                if fn.endswith(".json") and not fn.startswith("."):
                    src = os.path.join(wf_dir, fn)
                    if os.path.isfile(src):
                        shutil.copy2(src, os.path.join(workflows_backup, fn))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"备份失败: {e}")

    # 3. 下载并替换文件
    updated = []
    failed = []
    async with httpx.AsyncClient(timeout=60) as cli:
        for remote_path, local_rel in updatable_files:
            url = f"{remote_path}?t={int(time.time())}"
            try:
                resp = await cli.get(url, headers={"User-Agent": "Canvas571-Updater"})
                if resp.status_code == 200:
                    local_path = os.path.join(config.BASE_DIR, local_rel.replace("/", os.sep))
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(resp.content)
                    updated.append(local_rel)
                else:
                    failed.append(f"{local_rel} (HTTP {resp.status_code})")
            except Exception as e:
                failed.append(f"{local_rel} ({e})")

        # 尝试下载 static/ 文件（如果有目录列表）
        # 简单方案：遍历备份的 static 文件，逐个尝试更新
        if os.path.isdir(static_backup):
            for root, dirs, files in os.walk(static_backup):
                for fn in files:
                    rel = os.path.relpath(os.path.join(root, fn), static_backup).replace("\\", "/")
                    url = f"{GITHUB_REPO}/static/{rel}?t={int(time.time())}"
                    try:
                        resp = await cli.get(url, headers={"User-Agent": "Canvas571-Updater"})
                        if resp.status_code == 200:
                            local_path = os.path.join(static_dir, rel.replace("/", os.sep))
                            os.makedirs(os.path.dirname(local_path), exist_ok=True)
                            with open(local_path, "wb") as f:
                                f.write(resp.content)
                            updated.append(f"static/{rel}")
                    except Exception:
                        pass

    # 4. 重新加载版本
    try:
        ver_path = os.path.join(config.BASE_DIR, "VERSION")
        if os.path.exists(ver_path):
            with open(ver_path, "r", encoding="utf-8") as f:
                new_ver = f.read().strip().splitlines()[0].strip()
    except Exception:
        new_ver = check.get("latest", {}).get("version", "")

    return {
        "ok": True,
        "updated": updated,
        "failed": failed,
        "backup": ts,
        "new_version": new_ver,
        "message": f"更新完成，请重启服务以生效。备份位于: data/update_backups/{ts}",
    }


@router.get("/update/backups")
def list_backups():
    """列出所有备份。"""
    if not os.path.isdir(BACKUP_DIR):
        return {"backups": []}
    items = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        path = os.path.join(BACKUP_DIR, name)
        if os.path.isdir(path):
            items.append({
                "id": name,
                "created_at": name,
                "size": sum(
                    os.path.getsize(os.path.join(root, f))
                    for root, _, files in os.walk(path) for f in files
                ),
            })
    return {"backups": items[:20]}


@router.post("/update/rollback")
def rollback(backup_id: str = ""):
    """回滚到指定备份。"""
    backup_id = str(backup_id).strip()
    if not backup_id:
        raise HTTPException(status_code=400, detail="请指定备份 ID")

    backup_path = os.path.join(BACKUP_DIR, backup_id)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail="备份不存在")

    # 回滚 main.py
    src_main = os.path.join(backup_path, "main.py")
    if os.path.exists(src_main):
        shutil.copy2(src_main, os.path.join(config.BASE_DIR, "main.py"))

    # 回滚 VERSION
    src_ver = os.path.join(backup_path, "VERSION")
    if os.path.exists(src_ver):
        shutil.copy2(src_ver, os.path.join(config.BASE_DIR, "VERSION"))

    # 回滚 static/
    src_static = os.path.join(backup_path, "static")
    if os.path.isdir(src_static):
        static_dir = config.STATIC_DIR
        for root, _, files in os.walk(src_static):
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn), src_static).replace("\\", "/")
                src = os.path.join(root, fn)
                dst = os.path.join(static_dir, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

    return {"ok": True, "message": f"已回滚到备份 {backup_id}，请重启服务"}
