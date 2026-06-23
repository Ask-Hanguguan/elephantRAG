"""
密码哈希工具
================================================
使用 bcrypt 加盐哈希,安全存储用户密码
"""
from passlib.context import CryptContext

# bcrypt 上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    对明文密码进行 bcrypt 加盐哈希

    :param password: 明文密码
    :return: 哈希后的密码字符串
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码是否与哈希值匹配

    :param plain_password: 明文密码
    :param hashed_password: 哈希后的密码
    :return: 匹配返回 True,否则 False
    """
    return pwd_context.verify(plain_password, hashed_password)
