"""
页面处理器实现

该模块包含具体的页面处理器实现，用于处理不同的页面任务。
"""

import logging
import re
import time
import uuid
from collections import defaultdict
from typing import List, Optional
from urllib.parse import urlparse

from playwright.async_api import Request, Response
from prometheus_client import Counter, Gauge, Histogram

from .protocol import PageContext, PageProcessor, ProcessorState, URL, URLCollection, URLStatus

logger = logging.getLogger(__name__)

# Prometheus 指标
page_monitor_slow_requests = Counter(
    "page_monitor_slow_requests_total",
    "监控到的慢请求总数",
    ["domain", "path"],
)

page_monitor_failed_requests = Counter(
    "page_monitor_failed_requests_total",
    "监控到的失败请求总数",
    ["domain", "path", "failure_type"],
)

page_monitor_state_changes = Counter(
    "page_monitor_state_changes_total",
    "页面状态变化总数",
    ["state"],
)

page_monitor_processing_time = Histogram(
    "page_monitor_processing_seconds",
    "页面监控处理时间",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

page_monitor_active_pages = Gauge(
    "page_monitor_active_pages",
    "当前活跃的页面监控数量",
)

# RequestMonitor Prometheus 指标
request_monitor_blocked_urls = Counter(
    "request_monitor_blocked_urls_total",
    "被屏蔽的URL总数",
    ["reason", "domain", "path"],
)

request_monitor_cancelled_requests = Counter(
    "request_monitor_cancelled_requests_total", 
    "被取消的请求总数",
    ["reason", "domain", "path"],
)

request_monitor_processing_time = Histogram(
    "request_monitor_processing_seconds",
    "请求监控处理时间",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

request_monitor_active_monitors = Gauge(
    "request_monitor_active_monitors",
    "当前活跃的请求监控数量",
)

# LinksFinder Prometheus 指标
links_finder_discovered_links = Counter(
    "links_finder_discovered_links_total",
    "发现的链接总数",
    ["domain", "source_domain"],
)

links_finder_valid_links = Counter(
    "links_finder_valid_links_total",
    "有效链接总数",
    ["domain", "source_domain"],
)

links_finder_processing_time = Histogram(
    "links_finder_processing_seconds",
    "链接发现处理时间",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

links_finder_active_finders = Gauge(
    "links_finder_active_finders",
    "当前活跃的链接发现处理器数量",
)

links_found_total = Counter(
    'links_found_total', 
    'Total number of links found',
    ['css_selector']
)

# ElementCleaner 指标
elements_removed_total = Counter(
    'elements_removed_total',
    'Total number of elements removed',
    ['css_selector', 'success']
)

# ContentFinder 指标
content_finder_siblings_removed = Counter(
    'content_finder_siblings_removed_total',
    'Total number of sibling elements removed by ContentFinder',
    ['css_selector', 'level']
)

content_finder_processing_time = Histogram(
    'content_finder_processing_seconds',
    'ContentFinder processing time',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

content_finder_elements_found = Counter(
    'content_finder_elements_found_total',
    'Total number of content elements found',
    ['css_selector', 'found']
)

# PDFExporter 指标
pdf_exporter_success_total = Counter(
    'pdf_exporter_success_total',
    'Total number of successful PDF exports',
    ['format']
)

pdf_exporter_failed_total = Counter(
    'pdf_exporter_failed_total',
    'Total number of failed PDF exports',
    ['reason']
)

pdf_exporter_processing_time = Histogram(
    'pdf_exporter_processing_seconds',
    'PDFExporter processing time',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)


class PageMonitor(PageProcessor):
    """页面监控处理器，监控页面加载状态、慢请求和失败请求"""

    def __init__(self, name: str, page_timeout: float = 60.0, priority: int = 0):
        """
        初始化页面监控处理器

        Args:
            name: 处理器名称
            page_timeout: 页面加载超时时间（秒）
            priority: 优先级，固定为0（最高优先级）

        """
        super().__init__(name, priority)
        self.page_timeout = page_timeout
        self.slow_request_timeout = page_timeout / 10  # 慢请求超时为页面超时的1/10
        self._page_state = "loading"  # loading, ready, completed
        self._request_start_times = {}  # 请求开始时间
        self._monitoring_started = False
        self._start_time = None

    def _remove_query_string(self, url: str) -> str:
        """移除URL中的查询字符串"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _get_domain_path(self, url: str) -> tuple[str, str]:
        """获取URL的域名和路径"""
        parsed = urlparse(url)
        domain = parsed.netloc or "unknown"
        path = parsed.path or "/"
        return domain, path

    async def _on_request(self, request: Request) -> None:
        """请求开始事件处理"""
        self._request_start_times[request.url] = time.time()
        
        # 将请求信息共享给RequestMonitor
        self._context.data.setdefault("pending_requests", {})[request.url] = request
        
        logger.debug(f"请求开始: {request.url}")

    async def _on_response(self, response: Response) -> None:
        """响应事件处理"""
        request_url = response.request.url
        start_time = self._request_start_times.pop(request_url, None)
        
        # 从待处理请求中移除
        pending_requests = self._context.data.get("pending_requests", {})
        pending_requests.pop(request_url, None)

        if start_time:
            duration = time.time() - start_time

            # 检查慢请求
            if duration > self.slow_request_timeout:
                clean_url = self._remove_query_string(request_url)
                domain, path = self._get_domain_path(clean_url)

                logger.warning(f"慢请求检测: {clean_url}, 耗时: {duration:.2f}秒")

                # 更新上下文中的慢请求计数器
                if "slow_requests" not in self._context.data:
                    self._context.data["slow_requests"] = defaultdict(int)
                self._context.data["slow_requests"][clean_url] += 1

                # 更新 Prometheus 指标
                page_monitor_slow_requests.labels(domain=domain, path=path).inc()

        logger.debug(f"响应完成: {request_url}, 状态: {response.status}")

    async def _on_request_failed(self, request: Request) -> None:
        """请求失败事件处理"""
        request_url = request.url
        self._request_start_times.pop(request_url, None)
        
        # 从待处理请求中移除
        pending_requests = self._context.data.get("pending_requests", {})
        pending_requests.pop(request_url, None)

        clean_url = self._remove_query_string(request_url)
        domain, path = self._get_domain_path(clean_url)

        failure_reason = request.failure or "unknown"
        logger.warning(f"请求失败: {clean_url}, 原因: {failure_reason}")

        # 更新上下文中的失败请求计数器
        if "failed_requests" not in self._context.data:
            self._context.data["failed_requests"] = defaultdict(int)
        self._context.data["failed_requests"][clean_url] += 1

        # 更新 Prometheus 指标
        page_monitor_failed_requests.labels(
            domain=domain,
            path=path,
            failure_type=failure_reason,
        ).inc()

    async def _setup_page_listeners(self, page) -> None:
        """设置页面事件监听器"""
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)

        # 监听页面加载状态变化
        page.on("load", self._on_load)
        page.on("domcontentloaded", self._on_dom_content_loaded)

        logger.debug("页面事件监听器已设置")

    async def _on_load(self) -> None:
        """页面load事件处理"""
        if self._page_state == "loading":
            self._page_state = "ready"
            self._context.data["page_state"] = "ready"
            page_monitor_state_changes.labels(state="ready").inc()
            logger.info(f"页面进入load状态: {self._context.url.url}")

    async def _on_dom_content_loaded(self) -> None:
        """DOM内容加载完成事件处理"""
        logger.debug(f"DOM内容加载完成: {self._context.url.url}")

    async def _wait_for_network_idle(self, page, timeout: float = 5.0) -> bool:
        """等待网络空闲状态"""
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
            return True
        except Exception as e:
            logger.debug(f"网络空闲等待超时: {e}")
            return False

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否开始监控"""
        # 如果页面有URL且未开始监控，则开始
        if context.page and context.url and not self._monitoring_started:
            return ProcessorState.READY

        # 如果已经开始监控但未完成，继续运行
        if self._monitoring_started and self._page_state != "completed":
            return ProcessorState.RUNNING

        # 监控完成
        if self._page_state == "completed":
            return ProcessorState.COMPLETED

        return ProcessorState.WAITING

    async def run(self, context: PageContext) -> None:
        """执行页面监控"""
        self._context = context

        if not self._monitoring_started:
            # 初始化监控
            self._monitoring_started = True
            self._start_time = time.time()
            self._page_state = "loading"

            # 设置页面状态
            context.data["page_state"] = "loading"
            page_monitor_state_changes.labels(state="loading").inc()
            page_monitor_active_pages.inc()

            # 初始化请求计数器
            context.data["slow_requests"] = defaultdict(int)
            context.data["failed_requests"] = defaultdict(int)

            # 设置页面监听器
            await self._setup_page_listeners(context.page)

            logger.info(f"开始监控页面: {context.url.url}")

        # 检查页面load状态
        try:
            ready_state = await context.page.evaluate("document.readyState")
            if ready_state == "complete" and self._page_state == "loading":
                self._page_state = "ready"
                context.data["page_state"] = "ready"
                page_monitor_state_changes.labels(state="ready").inc()
                logger.info(f"页面进入load状态: {context.url.url}")
        except Exception as e:
            logger.warning(f"检查页面状态失败: {e}")

        # 检查网络空闲状态
        if self._page_state == "ready":
            network_idle = await self._wait_for_network_idle(context.page, timeout=2.0)
            if network_idle:
                self._page_state = "completed"
                context.data["page_state"] = "completed"
                page_monitor_state_changes.labels(state="completed").inc()
                logger.info(f"页面进入networkidle状态: {context.url.url}")

                # 检查是否有更高优先级的处理器在运行
                running_processors = [
                    p
                    for p in context.processors.values()
                    if p.state == ProcessorState.RUNNING and p.priority < self.priority
                ]

                if not running_processors:
                    logger.info(f"页面监控完成，无更高优先级处理器运行: {context.url.url}")
                else:
                    logger.debug(f"等待更高优先级处理器完成: {[p.name for p in running_processors]}")

        # 记录处理时间
        if self._start_time:
            processing_time = time.time() - self._start_time
            page_monitor_processing_time.observe(processing_time)

    async def finish(self, context: PageContext) -> None:
        """清理页面监控"""
        try:
            # 移除页面事件监听器
            if context.page:
                # Playwright 的事件监听器在页面关闭时会自动清理
                await context.page.close()
                logger.info(f"页面已关闭: {context.url.url}")

            # 更新指标
            page_monitor_active_pages.dec()

            # 清理请求时间记录
            self._request_start_times.clear()

            # 记录统计信息
            slow_count = sum(context.data.get("slow_requests", {}).values())
            failed_count = sum(context.data.get("failed_requests", {}).values())

            logger.info(
                f"页面监控完成: {context.url.url}, 慢请求: {slow_count}, 失败请求: {failed_count}",
            )

        except Exception as e:
            logger.error(f"页面监控清理失败: {e}")
        finally:
            self._set_state(ProcessorState.FINISHED)


class RequestMonitor(PageProcessor):
    """请求监控处理器，监控特殊请求并自动屏蔽问题URL"""

    def __init__(
        self,
        name: str,
        url_collection: URLCollection,
        slow_request_threshold: int = 100,
        failed_request_threshold: int = 10,
        priority: int = 1,
    ):
        """
        初始化请求监控处理器

        Args:
            name: 处理器名称
            url_collection: URL集合，用于添加屏蔽的URL
            slow_request_threshold: 慢请求数量阈值，默认100
            failed_request_threshold: 失败请求数量阈值，默认10
            priority: 优先级，固定为1

        """
        super().__init__(name, priority)
        self.url_collection = url_collection
        self.slow_request_threshold = slow_request_threshold
        self.failed_request_threshold = failed_request_threshold
        self.block_url_patterns = set()  # 存储需要屏蔽的URL模式
        self._compiled_patterns = []  # 编译后的正则表达式模式
        self._monitoring_started = False
        self._start_time = None

    def _remove_query_string(self, url: str) -> str:
        """移除URL中的查询字符串"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def _get_domain_path(self, url: str) -> tuple[str, str]:
        """获取URL的域名和路径"""
        parsed = urlparse(url)
        domain = parsed.netloc or "unknown"
        path = parsed.path or "/"
        return domain, path

    def _block_problematic_url(self, url: str, reason: str, context: PageContext) -> None:
        """将问题URL模式添加到屏蔽列表中"""
        try:
            clean_url = self._remove_query_string(url)
            domain, path = self._get_domain_path(clean_url)
            
            # 添加到屏蔽模式集合
            self.block_url_patterns.add(clean_url)
            
            logger.warning(f"添加URL模式到屏蔽列表: {clean_url}, 原因: {reason}")
            
            # 更新 Prometheus 指标
            request_monitor_blocked_urls.labels(
                reason=reason,
                domain=domain,
                path=path,
            ).inc()
            
            # 记录到上下文
            if "blocked_url_patterns" not in context.data:
                context.data["blocked_url_patterns"] = []
            context.data["blocked_url_patterns"].append({
                "url_pattern": clean_url,
                "reason": reason,
                "blocked_at": time.time(),
            })
                
        except Exception as e:
            logger.error(f"屏蔽URL模式失败 {url}: {e}")

    def _matches_blocked_pattern(self, url: str) -> bool:
        """检查URL是否匹配屏蔽模式"""
        import re
        
        # 编译模式（如果还没编译）
        if not self._compiled_patterns and self.block_url_patterns:
            self._compiled_patterns = [re.compile(pattern) for pattern in self.block_url_patterns]
        
        # 检查URL是否匹配任何模式
        for pattern in self._compiled_patterns:
            if pattern.search(url):
                return True
        return False

    async def _cancel_matching_requests(self, context: PageContext) -> int:
        """取消匹配屏蔽模式的未完成请求"""
        cancelled_count = 0
        
        # 从页面上下文获取当前的pending_requests
        if hasattr(context.page, 'context') and hasattr(context.page.context, 'pending_requests'):
            pending_requests = context.page.context.pending_requests
        else:
            return cancelled_count
        
        # 检查每个未完成的请求
        requests_to_cancel = []
        for request in pending_requests:
            if hasattr(request, 'url') and hasattr(request, 'is_finished'):
                if not request.is_finished() and self._matches_blocked_pattern(request.url):
                    requests_to_cancel.append(request)
        
        # 取消匹配的请求
        for request in requests_to_cancel:
            try:
                if hasattr(request, 'abort'):
                    await request.abort()
                    cancelled_count += 1
                    logger.info(f"已取消匹配模式的请求: {request.url}")
            except Exception as e:
                logger.debug(f"取消请求失败 {request.url}: {e}")
        
        return cancelled_count

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否开始监控"""
        # 在页面进入就绪状态时启动
        page_state = context.data.get("page_state", "loading")
        
        if not self._monitoring_started and page_state in ("ready", "completed"):
            return ProcessorState.READY
        
        # 如果已经开始监控但未完成，继续运行
        if self._monitoring_started and page_state != "completed":
            return ProcessorState.RUNNING
        
        # 页面进入完成状态，检查是否可以结束
        if page_state == "completed":
            # 检查是否有更高优先级的处理器在运行
            running_processors = [
                p
                for p in context.processors.values()
                if p.state == ProcessorState.RUNNING and p.priority < self.priority
            ]
            
            if not running_processors:
                return ProcessorState.COMPLETED
            else:
                return ProcessorState.RUNNING
        
        return ProcessorState.WAITING

    async def run(self, context: PageContext) -> None:
        """执行请求监控"""
        if not self._monitoring_started:
            # 初始化监控
            self._monitoring_started = True
            self._start_time = time.time()
            
            # 更新指标
            request_monitor_active_monitors.inc()
            
            # 初始化上下文数据
            context.data.setdefault("blocked_url_patterns", [])
            
            logger.info(f"开始监控特殊请求: {context.url.url}")
        
        # 检查慢请求阈值
        slow_requests = context.data.get("slow_requests", {})
        for url, count in slow_requests.items():
            if count >= self.slow_request_threshold:
                self._block_problematic_url(
                    url,
                    f"慢请求次数过多({count}>={self.slow_request_threshold})",
                    context,
                )
        
        # 检查失败请求阈值
        failed_requests = context.data.get("failed_requests", {})
        for url, count in failed_requests.items():
            if count >= self.failed_request_threshold:
                self._block_problematic_url(
                    url,
                    f"失败请求次数过多({count}>={self.failed_request_threshold})",
                    context,
                )
        
        # 取消匹配屏蔽模式的未完成请求
        cancelled_count = await self._cancel_matching_requests(context)
        if cancelled_count > 0:
            logger.info(f"取消了 {cancelled_count} 个匹配屏蔽模式的请求")
        
        # 记录处理时间
        if self._start_time:
            processing_time = time.time() - self._start_time
            request_monitor_processing_time.observe(processing_time)

    async def finish(self, context: PageContext) -> None:
        """清理请求监控"""
        try:
            # 更新指标
            request_monitor_active_monitors.dec()
            
            # 记录统计信息
            blocked_patterns_count = len(context.data.get("blocked_url_patterns", []))
            slow_count = sum(context.data.get("slow_requests", {}).values())
            failed_count = sum(context.data.get("failed_requests", {}).values())
            
            logger.info(
                f"请求监控完成: {context.url.url}, "
                f"屏蔽URL模式: {blocked_patterns_count}, 慢请求: {slow_count}, 失败请求: {failed_count}"
            )
            
        except Exception as e:
            logger.error(f"请求监控清理失败: {e}")
        finally:
            self._set_state(ProcessorState.FINISHED)


class LinksFinder(PageProcessor):
    """链接发现处理器，寻找更多的链接并添加到URL集合中"""

    def __init__(
        self,
        name: str,
        url_collection: URLCollection,
        css_selector: str = "body",
        priority: int = 10,
        url_pattern: Optional[str] = None,  # 向后兼容
        url_patterns: Optional[List[str]] = None,
        max_depth: int = 12,
    ):
        """
        初始化链接发现处理器

        Args:
            name: 处理器名称
            url_collection: URL集合，用于添加发现的链接
            css_selector: CSS选择器，指定要搜索链接的容器
            priority: 优先级，固定为10
            url_pattern: 单个URL匹配的正则表达式模式（向后兼容）
            url_patterns: 多个URL匹配的正则表达式模式列表
            max_depth: 基于根目录的最大链接深度

        """
        super().__init__(name, priority)
        self.url_collection = url_collection
        self.css_selector = css_selector
        
        # 处理URL模式参数兼容性
        self.url_patterns = []
        if url_patterns:
            self.url_patterns = url_patterns
        elif url_pattern:
            self.url_patterns = [url_pattern]
        
        self.max_depth = max_depth
        self._ready_executed = False
        self._completed_executed = False
        self._start_time = None
        
        # 编译正则表达式模式
        self._url_regexes = []
        if self.url_patterns:
            try:
                import re
                for pattern in self.url_patterns:
                    regex = re.compile(pattern)
                    self._url_regexes.append(regex)
                logger.info(f"LinksFinder URL模式已设置: {self.url_patterns}")
            except re.error as e:
                logger.error(f"URL模式正则表达式无效: {self.url_patterns}, 错误: {e}")
                self._url_regexes = []

    def _get_domain_path(self, url: str) -> tuple[str, str]:
        """获取URL的域名和路径"""
        parsed = urlparse(url)
        domain = parsed.netloc or "unknown"
        path = parsed.path or "/"
        return domain, path

    def _is_valid_url(self, url: str) -> bool:
        """检查URL是否有效"""
        if not url or not isinstance(url, str):
            return False
        
        url = url.strip()
        if not url:
            return False
        
        # 检查是否是HTTP/HTTPS协议
        if not url.startswith(("http://", "https://")):
            return False
        
        try:
            parsed = urlparse(url)
            return bool(parsed.netloc)
        except Exception:
            return False

    def _matches_url_pattern(self, url: str) -> bool:
        """检查URL是否匹配设定的模式"""
        if not self._url_regexes:
            return True  # 如果没有设置模式，则匹配所有URL
        
        try:
            # 检查是否匹配任何一个模式
            for regex in self._url_regexes:
                if regex.search(url):
                    return True
            return False  # 没有匹配任何模式
        except Exception as e:
            logger.warning(f"URL模式匹配错误: {e}")
            return True  # 出错时默认匹配

    def _calculate_url_depth(self, url: str, base_urls: List[str]) -> int:
        """
        计算URL相对于基础URL的深度
        
        Args:
            url: 要计算深度的URL
            base_urls: 基础URL列表（入口URLs）
            
        Returns:
            URL深度，如果无法计算则返回999
        """
        try:
            from urllib.parse import urlparse
            
            parsed_url = urlparse(url)
            url_path = parsed_url.path.rstrip('/')
            
            min_depth = 999
            
            for base_url in base_urls:
                parsed_base = urlparse(base_url)
                
                # 检查是否是同一域名
                if parsed_url.netloc != parsed_base.netloc:
                    continue
                
                base_path = parsed_base.path.rstrip('/')
                
                # 如果URL路径不是基础路径的子路径，跳过
                if not url_path.startswith(base_path):
                    continue
                
                # 计算深度
                relative_path = url_path[len(base_path):].lstrip('/')
                if not relative_path:
                    depth = 0
                else:
                    depth = len([p for p in relative_path.split('/') if p])
                
                min_depth = min(min_depth, depth)
            
            return min_depth if min_depth != 999 else 0
            
        except Exception as e:
            logger.warning(f"计算URL深度失败: {e}")
            return 0

    def _get_entry_urls(self) -> List[str]:
        """获取入口URL列表"""
        try:
            # 从URL集合中获取category为"entry"的URLs
            all_urls = self.url_collection.get_all_urls()
            entry_urls = [url.url for url in all_urls if url.category == "entry"]
            return entry_urls
        except Exception as e:
            logger.warning(f"获取入口URL失败: {e}")
            return []

    def _generate_url_id(self, url: str) -> str:
        """生成URL的唯一ID"""
        import hashlib
        # 使用URL的hash值和时间戳生成唯一ID
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        timestamp = int(time.time() * 1000) % 100000
        return f"links_{timestamp}_{url_hash}"

    async def _extract_links_from_container(self, page, container_selector: str, source_domain: str) -> list[str]:
        """从指定容器中提取所有有效链接"""
        try:
            # 使用JavaScript在页面中提取链接
            links = await page.evaluate(f"""
                () => {{
                    const container = document.querySelector('{container_selector}');
                    if (!container) return [];
                    
                    const links = [];
                    
                    // 如果容器本身是a标签，添加它
                    if (container.tagName === 'A' && container.href) {{
                        links.push(container.href);
                    }}
                    
                    // 查找容器下的所有a标签
                    const aElements = container.querySelectorAll('a[href]');
                    for (const a of aElements) {{
                        if (a.href) {{
                            links.push(a.href);
                        }}
                    }}
                    
                    return links;
                }}
            """)
            
            # 过滤和验证链接
            valid_links = []
            for link in links:
                if self._is_valid_url(link):
                    valid_links.append(link)
                    
                    # 更新指标
                    link_domain, _ = self._get_domain_path(link)
                    links_finder_valid_links.labels(
                        domain=link_domain,
                        source_domain=source_domain,
                    ).inc()
            
            # 更新发现链接总数指标
            total_discovered = len(links)
            if total_discovered > 0:
                links_finder_discovered_links.labels(
                    domain="all",
                    source_domain=source_domain,
                ).inc(total_discovered)
            
            logger.info(f"从 {container_selector} 提取到 {len(valid_links)} 个有效链接（总共 {total_discovered} 个）")
            return valid_links
            
        except Exception as e:
            logger.error(f"提取链接失败: {e}")
            return []

    async def _add_links_to_collection(self, links: list[str], context: PageContext) -> int:
        """将链接添加到URL集合中"""
        added_count = 0
        filtered_count = 0
        entry_urls = self._get_entry_urls()
        
        for link in links:
            try:
                # 应用URL模式过滤
                if not self._matches_url_pattern(link):
                    filtered_count += 1
                    logger.debug(f"URL不匹配模式，跳过: {link}")
                    continue
                
                # 应用深度过滤
                depth = self._calculate_url_depth(link, entry_urls)
                if depth > self.max_depth:
                    filtered_count += 1
                    logger.debug(f"URL深度({depth})超过限制({self.max_depth})，跳过: {link}")
                    continue
                
                # 生成唯一ID
                url_id = self._generate_url_id(link)
                
                # 创建URL对象
                url_obj = URL(
                    id=url_id,
                    url=link,
                    category="discovered_by_links_finder",
                    status=URLStatus.PENDING,  # 标记为待访问
                )
                
                # 添加到URL集合
                added = self.url_collection.add(url_obj)
                if added:
                    added_count += 1
                    logger.debug(f"添加新链接 (深度: {depth}): {link}")
                else:
                    logger.debug(f"链接已存在: {link}")
                    
            except Exception as e:
                logger.error(f"添加链接失败 {link}: {e}")
        
        if filtered_count > 0:
            logger.info(f"过滤了 {filtered_count} 个链接（模式/深度限制）")
        
        # 记录到上下文
        if "discovered_links" not in context.data:
            context.data["discovered_links"] = []
        
        context.data["discovered_links"].extend([
            {
                "url": link,
                "discovered_at": time.time(),
                "selector": self.css_selector,
            } for link in links
        ])
        
        logger.info(f"成功添加 {added_count} 个新链接到URL集合")
        return added_count

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否开始链接发现"""
        # 在页面进入就绪状态时启动
        page_state = context.data.get("page_state", "loading")
        
        if page_state in ("ready", "completed"):
            return ProcessorState.READY
        
        return ProcessorState.WAITING

    async def run(self, context: PageContext) -> None:
        """执行链接发现"""
        if not self._start_time:
            self._start_time = time.time()
            links_finder_active_finders.inc()
            logger.info(f"开始链接发现: {context.url.url}")
        
        page_state = context.data.get("page_state", "loading")
        source_domain, _ = self._get_domain_path(context.url.url)
        
        # 在页面就绪状态执行一次
        if page_state == "ready" and not self._ready_executed:
            logger.info(f"页面就绪状态 - 执行链接发现: {context.url.url}")
            
            links = await self._extract_links_from_container(
                context.page, 
                self.css_selector, 
                source_domain
            )
            
            if links:
                await self._add_links_to_collection(links, context)
            
            self._ready_executed = True
        
        # 在页面完成状态执行一次
        if page_state == "completed" and not self._completed_executed:
            logger.info(f"页面完成状态 - 执行链接发现: {context.url.url}")
            
            links = await self._extract_links_from_container(
                context.page, 
                self.css_selector, 
                source_domain
            )
            
            if links:
                await self._add_links_to_collection(links, context)
            
            self._completed_executed = True
            
            # 标记执行完成
            logger.info(f"链接发现完成: {context.url.url}")
        
        # 记录处理时间
        if self._start_time:
            processing_time = time.time() - self._start_time
            links_finder_processing_time.observe(processing_time)

    async def finish(self, context: PageContext) -> None:
        """清理链接发现处理器"""
        try:
            # 更新指标
            links_finder_active_finders.dec()
            
            # 记录统计信息
            discovered_count = len(context.data.get("discovered_links", []))
            
            logger.info(f"链接发现完成: {context.url.url}, 发现链接: {discovered_count}")
            
        except Exception as e:
            logger.error(f"链接发现清理失败: {e}")
        finally:
            self._set_state(ProcessorState.FINISHED)


class PageLoadProcessor(PageProcessor):
    """页面加载处理器，确保页面完全加载"""

    def __init__(self, name: str, priority: int = 10):
        """
        初始化页面加载处理器

        Args:
            name: 处理器名称
            priority: 优先级，默认为10（最高优先级）

        """
        super().__init__(name, priority)
        self._load_completed = False

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测页面是否已加载完成"""
        if self._load_completed:
            return ProcessorState.COMPLETED

        try:
            # 检查页面是否已加载
            ready_state = await context.page.evaluate("document.readyState")
            if ready_state == "complete":
                return ProcessorState.READY
            return ProcessorState.WAITING

        except Exception as e:
            logger.error(f"页面加载检测失败: {e}")
            return ProcessorState.CANCELLED

    async def run(self, context: PageContext) -> None:
        """执行页面加载处理"""
        logger.info(f"页面加载完成: {context.url.url}")
        self._load_completed = True
        # 注意：不要在这里设置状态，Manager会负责状态管理

        # 保存页面基本信息到上下文
        context.data["title"] = await context.page.title()
        context.data["page_url"] = context.page.url
        context.data["load_time"] = await context.page.evaluate("performance.now()")

    async def finish(self, context: PageContext) -> None:
        """清理页面加载处理器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"页面加载处理器清理完成: {context.url.url}")


class ContentExtractProcessor(PageProcessor):
    """内容提取处理器，提取页面主要内容"""

    def __init__(self, name: str, content_selector: str = "body", priority: int = 20):
        """
        初始化内容提取处理器

        Args:
            name: 处理器名称
            content_selector: 内容选择器
            priority: 优先级，默认为20（依赖页面加载）

        """
        super().__init__(name, priority)
        self.content_selector = content_selector
        self._content_extracted = False

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否可以提取内容"""
        if self._content_extracted:
            return ProcessorState.COMPLETED

        # 依赖页面加载完成（检查title存在）
        if "title" not in context.data:
            return ProcessorState.WAITING

        try:
            # 检查内容元素是否存在
            element = await context.page.query_selector(self.content_selector)
            if element:
                return ProcessorState.READY
            return ProcessorState.WAITING

        except Exception as e:
            logger.error(f"内容检测失败: {e}")
            return ProcessorState.CANCELLED

    async def run(self, context: PageContext) -> None:
        """执行内容提取"""
        try:
            # 提取文本内容
            text_content = await context.page.evaluate(f"""
                () => {{
                    const element = document.querySelector('{self.content_selector}');
                    return element ? element.innerText : '';
                }}
            """)

            # 提取HTML内容
            html_content = await context.page.evaluate(f"""
                () => {{
                    const element = document.querySelector('{self.content_selector}');
                    return element ? element.innerHTML : '';
                }}
            """)

            # 保存到上下文
            context.data["content"] = text_content
            context.data["html_content"] = html_content
            context.data["content_length"] = len(text_content)

            self._content_extracted = True
            # 注意：不要在这里设置状态，Manager会负责状态管理
            logger.info(f"内容提取完成: {context.url.url}, 长度: {len(text_content)}")

        except Exception as e:
            logger.error(f"内容提取失败 {context.url.url}: {e}")
            raise

    async def finish(self, context: PageContext) -> None:
        """清理内容提取处理器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"内容提取处理器清理完成: {context.url.url}")


class LinkExtractProcessor(PageProcessor):
    """链接提取处理器，提取页面中的链接"""

    def __init__(self, name: str, link_selector: str = "a[href]", priority: int = 30):
        """
        初始化链接提取处理器

        Args:
            name: 处理器名称
            link_selector: 链接选择器
            priority: 优先级，默认为30（依赖页面加载）

        """
        super().__init__(name, priority)
        self.link_selector = link_selector
        self._links_extracted = False

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否可以提取链接"""
        if self._links_extracted:
            return ProcessorState.COMPLETED

        # 依赖页面加载处理器
        page_loader = context.get_processor("page_loader")
        if not page_loader or page_loader.state != ProcessorState.COMPLETED:
            return ProcessorState.WAITING

        return ProcessorState.READY

    async def run(self, context: PageContext) -> None:
        """执行链接提取"""
        try:
            # 提取所有链接
            links = await context.page.evaluate(f"""
                () => {{
                    const links = Array.from(document.querySelectorAll('{self.link_selector}'));
                    return links.map(link => ({{
                        href: link.href,
                        text: link.innerText.trim(),
                        title: link.title || ''
                    }}));
                }}
            """)

            # 过滤和处理链接
            valid_links = []
            for link in links:
                href = link.get("href", "").strip()
                if href and href.startswith(("http://", "https://")):
                    valid_links.append(
                        {
                            "url": href,
                            "text": link.get("text", "")[:100],  # 限制文本长度
                            "title": link.get("title", "")[:100],
                        }
                    )

            # 保存到上下文
            context.data["extracted_links"] = valid_links
            context.data["links_count"] = len(valid_links)

            self._links_extracted = True
            logger.info(f"链接提取完成: {context.url.url}, 发现 {len(valid_links)} 个链接")

        except Exception as e:
            logger.error(f"链接提取失败 {context.url.url}: {e}")
            raise

    async def finish(self, context: PageContext) -> None:
        """清理链接提取处理器"""
        logger.debug(f"链接提取处理器清理完成: {context.url.url}")


class ScreenshotProcessor(PageProcessor):
    """截图处理器，为页面生成截图"""

    def __init__(self, name: str, output_dir: str = "/tmp", priority: int = 50):
        """
        初始化截图处理器

        Args:
            name: 处理器名称
            output_dir: 输出目录
            priority: 优先级，默认为50（依赖页面加载）

        """
        super().__init__(name, priority)
        self.output_dir = output_dir
        self._screenshot_taken = False

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否可以截图"""
        if self._screenshot_taken:
            return ProcessorState.COMPLETED

        # 依赖页面加载处理器
        page_loader = context.get_processor("page_loader")
        if not page_loader or page_loader.state != ProcessorState.COMPLETED:
            return ProcessorState.WAITING

        return ProcessorState.READY

    async def run(self, context: PageContext) -> None:
        """执行截图"""
        try:
            # 生成文件名
            safe_url = context.url.url.replace("://", "_").replace("/", "_").replace("?", "_")
            screenshot_path = f"{self.output_dir}/{safe_url}_{context.url.id}.png"

            # 截图
            await context.page.screenshot(
                path=screenshot_path,
                full_page=True,
                type="png",
            )

            # 保存截图信息到上下文
            context.data["screenshot_path"] = screenshot_path
            context.data["screenshot_taken"] = True

            self._screenshot_taken = True
            logger.info(f"截图完成: {context.url.url} -> {screenshot_path}")

        except Exception as e:
            logger.error(f"截图失败 {context.url.url}: {e}")
            raise

    async def finish(self, context: PageContext) -> None:
        """清理截图处理器"""
        logger.debug(f"截图处理器清理完成: {context.url.url}")


class ElementCleaner(PageProcessor):
    """
    元素清理处理器
    
    用于删除页面中指定CSS选择器匹配的元素，常用于移除广告、弹窗等不需要的内容。
    """
    
    def __init__(self, name: str, css_selector: str = "*[id*='ad'], *[class*='popup']", priority: int = 20) -> None:
        """
        初始化元素清理处理器
        
        Args:
            name: 处理器名称
            css_selector: CSS选择器，用于定位要删除的元素
            priority: 处理器优先级，固定为20
        """
        super().__init__(name, priority)
        self.css_selector = css_selector
        self._elements_removed = 0
        
        logger.info(f"ElementCleaner初始化: CSS选择器='{css_selector}', 优先级={priority}")
    
    async def detect(self, context: PageContext) -> ProcessorState:
        """
        检测是否应该执行元素清理
        
        在页面进入就绪状态时启动
        
        Args:
            context: 页面上下文
            
        Returns:
            ProcessorState: 处理器状态
        """
        # 检查页面状态
        page_state = context.data.get("page_state")
        if page_state in ["ready", "completed"]:
            logger.info(f"ElementCleaner检测到页面就绪，准备清理元素: {context.url.url}")
            return ProcessorState.READY
        
        return ProcessorState.WAITING
    
    async def run(self, context: PageContext) -> None:
        """
        执行元素清理
        
        删除CSS选择器对应的节点，删除完标记成功，否则标记放弃
        
        Args:
            context: 页面上下文
        """
        current_url = context.url
        if not current_url:
            self._set_state(ProcessorState.CANCELLED)
            return
        
        logger.info(f"开始清理元素: {current_url.url}")
        self._elements_removed = 0
        
        try:
            page = context.page
            if not page:
                logger.error("页面对象不存在")
                self._set_state(ProcessorState.CANCELLED)
                return
            
            # 查找匹配的元素
            elements = await page.query_selector_all(self.css_selector)
            if not elements:
                logger.info(f"未找到匹配CSS选择器 '{self.css_selector}' 的元素")
                self._set_state(ProcessorState.COMPLETED)
                elements_removed_total.labels(
                    css_selector=self.css_selector, 
                    success="true"
                ).inc(0)
                return
            
            logger.info(f"找到 {len(elements)} 个匹配元素，开始删除")
            
            # 删除所有匹配的元素
            removed_count = 0
            for element in elements:
                try:
                    await element.evaluate("element => element.remove()")
                    removed_count += 1
                except Exception as e:
                    logger.warning(f"删除元素失败: {e}")
            
            self._elements_removed = removed_count
            
            if removed_count > 0:
                logger.info(f"成功删除 {removed_count} 个元素")
                self._set_state(ProcessorState.COMPLETED)
                
                # 更新上下文数据
                context.data["elements_removed"] = removed_count
                context.data["css_selector_used"] = self.css_selector
                
                # 更新指标
                elements_removed_total.labels(
                    css_selector=self.css_selector,
                    success="true"
                ).inc(removed_count)
            else:
                logger.warning("没有成功删除任何元素")
                self._set_state(ProcessorState.CANCELLED)
                elements_removed_total.labels(
                    css_selector=self.css_selector,
                    success="false"
                ).inc()
            
        except Exception as e:
            logger.error(f"元素清理过程中发生错误: {e}")
            self._set_state(ProcessorState.CANCELLED)
            elements_removed_total.labels(
                css_selector=self.css_selector,
                success="false"
            ).inc()
    
    async def finish(self, context: PageContext) -> None:
        """
        完成元素清理处理
        
        Args:
            context: 页面上下文
        """
        current_url = context.url
        url_str = current_url.url if current_url else "unknown"
        
        if self.state == ProcessorState.COMPLETED:
            logger.info(f"元素清理完成: {url_str}, 删除了 {self._elements_removed} 个元素")
        elif self.state == ProcessorState.CANCELLED:
            logger.warning(f"元素清理取消: {url_str}")
        else:
            logger.info(f"元素清理处理器状态: {self.state.value}")
        
        # 清理临时数据
        self._elements_removed = 0
        
        self._set_state(ProcessorState.FINISHED)


class ContentFinder(PageProcessor):
    """内容查找处理器，保留核心内容并清理其他兄弟节点"""

    def __init__(self, css_selector: str, target_states: list[str] = None, priority: int = 30):
        """
        初始化内容查找处理器

        Args:
            css_selector: 用于查找核心内容的CSS选择器
            target_states: 目标页面状态列表，默认为 ['ready', 'completed']
            priority: 处理器优先级，默认为30
        """
        name = f"content_finder_{uuid.uuid4().hex[:8]}"
        super().__init__(name, priority)
        
        self.css_selector = css_selector
        self.target_states = target_states or ['ready', 'completed']
        self._siblings_removed = 0
        self._processing_start_time = None
        
        logger.info(
            f"ContentFinder初始化: CSS选择器='{css_selector}', "
            f"目标状态={self.target_states}, 优先级={priority}"
        )
        
        # 记录指标
        content_finder_elements_found.labels(
            css_selector=css_selector,
            found='initialized'
        ).inc()

    async def detect(self, context: PageContext) -> ProcessorState:
        """
        检测是否需要启动内容查找
        
        当页面状态符合目标状态且找到CSS选择器对应的元素时启动
        
        Args:
            context: 页面上下文
            
        Returns:
            ProcessorState: 检测后的状态
        """
        current_url = context.url
        url_str = current_url.url if current_url else "unknown"
        
        # 检查页面状态
        page_state = context.data.get("page_state", "loading")
        if page_state not in self.target_states:
            return ProcessorState.WAITING
            
        # 检查页面对象是否存在
        if not context.page:
            logger.warning(f"ContentFinder检测失败，页面对象不存在: {url_str}")
            self._set_state(ProcessorState.CANCELLED)
            return ProcessorState.CANCELLED
            
        try:
            # 查找目标元素
            element = await context.page.query_selector(self.css_selector)
            if element is None:
                logger.warning(
                    f"ContentFinder未找到目标元素，放弃执行: {url_str}, "
                    f"CSS选择器: {self.css_selector}"
                )
                self._set_state(ProcessorState.CANCELLED)
                content_finder_elements_found.labels(
                    css_selector=self.css_selector,
                    found='not_found'
                ).inc()
                return ProcessorState.CANCELLED
                
            logger.info(
                f"ContentFinder检测到目标元素，准备清理兄弟节点: {url_str}, "
                f"CSS选择器: {self.css_selector}"
            )
            
            content_finder_elements_found.labels(
                css_selector=self.css_selector,
                found='found'
            ).inc()
            
            self._set_state(ProcessorState.READY)
            return ProcessorState.READY
            
        except Exception as e:
            logger.error(f"ContentFinder检测过程中发生错误: {url_str}, 错误: {e}")
            self._set_state(ProcessorState.CANCELLED)
            return ProcessorState.CANCELLED

    async def run(self, context: PageContext) -> None:
        """
        执行内容查找和兄弟节点清理
        
        从目标元素开始向上遍历到body，删除所有兄弟节点
        
        Args:
            context: 页面上下文
        """
        current_url = context.url
        url_str = current_url.url if current_url else "unknown"
        
        if not context.page:
            logger.error(f"ContentFinder执行失败，页面对象不存在: {url_str}")
            self._set_state(ProcessorState.CANCELLED)
            return
            
        self._processing_start_time = time.time()
        
        try:
            logger.info(f"开始内容查找和清理: {url_str}")
            
            # 找到目标元素
            target_element = await context.page.query_selector(self.css_selector)
            if target_element is None:
                logger.warning(f"未找到目标元素: {url_str}, CSS选择器: {self.css_selector}")
                self._set_state(ProcessorState.CANCELLED)
                return
                
            # 执行向上遍历和兄弟节点清理的JavaScript代码
            siblings_removed = await context.page.evaluate("""
                (selector) => {
                    const targetElement = document.querySelector(selector);
                    if (!targetElement) {
                        return { totalRemoved: 0, level: 0 };
                    }
                    
                    let totalRemoved = 0;
                    let currentElement = targetElement;
                    let level = 0;
                    
                    // 向上遍历直到body元素
                    while (currentElement && currentElement.tagName.toLowerCase() !== 'body') {
                        const parent = currentElement.parentElement;
                        if (!parent) break;
                        
                        // 获取所有兄弟节点
                        const siblings = Array.from(parent.children);
                        
                        // 删除除当前元素外的所有兄弟节点
                        for (const sibling of siblings) {
                            if (sibling !== currentElement) {
                                sibling.remove();
                                totalRemoved++;
                            }
                        }
                        
                        // 移动到父元素继续向上
                        currentElement = parent;
                        level++;
                    }
                    
                    return { totalRemoved: totalRemoved, level: level };
                }
            """, self.css_selector)
            
            # 确保 siblings_removed 是一个字典
            if not isinstance(siblings_removed, dict):
                logger.warning(f"JavaScript 返回了意外的结果类型: {type(siblings_removed)}, 值: {siblings_removed}")
                siblings_removed = {"totalRemoved": 0, "level": 0}
            
            self._siblings_removed = siblings_removed.get('totalRemoved', 0)
            level = siblings_removed.get('level', 0)
            
            # 记录Prometheus指标
            content_finder_siblings_removed.labels(
                css_selector=self.css_selector,
                level=str(level)
            ).inc(self._siblings_removed)
            
            if self._siblings_removed > 0:
                logger.info(
                    f"内容查找完成: {url_str}, 清理了 {self._siblings_removed} 个兄弟节点，"
                    f"遍历了 {level} 层元素"
                )
                # 标记核心内容已处理
                if hasattr(context, 'data') and context.data is not None:
                    context.data["core_content_processed"] = True
                self._set_state(ProcessorState.COMPLETED)
            else:
                logger.info(f"内容查找完成: {url_str}, 没有需要清理的兄弟节点")
                # 即使没有清理兄弟节点，也认为核心内容已处理
                if hasattr(context, 'data') and context.data is not None:
                    context.data["core_content_processed"] = True
                self._set_state(ProcessorState.COMPLETED)
                
        except Exception as e:
            logger.error(f"内容查找过程中发生错误: {url_str}, 错误: {e}")
            self._set_state(ProcessorState.CANCELLED)
        finally:
            # 记录处理时间
            if self._processing_start_time:
                processing_time = time.time() - self._processing_start_time
                content_finder_processing_time.observe(processing_time)

    async def finish(self, context: PageContext) -> None:
        """
        完成内容查找处理
        
        Args:
            context: 页面上下文
        """
        current_url = context.url
        url_str = current_url.url if current_url else "unknown"
        
        if self.state == ProcessorState.COMPLETED:
            logger.info(f"内容查找完成: {url_str}, 清理了 {self._siblings_removed} 个兄弟节点")
        elif self.state == ProcessorState.CANCELLED:
            logger.warning(f"内容查找取消: {url_str}")
        else:
            logger.info(f"内容查找处理器状态: {self.state.value}")
        
        # 清理临时数据
        self._siblings_removed = 0
        self._processing_start_time = None
        
        self._set_state(ProcessorState.FINISHED)


class PDFExporter(PageProcessor):
    """
    PDF导出处理器
    
    将页面导出为 PDF，支持多种触发条件和灵活的输出路径配置
    """

    def __init__(self, name: str = None, output_path: str = None, output_dir: str = "/tmp", priority: int = 40):
        """
        初始化PDF导出处理器
        
        Args:
            name: 处理器名称，如果不提供则自动生成
            output_path: 完整的PDF输出路径，如果提供则忽略output_dir
            output_dir: PDF输出目录，当output_path为None时使用
            priority: 处理器优先级，默认为40
        """
        if name is None:
            name = f"pdf_exporter_{uuid.uuid4().hex[:8]}"
        super().__init__(name, priority)
        
        self.output_path = output_path
        self.output_dir = output_dir
        self._exported = False
        
        if output_path:
            logger.info(f"PDFExporter初始化: 输出路径='{output_path}', 优先级={priority}")
        else:
            logger.info(f"PDFExporter初始化: 输出目录='{output_dir}', 优先级={priority}")

    def _generate_pdf_path(self, context: PageContext) -> str:
        """
        生成PDF输出路径
        
        Args:
            context: 页面上下文
            
        Returns:
            str: 生成的PDF路径
        """
        if self.output_path:
            return self.output_path
        
        # 生成安全的文件名
        safe_url = context.url.url.replace("://", "_").replace("/", "_").replace("?", "_").replace(":", "_")
        # 限制文件名长度，避免过长
        if len(safe_url) > 100:
            safe_url = safe_url[:100]
        
        return f"{self.output_dir}/{safe_url}_{context.url.id}.pdf"

    async def detect(self, context: PageContext) -> ProcessorState:
        """
        检测是否应该启动PDF导出
        
        支持多种触发条件：
        1. 有核心内容已处理标记时（优先）
        2. 有内容提取完成时
        3. 页面加载完成时（兜底）
        
        Args:
            context: 页面上下文
            
        Returns:
            ProcessorState: 检测后的状态
        """
        if self._exported:
            return ProcessorState.COMPLETED
        
        # 条件1: 检查是否有核心内容已处理的标记（ContentFinder完成后）
        if context.data.get("core_content_processed", False):
            logger.info(f"PDFExporter检测到核心内容已处理，准备导出PDF: {context.url.url}")
            return ProcessorState.READY
        
        # 条件2: 检查是否有内容提取完成（ContentExtractProcessor完成后）
        if "content" in context.data and context.data.get("content_length", 0) > 0:
            logger.info(f"PDFExporter检测到内容提取完成，准备导出PDF: {context.url.url}")
            return ProcessorState.READY
        
        # 条件3: 兜底条件 - 页面加载完成且有标题
        if "title" in context.data and context.data.get("title"):
            logger.info(f"PDFExporter检测到页面加载完成，准备导出PDF: {context.url.url}")
            return ProcessorState.READY
        
        return ProcessorState.WAITING

    async def run(self, context: PageContext) -> None:
        """
        执行PDF导出
        
        将当前页面作为 PDF 输出到指定路径
        
        Args:
            context: 页面上下文
        """
        current_url = context.url
        url_str = current_url.url if current_url else "unknown"
        
        page = context.page
        if not page:
            logger.error(f"PDFExporter: 页面对象不存在，无法导出 PDF: {url_str}")
            pdf_exporter_failed_total.labels(reason="no_page_object").inc()
            self._set_state(ProcessorState.CANCELLED)
            return
        
        # 生成输出路径
        pdf_path = self._generate_pdf_path(context)
        
        # 确保输出目录存在
        import os
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        
        start_time = time.time()
        try:
            logger.info(f"开始PDF导出: {url_str} -> {pdf_path}")
            
            await page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={
                    "top": "1cm",
                    "right": "1cm",
                    "bottom": "1cm",
                    "left": "1cm",
                },
            )
            
            # 更新上下文数据
            context.data["pdf_exported"] = True
            context.data["pdf_path"] = pdf_path
            context.data["pdf_generated"] = True  # 保持向后兼容
            self._exported = True
            
            # 记录成功指标
            processing_time = time.time() - start_time
            pdf_exporter_processing_time.observe(processing_time)
            pdf_exporter_success_total.labels(format="A4").inc()
            
            logger.info(f"PDFExporter: PDF 导出成功 -> {pdf_path}")
            self._set_state(ProcessorState.COMPLETED)
            
        except Exception as e:
            # 记录失败指标
            processing_time = time.time() - start_time
            pdf_exporter_processing_time.observe(processing_time)
            pdf_exporter_failed_total.labels(reason="pdf_generation_error").inc()
            
            logger.error(f"PDFExporter: PDF 导出失败: {url_str}, 错误: {e}")
            self._set_state(ProcessorState.CANCELLED)

    async def finish(self, context: PageContext) -> None:
        """
        完成PDF导出处理
        
        Args:
            context: 页面上下文
        """
        current_url = context.url
        url_str = current_url.url if current_url else "unknown"
        
        if self.state == ProcessorState.COMPLETED:
            pdf_path = context.data.get("pdf_path", "unknown")
            logger.info(f"PDFExporter: 完成导出 {url_str} -> {pdf_path}")
        elif self.state == ProcessorState.CANCELLED:
            logger.warning(f"PDFExporter: 导出取消 {url_str}")
        else:
            logger.info(f"PDFExporter处理器状态: {self.state.value}")
        
        # 清理临时数据
        self._exported = False
        
        self._set_state(ProcessorState.FINISHED)


# 为了向后兼容，保留旧的类名作为别名
PdfExporter = PDFExporter
