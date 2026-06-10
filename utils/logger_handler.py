import logging
import os
from datetime import datetime

from utils.path_tool import get_abs_path

#日志保存的根目录
LOG_ROOT = get_abs_path('logs')

#确保日志的目录存在
os.makedirs(LOG_ROOT, exist_ok=True)

#日志的格式配置 error info debug
DEFAULT_LOG_FORMAT = logging.Formatter(
    '%(asctime)s-%(name)s-%(levelname)s- %(filename)s:%(lineno)d-%(message)s',
)
'''
%(asctime)s：日志消息的时间戳
%(levelname)s：日志级别（如 DEBUG、INFO、WARNING 等）
%(name)s：日志记录器的名称
%(message)s：日志内容
%(filename)s：生成日志的文件名
%(funcName)s：生成日志的函数名称
%(lineno)d：日志行所在的行号
'''

'''
日志初始化操作
1、创建日志记录器
2、设置输出处理器Handler
3、添加Handler
'''
def get_logger(
        name: str = 'agent',
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        log_file = None,
)->logging.Logger:
    #实例化logger
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    #避免重复添加handler
    if logger.handlers:
        return logger

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)

    #添加Handler
    logger.addHandler(console_handler)

    #文件handler
    if not log_file:
        log_file = os.path.join(LOG_ROOT, f'{name}_{datetime.now().strftime('%Y%m%d')}.log')    #strftime() 函数用于格式化时间

    file_handler = logging.FileHandler(log_file,encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(file_handler)

    return logger

logger = get_logger()

if __name__ == '__main__':
    logger.info('信息日志')
    logger.debug('调试日志')
    logger.error('错误日志')
    logger.warning('警告日志')


