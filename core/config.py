"""
YAML 配置加载模块

提供统一的配置加载入口，兼容旧版 utils.config_handler 的导入方式。
"""

import yaml
from core.path import get_abs_path


def load_rag_config(config_path: str = None, encoding="utf-8"):
    if config_path is None:
        config_path = get_abs_path("config/rag.yaml")
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)


def load_chroma_config(config_path: str = None, encoding="utf-8"):
    if config_path is None:
        config_path = get_abs_path("config/chroma.yaml")
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)


def load_prompts_config(config_path: str = None, encoding="utf-8"):
    if config_path is None:
        config_path = get_abs_path("config/prompts.yaml")
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)


def load_agent_config(config_path: str = None, encoding="utf-8"):
    if config_path is None:
        config_path = get_abs_path("config/agent.yaml")
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f.read(), Loader=yaml.FullLoader)


def load_prompt(prompt_name: str) -> str:
    """从 prompts.yaml 配置加载提示词模板内容

    支持名称映射: "rag" → "rag_summarize", "main" → "main", "report" → "report"
    """
    prompts_cfg = load_prompts_config()

    # 名称映射表（兼容 prompts.yaml 现有 key 格式）
    name_map = {
        "rag": "rag_summarize",
        "main": "main",
        "report": "report",
    }
    resolved = name_map.get(prompt_name, prompt_name)
    path_key = f"{resolved}_prompt_path"

    if path_key not in prompts_cfg:
        raise ValueError(f"Unknown prompt: {prompt_name} (looked for {path_key})")
    prompt_path = get_abs_path(prompts_cfg[path_key])
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


# 模块级单例（向下兼容）
rag_conf = load_rag_config()
chroma_conf = load_chroma_config()
prompts_conf = load_prompts_config()
agent_conf = load_agent_config()
