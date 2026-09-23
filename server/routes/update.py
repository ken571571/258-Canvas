"""API 路由：在线更新系统

支持从 GitHub 检测新版本、下载更新、备份与回滚。
更新策略：下载仓库 zip 包，按白名单覆盖代码文件，保留用户数据。
"""

import os
import re
import io
import time
import json
import shutil
import zipfile
import asyncio
from datetime import datetime
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException
import httpx

from .. import config

router = APIRouter(prefix="/api", tags=["update"])

# 更新源 URL —— 默认指向官方仓库（用户可在设置页修改或通过 UPDATE_REPO_URL 覆盖）
# raw 格式: "https://raw.githubusercontent.com/<user>/<repo>/<branch>"
_DEFAULT_REPO = "https://raw.githubusercontent.com/ken571571/258-Canvas/main"
GITHUB_REPO = os.getenv("UPDATE_REPO_URL", _DEFAULT_REPO)
GITHUB_REPO = GITHUB_REPO.rstrip("/") if GITHUB_REPO else ""

# 允许的更新源主机名（逗号分隔），防止指向恶意服务器
_ALLOWED_RAW = os.getenv("UPDATE_ALLOWED_HOSTS", "raw.githubusercontent.com,github.com,codeload.github.com")
UPDATE_ALLOWED_HOSTS = {h.strip().lower() for h in _ALLOWED_RAW.split(",") if h.strip()}

BACKUP_DIR = os.path.join(config.DATA_DIR, "update_backups")

# —— 更新白名单：只覆盖这些目录/文件（代码，不含用户数据）——
# 目录：递归覆盖其下所有文件
# 文件：精确匹配
UPDATE_WHITELIST_DIRS = [
    "server",
    "static",
    "skills",
    "scripts",
    "tests",
]
UPDATE_WHITELIST_FILES = [
    "run.py",
    "VERSION",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "启动服务.bat",
]
# workflows/ 整体允许覆盖，但排除 workflows/custom/（用户自定义工作流）
UPDATE_WHITELIST_DIRS_WITH_EXCLUDE = {
    "workflows": ["custom"],
}

# —— 黑名单：这些路径即使在白名单目录下也不覆盖 ——
UPDATE_BLACKLIST = [
    "data", "logs", "input", "output",
    "canvases", "agents",
    "API",            # 含 .env 密钥
    "python",         # 嵌入式 Python 环境
    ".git", ".gitignore",
]


def _validate_update_url(url: str) -> str | None:
    """验证更新源 URL 的安全性。返回错误信息字符串，无错误返回 None。"""
    if not url:
        return "未配置更新源（UPDATE_REPO_URL）"
    if not url.startswith("https://"):
        return "更新源必须以 https:// 开头"
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return "更新源 URL 格式无效"
    if host.lower() not in UPDATE_ALLOWED_HOSTS:
        return f"更新源主机名 {host} 不在允许列表中（{', '.join(sorted(UPDATE_ALLOWED_HOSTS))}）"
    return None


def _parse_github_info(repo_url: str) -> dict:
    """从 raw.githubusercontent.com URL 解析 GitHub 仓库信息。

    输入: https://raw.githubusercontent.com/ken571571/258-Canvas/main
    输出: {"user": "ken571571", "repo": "258-Canvas", "branch": "main"}
    """
    parsed = urlparse(repo_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3:
        raise ValueError("UPDATE_REPO_URL 格式应为 https://raw.githubusercontent.com/<user>/<repo>/<branch>")
    return {
        "user": parts[0],
        "repo": parts[1],
        "branch": parts[2],
    }


def _version_tuple(v: str) -> list:
    return [int(x) for x in re.findall(r"\d+", str(v or ""))]


def _version_gt(a: str, b: str) -> bool:
    ta, tb = _version_tuple(a), _version_tuple(b)
    n = max(len(ta), len(tb))
    ta += [0] * (n - len(ta))
    tb += [0] * (n - len(tb))
    return ta > tb


def _is_blacklisted(rel_path: str) -> bool:
    """检查相对路径是否在黑名单中（任何一级目录匹配即算）。"""
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in UPDATE_BLACKLIST:
            return True
    return False


def _is_in_whitelist(rel_path: str) -> bool:
    """检查相对路径是否在更新白名单中。"""
    rel = rel_path.replace("\\", "/")
    top = rel.split("/")[0]

    # 精确文件匹配
    if "/" not in rel and rel in UPDATE_WHITELIST_FILES:
        return True

    # 目录白名单
    if top in UPDATE_WHITELIST_DIRS:
        return True

    # 带排除的目录白名单（如 workflows/ 但排除 workflows/custom/）
    if top in UPDATE_WHITELIST_DIRS_WITH_EXCLUDE:
        excludes = UPDATE_WHITELIST_DIRS_WITH_EXCLUDE[top]
        parts = rel.split("/")
        for exc in excludes:
            if len(parts) > 1 and parts[1] == exc:
                return False
        return True

    return False


def _should_update_file(rel_path: str) -> bool:
    """综合判断：白名单内且不在黑名单中。"""
    if _is_blacklisted(rel_path):
        return False
    return _is_in_whitelist(rel_path)


@router.get("/app-info")
def app_info():
    """返回当前版本和仓库信息。"""
    return {
        "version": config.APP_VERSION,
        "repo_url": GITHUB_REPO,
        "update_sources": ["github"],
    }


@router.get("/settings/update-repo")
def get_update_repo():
    """读取当前更新源配置。"""
    return {"repo_url": GITHUB_REPO}


@router.post("/settings/update-repo")
async def save_update_repo(payload: dict = {}):
    """保存更新源 URL（带安全校验，防止供应链攻击）。

    仅允许 https:// 且主机名在白名单内的 URL。
    """
    url = str(payload.get("repo_url", "") or "").strip()

    if not url:
        # 清空更新源
        from .providers_cfg import _write_env
        await _write_env({"UPDATE_REPO_URL": ""})
        return {"ok": True, "repo_url": ""}

    # 安全校验
    err = _validate_update_url(url)
    if err:
        raise HTTPException(status_code=400, detail=err)

    from .providers_cfg import _write_env
    await _write_env({"UPDATE_REPO_URL": url})
    return {"ok": True, "repo_url": url}


@router.get("/check-update")
async def check_update():
    """检测更新源是否有新版本。"""
    if err := _validate_update_url(GITHUB_REPO):
        return {"current": config.APP_VERSION, "update_available": False, "error": err}
    version_url = f"{GITHUB_REPO}/VERSION"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as cli:
            resp = await cli.get(
                version_url,
                headers={"User-Agent": "Canvas571-Updater"},
                params={"t": int(time.time())},
            )
        if resp.status_code != 200:
            return {"current": config.APP_VERSION, "update_available": False, "error": f"HTTP {resp.status_code}"}

        remote_ver = resp.text.strip().splitlines()[0].strip()
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
async def do_update(payload: dict = {}):
    """从 GitHub 下载最新 zip 包并执行全量更新（白名单覆盖，保留用户数据）。

    安全要求:
    - UPDATE_REPO_URL 必须以 https:// 开头且主机名在白名单
    - 需要 confirm=true 确认操作
    """
    if err := _validate_update_url(GITHUB_REPO):
        raise HTTPException(status_code=400, detail=err)

    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail="更新操作需要 confirm=true 确认")

    # 1. 确认有更新
    check = await check_update()
    if not check.get("update_available"):
        raise HTTPException(status_code=400, detail="当前已是最新版本")

    # 2. 解析 GitHub 仓库信息，构造 zip 下载地址
    try:
        info = _parse_github_info(GITHUB_REPO)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    zip_url = f"https://github.com/{info['user']}/{info['repo']}/archive/refs/heads/{info['branch']}.zip"

    # 3. 创建备份目录
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = os.path.join(BACKUP_DIR, ts)
    os.makedirs(backup_root, exist_ok=True)

    try:
        # 4. 下载 zip 包
        zip_bytes = None
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as cli:
                resp = await cli.get(zip_url, headers={"User-Agent": "Canvas571-Updater"})
                if resp.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"下载更新包失败: HTTP {resp.status_code}")
                zip_bytes = resp.content
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"下载更新包失败: {e}")

        # 5. 解压 zip 到临时目录
        tmp_dir = os.path.join(config.DATA_DIR, f"_update_tmp_{ts}")
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"解压更新包失败: {e}")

        # zip 解压后顶层目录名格式：{repo}-{branch}
        extracted_root = os.path.join(tmp_dir, f"{info['repo']}-{info['branch']}")
        if not os.path.isdir(extracted_root):
            # 兜底：找 tmp_dir 下唯一的子目录
            subdirs = [d for d in os.listdir(tmp_dir) if os.path.isdir(os.path.join(tmp_dir, d))]
            if len(subdirs) == 1:
                extracted_root = os.path.join(tmp_dir, subdirs[0])
            else:
                raise HTTPException(status_code=500, detail="更新包结构异常：未找到仓库根目录")

        # 6. 遍历解压后的文件，按白名单覆盖 + 备份
        updated = []
        failed = []
        for root, dirs, files in os.walk(extracted_root):
            for fn in files:
                src_path = os.path.join(root, fn)
                rel_path = os.path.relpath(src_path, extracted_root).replace("\\", "/")

                # 判断是否需要更新
                if not _should_update_file(rel_path):
                    continue

                dst_path = os.path.join(config.BASE_DIR, rel_path.replace("/", os.sep))

                # 备份现有文件
                if os.path.exists(dst_path):
                    bak_path = os.path.join(backup_root, rel_path.replace("/", os.sep))
                    os.makedirs(os.path.dirname(bak_path), exist_ok=True)
                    try:
                        shutil.copy2(dst_path, bak_path)
                    except Exception:
                        pass  # 备份失败不阻断更新

                # 覆盖写入
                try:
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.copy2(src_path, dst_path)
                    updated.append(rel_path)
                except Exception as e:
                    failed.append(f"{rel_path} ({e})")

        # 7. 清理临时目录
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

        # 8. 读取新版本号
        new_ver = check.get("latest", {}).get("version", "")
        try:
            ver_path = os.path.join(config.BASE_DIR, "VERSION")
            if os.path.exists(ver_path):
                with open(ver_path, "r", encoding="utf-8") as f:
                    new_ver = f.read().strip().splitlines()[0].strip()
        except Exception:
            pass

        return {
            "ok": True,
            "updated": updated,
            "failed": failed,
            "backup": ts,
            "new_version": new_ver,
            "message": f"更新完成（{len(updated)} 个文件），请重启服务以生效。备份位于: data/update_backups/{ts}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {e}")


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
    import re as _re
    from ..security.paths import safe_join as _safe_join

    backup_id = str(backup_id).strip()
    if not backup_id:
        raise HTTPException(status_code=400, detail="请指定备份 ID")

    # 安全校验：备份 ID 必须为 YYYYMMDD-HHMMSS 格式，防止路径穿越
    if not _re.match(r"^\d{8}-\d{6}$", backup_id):
        raise HTTPException(status_code=400, detail="备份 ID 格式无效")

    try:
        backup_path = _safe_join(BACKUP_DIR, backup_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="备份 ID 不合法")
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail="备份不存在")

    # 遍历备份目录，恢复所有文件
    restored = []
    for root, _, files in os.walk(backup_path):
        for fn in files:
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, backup_path)
            dst = os.path.join(config.BASE_DIR, rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(rel.replace("\\", "/"))
            except Exception:
                pass

    return {"ok": True, "restored": len(restored), "message": f"已回滚到备份 {backup_id}（恢复 {len(restored)} 个文件），请重启服务"}
