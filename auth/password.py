"""
密码哈希工具
================================================
使用 bcrypt 直接进行加盐哈希,安全存储用户密码

注意: bcrypt 对输入长度有 72 字节硬性限制。
解决方案:先对密码做 SHA-256 摘要再传入 bcrypt,
         将任意长度密码压缩为固定 32 字节,彻底规避限制。
"""
import hashlib

import bcrypt


def _prehash(password: str) -> bytes:
    """
    对密码做 SHA-256 预哈希,确保输入 bcrypt 的内容不超过 72 字节

    :param password: 原始明文密码
    :return: SHA-256 摘要的 UTF-8 字节(固定 64 字节)
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")


def hash_password(password: str) -> str:
    """
    对明文密码进行 bcrypt 加盐哈希

    内部先做 SHA-256 预哈希以规避 bcrypt 72 字节限制。

    :param password: 明文密码
    :return: 哈希后的密码字符串
    """
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码是否与哈希值匹配

    :param plain_password: 明文密码
    :param hashed_password: 哈希后的密码
    :return: 匹配返回 True,否则 False
    """
    return bcrypt.checkpw(_prehash(plain_password), hashed_password.encode("utf-8"))
