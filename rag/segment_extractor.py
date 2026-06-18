"""
Relevant Segment Extraction —— 相关段落提取器

将融合检索返回的 Top-K chunk 按来源文档分组，
合并相邻 chunk（chunk_index 连续）为完整段落，
消除孤立碎片，提升 LLM 上下文连贯性。

原理：
  RRF 融合后的 top-5 chunk 可能来自同一文档的相邻位置
  （如 chunk_3, chunk_4, chunk_5），直接拼接会冗余且碎片化。
  本模块将其合并为连续段落，减少重复内容，提升可读性。
"""

from langchain_core.documents import Document
from utils.config_handler import chroma_conf
from utils.logger_handler import logger


class SegmentExtractor(object):
    """相关段落提取器：合并相邻chunk为连续段落"""

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def extract_segments(self, docs: list) -> list:
        """主入口：提取并合并相关段落

        :param docs: 融合检索返回的 Document 列表（需含 chunk_index 和 source 元数据）
        :return: 合并后的 Document 列表
        """
        if not docs:
            return []

        # 1. 按 source 分组
        grouped = self._group_by_source(docs)

        # 2. 每组内合并相邻chunk
        merged: list = []
        for source, chunks in grouped.items():
            if len(chunks) == 1:
                # 单chunk不合并，直接保留
                merged.extend(chunks)
            else:
                merged.extend(self._merge_adjacent_chunks(chunks))

        logger.debug(
            f"[Segment] 输入 {len(docs)} 个chunk → "
            f"输出 {len(merged)} 个段落 "
            f"（来自 {len(grouped)} 个文档来源）"
        )

        return merged

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _group_by_source(self, docs: list) -> dict:
        """按 source 元数据分组

        :param docs: Document列表
        :return: {source_path: [Document, ...]}
        """
        groups: dict = {}
        for doc in docs:
            source = doc.metadata.get('source', '__unknown__')
            if source not in groups:
                groups[source] = []
            groups[source].append(doc)
        return groups

    def _merge_adjacent_chunks(self, chunks: list) -> list:
        """在同一个source内合并相邻chunk

        chunk_index 差值 == 1 视为相邻，合并为连续段落。
        差值 > 1 表示原文中有未召回的内容，不应跨空缺合并。

        :param chunks: 同一source的chunk列表
        :return: 合并后的Document列表
        """
        # 按 chunk_index 升序排列
        # 缺 chunk_index 的放在最后（index=-1 处理）
        sorted_chunks = sorted(
            chunks,
            key=lambda c: c.metadata.get('chunk_index', -1),
        )

        result: list = []
        current_run: list = []

        for chunk in sorted_chunks:
            chunk_idx = chunk.metadata.get('chunk_index')

            # chunk_index 缺失 → 视为独立段落，结束当前run
            if chunk_idx is None:
                if current_run:
                    result.append(self._merge_documents(current_run))
                    current_run = []
                result.append(chunk)
                continue

            if not current_run:
                current_run.append(chunk)
                continue

            prev_idx = current_run[-1].metadata.get('chunk_index', -1)

            if chunk_idx == prev_idx + 1:
                # 相邻，加入当前run
                current_run.append(chunk)
            else:
                # 不相邻，结束当前run并开始新run
                result.append(self._merge_documents(current_run))
                current_run = [chunk]

        # 处理最后一个run
        if current_run:
            result.append(self._merge_documents(current_run))

        return result

    def _merge_documents(self, doc_list: list) -> Document:
        """将多个相邻Document合并为一个

        拼接 page_content（用换行分隔），保留第一个doc的元数据，
        添加 merged_from 和 chunk_range 标记。

        :param doc_list: 要合并的Document列表
        :return: 合并后的单个Document
        """
        if len(doc_list) == 1:
            return doc_list[0]

        # 拼接内容
        merged_content = "\n".join(d.page_content for d in doc_list)

        # 复制第一个doc的元数据并添加合并标记
        merged_metadata = dict(doc_list[0].metadata)
        merged_metadata['merged_from'] = len(doc_list)

        # 记录chunk范围
        indices = [
            d.metadata.get('chunk_index')
            for d in doc_list
            if d.metadata.get('chunk_index') is not None
        ]
        if indices:
            merged_metadata['chunk_range'] = f"{min(indices)}-{max(indices)}"

        return Document(
            page_content=merged_content,
            metadata=merged_metadata,
        )


if __name__ == '__main__':
    # 自测：模拟top-5 chunk，其中3个相邻、2个来自另一文档且相邻
    extractor = SegmentExtractor()

    mock_docs = [
        Document(
            page_content="这是文档A的第3个chunk的内容。",
            metadata={'source': 'docA.pdf', 'chunk_index': 3, 'title': '文档A'},
        ),
        Document(
            page_content="这是文档A的第4个chunk的内容。",
            metadata={'source': 'docA.pdf', 'chunk_index': 4, 'title': '文档A'},
        ),
        Document(
            page_content="这是文档A的第5个chunk的内容。",
            metadata={'source': 'docA.pdf', 'chunk_index': 5, 'title': '文档A'},
        ),
        Document(
            page_content="这是文档B的第1个chunk的内容。",
            metadata={'source': 'docB.pdf', 'chunk_index': 1, 'title': '文档B'},
        ),
        Document(
            page_content="这是文档B的第2个chunk的内容。",
            metadata={'source': 'docB.pdf', 'chunk_index': 2, 'title': '文档B'},
        ),
    ]

    print(f"输入 {len(mock_docs)} 个chunk:")
    for i, d in enumerate(mock_docs):
        ci = d.metadata.get('chunk_index', '?')
        src = d.metadata.get('source', '?')
        print(f"  {i+1}. source={src}, chunk_index={ci}")

    result = extractor.extract_segments(mock_docs)

    print(f"\n输出 {len(result)} 个段落:")
    for i, d in enumerate(result):
        ci = d.metadata.get('chunk_range', d.metadata.get('chunk_index', '?'))
        mf = d.metadata.get('merged_from', 1)
        src = d.metadata.get('source', '?')
        print(f"  {i+1}. source={src}, chunk_range={ci}, merged_from={mf}")
        print(f"     内容: {d.page_content[:100]}...")
