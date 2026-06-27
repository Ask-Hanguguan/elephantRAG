"""
为整个项目提供统一路径
"""

import os


def get_project_root() -> str:
    """获取工程根目录"""
    current_file = os.path.abspath(__file__)          # core/path.py
    current_dir = os.path.dirname(current_file)        # core/
    project_dir = os.path.dirname(current_dir)         # 项目根目录
    return project_dir


def get_abs_path(relative_path: str) -> str:
    """传递相对路径，得到绝对路径"""
    return os.path.join(get_project_root(), relative_path)
