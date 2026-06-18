import hashlib
import os
from typing import Optional
from utils.logger_handler import logger
from langchain_core.documents import Document
from langchain_docling import DoclingLoader

def get_file_md5_hex(filepath: str) -> Optional[str]:
    '''
    计算文件的MD5哈希值，返回十六进制字符串
    :param filepath: 文件的绝对/相对路径
    :return: 成功返回32位MD5十六进制字符串，失败返回None
    '''

    # 1. 校验文件是否存在
    if not os.path.exists(filepath):
        logger.error(f"错误：文件 {filepath} 不存在")
        return None

    #2. 校验是否是文件（避免传入文件夹路径）
    if not os.path.isfile(filepath):
        logger.error(f"错误：{filepath} 不是有效文件")
        return None

    # 3. 初始化MD5对象
    md5_obj = hashlib.md5()

    # 4. 分片读取大文件（避免一次性加载占满内存）
    chunk_size = 4096  # 4KB分片，可根据需求调整
    try:
        with open(filepath, "rb") as f: # 必须以二进制模式打开
            # Python3.8后的海象运算法： 先读，后判断
            while chunk := f.read(chunk_size):  # 逐片读取
                md5_obj.update(chunk)   # 更新MD5摘要

        # 5. 获取十六进制字符串（32位小写）
        md5_hex = md5_obj.hexdigest()
        return md5_hex

    except PermissionError:
        logger.error(f"错误：无权限读取文件 {filepath}")
        return None
    except Exception as e:
        logger.error(f"计算MD5失败：{str(e)}")
        return None


def listdir_with_allowed_type(path: str, allowed_types: tuple[str]):
    '''
    输入文件夹和允许文件类型列表，返回一个允许文件路径元组
    :param path:
    :param allowed_types:
    :return:
    '''
    files =[ ]
    # print("x2:",allowed_types, type(allowed_types))
    if not os.path.isdir(path):
        logger.error(f"错误：{path} 不是有效目录或不存在")
        return tuple(files)

    for f in os.listdir(path):
        # print('x1:',f)
        if f.endswith(allowed_types):    # 元组参数，满足任一后缀即匹配
            # print("x2: ", f)
            files.append(os.path.join(path, f))

    return tuple(files)

def docling_loader(filepath: str) -> list[Document]:
    """
    使用 DoclingLoader 懒加载文档（支持 PDF/DOCX/HTML/PPTX/图片等）
    内部使用 lazy_load() 逐文档处理，返回 list[Document] 保持接口兼容。
    """
    try:
        loader = DoclingLoader(
            file_path=filepath,
            export_type="markdown",
        )
        return list(loader.lazy_load())
    except Exception as e:
        logger.error(f"Docling 加载失败 [{filepath}]: {str(e)}")
        return []
