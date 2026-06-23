"""
用户模型与数据库操作
================================================
基于 SQLite 存储用户信息,支持用户 CRUD 和默认用户初始化
"""
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

from utils.path_tool import get_abs_path
from utils.logger_handler import logger
from auth.password import hash_password


# ============================================================
# 数据库配置
# ============================================================
# 数据库路径,可通过环境变量 DB_PATH 覆盖
DEFAULT_DB_PATH = get_abs_path("data/users.db")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def get_db_connection() -> sqlite3.Connection:
    """
    获取 SQLite 数据库连接

    :return: sqlite3.Connection 实例(行工厂为 Row)
    """
    # 确保数据目录存在
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库,创建 users 表(如不存在)"""
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        TEXT PRIMARY KEY,
                username       TEXT UNIQUE NOT NULL,
                password_hash  TEXT NOT NULL,
                role           TEXT NOT NULL DEFAULT 'viewer',
                tenant_id      TEXT NOT NULL DEFAULT 'default',
                created_at     TEXT NOT NULL,
                is_active      INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.commit()
        logger.info("[auth] 数据库初始化完成,users 表已就绪")
    finally:
        conn.close()


# ============================================================
# 用户数据模型
# ============================================================
@dataclass
class User:
    """用户数据模型"""
    user_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    username: str = ""
    password_hash: str = ""
    role: str = "viewer"          # admin | editor | viewer
    tenant_id: str = "default"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_active: int = 1

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "User":
        """从数据库行构造 User 对象"""
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            password_hash=row["password_hash"],
            role=row["role"],
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
            is_active=row["is_active"],
        )

    def to_dict(self, include_hash: bool = False) -> dict:
        """
        转为字典

        :param include_hash: 是否包含密码哈希(默认不包含)
        :return: 用户信息字典
        """
        data = {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at,
            "is_active": bool(self.is_active),
        }
        if include_hash:
            data["password_hash"] = self.password_hash
        return data


# ============================================================
# 用户 CRUD 操作
# ============================================================
def create_user(username: str, password: str, role: str = "viewer",
                tenant_id: str = "default") -> User:
    """
    创建新用户

    :param username: 用户名
    :param password: 明文密码
    :param role: 角色(admin | editor | viewer)
    :param tenant_id: 租户ID
    :return: 创建的 User 对象
    """
    init_db()
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        tenant_id=tenant_id,
    )
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role, tenant_id, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user.user_id, user.username, user.password_hash, user.role,
             user.tenant_id, user.created_at, user.is_active)
        )
        conn.commit()
        logger.info(f"[auth] 创建用户: {username} (role={role}, tenant={tenant_id})")
        return user
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[User]:
    """
    根据用户名查询用户

    :param username: 用户名
    :return: User 对象,不存在返回 None
    """
    init_db()
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return User.from_row(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[User]:
    """
    根据 user_id 查询用户

    :param user_id: 用户ID
    :return: User 对象,不存在返回 None
    """
    init_db()
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return User.from_row(row) if row else None
    finally:
        conn.close()


def list_users(tenant_id: Optional[str] = None) -> List[User]:
    """
    列出用户

    :param tenant_id: 可选,按租户过滤
    :return: User 列表
    """
    init_db()
    conn = get_db_connection()
    try:
        if tenant_id:
            rows = conn.execute(
                "SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at", (tenant_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at"
            ).fetchall()
        return [User.from_row(r) for r in rows]
    finally:
        conn.close()


def delete_user(user_id: str) -> bool:
    """
    删除用户

    :param user_id: 用户ID
    :return: 删除成功返回 True
    """
    init_db()
    conn = get_db_connection()
    try:
        cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"[auth] 删除用户: user_id={user_id}")
        return deleted
    finally:
        conn.close()


def init_default_users():
    """
    初始化默认用户(仅当 users 表为空时创建)

    创建默认 admin 账户:
      - 用户名: admin
      - 密码: admin123 (生产环境请立即修改)
      - 角色: admin
      - 租户: default
    """
    init_db()
    users = list_users()
    if users:
        logger.info(f"[auth] 已存在 {len(users)} 个用户,跳过默认用户初始化")
        return

    create_user(
        username="admin",
        password="admin123",
        role="admin",
        tenant_id="default",
    )
    logger.info("[auth] 默认 admin 用户已创建 (密码: admin123,请及时修改)")


if __name__ == "__main__":
    # 直接运行此文件可初始化数据库和默认用户
    init_default_users()
    print("用户列表:")
    for u in list_users():
        print(f"  - {u.username} (role={u.role}, tenant={u.tenant_id})")
