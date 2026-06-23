"""
JWT Token 管理
================================================
提供 access token 和 refresh token 的签发与验证
基于 python-jose 实现
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError

from utils.logger_handler import logger


# ============================================================
# JWT 配置(通过环境变量,支持容器化部署)
# ============================================================
# 签名密钥:生产环境必须通过环境变量设置
JWT_SECRET = os.environ.get("JWT_SECRET", "enterprise-qa-secret-change-in-production")
# 签名算法
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
# access token 过期时间(分钟)
JWT_ACCESS_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_EXPIRE_MINUTES", "30"))
# refresh token 过期时间(天)
JWT_REFRESH_EXPIRE_DAYS = int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))


def create_access_token(user_id: str, username: str, role: str,
                        tenant_id: str) -> str:
    """
    签发 access token

    :param user_id: 用户ID
    :param username: 用户名
    :param role: 角色
    :param tenant_id: 租户ID
    :return: JWT access token 字符串
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,           # subject(用户ID)
        "username": username,
        "role": role,
        "tenant_id": tenant_id,
        "exp": expire,             # 过期时间
        "iat": datetime.now(timezone.utc),  # 签发时间
        "type": "access",
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.info(f"[auth] 签发 access token: user={username}, role={role}")
    return token


def create_refresh_token(user_id: str, username: str) -> str:
    """
    签发 refresh token(用于刷新 access token)

    :param user_id: 用户ID
    :param username: 用户名
    :return: JWT refresh token 字符串
    """
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    解码并验证 JWT token

    :param token: JWT token 字符串
    :return: 解码后的 payload 字典,验证失败返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"[auth] JWT 验证失败: {e}")
        return None


def verify_access_token(token: str) -> Optional[dict]:
    """
    验证 access token

    :param token: JWT access token
    :return: 验证通过返回 payload,失败返回 None
    """
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != "access":
        logger.warning("[auth] token 类型错误,期望 access")
        return None
    return payload


def verify_refresh_token(token: str) -> Optional[dict]:
    """
    验证 refresh token

    :param token: JWT refresh token
    :return: 验证通过返回 payload,失败返回 None
    """
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != "refresh":
        logger.warning("[auth] token 类型错误,期望 refresh")
        return None
    return payload
