"""
页面处理器构建器

该模块提供了一个Builder模式的实现，用于方便地构建完整的页面处理流水线。
通过链式调用，可以轻松配置各种处理器，最终生成一个完整的PageManager。
"""

import logging
from typing import List, Optional, Callable, Any
from pathlib import Path

from .manager import ChromiumManager, PageManagerConfig
from .protocol import PageManager, URLCollection, RetryCallback
from .url_collection import SimpleCollection
from .processors import (
    PageMonitor, RequestMonitor, LinksFinder, ElementCleaner, 
    ContentFinder, PDFExporter
)

logger = logging.getLogger(__name__)


class PageProcessingBuilder:
    """
    页面处理流水线构建器
    
    通过Builder模式构建完整的页面处理流水线，支持：
    - 页面监控 (PageMonitor - 自动添加)
    - 请求监控和屏蔽 (RequestMonitor)
    - 链接发现 (LinksFinder) 
    - 元素清理 (ElementCleaner)
    - 内容查找和处理 (ContentFinder)
    - PDF导出 (PDFExporter)
    
    示例:
        builder = (PageProcessingBuilder()
            .set_entry_url("https://example.com")
            .set_concurrent_tabs(3)
            .block_url_patterns([".*\\.gif", ".*analytics.*"])
            .find_links("body a")
            .clean_elements("*[id*='ad'], .popup")
            .find_content("main article")
            .export_pdf("/output/result.pdf")
            .build())
    """
    
    def __init__(self):
        """初始化构建器"""
        self._url_collection: Optional[URLCollection] = None
        self._entry_urls: List[str] = []
        self._concurrent_tabs: int = 1
        self._page_timeout: float = 60.0
        self._poll_interval: float = 1.0
        self._detect_timeout: float = 5.0
        self._headless: bool = True
        self._processors: List[Any] = []
        self._request_monitor: Optional[RequestMonitor] = None
        self._content_finder: Optional[ContentFinder] = None
        self._config: Optional[PageManagerConfig] = None
        self._verbose: bool = False
        self._retry_callback: Optional[RetryCallback] = None
        
        logger.info("PageProcessingBuilder 初始化完成")
    
    def set_url_collection(self, url_collection: URLCollection) -> 'PageProcessingBuilder':
        """
        设置URL集合
        
        Args:
            url_collection: URL集合实例
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._url_collection = url_collection
        logger.debug("设置URL集合")
        return self
    
    def set_entry_url(self, url: str) -> 'PageProcessingBuilder':
        """
        设置入口URL
        
        Args:
            url: 入口URL地址
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._entry_urls = [url]
        logger.info(f"设置入口URL: {url}")
        return self
        
    def set_entry_urls(self, urls: List[str]) -> 'PageProcessingBuilder':
        """
        设置多个入口URL
        
        Args:
            urls: URL地址列表
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._entry_urls = urls
        logger.info(f"设置入口URLs: {len(urls)} 个")
        return self
    
    def set_concurrent_tabs(self, count: int) -> 'PageProcessingBuilder':
        """
        设置并发标签页数量
        
        Args:
            count: 并发标签页数量
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._concurrent_tabs = max(1, count)
        logger.info(f"设置并发标签页数量: {self._concurrent_tabs}")
        return self
    
    def set_page_timeout(self, timeout: float) -> 'PageProcessingBuilder':
        """
        设置页面超时时间
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._page_timeout = timeout
        logger.info(f"设置页面超时: {timeout}秒")
        return self
    
    def set_verbose(self, verbose: bool = True) -> 'PageProcessingBuilder':
        """
        设置可视化模式
        
        Args:
            verbose: 是否启用可视化模式（显示浏览器界面）
            
        Returns:
            PageProcessingBuilder: 当前构建器实例
        """
        self._verbose = verbose
        logger.info(f"设置可视化模式: {verbose}")
        return self
    
    def set_headless(self, headless: bool = True) -> 'PageProcessingBuilder':
        """
        设置无头模式
        
        Args:
            headless: 是否使用无头模式
            
        Returns:
            PageProcessingBuilder: 当前构建器实例
        """
        self._headless = headless
        logger.info(f"设置无头模式: {headless}")
        return self
    
    def set_poll_interval(self, interval: float) -> 'PageProcessingBuilder':
        """
        设置轮询间隔
        
        Args:
            interval: 轮询间隔（秒）
            
        Returns:
            PageProcessingBuilder: 当前构建器实例
        """
        self._poll_interval = interval
        logger.info(f"设置轮询间隔: {interval}秒")
        return self
    
    def set_detect_timeout(self, timeout: float) -> 'PageProcessingBuilder':
        """
        设置检测超时时间
        
        Args:
            timeout: 检测超时时间（秒）
            
        Returns:
            PageProcessingBuilder: 当前构建器实例
        """
        self._detect_timeout = timeout
        logger.info(f"设置检测超时时间: {timeout}秒")
        return self
    
    def set_retry_callback(self, callback: RetryCallback) -> 'PageProcessingBuilder':
        """
        设置重试回调函数
        
        Args:
            callback: 重试回调函数
            
        Returns:
            PageProcessingBuilder: 当前构建器实例
        """
        self._retry_callback = callback
        logger.info("设置重试回调函数")
        return self
    
    def set_config(self, config: PageManagerConfig) -> 'PageProcessingBuilder':
        """
        设置自定义页面管理器配置
        
        Args:
            config: 页面管理器配置
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._config = config
        logger.info("设置自定义页面管理器配置")
        return self
    
    def add_processor(self, processor: Any) -> 'PageProcessingBuilder':
        """
        添加自定义处理器
        
        Args:
            processor: 处理器实例
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        self._processors.append(processor)
        logger.info(f"添加自定义处理器: {processor.name}")
        return self
    
    def block_url_patterns(
        self, 
        patterns: List[str],
        slow_request_threshold: int = 100,
        failed_request_threshold: int = 10
    ) -> 'PageProcessingBuilder':
        """
        添加请求监控和URL屏蔽功能
        
        Args:
            patterns: 需要屏蔽的URL正则表达式模式列表
            slow_request_threshold: 慢请求数量阈值
            failed_request_threshold: 失败请求数量阈值
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        if self._request_monitor is not None:
            logger.warning("RequestMonitor已存在，将替换现有实例")
        
        # 确保有URL集合
        if self._url_collection is None:
            self._url_collection = SimpleCollection()
        
        self._request_monitor = RequestMonitor(
            name="request_monitor",
            url_collection=self._url_collection,
            slow_request_threshold=slow_request_threshold,
            failed_request_threshold=failed_request_threshold
        )
        
        # 设置屏蔽模式
        self._request_monitor.block_url_patterns = set(patterns)
        
        logger.info(f"添加RequestMonitor，屏蔽模式: {len(patterns)} 个")
        return self
    
    def find_links(
        self,
        css_selector: str = "body a",
        priority: int = 10,
        url_pattern: Optional[str] = None,
        max_depth: int = 12
    ) -> 'PageProcessingBuilder':
        """
        添加链接发现处理器
        
        Args:
            css_selector: CSS选择器，指定要搜索链接的容器
            priority: 处理器优先级
            url_pattern: URL匹配的正则表达式模式
            max_depth: 基于根目录的最大链接深度
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        # 确保有URL集合
        if self._url_collection is None:
            self._url_collection = SimpleCollection()
        
        links_finder = LinksFinder(
            name=f"links_finder_{len(self._processors)}",
            url_collection=self._url_collection,
            css_selector=css_selector,
            priority=priority,
            url_pattern=url_pattern,
            max_depth=max_depth
        )
        
        self._processors.append(links_finder)
        pattern_info = f", URL模式: {url_pattern}" if url_pattern else ""
        logger.info(f"添加LinksFinder，CSS选择器: {css_selector}, 最大深度: {max_depth}{pattern_info}")
        return self
    
    def clean_elements(
        self,
        css_selector: str,
        priority: int = 20
    ) -> 'PageProcessingBuilder':
        """
        添加元素清理处理器
        
        Args:
            css_selector: CSS选择器，指定要删除的元素
            priority: 处理器优先级
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        element_cleaner = ElementCleaner(
            name=f"element_cleaner_{len(self._processors)}",
            css_selector=css_selector,
            priority=priority
        )
        
        self._processors.append(element_cleaner)
        logger.info(f"添加ElementCleaner，CSS选择器: {css_selector}")
        return self
    
    def find_content(
        self,
        css_selector: str,
        target_states: Optional[List[str]] = None,
        priority: int = 30
    ) -> 'PageProcessingBuilder':
        """
        添加内容查找处理器
        
        Args:
            css_selector: CSS选择器，用于查找核心内容
            target_states: 目标页面状态列表，默认为 ['ready', 'completed']
            priority: 处理器优先级
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        if self._content_finder is not None:
            logger.warning("ContentFinder已存在，将替换现有实例")
        
        self._content_finder = ContentFinder(
            css_selector=css_selector,
            target_states=target_states,
            priority=priority
        )
        
        logger.info(f"添加ContentFinder，CSS选择器: {css_selector}")
        return self
    
    def export_pdf(
        self,
        output_path: Optional[str] = None,
        output_dir: str = "/tmp",
        priority: int = 40
    ) -> 'PageProcessingBuilder':
        """
        添加PDF导出处理器
        
        Args:
            output_path: 完整的PDF输出路径，如果提供则忽略output_dir
            output_dir: PDF输出目录，当output_path为None时使用
            priority: 处理器优先级
            
        Returns:
            PageProcessingBuilder: 构建器实例，支持链式调用
        """
        pdf_exporter = PDFExporter(
            name=f"pdf_exporter_{len(self._processors)}",
            output_path=output_path,
            output_dir=output_dir,
            priority=priority
        )
        
        self._processors.append(pdf_exporter)
        
        output_info = output_path if output_path else f"目录: {output_dir}"
        logger.info(f"添加PDFExporter，输出: {output_info}")
        return self
    
    def build(self) -> PageManager:
        """
        构建并返回PageManager实例
        
        Returns:
            PageManager: 配置完成的页面管理器
            
        Raises:
            ValueError: 当配置不完整时抛出异常
        """
        if not self._entry_urls:
            raise ValueError("必须设置至少一个入口URL")
        
        # 确保有URL集合
        if self._url_collection is None:
            self._url_collection = SimpleCollection()
        
        # 添加入口URL到集合
        for url in self._entry_urls:
            self._url_collection.add_url(url, category="entry")
        
        # 创建配置
        if self._config is None:
            self._config = PageManagerConfig(
                max_concurrent_tabs=self._concurrent_tabs,
                page_timeout=self._page_timeout,
                poll_interval=self._poll_interval,
                detect_timeout=self._detect_timeout,
                headless=self._headless
            )
        
        # 构建处理器工厂列表
        processor_factories = []
        
        # 自动添加PageMonitor（优先级0，最高）
        page_monitor = PageMonitor(
            name="page_monitor",
            page_timeout=self._page_timeout,
            priority=0
        )
        processor_factories.append(lambda: page_monitor)
        
        # 添加RequestMonitor（如果有的话）
        if self._request_monitor is not None:
            monitor = self._request_monitor
            processor_factories.append(lambda: monitor)
        
        # 添加ContentFinder（如果有的话）
        if self._content_finder is not None:
            finder = self._content_finder
            processor_factories.append(lambda: finder)
        
        # 添加其他处理器
        for processor in self._processors:
            processor_factories.append(lambda p=processor: p)

        # 创建管理器
        manager = ChromiumManager(
            url_collection=self._url_collection,
            processor_factories=processor_factories,
            config=self._config,
            retry_callback=self._retry_callback,
            verbose=self._verbose
        )
        
        logger.info(
            f"构建完成 - 入口URLs: {len(self._entry_urls)}, "
            f"并发标签页: {self._concurrent_tabs}, "
            f"处理器总数: {len(self._processors) + (1 if self._request_monitor else 0) + (1 if self._content_finder else 0) + 1}"
        )
        
        return manager


def create_web_scraper() -> PageProcessingBuilder:
    """
    创建一个新的网页爬虫构建器
    
    Returns:
        PageProcessingBuilder: 新的构建器实例
    """
    return PageProcessingBuilder()


def create_pdf_generator() -> PageProcessingBuilder:
    """
    创建一个预配置的PDF生成器构建器
    
    Returns:
        PageProcessingBuilder: 预配置的构建器实例，已添加基本的PDF生成功能
    """
    return (PageProcessingBuilder()
            .clean_elements("*[id*='ad'], *[class*='popup'], script[src*='analytics']")
            .find_content("main, article, .content, #content")
            .export_pdf())


def create_link_crawler() -> PageProcessingBuilder:
    """
    创建一个预配置的链接爬虫构建器
    
    Returns:
        PageProcessingBuilder: 预配置的构建器实例，已添加链接发现功能
    """
    return (PageProcessingBuilder()
            .block_url_patterns([
                ".*\\.gif", ".*\\.jpg", ".*\\.png", ".*\\.css", ".*\\.js",
                ".*analytics.*", ".*tracking.*", ".*\\.woff"
            ])
            .find_links("body a")
            .clean_elements("*[id*='ad'], *[class*='popup']"))