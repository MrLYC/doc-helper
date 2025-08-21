"""
PDF Helper - 页面处理框架

该包提供了一个灵活的页面处理框架，用于批量处理网页，支持内容提取、PDF生成、链接发现等功能。
"""

from .protocol import (
    URL, URLCollection, URLStatus, 
    PageContext, PageProcessor, ProcessorState,
    PageManager, PageManagerConfig, RetryCallback
)

from .manager import ChromiumManager

from .processors import (
    PageLoadProcessor,
    ContentExtractProcessor, 
    PDFExporter,
    PageMonitor,
    RequestMonitor,
    LinksFinder,
    ElementCleaner,
    ContentFinder
)

from .builder import (
    PageProcessingBuilder,
    create_web_scraper,
    create_pdf_generator,
    create_link_crawler
)

from .pdf_merger import (
    PdfMerger,
    MergeConfig,
    PdfInfo,
    MergeResult,
    create_merger
)

__version__ = "1.0.0"

__all__ = [
    # 协议类
    "URL",
    "URLCollection", 
    "URLStatus",
    "PageContext",
    "PageProcessor",
    "ProcessorState",
    # 处理器类
    "PageLoadProcessor",
    "ContentExtractProcessor",
    "PDFExporter", 
    "PageMonitor",
    "RequestMonitor",
    "LinksFinder",
    "ElementCleaner",
    "ContentFinder",
    # 构建器类
    "PageProcessingBuilder",
    "create_web_scraper", 
    "create_pdf_generator",
    "create_link_crawler",
    # PDF合并器类
    "PdfMerger",
    "MergeConfig",
    "PdfInfo", 
    "MergeResult",
    "create_merger",
    # 管理器类
    "ChromiumManager",
    "PageManagerConfig",
    # 工具函数
    "create_file_collection",
    "create_simple_collection",
]