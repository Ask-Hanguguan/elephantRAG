import sqlite3
from typing import Optional
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
import os


class MD5Store(object):
    def __init__(self):
        path = get_abs_path(chroma_conf['persist_directory'])
        self.conn = sqlite3.connect(os.path.join(path, chroma_conf['md5_hex_store']), check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._old_md5s = []  # 迁移时保留的旧MD5列表
        self.create_table()

    @property
    def old_md5s(self):
        """迁移时保留的旧MD5列表（无 file_path，供首次同步匹配）"""
        return self._old_md5s

    def create_table(self):
        """创建MD5存储表（含文件路径，支持级联同步）"""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_md5 (
                md5 TEXT NOT NULL,
                file_path TEXT UNIQUE NOT NULL,
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self.conn.commit()

        # 检查是否需要迁移旧表
        self._migrate_if_needed()

    def _migrate_if_needed(self):
        """检测旧表（只有 md5 字段）并迁移

        旧表结构：md5 TEXT UNIQUE NOT NULL（无 file_path）
        新表结构：md5 TEXT, file_path TEXT UNIQUE, updated_at TEXT
        """
        self.cursor.execute("PRAGMA table_info(file_md5)")
        columns = [col[1] for col in self.cursor.fetchall()]

        if 'file_path' in columns:
            return  # 已经是最新结构

        # 旧表：保存 MD5 列表，重新建表
        try:
            self.cursor.execute("SELECT md5 FROM file_md5")
            self._old_md5s = [row[0] for row in self.cursor.fetchall()]
        except sqlite3.OperationalError:
            self._old_md5s = []

        self.cursor.execute("DROP TABLE IF EXISTS file_md5")
        self.create_table()

        if self._old_md5s:
            logger.info(
                f"[MD5Store] 检测到旧表结构，已迁移 {len(self._old_md5s)} 条记录"
            )

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------

    def is_existing_md5(self, target_md5: str) -> bool:
        """判断MD5是否已存在"""
        sql = "SELECT COUNT(*) FROM file_md5 WHERE md5 = ?"
        self.cursor.execute(sql, (target_md5,))
        count = self.cursor.fetchone()[0]
        return count > 0

    def get_md5(self, file_path: str) -> Optional[str]:
        """按文件路径查 MD5"""
        sql = "SELECT md5 FROM file_md5 WHERE file_path = ?"
        self.cursor.execute(sql, (file_path,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def get_all_records(self) -> dict:
        """获取所有记录 {file_path: md5}，供同步比对"""
        sql = "SELECT file_path, md5 FROM file_md5"
        self.cursor.execute(sql)
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def count(self) -> int:
        """记录总数"""
        self.cursor.execute("SELECT COUNT(*) FROM file_md5")
        return self.cursor.fetchone()[0]

    # ------------------------------------------------------------------
    # 写入方法
    # ------------------------------------------------------------------

    def add_md5(self, target_md5: str, file_path: str):
        """添加或更新MD5记录

        :param target_md5: 文件MD5值
        :param file_path: 文件绝对路径
        """
        try:
            sql = """INSERT INTO file_md5 (md5, file_path)
                     VALUES (?, ?)
                     ON CONFLICT(file_path) DO UPDATE SET
                         md5 = excluded.md5,
                         updated_at = datetime('now', 'localtime')"""
            self.cursor.execute(sql, (target_md5, file_path))
            self.conn.commit()
            logger.debug(f"[MD5Store] MD5保存成功：{file_path}")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"[MD5Store] MD5插入失败：{str(e)}")

    def delete_by_path(self, file_path: str):
        """按文件路径删除记录"""
        try:
            sql = "DELETE FROM file_md5 WHERE file_path = ?"
            self.cursor.execute(sql, (file_path,))
            self.conn.commit()
            logger.debug(f"[MD5Store] 已删除记录：{file_path}")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"[MD5Store] 删除失败：{str(e)}")


# ------------------------------------------------------------------
# 自测
# ------------------------------------------------------------------
from utils.file_handler import get_file_md5_hex
if __name__ == '__main__':
    store = MD5Store()
    print(f"当前记录数：{store.count()}")

    # 测试写入
    store.add_md5("test_md5_12345", "/test/path/file.txt")
    print(f"查询MD5：{store.get_md5('/test/path/file.txt')}")
    print(f"记录数：{store.count()}")

    # 测试删除
    store.delete_by_path("/test/path/file.txt")
    print(f"删除后记录数：{store.count()}")

