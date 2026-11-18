"""下载器密码加密存储（零第三方依赖）。

目标：traffic.db 或备份单独泄露时，不直接暴露 qB / Transmission 的账号密码。

实现：标准库实现的带认证对称加密。
- 主密钥默认由 SECRET_KEY 派生；未设置时在 data 目录生成 32 字节随机
  .secret_key（权限 600），首次生成后长期复用。
- 每条密文用独立 12 字节 nonce；密钥流 = HMAC-SHA256(key, nonce||counter)，
  密文 = 明文 XOR 密钥流，认证标签 = HMAC-SHA256(key, nonce||密文) 前 16 字节。
- 存储格式 enc:<base64url(nonce|tag|ciphertext)>；解密先验标签，校验失败
  返回空串，绝不把乱码当密码发出去。
- 支持多密钥回退与启动时 rekey：更换 SECRET_KEY 后旧密文仍可解密并自动迁移。
- 未带 enc: 前缀的旧值按明文读取，init_db 一次性改写为密文，老库平滑升级。

请务必备份 SECRET_KEY / .secret_key，并与数据卷分开存放。
"""
import base64
import hashlib
import hmac
import os
import secrets

from . import config, log

PREFIX = "enc:"
_NONCE = 12
_TAG = 16

_key = None            # 当前主密钥（encrypt 用）
_keys = []             # 候选密钥列表（decrypt 依次尝试）
_key_path = None
_warned_fallback = False
_warned_mismatch = False


def _derive(raw):
    return hashlib.sha256(raw).digest()


def configure(data_dir):
    """由 db.configure() 调用，准备主密钥与回退密钥。"""
    global _key, _keys, _key_path
    _keys = []
    _key_path = os.path.join(data_dir, ".secret_key")

    env_raw = config.SECURITY.get("secret_key", "")
    env_material = str(env_raw).encode("utf-8") if env_raw else None
    if env_material:
        _keys.append(_derive(env_material))

    file_material = None
    try:
        if os.path.isfile(_key_path):
            with open(_key_path, "rb") as f:
                file_material = f.read()
            if not file_material:
                file_material = None
        if file_material is None:
            # 文件缺失：用当前生效的材料（SECRET_KEY 或随机值）补写一份，
            # 作为持久回退，避免「设定后又移除 SECRET_KEY」导致密码全丢。
            file_material = env_material or secrets.token_bytes(32)
            with open(_key_path, "wb") as f:
                f.write(file_material)
            try:
                os.chmod(_key_path, 0o600)
            except OSError:
                pass
            if not env_material:
                print("[crypto] 已生成下载器密码加密密钥 .secret_key"
                      "（建议改用 SECRET_KEY 环境变量并与数据卷分开保存）", flush=True)
    except (OSError, ValueError) as exc:
        # 只读数据卷等极端情况：不静默失败
        log.warn("crypto.key_unavailable", error=str(exc))

    if file_material:
        k = _derive(file_material)
        if k not in _keys:
            _keys.append(k)
    _key = _keys[0] if _keys else None
    if _key is None:
        log.warn("crypto.key_unavailable", error="无可用密钥材料，下载器密码将降级为明文")


def _master():
    return _key


def _keystream(key, nonce, n):
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out += hmac.new(key, nonce + ctr.to_bytes(4, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:n])


def encrypt(plain):
    """加密；空值 / 无密钥时原样返回（后者仅在极端降级时发生）。"""
    global _warned_fallback
    s = "" if plain is None else str(plain)
    if not s or s.startswith(PREFIX):
        return s
    key = _master()
    if key is None:
        if not _warned_fallback:
            log.warn("crypto.plaintext_fallback")
            _warned_fallback = True
        return s
    nonce = secrets.token_bytes(_NONCE)
    data = s.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:_TAG]
    return PREFIX + base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def _decrypt_blob(s, keys):
    """用给定候选密钥依次尝试，返回明文或 None（标签全部不通过 / 格式错误）。"""
    try:
        blob = base64.urlsafe_b64decode(s[len(PREFIX):].encode("ascii"))
        if len(blob) < _NONCE + _TAG:
            return None
        nonce = blob[:_NONCE]
        tag = blob[_NONCE:_NONCE + _TAG]
        ct = blob[_NONCE + _TAG:]
        for key in keys:
            expect = hmac.new(key, nonce + ct, hashlib.sha256).digest()[:_TAG]
            if hmac.compare_digest(tag, expect):
                ks = _keystream(key, nonce, len(ct))
                return bytes(a ^ b for a, b in zip(ct, ks)).decode("utf-8", "replace")
        return None
    except Exception:
        return None


def decrypt(stored):
    """解密；明文旧值原样返回；所有候选密钥都校验失败返回空串（只告警一次）。"""
    global _warned_mismatch
    s = "" if stored is None else str(stored)
    if not s or not s.startswith(PREFIX):
        return s
    if not _keys:
        return ""
    plain = _decrypt_blob(s, _keys)
    if plain is not None:
        return plain
    # 采集线程每轮都会读密码，密钥不匹配时不能每 5 秒刷一条日志（5.5）。
    if not _warned_mismatch:
        log.warn("crypto.tag_mismatch",
                 hint="历史密文与当前密钥不匹配，请检查 SECRET_KEY / .secret_key 是否被更换")
        _warned_mismatch = True
    return ""


def rekey(stored):
    """启动时把「用回退密钥加密的历史密文」统一重加密到当前主密钥。

    返回新的密文；若本就由主密钥加密、是明文旧值或无法解开则返回 None。
    """
    s = str(stored or "")
    if not s.startswith(PREFIX) or not _key or len(_keys) < 2:
        return None
    # 主密钥能直接解开说明无需处理
    if _decrypt_blob(s, _keys[:1]) is not None:
        return None
    plain = _decrypt_blob(s, _keys[1:])
    if plain is None:
        return None
    return encrypt(plain)


def is_encrypted(stored):
    return str(stored or "").startswith(PREFIX)
