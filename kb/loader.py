"""
文档加载管线 — MD5 / 格式分发 / PDF 解析 (PyMuPDF + PaddleOCR) / 文本规范化
"""

import os
import re
import hashlib
import unicodedata
from typing import Optional

from core.logger import logger
from langchain_core.documents import Document


# ============================================================================
# MD5
# ============================================================================


def get_file_md5_hex(file_path: str) -> Optional[str]:
    """计算文件的 MD5 哈希值（流式读取，8KB 分块）

    Args:
        file_path: 文件绝对/相对路径

    Returns:
        32 位小写 MD5 十六进制字符串；失败返回 None
    """
    if not os.path.exists(file_path):
        logger.error(f"[MD5] 文件不存在: {file_path}")
        return None

    if not os.path.isfile(file_path):
        logger.error(f"[MD5] 不是有效文件: {file_path}")
        return None

    md5_obj = hashlib.md5()
    chunk_size = 8192  # 8KB
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)

        md5_hex = md5_obj.hexdigest()
        return md5_hex

    except PermissionError:
        logger.error(f"[MD5] 无权限读取: {file_path}")
        return None
    except Exception as e:
        logger.error(f"[MD5] 计算失败 [{file_path}]: {e}")
        return None


def listdir_with_allowed_type(directory: str, allowed_exts: tuple) -> list[str]:
    """列出目录中所有符合扩展名要求的文件路径

    Args:
        directory: 目录路径
        allowed_exts: 允许的扩展名元组，如 ('.txt', '.md', '.pdf')

    Returns:
        匹配的文件绝对路径列表
    """
    if not os.path.isdir(directory):
        logger.error(f"[Loader] 目录不存在或非目录: {directory}")
        return []

    result: list[str] = []
    for fname in os.listdir(directory):
        if fname.lower().endswith(allowed_exts):
            result.append(os.path.join(directory, fname))

    return result


# ============================================================================
# 文本规范化
# ============================================================================


def _normalize_text(text: str) -> str:
    """文本规范化 — 去乱码/控制字符、全半角转换、空白合并

    处理步骤:
    1. Unicode NFKC 规范化（全角→半角、合字分解等）
    2. 移除控制字符（保留换行符）
    3. 合并连续空行（≥3 → 2）
    4. 合并行内连续空白
    """
    text = text.strip()
    if not text:
        return text

    # 1. Unicode 规范化
    text = unicodedata.normalize("NFKC", text)

    # 2. 移除控制字符（保留 \n \r \t）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # 3. 合并连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 4. 合并行内连续空白（保留单个空格）
    text = re.sub(r"[ \t]+", " ", text)

    # 5. 清理行首尾空白
    lines = [line.strip() for line in text.split("\n")]
    # 移除首尾空白行
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines)


# ============================================================================
# PaddleOCR 单例
# ============================================================================

_ocr_instance = None


def _get_paddle_ocr():
    """PaddleOCR 延迟初始化单例（中英文混合，CPU 模式）

    兼容 PaddleOCR 2.x 和 3.x：
    - 2.x: ``show_log=False`` 抑制日志
    - 3.x: ``show_log`` 已移除，通过环境变量 / logging 控制
    """
    global _ocr_instance
    if _ocr_instance is None:
        import logging
        logging.getLogger("paddleocr").setLevel(logging.WARNING)

        try:
            from paddleocr import PaddleOCR

            # 尝试 3.x 构造（无 show_log 参数）
            _ocr_instance = PaddleOCR(
                lang="ch",
                use_angle_cls=True,
            )
        except TypeError:
            # 回退 2.x 构造
            from paddleocr import PaddleOCR

            _ocr_instance = PaddleOCR(
                lang="ch",
                use_angle_cls=True,
                show_log=False,
            )

        logger.info("[Loader] PaddleOCR 初始化完成")
    return _ocr_instance


def _extract_ocr_texts(ocr_result) -> list[str]:
    """从 PaddleOCR 3.x OCRResult 或 2.x 嵌套列表提取文本

    3.x: ``OCRResult.rec_texts`` (list[str])  或 dict-like 访问
    2.x: ``[[[bbox, (text, score)], ...], ...]``

    Returns:
        文本列表
    """
    texts: list[str] = []

    if not ocr_result:
        return texts

    # 3.x 格式：list[OCRResult]
    for res in ocr_result:
        if res is None:
            continue

        # 3.x 对象格式
        if hasattr(res, "rec_texts"):
            texts.extend(t for t in res.rec_texts if t and t.strip())
        elif hasattr(res, "texts"):
            texts.extend(t for t in res.texts if t and t.strip())
        elif isinstance(res, dict):
            # 3.x dict 格式
            rec_texts = res.get("rec_texts", [])
            texts.extend(t for t in rec_texts if t and t.strip())
        elif isinstance(res, (list, tuple)):
            # 2.x 嵌套列表格式
            for line_info in res:
                if isinstance(line_info, (list, tuple)) and len(line_info) >= 2:
                    text = line_info[1]
                    if isinstance(text, (list, tuple)):
                        text = text[0]
                    if text and str(text).strip():
                        texts.append(str(text).strip())

    return texts


# ============================================================================
# PDF 加载：PyMuPDF 文字提取 + 嵌入图片 PaddleOCR 双路互补
# ============================================================================


def _load_pdf(file_path: str) -> list[Document]:
    """加载 PDF — PyMuPDF 逐页提取嵌入文字 + PaddleOCR 识别嵌入图片

    处理流程（每页）::

        1. PyMuPDF ``page.get_text("")`` 提取嵌入文字层
        2. ``page.get_image_info(xrefs=True)`` 获取页面内嵌图片
        3. 过滤装饰性小图（宽高均 < 页面 60%）
        4. 对达标图片调用 PaddleOCR 识别
        5. 合并文字 + OCR 结果 → 文本规范化

    相比「整页渲染→OCR」方案，此方法:
    - 嵌入文字页不触发 OCR（保持原始精度 + 快速）
    - 仅对嵌入图片进行 OCR 补充扫描/图表文字
    - 一张图片一次 OCR，像素利用率高

    Args:
        file_path: PDF 文件绝对路径

    Returns:
        Document 列表（每页一个 Document）
    """
    import fitz  # PyMuPDF
    import numpy as np

    pdf_name = os.path.basename(file_path)
    docs: list[Document] = []

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.error(f"[Loader] PyMuPDF 打开失败 [{pdf_name}]: {e}")
        return []

    ocr = _get_paddle_ocr()

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_rect = page.rect
        texts: list[str] = []

        # ── 第一步：提取嵌入文字层 ──
        # "text" 模式返回页面已有的文字（包括格式控制字符）
        embedded_text = page.get_text("text")
        if embedded_text.strip():
            texts.append(embedded_text)

        # ── 第二步：获取嵌入图片列表 ──
        img_list = page.get_image_info(xrefs=True)

        # ── 第三步：对每张图片判断是否调用 OCR ──
        for img in img_list:
            xref = img.get("xref")
            if not xref:
                continue

            bbox = img["bbox"]
            img_w = bbox[2] - bbox[0]
            img_h = bbox[3] - bbox[1]

            # 过滤装饰性小图（icon / logo / 分割线等）
            # 宽 AND 高均小于页面 60% → 跳过
            page_w_ratio = img_w / page_rect.width if page_rect.width > 0 else 0
            page_h_ratio = img_h / page_rect.height if page_rect.height > 0 else 0
            if page_w_ratio < 0.6 and page_h_ratio < 0.6:
                continue

            # ── 第四步：提取像素 → PaddleOCR ──
            try:
                pix = fitz.Pixmap(doc, xref)

                # PyMuPDF Pixmap: h × w × n (n 为通道数)
                samples = np.frombuffer(pix.samples, dtype=np.uint8)

                if pix.n < 4:  # 灰度 (1) 或 RGB (3)
                    img_array = samples.reshape(pix.h, pix.w, pix.n)
                    if pix.n == 1:
                        # 灰度 → 复制为 3 通道
                        img_array = np.stack([img_array] * 3, axis=-1)
                else:  # CMYK (4) 或带 alpha
                    img_array = samples.reshape(pix.h, pix.w, pix.n)
                    if img_array.shape[2] == 4:
                        # RGBA / CMYK → 取前 3 通道
                        img_array = img_array[:, :, :3]

                # PaddleOCR: uint8 [H, W, 3] RGB → OCRResult (3.x) 或 list (2.x)
                ocr_result = ocr.ocr(img_array)
                ocr_lines = _extract_ocr_texts(ocr_result)
                if ocr_lines:
                    texts.append("\n".join(ocr_lines))

            except Exception as e:
                logger.warning(
                    f"[Loader] PaddleOCR 图片识别失败 "
                    f"({pdf_name} 第 {page_num + 1} 页, xref={xref}): {e}"
                )

        # ── 合并所有文本 → 规范化 ──
        page_text = _normalize_text("\n".join(texts))

        if page_text:
            docs.append(
                Document(
                    page_content=page_text,
                    metadata={"source": file_path, "page": page_num + 1},
                )
            )

    doc.close()
    logger.info(f"[Loader] {pdf_name} → {len(docs)} 页 (PyMuPDF + PaddleOCR)")
    return docs


# ============================================================================
# 非 PDF 文档加载（与旧版一致）
# ============================================================================


def _load_other(file_path: str) -> list[Document]:
    """加载非 PDF 文档，按扩展名分发到对应的 langchain loader

    Args:
        file_path: 文件路径

    Returns:
        Document 列表
    """
    ext = os.path.splitext(file_path)[1].lower()
    fname = os.path.basename(file_path)

    # --- docx / xlsx / pptx → UnstructuredFileLoader ---
    if ext in (".docx", ".xlsx", ".pptx"):
        try:
            from langchain_community.document_loaders import UnstructuredFileLoader

            loader = UnstructuredFileLoader(file_path)
            docs = list(loader.lazy_load())
            logger.info(f"[Loader] {fname} → {len(docs)} 个文档 (UnstructuredFileLoader)")
            return docs
        except Exception as e:
            logger.warning(f"[Loader] UnstructuredFileLoader 失败 [{fname}]: {e}")
            return []

    # --- txt / md → TextLoader ---
    if ext in (".txt", ".md"):
        try:
            from langchain_community.document_loaders import TextLoader

            loader = TextLoader(file_path, encoding="utf-8")
            docs = list(loader.lazy_load())
            logger.info(f"[Loader] {fname} → {len(docs)} 个文档 (TextLoader)")
            return docs
        except Exception as e:
            logger.warning(f"[Loader] TextLoader 失败 [{fname}]: {e}")
            return []

    # --- csv → CSVLoader ---
    if ext == ".csv":
        try:
            from langchain_community.document_loaders import CSVLoader

            loader = CSVLoader(file_path, encoding="utf-8")
            docs = list(loader.lazy_load())
            logger.info(f"[Loader] {fname} → {len(docs)} 个文档 (CSVLoader)")
            return docs
        except Exception as e:
            logger.warning(f"[Loader] CSVLoader 失败 [{fname}]: {e}")
            return []

    # --- html / htm → BSHTMLLoader ---
    if ext in (".html", ".htm"):
        try:
            from langchain_community.document_loaders import BSHTMLLoader

            loader = BSHTMLLoader(file_path, open_encoding="utf-8")
            docs = list(loader.lazy_load())
            logger.info(f"[Loader] {fname} → {len(docs)} 个文档 (BSHTMLLoader)")
            return docs
        except Exception as e:
            logger.warning(f"[Loader] BSHTMLLoader 失败 [{fname}]: {e}")
            return []

    logger.warning(f"[Loader] 不支持的文件类型: {ext} [{fname}]")
    return []


# ============================================================================
# 主入口
# ============================================================================


def load_document(file_path: str) -> list[Document]:
    """加载文档为 Document 列表

    - PDF: PyMuPDF 嵌入文字 + PaddleOCR 嵌入图片 → 合并且规范化
    - 其他格式: 按扩展名分发到对应的 langchain_community loader

    Args:
        file_path: 文件绝对路径

    Returns:
        Document 列表
    """
    if not os.path.isfile(file_path):
        logger.error(f"[Loader] 文件不存在或非文件: {file_path}")
        return []

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _load_pdf(file_path)
    else:
        return _load_other(file_path)


# 向后兼容别名
docling_loader = load_document
