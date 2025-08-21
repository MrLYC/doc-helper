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
    PageMonitor, PageLoadProcessor, ContentExtractProcessor, 
    PDFGenerateProcessor, LinkExtractProcessor, ScreenshotProcessor
)

__version__ = "1.0.0"

__all__ = [
    # 协议和数据结构
    "URL", "URLCollection", "URLStatus",
    "PageContext", "PageProcessor", "ProcessorState", 
    "PageManager", "PageManagerConfig", "RetryCallback",
    
    # 管理器实现
    "ChromiumManager",
    
    # 处理器实现
    "PageMonitor", "PageLoadProcessor", "ContentExtractProcessor",
    "PDFGenerateProcessor", "LinkExtractProcessor", "ScreenshotProcessor",
]