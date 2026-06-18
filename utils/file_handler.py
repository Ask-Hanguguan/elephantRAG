import hashlib
import os
import tempfile
from typing import Optional
from utils.logger_handler import logger
from langchain_core.documents import Document

# Docling 回退时每批页数（避免扫描版大 PDF OOM）
DOCLING_BATCH_PAGES = 10

# 模块级共享 converter（回退模式复用，OCR 模型只初始化一次）
_docling_converter = None


def _get_docling_converter():
    """获取共享 DocumentConverter（默认构造，不传自定义参数避免兼容问题）"""
    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter
        _docling_converter = DocumentConverter()
        logger.info("[Docling] 共享 DocumentConverter 已创建")
    return _docling_converter


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


# ============================================================================
# 文档加载：PDF 用 pypdfium2 逐页提取，其他用 docling
# ============================================================================

def _load_pdf_with_pypdfium(filepath: str) -> tuple[list[Document], int]:
    """使用 pypdfium2 逐页提取 PDF 文字（轻量，无 OCR，内存友好）

    仅提取 PDF 中已嵌入的文本层。纯扫描版/图片型 PDF 将返回空内容。

    Returns:
        (docs, total_pages) — docs: 有嵌入文字的页面; total_pages: PDF 总页数
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(filepath)
    total_pages = len(pdf)
    docs: list[Document] = []
    empty_pages = 0

    for i in range(total_pages):
        try:
            page = pdf[i]
            textpage = page.get_textpage()
            text = textpage.get_text_range().strip()
            if text:
                docs.append(Document(
                    page_content=text,
                    metadata={"source": filepath, "page": i + 1},
                ))
            else:
                empty_pages += 1
        except Exception:
            empty_pages += 1

    pdf.close()

    if empty_pages:
        logger.debug(
            f"[PDF] {os.path.basename(filepath)}: {total_pages} 页, "
            f"{len(docs)} 页有文字, {empty_pages} 页空白/纯图片"
        )

    return docs, total_pages


def _docling_load_one(filepath: str) -> list[Document]:
    """DoclingLoader 单次调用（复用共享 converter）"""
    from langchain_docling import DoclingLoader

    try:
        loader = DoclingLoader(
            file_path=filepath,
            converter=_get_docling_converter(),
            export_type="markdown",
        )
        return list(loader.lazy_load())
    except Exception as e:
        logger.error(f"Docling 加载失败 [{filepath}]: {str(e)}")
        return []


def _get_pdf_pages(filepath: str) -> int:
    """获取 PDF 总页数（pypdfium2）"""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(filepath)
    n = len(doc)
    doc.close()
    return n


def _split_pdf_pages(filepath: str, start: int, end: int) -> str:
    """切出 PDF [start, end) 页 → 临时文件路径"""
    import pypdfium2 as pdfium

    src = pdfium.PdfDocument(filepath)
    total = len(src)
    end = min(end, total)
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, pages=list(range(start, end)))

    fd, tmp = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        dst.save(tmp)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    finally:
        src.close()
        dst.close()
    return tmp


def _load_pdf_with_docling_batched(
    filepath: str, batch_pages: int = DOCLING_BATCH_PAGES
) -> list[Document]:
    """Docling 分批加载大 PDF（扫描版/纯图片 PDF 专用）"""
    total = _get_pdf_pages(filepath)
    if total <= batch_pages:
        return _docling_load_one(filepath)

    logger.info(
        f"[Docling] {os.path.basename(filepath)} 共 {total} 页, "
        f"按 {batch_pages} 页/批分批 OCR"
    )

    all_docs: list[Document] = []
    for start in range(0, total, batch_pages):
        end = min(start + batch_pages, total)
        tmp = None
        try:
            tmp = _split_pdf_pages(filepath, start, end)
            batch = _docling_load_one(tmp)
            all_docs.extend(batch)
        except Exception as e:
            logger.warning(
                f"[Docling] 批次 [{start + 1}-{end}] 失败: {e}"
            )
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    logger.info(
        f"[Docling] {os.path.basename(filepath)} 分批完成 → {len(all_docs)} 个文档"
    )
    return all_docs


def docling_loader(filepath: str) -> list[Document]:
    """加载文档为 Document 列表

    - PDF: 先用 pypdfium2 提取嵌入文字层（快、轻量）；
           若无文字，回退到 DoclingLoader 分批 OCR（处理扫描版/图片型 PDF）
    - 其他格式 (docx/pptx/xlsx/html 等): 使用 DoclingLoader

    :param filepath: 文件绝对路径
    :return: Document 列表
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.pdf':
        # 第一轮：pypdfium2 快速提取嵌入文字
        docs, total = _load_pdf_with_pypdfium(filepath)

        if docs and len(docs) == total:
            # 全部页面都有嵌入文字，直接用 pypdfium2 结果
            logger.info(
                f"[加载] {os.path.basename(filepath)} → {len(docs)} 页 (pypdfium2)"
            )
            return docs

        if not docs:
            # 无嵌入文字 → 扫描版/纯图片 PDF，docling 分批 OCR
            logger.info(
                f"[加载] {os.path.basename(filepath)} → "
                f"无嵌入文字，回退到 DoclingLoader 分批 OCR"
            )
        else:
            # 部分页面有嵌入文字，部分没有 → 也回退到 docling 分批整体 OCR
            logger.info(
                f"[加载] {os.path.basename(filepath)} → "
                f"部分嵌入文字({len(docs)}/{total})，回退到 Docling 分批整体 OCR"
            )

        return _load_pdf_with_docling_batched(filepath)

    # 非 PDF：docling
    docs = _docling_load_one(filepath)
    if docs:
        logger.info(f"[加载] {os.path.basename(filepath)} → {len(docs)} 个文档")
    return docs
