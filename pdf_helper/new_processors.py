"""
新的页面处理器实现

该模块包含高级页面处理器，用于页面监控、请求监控、链接发现、内容清理和PDF导出。
"""

import asyncio
import logging
import time
from typing import Optional, Set, Dict, Any
from urllib.parse import urlparse, urlunparse

from playwright.async_api import Request, Response, Page
from prometheus_client import Counter, Histogram, Gauge

from .protocol import PageContext, PageProcessor, ProcessorState, URL, URLStatus

logger = logging.getLogger(__name__)


class PageMonitor(PageProcessor):
    """
    页面监控处理器，监控页面加载状态和网络请求
    
    负责监控页面加载过程，跟踪慢请求和失败请求，并管理页面状态转换。
    优先级固定为0，确保最早执行。
    """
    
    def __init__(self, name: str, slow_request_timeout: Optional[float] = None):
        """
        初始化页面监控处理器
        
        Args:
            name: 处理器名称
            slow_request_timeout: 慢请求超时阈值，默认为页面超时的1/10
        """
        super().__init__(name, priority=0)  # 固定优先级0
        self.slow_request_timeout = slow_request_timeout
        self._monitoring_started = False
        self._page_state = "loading"  # loading, ready, completed
        self._pending_requests: Set[str] = set()
        self._slow_requests: Dict[str, int] = {}
        self._failed_requests: Dict[str, int] = {}
        
        # Prometheus 指标
        self.slow_request_counter = Counter(
            'page_monitor_slow_requests_total',
            'Total number of slow requests detected',
            ['domain', 'path']
        )
        self.failed_request_counter = Counter(
            'page_monitor_failed_requests_total', 
            'Total number of failed requests',
            ['domain', 'path', 'error_type']
        )
        self.page_load_duration = Histogram(
            'page_monitor_load_duration_seconds',
            'Time taken for page to reach different states',
            ['state', 'domain']
        )
        self.active_requests_gauge = Gauge(
            'page_monitor_active_requests',
            'Number of active network requests',
            ['domain']
        )
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否应该开始监控"""
        if self._monitoring_started:
            return ProcessorState.RUNNING if self._page_state != "completed" else ProcessorState.COMPLETED
            
        # 如果页面有URL在加载中，开始监控
        if context.url and context.url.status == URLStatus.PENDING:
            return ProcessorState.READY
            
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """执行页面监控"""
        if not self._monitoring_started:
            await self._start_monitoring(context)
            self._monitoring_started = True
            
        # 设置慢请求超时默认值
        if self.slow_request_timeout is None:
            # 获取页面超时设置，默认30秒的1/10 = 3秒
            page_timeout = getattr(context.page, '_timeout_settings', {}).get('timeout', 30000)
            self.slow_request_timeout = page_timeout / 10000  # 转换为秒并取1/10
            
        logger.info(f"页面监控已启动: {context.url.url}, 慢请求阈值: {self.slow_request_timeout}s")
    
    async def _start_monitoring(self, context: PageContext) -> None:
        """开始监控页面和网络请求"""
        page = context.page
        domain = self._get_domain(context.url.url)
        
        # 监听页面加载事件
        async def on_load():
            self._page_state = "ready"
            context.data["page_state"] = "ready"
            self.page_load_duration.labels(state="ready", domain=domain).observe(time.time() - context.start_time)
            logger.info(f"页面进入就绪状态: {context.url.url}")
            
        async def on_network_idle():
            self._page_state = "completed" 
            context.data["page_state"] = "completed"
            self.page_load_duration.labels(state="completed", domain=domain).observe(time.time() - context.start_time)
            logger.info(f"页面加载完成: {context.url.url}")
            
        # 监听网络请求
        async def on_request(request: Request):
            url_without_query = self._remove_query_string(request.url)
            self._pending_requests.add(request.url)
            self.active_requests_gauge.labels(domain=domain).set(len(self._pending_requests))
            
            # 记录请求开始时间
            setattr(request, '_start_time', time.time())
            
        async def on_response(response: Response):
            request = response.request
            url_without_query = self._remove_query_string(request.url)
            
            if request.url in self._pending_requests:
                self._pending_requests.remove(request.url)
                self.active_requests_gauge.labels(domain=domain).set(len(self._pending_requests))
            
            # 检查慢请求
            start_time = getattr(request, '_start_time', None)
            if start_time:
                duration = time.time() - start_time
                if duration > self.slow_request_timeout:
                    self._slow_requests[url_without_query] = self._slow_requests.get(url_without_query, 0) + 1
                    
                    req_domain = self._get_domain(request.url)
                    req_path = urlparse(request.url).path or "/"
                    self.slow_request_counter.labels(domain=req_domain, path=req_path).inc()
                    
                    logger.warning(f"慢请求检测: {url_without_query} 耗时 {duration:.2f}s")
                    
        async def on_request_failed(request: Request):
            url_without_query = self._remove_query_string(request.url)
            self._failed_requests[url_without_query] = self._failed_requests.get(url_without_query, 0) + 1
            
            if request.url in self._pending_requests:
                self._pending_requests.remove(request.url)
                self.active_requests_gauge.labels(domain=domain).set(len(self._pending_requests))
            
            req_domain = self._get_domain(request.url)
            req_path = urlparse(request.url).path or "/"
            self.failed_request_counter.labels(domain=req_domain, path=req_path, error_type="failed").inc()
            
            logger.warning(f"请求失败: {url_without_query}")
        
        # 注册事件监听器
        page.on("load", on_load)
        page.on("networkidle", on_network_idle)
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        
        # 保存监控数据到上下文
        context.data["slow_requests"] = self._slow_requests
        context.data["failed_requests"] = self._failed_requests
        context.data["page_state"] = self._page_state
        
        # 设置上下文状态为加载中
        context.data["page_state"] = "loading"
    
    def _get_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"
    
    def _remove_query_string(self, url: str) -> str:
        """移除URL的查询字符串"""
        try:
            parsed = urlparse(url)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        except Exception:
            return url
    
    async def finish(self, context: PageContext) -> None:
        """清理页面监控器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"页面监控器清理完成: {context.url.url}")


class RequestMonitor(PageProcessor):
    """
    请求监控处理器，监控和屏蔽异常请求
    
    监控页面的慢请求和失败请求，当超过阈值时自动屏蔽相关URL。
    """
    
    def __init__(self, name: str, slow_threshold: int = 100, failed_threshold: int = 10):
        """
        初始化请求监控处理器
        
        Args:
            name: 处理器名称
            slow_threshold: 慢请求数量阈值，默认100
            failed_threshold: 失败请求数量阈值，默认10
        """
        super().__init__(name, priority=1)
        self.slow_threshold = slow_threshold
        self.failed_threshold = failed_threshold
        self._monitoring_completed = False
        
        # Prometheus 指标
        self.blocked_urls_counter = Counter(
            'request_monitor_blocked_urls_total',
            'Total number of URLs blocked due to excessive slow/failed requests',
            ['reason', 'domain']
        )
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否应该启动请求监控"""
        if self._monitoring_completed:
            return ProcessorState.COMPLETED
            
        # 在页面进入就绪状态时启动
        page_state = context.data.get("page_state")
        if page_state == "ready":
            return ProcessorState.READY
            
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """执行请求监控和屏蔽逻辑"""
        slow_requests = context.data.get("slow_requests", {})
        failed_requests = context.data.get("failed_requests", {})
        
        blocked_urls = []
        
        # 检查慢请求超过阈值的URL
        for url, count in slow_requests.items():
            if count > self.slow_threshold:
                blocked_urls.append((url, "slow_requests"))
                domain = self._get_domain(url)
                self.blocked_urls_counter.labels(reason="slow_requests", domain=domain).inc()
                logger.warning(f"屏蔽慢请求URL: {url} (慢请求: {count})")
        
        # 检查失败请求超过阈值的URL
        for url, count in failed_requests.items():
            if count > self.failed_threshold:
                blocked_urls.append((url, "failed_requests"))
                domain = self._get_domain(url)
                self.blocked_urls_counter.labels(reason="failed_requests", domain=domain).inc()
                logger.warning(f"屏蔽失败请求URL: {url} (失败请求: {count})")
        
        # 将屏蔽的URL添加到URL集合中并标记为已屏蔽
        if blocked_urls and hasattr(context, 'url_collection'):
            for url, reason in blocked_urls:
                # 创建URL对象并添加到集合
                blocked_url = URL(id=f"blocked_{hash(url)}", url=url, status=URLStatus.BLOCKED)
                context.url_collection.add(blocked_url)
                logger.info(f"URL已屏蔽: {url} (原因: {reason})")
        
        # 检查是否可以标记完成
        page_state = context.data.get("page_state")
        if page_state == "completed":
            # 检查是否有更高优先级的处理器在运行
            if not self._has_higher_priority_processors_running(context):
                self._monitoring_completed = True
                logger.info(f"请求监控完成: {context.url.url}")
    
    def _get_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"
    
    def _has_higher_priority_processors_running(self, context: PageContext) -> bool:
        """检查是否有优先级更高的处理器在运行"""
        for processor in context.processors:
            if processor.priority < self.priority and processor.state == ProcessorState.RUNNING:
                return True
        return False
    
    async def finish(self, context: PageContext) -> None:
        """清理请求监控器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"请求监控器清理完成: {context.url.url}")


class LinksFinder(PageProcessor):
    """
    链接发现处理器，在页面中发现并收集链接
    
    使用CSS选择器在页面中查找链接，并将其添加到URL集合中。
    """
    
    def __init__(self, name: str, css_selector: str = "a[href]"):
        """
        初始化链接发现处理器
        
        Args:
            name: 处理器名称
            css_selector: CSS选择器，用于查找链接元素
        """
        super().__init__(name, priority=10)
        self.css_selector = css_selector
        self._executed_states: Set[str] = set()
        self._links_found = False
        
        # Prometheus 指标
        self.links_found_counter = Counter(
            'links_finder_links_found_total',
            'Total number of links found',
            ['domain', 'state']
        )
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否应该启动链接发现"""
        if self._links_found:
            return ProcessorState.COMPLETED
            
        # 在页面进入就绪状态时启动
        page_state = context.data.get("page_state")
        if page_state in ["ready", "completed"] and page_state not in self._executed_states:
            return ProcessorState.READY
            
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """执行链接发现"""
        page_state = context.data.get("page_state")
        if page_state in self._executed_states:
            return
            
        domain = self._get_domain(context.url.url)
        
        try:
            # 查找所有匹配的链接元素
            elements = await context.page.query_selector_all(self.css_selector)
            links_found = 0
            
            for element in elements:
                href = await element.get_attribute("href")
                if href and self._is_valid_url(href):
                    # 将相对URL转换为绝对URL
                    absolute_url = await context.page.evaluate(
                        f"new URL('{href}', window.location.href).href"
                    )
                    
                    # 创建URL对象并添加到集合
                    if hasattr(context, 'url_collection'):
                        url_obj = URL(
                            id=f"found_{hash(absolute_url)}", 
                            url=absolute_url,
                            status=URLStatus.PENDING
                        )
                        context.url_collection.add(url_obj)
                        links_found += 1
            
            self._executed_states.add(page_state)
            self.links_found_counter.labels(domain=domain, state=page_state).inc(links_found)
            
            logger.info(f"链接发现完成: {context.url.url}, 状态: {page_state}, 发现链接: {links_found}")
            
            # 如果在加载完成状态执行，标记完成
            if page_state == "completed":
                self._links_found = True
                
        except Exception as e:
            logger.error(f"链接发现失败 {context.url.url}: {e}")
            raise
    
    def _get_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"
    
    def _is_valid_url(self, href: str) -> bool:
        """检查URL是否有效"""
        if not href:
            return False
        href = href.strip()
        return href.startswith(("http://", "https://", "/")) and not href.startswith(("javascript:", "mailto:", "tel:"))
    
    async def finish(self, context: PageContext) -> None:
        """清理链接发现器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"链接发现器清理完成: {context.url.url}")


class ElementCleaner(PageProcessor):
    """
    元素清理处理器，清理页面中的特定元素
    
    使用CSS选择器删除页面中不需要的元素，如广告、导航等。
    """
    
    def __init__(self, name: str, css_selector: str):
        """
        初始化元素清理处理器
        
        Args:
            name: 处理器名称
            css_selector: CSS选择器，用于选择要删除的元素
        """
        super().__init__(name, priority=20)
        self.css_selector = css_selector
        self._cleaning_completed = False
        
        # Prometheus 指标
        self.elements_cleaned_counter = Counter(
            'element_cleaner_elements_cleaned_total',
            'Total number of elements cleaned',
            ['domain', 'selector']
        )
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否应该启动元素清理"""
        if self._cleaning_completed:
            return ProcessorState.COMPLETED
            
        # 在页面进入就绪状态时启动
        page_state = context.data.get("page_state")
        if page_state == "ready":
            return ProcessorState.READY
            
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """执行元素清理"""
        domain = self._get_domain(context.url.url)
        
        try:
            # 执行JavaScript删除元素
            elements_removed = await context.page.evaluate(f"""
                () => {{
                    const elements = document.querySelectorAll('{self.css_selector}');
                    let count = elements.length;
                    elements.forEach(el => el.remove());
                    return count;
                }}
            """)
            
            self.elements_cleaned_counter.labels(
                domain=domain, 
                selector=self.css_selector[:50]  # 限制标签长度
            ).inc(elements_removed)
            
            self._cleaning_completed = True
            context.data["elements_cleaned"] = context.data.get("elements_cleaned", 0) + elements_removed
            
            logger.info(f"元素清理完成: {context.url.url}, 删除元素: {elements_removed}")
            
        except Exception as e:
            logger.error(f"元素清理失败 {context.url.url}: {e}")
            # 标记为放弃
            self._set_state(ProcessorState.CANCELLED)
            raise
    
    def _get_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"
    
    async def finish(self, context: PageContext) -> None:
        """清理元素清理器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"元素清理器清理完成: {context.url.url}")


class ContentFinder(PageProcessor):
    """
    核心内容发现处理器，提取和优化页面的核心内容
    
    使用CSS选择器定位核心内容，并清理周围的非核心元素，
    确保内容适合A4纸尺寸显示。
    """
    
    def __init__(self, name: str, css_selector: str, target_state: str = "ready"):
        """
        初始化核心内容发现处理器
        
        Args:
            name: 处理器名称
            css_selector: CSS选择器，用于选择核心内容元素
            target_state: 目标状态，可选"ready"或"completed"
        """
        super().__init__(name, priority=30)
        self.css_selector = css_selector
        self.target_state = target_state
        self._content_processed = False
        
        # Prometheus 指标
        self.content_processed_counter = Counter(
            'content_finder_content_processed_total',
            'Total number of content sections processed',
            ['domain', 'target_state']
        )
        self.content_size_histogram = Histogram(
            'content_finder_content_size_bytes',
            'Size of processed content in bytes',
            ['domain']
        )
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否应该启动内容处理"""
        if self._content_processed:
            return ProcessorState.COMPLETED
            
        # 在页面进入目标状态时启动
        page_state = context.data.get("page_state")
        if page_state == self.target_state:
            # 检查是否能找到核心内容元素
            try:
                element = await context.page.query_selector(self.css_selector)
                if element:
                    return ProcessorState.READY
                else:
                    logger.warning(f"找不到核心内容元素: {self.css_selector}")
                    self._set_state(ProcessorState.CANCELLED)
                    return ProcessorState.CANCELLED
            except Exception as e:
                logger.error(f"检测核心内容失败: {e}")
                self._set_state(ProcessorState.CANCELLED)
                return ProcessorState.CANCELLED
            
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """执行核心内容处理"""
        domain = self._get_domain(context.url.url)
        
        try:
            # 执行内容清理和优化
            content_info = await context.page.evaluate(f"""
                () => {{
                    const contentElement = document.querySelector('{self.css_selector}');
                    if (!contentElement) {{
                        return {{ success: false, error: 'Content element not found' }};
                    }}
                    
                    let currentElement = contentElement;
                    let cleanedElements = 0;
                    
                    // 向上遍历到body元素，清理兄弟节点
                    while (currentElement && currentElement.tagName !== 'BODY') {{
                        const parent = currentElement.parentElement;
                        if (parent) {{
                            // 删除所有兄弟节点，保留当前元素
                            const siblings = Array.from(parent.children);
                            siblings.forEach(sibling => {{
                                if (sibling !== currentElement) {{
                                    sibling.remove();
                                    cleanedElements++;
                                }}
                            }});
                        }}
                        currentElement = parent;
                    }}
                    
                    // 设置页面样式以适应A4纸张
                    const style = document.createElement('style');
                    style.textContent = `
                        @page {{
                            size: A4;
                            margin: 1cm;
                        }}
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                            line-height: 1.6;
                            color: #333;
                            max-width: 19cm;
                            margin: 0 auto;
                            padding: 0;
                        }}
                        img {{
                            max-width: 100%;
                            height: auto;
                        }}
                        table {{
                            width: 100%;
                            border-collapse: collapse;
                        }}
                        th, td {{
                            border: 1px solid #ddd;
                            padding: 8px;
                            text-align: left;
                        }}
                    `;
                    document.head.appendChild(style);
                    
                    const contentSize = contentElement.innerHTML.length;
                    
                    return {{
                        success: true,
                        cleanedElements: cleanedElements,
                        contentSize: contentSize
                    }};
                }}
            """)
            
            if content_info.get("success"):
                self._content_processed = True
                context.data["core_content_processed"] = True
                context.data["content_size"] = content_info.get("contentSize", 0)
                
                self.content_processed_counter.labels(
                    domain=domain, 
                    target_state=self.target_state
                ).inc()
                self.content_size_histogram.labels(domain=domain).observe(content_info.get("contentSize", 0))
                
                logger.info(
                    f"核心内容处理完成: {context.url.url}, "
                    f"清理元素: {content_info.get('cleanedElements', 0)}, "
                    f"内容大小: {content_info.get('contentSize', 0)} 字节"
                )
            else:
                error = content_info.get("error", "Unknown error")
                logger.error(f"核心内容处理失败: {error}")
                self._set_state(ProcessorState.CANCELLED)
                
        except Exception as e:
            logger.error(f"核心内容处理失败 {context.url.url}: {e}")
            self._set_state(ProcessorState.CANCELLED)
            raise
    
    def _get_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"
    
    async def finish(self, context: PageContext) -> None:
        """清理内容发现器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"内容发现器清理完成: {context.url.url}")


class PdfExporter(PageProcessor):
    """
    PDF导出处理器，将处理后的页面导出为PDF文件
    
    在核心内容处理完成后，将页面导出为PDF文件。
    """
    
    def __init__(self, name: str, output_path: str):
        """
        初始化PDF导出处理器
        
        Args:
            name: 处理器名称
            output_path: PDF输出路径
        """
        super().__init__(name, priority=40)
        self.output_path = output_path
        self._export_completed = False
        
        # Prometheus 指标
        self.pdf_exported_counter = Counter(
            'pdf_exporter_pdfs_exported_total',
            'Total number of PDFs exported',
            ['domain', 'status']
        )
        self.pdf_export_duration = Histogram(
            'pdf_exporter_export_duration_seconds',
            'Time taken to export PDF',
            ['domain']
        )
        self.pdf_file_size = Histogram(
            'pdf_exporter_file_size_bytes',
            'Size of exported PDF files',
            ['domain']
        )
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否应该启动PDF导出"""
        if self._export_completed:
            return ProcessorState.COMPLETED
            
        # 当上下文中有已处理核心内容的标记时启动
        if context.data.get("core_content_processed"):
            return ProcessorState.READY
            
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """执行PDF导出"""
        domain = self._get_domain(context.url.url)
        start_time = time.time()
        
        try:
            # 等待页面完全加载
            await asyncio.sleep(1)
            
            # 生成PDF
            await context.page.pdf(
                path=self.output_path,
                format="A4",
                print_background=True,
                margin={
                    "top": "1cm",
                    "right": "1cm",
                    "bottom": "1cm", 
                    "left": "1cm"
                },
                prefer_css_page_size=True
            )
            
            # 获取文件大小
            import os
            file_size = os.path.getsize(self.output_path) if os.path.exists(self.output_path) else 0
            
            export_duration = time.time() - start_time
            
            self._export_completed = True
            context.data["pdf_exported"] = True
            context.data["pdf_path"] = self.output_path
            context.data["pdf_size"] = file_size
            
            # 记录指标
            self.pdf_exported_counter.labels(domain=domain, status="success").inc()
            self.pdf_export_duration.labels(domain=domain).observe(export_duration)
            self.pdf_file_size.labels(domain=domain).observe(file_size)
            
            logger.info(
                f"PDF导出完成: {context.url.url} -> {self.output_path}, "
                f"大小: {file_size} 字节, 耗时: {export_duration:.2f}s"
            )
            
        except Exception as e:
            self.pdf_exported_counter.labels(domain=domain, status="failed").inc()
            logger.error(f"PDF导出失败 {context.url.url}: {e}")
            self._set_state(ProcessorState.CANCELLED)
            raise
    
    def _get_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"
    
    async def finish(self, context: PageContext) -> None:
        """清理PDF导出器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"PDF导出器清理完成: {context.url.url}")
