import sqlite3
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
import os

class MD5Store(object):
    def __init__(self):
        path = get_abs_path(chroma_conf['persist_directory'])
        self.conn = sqlite3.connect(os.path.join(path, chroma_conf['md5_hex_store']))
        self.cursor = self.conn.cursor()
        self.create_table()

    def create_table(self):
        """创建MD5存储表"""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_md5
            (
                md5 TEXT UNIQUE NOT NULL
            )
        """)
        self.conn.commit()

    #接收MD5，返回存在状态，True表示已存在
    def is_existing_md5(self,target_md5)->bool:
        sql = "SELECT COUNT(*) FROM file_md5 WHERE md5 = ?"
        self.cursor.execute(sql, (target_md5,))
        count = self.cursor.fetchone()[0]
        return count > 0

    #添加MD5
    def add_md5(self,target_md5):
        # 插入SQL
        try:
            sql = "INSERT INTO file_md5 (md5) VALUES (?)"

            self.cursor.execute(sql, (target_md5,))

            self.conn.commit()

            logger.info('MD5保存成功')

        except Exception as e:
            # 出错时回滚事务，保证数据安全
            self.conn.rollback()
            logger.error(f"MD5插入失败，错误原因：{str(e)}")


from utils.file_handler import get_file_md5_hex
if __name__ == '__main__':
    md5_store = MD5Store()
    md5_hex = get_file_md5_hex('../data/维护保养.txt')
    md5_store.add_md5(md5_hex)
    md5_store.is_existing_md5(md5_hex)