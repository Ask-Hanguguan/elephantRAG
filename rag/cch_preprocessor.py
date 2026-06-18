"""
CCH（Contextual Chunk Headers）文档预处理器
负责：
  - 从文件名/Markdown标题提取文档标题
  - 通过LLM生成文档摘要
  - 解析Markdown章节/子标题结构
  - 为每个chunk构建上下文头部信息
"""

import os
import re
from typing import Optional
from langchain_core.language_models import BaseChatModel
from utils.config_handler import chroma_conf
from utils.logger_handler import logger


class CCHPreprocessor(object):
    """CCH文档预处理器——为每个分块添加上下文头部（标题/摘要/章节路径）"""

    def __init__(self, llm: Optional[BaseChatModel] = None):
        """
        :param llm: LLM实例，用于生成摘要，默认延迟加载 model.factory.chat_model
        """
        self._llm = llm

    @property
    def llm(self):
        """延迟加载LLM，避免在模块导入时触发网络连接"""
        if self._llm is None:
            from model.factory import chat_model
            self._llm = chat_model
        return self._llm

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def extract_title(self, source_path: str, full_text: str) -> str:
        """从Markdown第一个H1标题提取文档标题，未找到则从文件名推导

        :param source_path: 源文件绝对路径
        :param full_text: 文档完整markdown文本
        :return: 标题字符串
        """
        # 1. 尝试匹配第一个 # 标题
        match = re.search(r'^#\s+(.+)', full_text, re.MULTILINE)
        if match:
            title = match.group(1).strip()
            if title:
                logger.debug(f"[CCH] 从H1提取标题：{title}")
                return title

        # 2. 回退：从文件名推导
        filename = os.path.basename(source_path)
        # 去掉扩展名，替换连字符/下划线为空格
        name_no_ext = os.path.splitext(filename)[0]
        title = name_no_ext.replace('_', ' ').replace('-', ' ').strip()
        logger.debug(f"[CCH] 从文件名推导标题：{title}")
        return title if title else "未命名文档"

    def generate_summary(self, full_text: str,
                         max_length: int = 200,
                         truncate_chars: int = 3000) -> str:
        """使用LLM生成文档摘要，失败时回退到文档前N字符

        :param full_text: 文档完整文本
        :param max_length: 摘要最大字符数
        :param truncate_chars: 送至LLM的截断长度（避免token超限）
        :return: 摘要字符串
        """
        # 截断超长文本
        truncated = full_text[:truncate_chars] if len(full_text) > truncate_chars else full_text

        prompt = (
            f"请用一段简洁的中文（不超过{max_length}字）总结以下文档的主要内容，"
            f"只需输出摘要文本本身，不要额外说明：\n\n{truncated}"
        )

        try:
            response = self.llm.invoke(prompt)
            # ChatTongyi 返回 AIMessage，取其 content 字段
            summary = response.content if hasattr(response, 'content') else str(response)
            summary = summary.strip()
            if summary and len(summary) > 10:
                logger.debug(f"[CCH] LLM摘要生成成功，长度={len(summary)}")
                return summary[:max_length]  # 硬截断
        except Exception as exc:
            logger.warning(f"[CCH] LLM摘要生成失败，使用回退策略：{str(exc)}")

        # 回退：“无摘要”
        fallback = "无摘要"
        logger.debug(f"[CCH] 使用回退摘要，长度={len(fallback)}")
        return fallback

    def parse_section_tree(self, full_text: str) -> list:
        """解析Markdown标题（# ~ ######），构建章节路径映射

        返回列表，每项为 (字符偏移量, 章节路径字符串)，
        按偏移量升序排列，用于后续按chunk位置查询所属章节。

        :param full_text: 文档完整markdown文本
        :return: [(char_offset, section_path), ...]
        """
        section_map: list = []
        # 栈元素: (heading_level, heading_text)
        stack: list = []

        # 逐行扫描
        for match in re.finditer(r'^(#{1,6})\s+(.+)', full_text, re.MULTILINE):
            heading_line = match.group(0)
            hashes = match.group(1)
            heading_text = match.group(2).strip()
            level = len(hashes)
            offset = match.start()

            # 维护栈：弹出所有 >= 当前level 的标题
            while stack and stack[-1][0] >= level:
                stack.pop()

            # 压入当前标题
            stack.append((level, heading_text))

            # 构建章节路径：栈中所有标题用 " > " 连接
            section_path = " > ".join(item[1] for item in stack)
            section_map.append((offset, section_path))

        # 如果文档无任何标题，添加一个默认"正文"入口
        if not section_map:
            section_map.append((0, "正文"))

        return section_map

    def determine_section(self, chunk_text: str, full_text: str,
                          section_map: list) -> str:
        """根据chunk内容在原文中的位置，确定所属章节路径

        取chunk前40个非空白字符作为搜索key，在原文中定位偏移量，
        然后在section_map中二分查找最近的章节节点。

        :param chunk_text: 当前chunk的文本内容
        :param full_text: 文档完整文本
        :param section_map: parse_section_tree() 返回的章节映射
        :return: 章节路径字符串
        """
        # 取chunk前N个字符用于定位
        search_key = chunk_text.strip()[:40]
        if not search_key or len(search_key) < 10:
            # chunk太短，使用默认路径
            return section_map[0][1] if section_map else "正文"

        pos = full_text.find(search_key)
        if pos == -1:
            # 无法定位（如chunk内容经过变换），使用默认路径
            logger.debug(f"[CCH] 无法定位chunk在原文中的位置，使用默认章节")
            return section_map[0][1] if section_map else "正文"

        # 二分查找：找到 offset <= pos 的最后一个章节节点
        target_section = section_map[0][1]  # 默认第一个
        for offset, path in section_map:
            if offset <= pos:
                target_section = path
            else:
                break

        return target_section

    def build_cch_header(self, title: str, summary: str,
                         section_path: str) -> str:
        """构建CCH（Contextual Chunk Header）头部文本

        格式：
        【文档标题】：{title}
        【文档摘要】：{summary}
        【章节路径】：{section_path}
        ---

        :param title: 文档标题
        :param summary: 文档摘要
        :param section_path: 章节路径
        :return: CCH头部字符串（不含原始chunk内容）
        """
        header = (
            f"【文档标题】：{title}\n"
            f"【文档摘要】：{summary}\n"
            f"【章节路径】：{section_path}\n"
            f"---\n"
        )
        return header

    def preprocess(self, source_path: str, full_text: str) -> dict:
        """一站式预处理：提取标题、摘要、章节映射

        :param source_path: 源文件路径
        :param full_text: 文档完整文本
        :return: {'title': str, 'summary': str, 'section_map': list}
        """
        cch_conf = chroma_conf.get('cch', {})

        title = self.extract_title(source_path, full_text)
        summary = self.generate_summary(
            full_text,
            max_length=cch_conf.get('summary_max_length', 200),
            truncate_chars=cch_conf.get('summary_truncate_chars', 3000),
        )
        section_map = self.parse_section_tree(full_text)

        return {
            'title': title,
            'summary': summary,
            'section_map': section_map,
        }


if __name__ == '__main__':
    # 简单自测：用一段模拟markdown验证解析逻辑
    sample_text = """# 机器学习课程复习指南

这是文档的引言部分，介绍机器学习的基本概念。

## 第一章 监督学习概述
监督学习是机器学习的重要分支。

### 1.1 线性回归
线性回归用于预测连续值。

### 1.2 逻辑回归
逻辑回归用于二分类问题。

## 第二章 无监督学习
无监督学习不需要标注数据。

### 2.1 K-Means聚类
K-Means是一种常用的聚类算法。

### 2.2 主成分分析
PCA用于降维处理。
"""

    preprocessor = CCHPreprocessor()
    title = preprocessor.extract_title("机器学习复习指南.pdf", sample_text)
    section_map = preprocessor.parse_section_tree(sample_text)

    print(f"标题: {title}")
    print(f"\n章节映射 ({len(section_map)} 条):")
    for offset, path in section_map:
        print(f"  offset={offset:4d}  ->  {path}")

    # 模拟一个chunk定位
    chunk = "K-Means是一种常用的聚类算法。"
    section = preprocessor.determine_section(chunk, sample_text, section_map)
    print(f"\nChunk: \"{chunk}\"")
    print(f"所属章节: {section}")

    # 查看CCH头部格式
    print(f"\nCCH头部示例:")
    print(preprocessor.build_cch_header(title, "本文介绍机器学习的基本概念和监督学习方法", section))
