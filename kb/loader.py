"""
文档加载管线 — 文件 MD5 / 文档解析 / 切片

Port of utils/file_handler.py into kb/ module.
"""

import os
import hashlib
from typing import Optional

from core.logger import logger
from langchain_core.documents import Document


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
# PDF 图片渲染 & DashScope VL
# ============================================================================


def _split_pdf_to_images(file_path: str) -> list[bytes]:
    """使用 pypdfium2 将 PDF 每页渲染为 PNG 图片字节

    Args:
        file_path: PDF 文件路径

    Returns:
        PNG 字节列表，每页一张
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.error("[Loader] pypdfium2 未安装，无法渲染 PDF")
        return []

    try:
        pdf = pdfium.PdfDocument(file_path)
    except Exception as e:
        logger.error(f"[Loader] pypdfium2 打开 PDF 失败 [{file_path}]: {e}")
        return []

    total = len(pdf)
    images: list[bytes] = []

    for i in range(total):
        try:
            page = pdf[i]
            bitmap = page.render(scale=2)  # 2x 提高 OCR 准确率
            pil_image = bitmap.to_pil()
            import io

            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            images.append(buf.getvalue())
        except Exception as e:
            logger.warning(f"[Loader] 渲染第 {i + 1} 页失败: {e}")

    pdf.close()
    logger.info(f"[Loader] PDF 共 {total} 页，成功渲染 {len(images)} 页图片")
    return images


def _describe_image_with_dashscope_vl(file_path: str) -> str:
    """使用 DashScope qwen-vl-max 逐页描述 PDF 页面内容

    Args:
        file_path: PDF 文件路径

    Returns:
        所有页面的描述文本拼接
    """
    from openai import OpenAI
    import base64

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        logger.warning("[Loader] DASHSCOPE_API_KEY 未设置，跳过 VL OCR")
        return ""

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    images = _split_pdf_to_images(file_path)
    if not images:
        return ""

    descriptions: list[str] = []
    for i, img_bytes in enumerate(images):
        try:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            resp = client.chat.completions.create(
                model="qwen-vl-max",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": f"data:image/png;base64,{b64}",
                            },
                            {
                                "type": "text",
                                "text": "请详细描述这张图片中的文字内容。",
                            },
                        ],
                    }
                ],
                timeout=30,
            )
            text = resp.choices[0].message.content
            descriptions.append(text or "")
        except Exception as e:
            logger.warning(f"[Loader] VL OCR 第 {i + 1} 页失败: {e}")

    return "\n".join(descriptions)


# ============================================================================
# PDF 加载（pypdfium2 → Docling OCR → DashScope VL）
# ============================================================================


def _load_pdf(file_path: str) -> list[Document]:
    """加载 PDF 文档，带三级 fallback

    1. pypdfium2 逐页提取嵌入文字
    2. 空白页回退 Docling OCR（扫描版）
    3. 仍失败则使用 DashScope VL 描述

    Args:
        file_path: PDF 文件路径

    Returns:
        Document 列表
    """
    import pypdfium2 as pdfium

    pdf_name = os.path.basename(file_path)
    docs: list[Document] = []
    total_pages = 0

    # ------ 第一步：pypdfium2 逐页提取嵌入文字 ------
    try:
        pdf = pdfium.PdfDocument(file_path)
        total_pages = len(pdf)

        for i in range(total_pages):
            try:
                page = pdf[i]
                textpage = page.get_textpage()
                text = textpage.get_text_range().strip()
                if text:
                    docs.append(
                        Document(
                            page_content=text,
                            metadata={"source": file_path, "page": i + 1},
                        )
                    )
                else:
                    docs.append(None)  # type: ignore[arg-type]  # 占位，后续 fallback
            except Exception:
                docs.append(None)  # type: ignore[arg-type]

        pdf.close()
    except Exception as e:
        logger.error(f"[Loader] pypdfium2 打开失败 [{pdf_name}]: {e}")
        return []

    pages_with_text = sum(1 for d in docs if d is not None)
    blank_indices = [i for i, d in enumerate(docs) if d is None]

    if not blank_indices:
        # 所有页都有文字
        logger.info(f"[Loader] {pdf_name} → {total_pages} 页 (pypdfium2)")
        return [d for d in docs if d is not None]  # type: ignore[return-value]

    logger.info(
        f"[Loader] {pdf_name} → {pages_with_text}/{total_pages} 页有文字, "
        f"{len(blank_indices)} 页需 fallback"
    )

    # ------ 第二步：对空白页尝试 Docling OCR ------
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(file_path)
        docling_doc = result.document
        docling_text = docling_doc.export_to_markdown() if hasattr(docling_doc, "export_to_markdown") else str(docling_doc)

        if docling_text and len(docling_text.strip()) > 50:
            # Docling 有实质内容，用它替换空白页
            # 按段落/页拆分 docling 文本（Docling 输出含分页标记）
            paragraphs = docling_text.split("\n\n")
            docling_idx = 0
            for idx in blank_indices:
                if docling_idx < len(paragraphs):
                    docs[idx] = Document(
                        page_content=paragraphs[docling_idx].strip(),
                        metadata={"source": file_path, "page": idx + 1},
                    )
                    docling_idx += 1
                else:
                    break

            # 重新检查还有哪些空白页
            remaining_blank = [i for i, d in enumerate(docs) if d is None]
            if not remaining_blank:
                logger.info(f"[Loader] {pdf_name} → pypdfium2 + Docling 完成")
                return [d for d in docs if d is not None]  # type: ignore[return-value]

            logger.info(
                f"[Loader] {pdf_name} → Docling 覆盖了 {len(blank_indices) - len(remaining_blank)} 页, "
                f"仍有 {len(remaining_blank)} 页空白"
            )
            blank_indices = remaining_blank
        else:
            logger.info(f"[Loader] {pdf_name} → Docling 未产出实质内容")
    except Exception as e:
        logger.warning(f"[Loader] Docling OCR 失败 [{pdf_name}]: {e}")

    # ------ 第三步：仍空白页使用 DashScope VL ------
    remaining_blank = [i for i, d in enumerate(docs) if d is None]
    if remaining_blank:
        logger.info(f"[Loader] {pdf_name} → 尝试 DashScope VL 描述 {len(remaining_blank)} 页")
        vl_text = _describe_image_with_dashscope_vl(file_path)
        if vl_text and len(vl_text.strip()) > 20:
            segments = vl_text.split("\n")
            if len(segments) >= len(remaining_blank):
                for j, idx in enumerate(remaining_blank):
                    docs[idx] = Document(
                        page_content=segments[j].strip(),
                        metadata={"source": file_path, "page": idx + 1},
                    )
            else:
                # VL 输出页数不足，合并注入最后一页
                for idx in remaining_blank:
                    docs[idx] = Document(
                        page_content=vl_text,
                        metadata={"source": file_path, "page": idx + 1},
                    )

    # 清理剩余 None，回退为空文档
    final_docs: list[Document] = []
    for d in docs:
        if d is None:
            final_docs.append(
                Document(
                    page_content="",
                    metadata={"source": file_path, "page": docs.index(None) + 1},
                )
            )
        else:
            final_docs.append(d)

    logger.info(
        f"[Loader] {pdf_name} → {len(final_docs)} 页 "
        f"(pypdfium2 + Docling + VL fallback)"
    )
    return final_docs


# ============================================================================
# 非 PDF 文档加载
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


def docling_loader(file_path: str) -> list[Document]:
    """加载文档为 Document 列表

    - PDF: 三级 fallback 链 —
        1. pypdfium2 逐页提取嵌入文字
        2. 空白页回退 Docling OCR
        3. 仍失败则使用 DashScope VL 描述
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
