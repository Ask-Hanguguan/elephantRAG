"""
RAG 策略基准测试

对比不同检索策略（Dense / BM25 / RRF Fusion）的检索效果和性能。
支持预定义测试集和手动查询，输出格式化对比报告 + 策略重叠度矩阵。

策略说明:
  strategy         | 检索方式            | 段落合并 | 说明
  -----------------|---------------------|----------|-------------------------------
  dense_only       | 仅稠密向量检索      | 是       | 纯语义相似度
  bm25_only        | 仅稀疏检索 (BM25)   | 是       | 纯关键词匹配
  rrf_fusion       | BM25 + Dense → RRF  | 是       | 默认融合策略
  fusion_no_segment| BM25 + Dense → RRF  | 否       | 融合但不合并相邻段落

用法:
  python rag/benchmark.py                           # 运行全部策略
  python rag/benchmark.py --strategies dense_only bm25_only   # 指定策略
  python rag/benchmark.py --query "你的问题"                  # 手动单条查询
  python rag/benchmark.py --strategies rrf_fusion --top-k 10  # 自定义 Top-K
  python rag/benchmark.py --no-report              # 仅输出聚合表，不打印详细对比
"""

import os
import re
import time
import json
import yaml
import argparse
from typing import Optional
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, field, asdict
from itertools import combinations

from langchain_core.documents import Document
from model.factory import embed_model
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


# ============================================================================
# 策略定义
# ============================================================================

STRATEGY_DEFS = {
    "dense_only": {
        "name": "Dense Only",
        "desc": "仅稠密向量检索（语义相似度）",
        "icon": "🔍",
    },
    "bm25_only": {
        "name": "BM25 Only",
        "desc": "仅稀疏检索（关键词匹配）",
        "icon": "📖",
    },
    "rrf_fusion": {
        "name": "RRF Fusion",
        "desc": "BM25 + Dense → RRF 融合 + 段落合并（默认）",
        "icon": "⚡",
    },
    "fusion_no_segment": {
        "name": "Fusion (no seg)",
        "desc": "RRF 融合，跳过相邻段落合并",
        "icon": "🔗",
    },
}


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class QueryResult:
    """单条查询的单个策略结果"""
    strategy: str
    query: str
    doc_count: int = 0
    latency_ms: float = 0.0
    source_count: int = 0
    source_files: set = field(default_factory=set)
    total_chars: int = 0
    merged_segments: int = 0
    has_merge_info: bool = False
    chunk_ids: list = field(default_factory=list)
    previews: list = field(default_factory=list)      # Top-K 内容预览
    merge_tags: list = field(default_factory=list)     # 合并标记
    # 精确率 / 召回率（基于 expected_sources）
    precision: float = 0.0
    recall: float = 0.0
    has_expected: bool = False

    @property
    def avg_chars_per_doc(self) -> float:
        return round(self.total_chars / self.doc_count, 1) if self.doc_count else 0.0


@dataclass
class BenchmarkReport:
    """完整基准报告"""
    timestamp: str = ""
    total_queries: int = 0
    total_strategies: int = 0
    strategies_run: list = field(default_factory=list)
    results: list = field(default_factory=list)        # list[QueryResult]


# ============================================================================
# 主测试类
# ============================================================================

class RAGBenchmark:
    """RAG 策略基准测试引擎"""

    def __init__(self, top_k: int = 5, strategies: Optional[list] = None):
        """
        :param top_k: 检索返回的 Top-K 文档数
        :param strategies: 要测试的策略列表，默认全部
        """
        self.top_k = top_k
        self.strategies = strategies or list(STRATEGY_DEFS.keys())

        # 校验策略名
        for s in self.strategies:
            if s not in STRATEGY_DEFS:
                raise ValueError(f"未知策略: {s}，可选: {list(STRATEGY_DEFS.keys())}")

        # 延迟初始化各组件（首次调用检索方法时构建）
        self._collection = None
        self._bm25 = None
        self._fusion = None
        self._segmenter = None
        self._initialized = False

    # ------------------------------------------------------------------
    # 服务初始化
    # ------------------------------------------------------------------

    def _ensure_services(self):
        """确保检索组件已初始化（仅一次）"""
        if self._initialized:
            return

        from rag.vector_store import VectorStoreService
        from rag.bm25_index import BM25SparseIndex
        from rag.fusion_retriever import FusionRetriever
        from rag.segment_extractor import SegmentExtractor

        vs_svc = VectorStoreService()
        self._collection = vs_svc.vector_store._collection
        self._segmenter = SegmentExtractor()

        # BM25 索引
        self._bm25 = BM25SparseIndex(vs_svc.vector_store)

        # 融合检索器
        fusion_conf = chroma_conf.get('fusion', {})
        self._fusion = FusionRetriever(
            vector_store=vs_svc.vector_store,
            bm25_index=self._bm25,
            embed_model=embed_model,
            k=self.top_k,
            rrf_k=fusion_conf.get('rrf_k', 60),
            dense_top_k=fusion_conf.get('dense_top_k', 10),
            bm25_top_k=fusion_conf.get('bm25_top_k', 10),
        )

        # 获取 ChromaDB 总 chunk 数作为环境信息
        try:
            self._total_chunks = len(
                self._collection.get(include=[], limit=0)['ids']
            )
        except Exception:
            self._total_chunks = 0

        self._initialized = True

        logger.info(
            f"[Benchmark] 初始化完成 — ChromaDB 共 {self._total_chunks} 个 chunk"
        )

    # ------------------------------------------------------------------
    # 各策略检索方法
    # ------------------------------------------------------------------

    def _dense_search(self, query: str) -> tuple[list[Document], list[str]]:
        """纯稠密向量检索

        :return: (documents, chunk_ids)
        """
        query_embedding = embed_model.embed_query(query)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=self.top_k,
            include=['documents', 'metadatas'],
        )

        docs, ids = [], []
        for i in range(len(results['ids'][0])):
            cid = results['ids'][0][i]
            ids.append(cid)
            docs.append(Document(
                page_content=results['documents'][0][i],
                metadata=results['metadatas'][0][i],
            ))

        return docs, ids

    def _bm25_search(self, query: str) -> tuple[list[Document], list[str]]:
        """纯 BM25 稀疏检索"""
        scored = self._bm25.search(query, k=self.top_k)
        chunk_ids = [cid for cid, _ in scored]
        if not chunk_ids:
            return [], []

        data = self._collection.get(
            ids=chunk_ids,
            include=['documents', 'metadatas'],
        )

        id_map = {cid: i for i, cid in enumerate(data.get('ids', []))}
        docs = []
        for cid in chunk_ids:
            if cid in id_map:
                idx = id_map[cid]
                docs.append(Document(
                    page_content=data['documents'][idx],
                    metadata=data['metadatas'][idx],
                ))

        return docs, chunk_ids

    def _fusion_search(self, query: str) -> tuple[list[Document], list[str]]:
        """RRF 融合检索"""
        docs = self._fusion.retrieve(query)
        chunk_ids = [d.metadata.get('_id', '') for d in docs]
        return docs, chunk_ids

    # ------------------------------------------------------------------
    # 相关性判别（用于精确率/召回率计算）
    # ------------------------------------------------------------------

    @staticmethod
    def _is_relevant(source_path: str, expected_keywords: list[str]) -> bool:
        """判断文档来源是否匹配任一预期关键词

        匹配规则：expected_keywords 中的任一关键词出现在 source_path 中即视为相关。
        例如 expected_keywords=["频域滤波"] 匹配 "4 频域滤波.pdf"。

        :param source_path: 文档的 source 元数据（文件绝对路径）
        :param expected_keywords: 预期来源关键词列表
        :return: True 如果匹配
        """
        if not expected_keywords:
            return False
        source_lower = source_path.lower()
        return any(kw.lower() in source_lower for kw in expected_keywords)

    @staticmethod
    def _calc_precision_recall(
        source_files: set,
        expected_keywords: list[str],
    ) -> tuple[float, float]:
        """计算精确率（Precision）和召回率（Recall）

        Precision = 检索结果中相关文档数 ÷ 总检索文档数
        Recall    = 命中的预期来源数 ÷ 总预期来源数

        命中判断：每个预期来源关键词只要被至少一个检索到的文档匹配即算命中。

        :param source_files: 检索结果涉及的源文件名集合
        :param expected_keywords: 预期来源关键词列表
        :return: (precision, recall)
        """
        if not expected_keywords:
            return 0.0, 0.0

        # 精确率：文档级别
        total_docs_in_result = len(source_files) if source_files else 1
        relevant_docs = sum(
            1 for sf in source_files
            if RAGBenchmark._is_relevant(sf, expected_keywords)
        )
        precision = relevant_docs / total_docs_in_result if total_docs_in_result else 0.0

        # 召回率：预期来源级别（每个关键词是否被至少一个检索文档覆盖）
        matched_expected = sum(
            1 for kw in expected_keywords
            if any(RAGBenchmark._is_relevant(sf, [kw]) for sf in source_files)
        )
        recall = matched_expected / len(expected_keywords) if expected_keywords else 0.0

        return round(precision, 3), round(recall, 3)

    def run_single(self, strategy: str, query: str,
                   expected_sources: Optional[list[str]] = None) -> QueryResult:
        """运行单个策略的单条查询

        :param strategy: 策略名
        :param query: 查询文本
        :param expected_sources: 预期来源关键词列表（用于精确率/召回率计算）
        :return: QueryResult
        """
        self._ensure_services()
        t0 = time.perf_counter()

        # 执行检索
        if strategy == "dense_only":
            docs, chunk_ids = self._dense_search(query)
            docs = self._segmenter.extract_segments(docs)
        elif strategy == "bm25_only":
            docs, chunk_ids = self._bm25_search(query)
            docs = self._segmenter.extract_segments(docs)
        elif strategy == "rrf_fusion":
            docs, chunk_ids = self._fusion_search(query)
            docs = self._segmenter.extract_segments(docs)
        elif strategy == "fusion_no_segment":
            docs, chunk_ids = self._fusion_search(query)
        else:
            raise ValueError(f"未知策略: {strategy}")

        latency_ms = (time.perf_counter() - t0) * 1000

        # 提取指标
        return self._build_result(strategy, query, docs, chunk_ids, latency_ms,
                                  expected_sources)

    def _build_result(self, strategy: str, query: str,
                      docs: list[Document], chunk_ids: list[str],
                      latency_ms: float,
                      expected_sources: Optional[list[str]] = None) -> QueryResult:
        """从检索结果提取指标"""
        source_files = set()
        total_chars = 0
        merged_count = 0
        has_merge = False
        previews = []
        merge_tags = []
        source_paths = set()  # 完整路径，用于相关性判别

        for d in docs:
            src = d.metadata.get('source', 'unknown')
            filename = os.path.basename(src) if src != 'unknown' else 'unknown'
            source_files.add(filename)
            source_paths.add(src)
            total_chars += len(d.page_content)

            mf = d.metadata.get('merged_from', 1)
            if mf > 1:
                merged_count += 1
                has_merge = True
                cr = d.metadata.get('chunk_range', '?')
                merge_tags.append(f"[合并{mf}段-{cr}]")
            else:
                merge_tags.append("")

            # 内容预览（截取前 N 字符 + 去换行）
            preview = d.page_content.replace('\n', ' ').strip()
            if len(preview) > 120:
                preview = preview[:120] + "..."
            previews.append(preview)

        # 精确率/召回率
        expected = expected_sources or []
        precision, recall = self._calc_precision_recall(source_paths, expected)

        return QueryResult(
            strategy=strategy,
            query=query,
            doc_count=len(docs),
            latency_ms=round(latency_ms, 2),
            source_count=len(source_files),
            source_files=source_files,
            total_chars=total_chars,
            merged_segments=merged_count,
            has_merge_info=has_merge,
            chunk_ids=chunk_ids,
            previews=previews,
            merge_tags=merge_tags,
            precision=precision,
            recall=recall,
            has_expected=bool(expected),
        )

    # ------------------------------------------------------------------
    # 批量运行
    # ------------------------------------------------------------------

    def run_queries(self, query_entries: list[dict]) -> BenchmarkReport:
        """对多个查询运行所有策略

        :param query_entries: [{'query': str, 'expected_sources': list[str]}, ...]
        :return: BenchmarkReport
        """
        self._ensure_services()
        all_results: list[QueryResult] = []

        total = len(query_entries) * len(self.strategies)
        done = 0

        logger.info(
            f"[Benchmark] 开始测试 — {len(query_entries)} 条查询 × "
            f"{len(self.strategies)} 种策略 = {total} 轮"
        )
        print()

        for q_idx, entry in enumerate(query_entries, 1):
            query_text = entry["query"]
            expected = entry.get("expected_sources", [])

            for s_idx, strategy in enumerate(self.strategies, 1):
                display_name = STRATEGY_DEFS[strategy]["name"]
                icon = STRATEGY_DEFS[strategy]["icon"]
                done += 1

                print(
                    f"  [{done}/{total}] {icon} "
                    f"查询{q_idx} × {display_name} ... ",
                    end="", flush=True,
                )

                result = self.run_single(strategy, query_text, expected)
                all_results.append(result)

                print(f"{result.latency_ms}ms | {result.doc_count} 文档", flush=True)

        print()
        logger.info("[Benchmark] 全部测试完成\n")

        report = BenchmarkReport(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_queries=len(query_entries),
            total_strategies=len(self.strategies),
            strategies_run=list(self.strategies),
            results=all_results,
        )

        return report

    # ------------------------------------------------------------------
    # 手动单条查询快速测试
    # ------------------------------------------------------------------

    def quick_test(self, query: str):
        """手动输入一条查询，运行所有策略并打印对比"""
        self._ensure_services()

        print(f"\n{'='*60}")
        print(f"  查询: \"{query}\"")
        print(f"{'='*60}\n")

        for strategy in self.strategies:
            info = STRATEGY_DEFS[strategy]
            result = self.run_single(strategy, query)

            print(f"  {info['icon']} {info['name']} — {info['desc']}")
            print(f"  {'─'*50}")
            print(f"    耗时: {result.latency_ms:>8.2f} ms")
            print(f"    文档数: {result.doc_count}  |  "
                  f"来源文件: {result.source_count}  |  "
                  f"内容总长: {result.total_chars} 字符")
            if result.has_merge_info:
                print(f"    合并段落: {result.merged_segments} 个")
            print(f"    来源: {', '.join(sorted(result.source_files))}")
            print()

            for i, (preview, tag) in enumerate(zip(result.previews, result.merge_tags), 1):
                tag_str = f" {tag}" if tag else ""
                print(f"      [{i}]{tag_str} {preview}")
            print()


# ============================================================================
# 报告生成器
# ============================================================================

class ReportPrinter:
    """格式化基准报告输出"""

    # 表格分隔符
    H_LINE = "─"
    V_LINE = "│"
    TL = "┌"
    TR = "┐"
    BL = "└"
    BR = "┘"
    TM = "┬"
    BM = "┴"
    LM = "├"
    RM = "┤"
    CROSS = "┼"

    @classmethod
    def _divider(cls, widths: list[int], left=LM, mid=CROSS, right=RM) -> str:
        parts = [left]
        for w in widths:
            parts.append(cls.H_LINE * (w + 2))
            parts.append(mid)
        parts[-1] = right
        return "".join(parts)

    @classmethod
    def _row(cls, cells: list[str], widths: list[int]) -> str:
        parts = [cls.V_LINE]
        for cell, w in zip(cells, widths):
            # 中文占位自适应
            display_w = sum(2 if ord(c) > 127 else 1 for c in str(cell))
            pad = w - display_w
            parts.append(f" {cell}{' ' * pad} ")
            parts.append(cls.V_LINE)
        return "".join(parts)

    @classmethod
    def print_header(cls, text: str):
        """打印分段标题"""
        print(f"\n  {'─' * 50}")
        print(f"  {text}")
        print(f"  {'─' * 50}\n")

    @classmethod
    def print_environment(cls, total_chunks: int, query_entries: list, strategies: list):
        """打印测试环境信息"""
        print()
        print(f"  {'=' * 60}")
        print(f"    RAG 策略基准测试报告")
        print(f"  {'=' * 60}")
        print()
        print(f"    测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"    ChromaDB: {total_chunks} 个 chunk")
        print(f"    测试查询: {len(query_entries)} 条")
        print(f"    测试策略: {len(strategies)} 种 — ", end="")
        print(", ".join(STRATEGY_DEFS[s]["name"] for s in strategies))
        print()

        # 查询列表
        print(f"    {'─' * 50}")
        print(f"    查询列表:")
        for i, entry in enumerate(query_entries, 1):
            query_text = entry["query"]
            expected = entry.get("expected_sources", [])
            tag = f"  [{', '.join(expected)}]" if expected else ""
            print(f"      {i:2d}. \"{query_text}\"{tag}")
        print()

    @classmethod
    def print_query_comparison(cls, query: str, results: list[QueryResult],
                               top_k: int = 3, max_preview: int = 150):
        """打印单条查询的策略对比"""
        print(f"  {'▸'} 查询: \"{query}\"")
        print()

        for r in results:
            info = STRATEGY_DEFS[r.strategy]
            print(f"    {info['icon']} {info['name']}  "
                  f"({r.latency_ms}ms, {r.doc_count}文档, {r.source_count}来源)")

            if r.has_expected:
                print(f"      精确率: {r.precision:.1%}  |  召回率: {r.recall:.1%}")

            if r.has_merge_info:
                print(f"      合并 {r.merged_segments} 个连续段落")

            for i, (preview, tag) in enumerate(zip(r.previews[:top_k], r.merge_tags[:top_k]), 1):
                content = preview
                if max_preview and len(content) > max_preview:
                    content = content[:max_preview] + "..."
                tag_str = f" {tag}" if tag else ""
                print(f"      [{i}]{tag_str} {content}")

            if r.doc_count > top_k:
                print(f"      ... 还有 {r.doc_count - top_k} 个结果")
            print()
        print()

    @classmethod
    def print_aggregate_table(cls, results: list[QueryResult]):
        """打印聚合统计表"""
        # 按策略分组统计
        stats = defaultdict(lambda: {
            'latencies': [], 'doc_counts': [], 'source_counts': [],
            'total_chars': [], 'has_merge': False,
        })

        query_map = defaultdict(list)
        for r in results:
            query_map[r.strategy].append(r)

        rows = []
        for strategy in STRATEGY_DEFS:
            if strategy not in query_map:
                continue
            group = query_map[strategy]
            latencies = [r.latency_ms for r in group]
            doc_counts = [r.doc_count for r in group]
            src_counts = [r.source_count for r in group]
            chars = [r.total_chars for r in group]
            has_merge = any(r.has_merge_info for r in group)
            # 精确率/召回率（只统计有预期来源的查询）
            precisions = [r.precision for r in group if r.has_expected]
            recalls = [r.recall for r in group if r.has_expected]
            avg_precision = round(sum(precisions) / len(precisions), 3) if precisions else None
            avg_recall = round(sum(recalls) / len(recalls), 3) if recalls else None

            rows.append({
                'name': STRATEGY_DEFS[strategy]["name"],
                'icon': STRATEGY_DEFS[strategy]["icon"],
                'avg_latency': round(sum(latencies) / len(latencies), 2),
                'min_latency': round(min(latencies), 2),
                'max_latency': round(max(latencies), 2),
                'avg_docs': round(sum(doc_counts) / len(doc_counts), 1),
                'avg_sources': round(sum(src_counts) / len(src_counts), 1),
                'avg_chars': round(sum(chars) / len(chars), 1),
                'has_merge': has_merge,
                'avg_precision': avg_precision,
                'avg_recall': avg_recall,
            })

        if not rows:
            return

        cls.print_header("聚合统计")

        headers = ["策略", "平均耗时", "最快", "最慢", "平均文档", "平均来源", "平均字符", "合并", "精确率", "召回率"]
        widths = [18, 10, 8, 8, 10, 10, 10, 6, 8, 8]

        print(f"    {cls.TL}{cls.H_LINE * (sum(widths) + len(widths) * 3 - 1)}{cls.TR}")
        print(f"    {cls._row(headers, widths)}")
        print(f"    {cls._divider(widths)}")

        for row in rows:
            cells = [
                f"{row['icon']} {row['name']}",
                f"{row['avg_latency']}ms",
                f"{row['min_latency']}ms",
                f"{row['max_latency']}ms",
                str(row['avg_docs']),
                str(row['avg_sources']),
                str(row['avg_chars']),
                "✅" if row['has_merge'] else "—",
                f"{row['avg_precision']:.0%}" if row['avg_precision'] is not None else "—",
                f"{row['avg_recall']:.0%}" if row['avg_recall'] is not None else "—",
            ]
            print(f"    {cls._row(cells, widths)}")

        print(f"    {cls.BL}{cls.H_LINE * (sum(widths) + len(widths) * 3 - 1)}{cls.BR}")
        print()

    @classmethod
    def print_overlap_matrix(cls, results: list[QueryResult]):
        """打印策略结果重叠度（Jaccard 系数）矩阵"""
        # 按策略收集所有查询的 chunk_id 集合
        strategy_sets = defaultdict(set)
        for r in results:
            strategy_sets[r.strategy].update(r.chunk_ids)

        strategies = [s for s in STRATEGY_DEFS if s in strategy_sets]
        if len(strategies) < 2:
            return

        cls.print_header("策略重叠度 (Jaccard 系数)")

        # 计算矩阵
        n = len(strategies)
        matrix = [[0.0] * n for _ in range(n)]
        for i, si in enumerate(strategies):
            for j, sj in enumerate(strategies):
                if i == j:
                    matrix[i][j] = 1.0
                else:
                    set_i = strategy_sets[si]
                    set_j = strategy_sets[sj]
                    if not set_i or not set_j:
                        matrix[i][j] = 0.0
                    else:
                        intersection = len(set_i & set_j)
                        union = len(set_i | set_j)
                        matrix[i][j] = round(intersection / union, 3) if union else 0.0

        # 表头
        headers = [""] + [STRATEGY_DEFS[s]["name"] for s in strategies]
        widths = [18] + [12] * n

        print(f"    {cls.TL}{cls.H_LINE * (sum(widths) + len(widths) * 3 - 1)}{cls.TR}")
        print(f"    {cls._row(headers, widths)}")
        print(f"    {cls._divider(widths)}")

        for i, si in enumerate(strategies):
            cells = [STRATEGY_DEFS[si]["name"]]
            for j in range(n):
                cells.append(f"{matrix[i][j]:.3f}")
            print(f"    {cls._row(cells, widths)}")

        print(f"    {cls.BL}{cls.H_LINE * (sum(widths) + len(widths) * 3 - 1)}{cls.BR}")
        print()

        # 解读
        print(f"    说明: Jaccard = |A∩B| / |A∪B|，值越大表示两策略召回结果越相似\n")

    @classmethod
    def print_latency_ranking(cls, results: list[QueryResult]):
        """打印延迟排名"""
        # 按策略聚合
        strat_lat = defaultdict(list)
        for r in results:
            strat_lat[r.strategy].append(r.latency_ms)

        if not strat_lat:
            return

        avg_lat = {s: round(sum(v) / len(v), 2) for s, v in strat_lat.items()}
        sorted_strats = sorted(avg_lat.items(), key=lambda x: x[1])

        cls.print_header("平均耗时排名")
        for rank, (strategy, lat) in enumerate(sorted_strats, 1):
            icon = STRATEGY_DEFS[strategy]["icon"]
            name = STRATEGY_DEFS[strategy]["name"]
            bar_len = max(1, int(lat / max(v for _, v in sorted_strats) * 20))
            bar = "█" * bar_len
            print(f"    {rank}. {icon} {name}: {lat:>8.2f}ms  {bar}")
        print()

    @classmethod
    def print_report(cls, report: BenchmarkReport, query_entries: list[dict],
                     top_k: int = 3, max_preview: int = 150,
                     full_report: bool = True):
        """打印完整报告

        :param report: BenchmarkReport
        :param query_entries: [{query: str, expected_sources: [str]}, ...]
        :param top_k: 每策略显示 Top-K 预览
        :param max_preview: 预览截断字符数
        :param full_report: True=详细对比, False=仅聚合
        """
        # 提取纯查询文本列表
        query_texts = [e["query"] for e in query_entries]

        # 按查询分组
        query_groups = defaultdict(list)
        for r in report.results:
            query_groups[r.query].append(r)

        # 环境信息
        print()
        print(f"  {'=' * 60}")
        print(f"    RAG 策略基准测试报告")
        print(f"  {'=' * 60}")
        print()
        print(f"    测试时间: {report.timestamp}")
        print(f"    测试查询: {report.total_queries} 条")
        print(f"    测试策略: {report.total_strategies} 种 — ", end="")
        print(", ".join(STRATEGY_DEFS[s]["name"] for s in report.strategies_run))
        print()

        if full_report:
            print(f"    {'─' * 50}")
            print(f"    查询列表:")
            for i, entry in enumerate(query_entries, 1):
                q_text = entry["query"]
                expected = entry.get("expected_sources", [])
                tag = f"  [{', '.join(expected)}]" if expected else ""
                print(f"      {i:2d}. \"{q_text}\"{tag}")
            print()

            # 逐条查询详细对比
            cls.print_header("逐条查询对比")
            for query in query_texts:
                q_results = query_groups.get(query, [])
                if q_results:
                    cls.print_query_comparison(query, q_results, top_k, max_preview)

        # 聚合统计
        cls.print_aggregate_table(report.results)

        # 延迟排名
        cls.print_latency_ranking(report.results)

        # 重叠度矩阵
        cls.print_overlap_matrix(report.results)


# ============================================================================
# 报告持久化
# ============================================================================

def save_report_to_file(report: BenchmarkReport, query_entries: list[dict],
                        output_dir: str = "logs") -> str:
    """将报告保存到文件

    :param report: BenchmarkReport
    :param query_entries: [{query: str, expected_sources: [str]}, ...]
    :param output_dir: 输出目录
    :return: 文件路径
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"benchmark_report_{timestamp}.txt")

    # 重定向 stdout 到文件
    import sys
    from io import StringIO

    old_stdout = sys.stdout
    sys.stdout = StringIO()

    ReportPrinter.print_report(report, query_entries, full_report=True)

    output = sys.stdout.getvalue()
    sys.stdout = old_stdout

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(output)

    return filepath


def save_json_results(report: BenchmarkReport, output_dir: str = "logs") -> str:
    """保存 JSON 格式结果

    :param report: BenchmarkReport
    :param output_dir: 输出目录
    :return: 文件路径
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"benchmark_results_{timestamp}.json")

    # 构建可序列化的数据结构
    data = {
        "timestamp": report.timestamp,
        "total_queries": report.total_queries,
        "total_strategies": report.total_strategies,
        "strategies": report.strategies_run,
        "results": [],
    }

    for r in report.results:
        data["results"].append({
            "strategy": r.strategy,
            "query": r.query,
            "doc_count": r.doc_count,
            "latency_ms": r.latency_ms,
            "source_count": r.source_count,
            "source_files": sorted(r.source_files),
            "total_chars": r.total_chars,
            "merged_segments": r.merged_segments,
            "precision": r.precision,
            "recall": r.recall,
            "has_expected": r.has_expected,
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filepath


# ============================================================================
# 测试查询加载
# ============================================================================

def load_test_queries(path: str = None) -> list[dict]:
    """从 YAML 文件加载测试查询

    :param path: YAML 文件路径
    :return: [{'query': str, 'expected_sources': list[str]}, ...]
    """
    if path is None:
        path = get_abs_path("config/benchmark_queries.yaml")

    if not os.path.exists(path):
        logger.warning(f"[Benchmark] 测试查询文件不存在: {path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entries = []
    for entry in data.get("queries", []):
        q_text = entry.get("query", "").strip()
        if q_text:
            entries.append({
                "query": q_text,
                "expected_sources": entry.get("expected_sources", []),
            })

    logger.info(f"[Benchmark] 加载 {len(entries)} 条测试查询: {path}")
    return entries


# ============================================================================
# CLI
# ============================================================================

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="RAG 策略基准测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python rag/benchmark.py                                 # 全部策略全部查询
  python rag/benchmark.py --strategies dense_only bm25_only  # 指定策略
  python rag/benchmark.py --query "图像分割有哪些方法"       # 手动单条
  python rag/benchmark.py --strategies rrf_fusion --top-k 10 # 自定义 Top-K
  python rag/benchmark.py --no-report                        # 仅聚合不详细
        """,
    )

    parser.add_argument(
        "--strategies", "-s",
        nargs="+",
        default=None,
        choices=list(STRATEGY_DEFS.keys()),
        help=f"要测试的策略，可选: {', '.join(STRATEGY_DEFS.keys())}（默认全部）",
    )
    parser.add_argument(
        "--top-k", "-k",
        type=int,
        default=5,
        help="检索返回文档数（默认 5）",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="手动输入单条查询（跳过测试集）",
    )
    parser.add_argument(
        "--queries", "-f",
        type=str,
        default=None,
        help="指定测试查询 YAML 文件路径",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="仅输出聚合统计，不打印详细逐条对比",
    )
    parser.add_argument(
        "--show-top-k",
        type=int,
        default=3,
        help="报告中每策略显示的预览条数（默认 3）",
    )
    parser.add_argument(
        "--preview-len",
        type=int,
        default=150,
        help="预览截断字符数（默认 150）",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="同时保存 JSON 格式结果到 logs/",
    )

    return parser.parse_args()


def main():
    """主入口"""
    args = parse_args()

    # 初始化测试引擎
    benchmark = RAGBenchmark(
        top_k=args.top_k,
        strategies=args.strategies,
    )

    # 获取总 chunk 数用于环境显示
    benchmark._ensure_services()
    total_chunks = benchmark._total_chunks

    # 手动单条查询模式
    if args.query:
        benchmark.quick_test(args.query)
        return

    # 批量测试模式
    queries = load_test_queries(args.queries)
    if not queries:
        logger.error("[Benchmark] 无测试查询，退出")
        return

    # 打印环境信息
    ReportPrinter.print_environment(total_chunks, queries, benchmark.strategies)

    # 执行测试
    report = benchmark.run_queries(queries)

    # 打印报告
    ReportPrinter.print_report(
        report=report,
        queries=queries,
        top_k=args.show_top_k,
        max_preview=args.preview_len,
        full_report=not args.no_report,
    )

    # 保存报告到文件
    report_path = save_report_to_file(report, queries)
    print(f"  📄 报告已保存: {report_path}")

    if args.save_json:
        json_path = save_json_results(report)
        print(f"  📊 JSON 已保存: {json_path}")

    print(f"\n  {'=' * 60}\n")


if __name__ == "__main__":
    main()
