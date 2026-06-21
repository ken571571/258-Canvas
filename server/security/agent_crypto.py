"""Agent 加密模块 — AES-256-GCM 加密 / PBKDF2 密钥派生 / 机器指纹

双密码 + 试用次数设计：
- permanent 密码：永久使用
- trial 密码：限制使用次数，用完锁定

所有加密使用 AES-256-GCM（认证加密），密文不可篡改。
"""

import os
import sys
import time
import hashlib
import subprocess
import socket
import uuid as _uuid
import json
from typing import Tuple, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# —— 常量 ——
AGENT_MAGIC = b"AGP1"                    # .agent 文件魔数
PBKDF2_ITERATIONS = 600_000              # OWASP 2023 推荐
SALT_LENGTH = 16
NONCE_LENGTH = 12                        # AES-GCM 标准
KEY_LENGTH = 32                          # AES-256
FINGERPRINT_CACHE = None                  # 进程级缓存


# ============================================================
#  机器指纹
# ============================================================

def collect_machine_fingerprint() -> str:
    """采集机器硬件指纹，多源组合后 SHA-256 哈希。

    Windows: wmic 获取主板 UUID + CPU ID + 磁盘序列号 + MAC + 主机名
    单源故障不影响整体——有多少取多少。
    返回 32 字符 hex 字符串。
    """
    global FINGERPRINT_CACHE
    if FINGERPRINT_CACHE:
        return FINGERPRINT_CACHE

    sources = []

    if sys.platform == "win32":
        # 主板 UUID
        try:
            r = subprocess.run(
                ["wmic", "csproduct", "get", "uuid"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and l.strip().lower() != "uuid"]
            if lines:
                sources.append(lines[0])
        except Exception:
            pass

        # CPU ID
        try:
            r = subprocess.run(
                ["wmic", "cpu", "get", "processorid"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and l.strip().lower() != "processorid"]
            if lines:
                sources.append(lines[0])
        except Exception:
            pass

        # 系统盘序列号
        try:
            r = subprocess.run(
                ["wmic", "diskdrive", "get", "serialnumber"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and l.strip().lower() != "serialnumber"]
            if lines:
                sources.append(lines[0])
        except Exception:
            pass
    else:
        # Linux: /etc/machine-id + DMI + MAC
        try:
            with open("/etc/machine-id", "r") as f:
                sources.append(f.read().strip())
        except Exception:
            pass
        for dmi in ["/sys/class/dmi/id/product_uuid", "/sys/class/dmi/id/board_serial"]:
            try:
                with open(dmi, "r") as f:
                    v = f.read().strip()
                    if v and v != "0" * len(v):
                        sources.append(v)
            except Exception:
                pass

    # MAC 地址（跨平台）
    try:
        sources.append(str(_uuid.getnode()))
    except Exception:
        pass

    # 主机名（跨平台）
    try:
        sources.append(socket.gethostname())
    except Exception:
        pass

    if not sources:
        # 极端情况：什么硬件信息都取不到，用随机值（每次启动不同）
        sources.append(_uuid.uuid4().hex)

    combined = "|".join(s for s in sources if s)
    FINGERPRINT_CACHE = hashlib.sha256(combined.encode()).hexdigest()[:32]
    return FINGERPRINT_CACHE


def fingerprint_hash(fingerprint: str) -> str:
    """用于 agent.json 快速校验的短哈希。"""
    return "sha256:" + hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


# ============================================================
#  密钥派生
# ============================================================

def derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 派生 32 字节 AES-256 密钥。"""
    if isinstance(password, str):
        password = password.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password)


# ============================================================
#  AES-256-GCM 加密 / 解密
# ============================================================

def encrypt_bytes(plaintext: bytes, key: bytes, aad: bytes | None = None) -> bytes:
    """AES-256-GCM 加密。

    输出格式: MAGIC(4) + nonce(12) + ciphertext+tag
    key 必须是 32 字节的 AES-256 密钥。
    aad 可选附加认证数据（用于绑定明文头，防篡改）。
    """
    if not isinstance(key, bytes) or len(key) != KEY_LENGTH:
        raise ValueError(f"Key must be {KEY_LENGTH} bytes, got {len(key) if isinstance(key, bytes) else type(key)}")

    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    return AGENT_MAGIC + nonce + ciphertext


def decrypt_bytes(data: bytes, key: bytes, aad: bytes | None = None) -> bytes:
    """AES-256-GCM 解密。自动从头部提取 nonce。

    aad 必须与加密时使用的 aad 完全一致，否则 GCM MAC 校验失败。

    Raises:
        ValueError: 密码错误或数据损坏（GCM MAC 校验失败）
    """
    if len(data) < 4 + NONCE_LENGTH + 16:
        raise ValueError("Data too short to be valid encrypted payload")

    magic = data[:4]
    if magic != AGENT_MAGIC:
        raise ValueError(f"Invalid magic bytes: {magic!r}")

    nonce = data[4:4 + NONCE_LENGTH]
    ciphertext = data[4 + NONCE_LENGTH:]

    if len(ciphertext) < 16:
        raise ValueError("Ciphertext too short (missing GCM tag)")

    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, aad)
    except Exception as e:
        raise ValueError(f"Decryption failed: wrong key or corrupted data") from e


def is_encrypted(data: bytes) -> bool:
    """检测数据是否以 AGP1 魔数开头。"""
    return len(data) >= 4 and data[:4] == AGENT_MAGIC


# ============================================================
#  字符串加密（用于 JSON 字段内嵌）
# ============================================================

def encrypt_str(plaintext: str, key: bytes) -> str:
    """加密字符串，返回 base64 字符串（可嵌入 JSON）。"""
    import base64
    ciphertext = encrypt_bytes(plaintext.encode("utf-8"), key)
    return base64.urlsafe_b64encode(ciphertext).decode("ascii")


def decrypt_str(encrypted_b64: str, key: bytes) -> str:
    """解密 base64 字符串，返回明文。"""
    import base64
    data = base64.urlsafe_b64decode(encrypted_b64.encode("ascii"))
    return decrypt_bytes(data, key).decode("utf-8")


# ============================================================
#  便捷函数（封装指纹→密钥的派生）
# ============================================================

def _fingerprint_key(fingerprint: str) -> bytes:
    """从指纹字符串派生固定 32 字节密钥。"""
    return hashlib.sha256(("agent_fingerprint:" + fingerprint).encode()).digest()


def encrypt_with_fingerprint(plaintext: str, fingerprint: str) -> str:
    """用机器指纹加密字符串。"""
    key = _fingerprint_key(fingerprint)
    return encrypt_str(plaintext, key)


def decrypt_with_fingerprint(encrypted_b64: str, fingerprint: str) -> str:
    """用机器指纹解密字符串。"""
    key = _fingerprint_key(fingerprint)
    return decrypt_str(encrypted_b64, key)


def encrypt_file(path: str, fingerprint: str) -> None:
    """加密文件到临时文件然后原子替换（防止写入失败损坏原文件）。"""
    with open(path, "rb") as f:
        plaintext = f.read()
    key = _fingerprint_key(fingerprint)
    ciphertext = encrypt_bytes(plaintext, key)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(ciphertext)
    os.replace(tmp, path)


def decrypt_file_to_memory(path: str, fingerprint: str) -> bytes:
    """解密文件到内存（不写盘）。"""
    with open(path, "rb") as f:
        data = f.read()
    key = _fingerprint_key(fingerprint)
    return decrypt_bytes(data, key)


# ============================================================
#  导出 / 导入：双密码 + 试用次数
# ============================================================

def export_bundle(agent_config: dict, files: dict, kb_snapshot: dict,
                  permanent_password: str, trial_password: str = "",
                  trial_limit: int = 5, expires_hours: int = 24) -> bytes:
    """创建加密的 .agent 导出文件。

    Args:
        agent_config: Agent 配置字典（明文）
        files: {"skills/foo.py": "content", ...}
        kb_snapshot: 知识库快照字典
        permanent_password: 永久密码（必填，≥8 字符）
        trial_password: 试用密码（可选，≥8 字符）
        trial_limit: 试用次数（默认 5）
        expires_hours: 导入有效期（小时，默认 24，0=永不过期）
    """
    if len(permanent_password) < 8:
        raise ValueError("Permanent password must be at least 8 characters")

    # 过期时间戳
    expires_at = 0
    if expires_hours > 0:
        expires_at = int(time.time()) + expires_hours * 3600

    # 生成随机的 agent_data_key
    agent_data_key = os.urandom(KEY_LENGTH)

    # 用 data_key 加密 Agent 内容
    bundle_plaintext = json.dumps({
        "agent_config": agent_config,
        "files": files,
        "kb_snapshot": kb_snapshot,
    }, ensure_ascii=False).encode("utf-8")

    # 构建 slots
    slots = []

    # 永久密码 slot
    perm_salt = os.urandom(SALT_LENGTH)
    perm_key = derive_key(permanent_password, perm_salt)
    slots.append({
        "type": "permanent",
        "salt": perm_salt.hex(),
        "key": encrypt_bytes(agent_data_key, perm_key).hex(),
    })

    # 试用密码 slot（可选）
    if trial_password and len(trial_password) >= 8:
        trial_salt = os.urandom(SALT_LENGTH)
        trial_key = derive_key(trial_password, trial_salt)
        slots.append({
            "type": "trial",
            "salt": trial_salt.hex(),
            "limit": trial_limit,
            "key": encrypt_bytes(agent_data_key, trial_key).hex(),
        })

    # 打包（含过期时间戳）
    header = json.dumps({
        "version": 1,
        "slots": slots,
        "expires_at": expires_at,   # Unix 时间戳，0=永不过期
    }, ensure_ascii=False)
    header_bytes = header.encode("utf-8")

    # 用 header 作为 AAD 重新加密 bundle，防止 header 被篡改
    encrypted_bundle = encrypt_bytes(bundle_plaintext, agent_data_key, aad=header_bytes)
    header_len = len(header_bytes)

    import struct
    # 格式: MAGIC(4) + header_len(4) + header_json + encrypted_bundle
    return AGENT_MAGIC + struct.pack(">I", header_len) + header_bytes + encrypted_bundle


def extract_slots_from_agent_file(data: bytes) -> list:
    """从 .agent 文件中提取 slots 列表（不解密内容）。"""
    if len(data) < 8 or data[:4] != AGENT_MAGIC:
        raise ValueError("Invalid .agent file format")

    import struct
    header_len = struct.unpack(">I", data[4:8])[0]
    header_bytes = data[8:8 + header_len]
    header = json.loads(header_bytes.decode("utf-8"))
    return header.get("slots", []), header.get("version", 1)


def import_bundle(data: bytes, password: str) -> dict:
    """用密码解密 .agent 文件，返回 Agent 内容。

    自动匹配 slots 中的密码类型。
    返回: {
        "agent_config": {...},
        "files": {...},
        "kb_snapshot": {...},
        "slot_type": "permanent" | "trial",
        "trial_limit": int or None,
    }
    """
    if len(data) < 8 or data[:4] != AGENT_MAGIC:
        raise ValueError("Invalid .agent file format")

    import struct
    header_len = struct.unpack(">I", data[4:8])[0]
    header_bytes = data[8:8 + header_len]
    header = json.loads(header_bytes.decode("utf-8"))
    slots = header.get("slots", [])

    # 时间锁检查
    expires_at = header.get("expires_at", 0)
    if expires_at > 0 and int(time.time()) > expires_at:
        expired_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at))
        raise ValueError(f"Agent 文件已于 {expired_str} 过期，请联系创作者获取新文件")

    encrypted_bundle = data[8 + header_len:]

    # 遍历 slots，尝试密码
    for slot in slots:
        salt = bytes.fromhex(slot["salt"])
        derived = derive_key(password, salt)
        try:
            agent_data_key = decrypt_bytes(bytes.fromhex(slot["key"]), derived)
            # 用 data_key 解密 bundle（header_bytes 作为 AAD 防篡改）
            bundle_plaintext = decrypt_bytes(encrypted_bundle, agent_data_key, aad=header_bytes)
            bundle = json.loads(bundle_plaintext.decode("utf-8"))
            bundle["slot_type"] = slot["type"]
            bundle["trial_limit"] = slot.get("limit")
            return bundle
        except ValueError:
            continue  # 密码不匹配这个 slot（GCM MAC 校验失败），试下一个
        except json.JSONDecodeError:
            raise ValueError("Agent file contains corrupted data")

    raise ValueError("Incorrect password")


def encrypt_agent_data_with_fingerprint(data: str, fingerprint: str) -> str:
    """用机器指纹加密 Agent 数据（用于保存到 agent.json）。"""
    return encrypt_with_fingerprint(data, fingerprint)


def decrypt_agent_data_with_fingerprint(encrypted_b64: str, fingerprint: str) -> str:
    """用机器指纹解密 Agent 数据。"""
    return decrypt_with_fingerprint(encrypted_b64, fingerprint)
