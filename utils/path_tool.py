'''
为整个项目提供统一路径
'''

import os

def get_project_root()->str:
    '''
    获取工程根目录
    :return: 字符串根目录
    '''
    #当前文件绝对路径 D:\Desktop\py\AI大模型RAG和智能体开发_Agent项目\utils\path_tool.py
    current_file = os.path.abspath(__file__)

    #返回当前文件夹的文件路径 D:\Desktop\py\AI大模型RAG和智能体开发_Agent项目\utils
    current_dir = os.path.dirname(current_file)

    #再返回上一级文件路径 D:\Desktop\py\AI大模型RAG和智能体开发_Agent项目
    project_dir = os.path.dirname(current_dir)

    return project_dir

def get_abs_path(relative_path: str) -> str:
    '''
    传递相对路径，得到绝对路径
    :param relative_path: 相对路径
    :return: 绝对路径
    '''
    project_root = get_project_root()
    return os.path.join(project_root, relative_path)

if __name__ == '__main__':
    get_project_root()