import yaml
from utils.path_tool import get_abs_path

class ConfigHandler(object):
    @staticmethod
    def lod_rag_config(config_path: str=get_abs_path("config/rag.yaml"),encoding="utf-8"):
        with open(config_path,"r",encoding=encoding) as f:
            return yaml.load(f.read(),Loader=yaml.FullLoader)

    @staticmethod
    def load_chroma_config(config_path: str = get_abs_path("config/chroma.yaml"), encoding="utf-8"):
        with open(config_path, "r", encoding=encoding) as f:
            return yaml.load(f.read(), Loader=yaml.FullLoader)

    @staticmethod
    def load_prompts_config(config_path: str = get_abs_path("config/prompts.yaml"), encoding="utf-8"):
        with open(config_path, "r", encoding=encoding) as f:
            return yaml.load(f.read(), Loader=yaml.FullLoader)

    @staticmethod
    def load_agent_config(config_path: str = get_abs_path("config/agent.yaml"), encoding="utf-8"):
        with open(config_path, "r", encoding=encoding) as f:
            return yaml.load(f.read(), Loader=yaml.FullLoader)

rag_conf = ConfigHandler.lod_rag_config()
chroma_conf = ConfigHandler.load_chroma_config()
prompts_conf = ConfigHandler.load_prompts_config()
agent_conf = ConfigHandler.load_agent_config()