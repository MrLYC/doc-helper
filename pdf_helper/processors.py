"""
页面处理器实现

该模块包含具体的页面处理器实现，用于处理不同的页面任务。
"""

import logging
import time
from collections import defaultdict
from urllib.parse import urlparse

from playwright.async_api import Request, Response
from prometheus_client import Counter, Gauge, Histogram

from .protocol import PageContext, PageProcessor, ProcessorState

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
        logger.debug(f"请求开始: {request.url}")

    async def _on_response(self, response: Response) -> None:
        """响应事件处理"""
        request_url = response.request.url
        start_time = self._request_start_times.pop(request_url, None)

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


class PDFGenerateProcessor(PageProcessor):
    """PDF生成处理器，将页面转换为PDF"""

    def __init__(self, name: str, output_dir: str = "/tmp", priority: int = 40):
        """
        初始化PDF生成处理器

        Args:
            name: 处理器名称
            output_dir: 输出目录
            priority: 优先级，默认为40（依赖内容提取）

        """
        super().__init__(name, priority)
        self.output_dir = output_dir
        self._pdf_generated = False

    async def detect(self, context: PageContext) -> ProcessorState:
        """检测是否可以生成PDF"""
        if self._pdf_generated:
            return ProcessorState.COMPLETED

        # 依赖内容提取完成
        if "content" not in context.data:
            return ProcessorState.WAITING

        # 检查是否有内容
        if context.data.get("content_length", 0) > 0:
            return ProcessorState.READY
        logger.warning(f"页面无内容，跳过PDF生成: {context.url.url}")
        return ProcessorState.CANCELLED

    async def run(self, context: PageContext) -> None:
        """执行PDF生成"""
        try:
            # 生成文件名
            safe_url = context.url.url.replace("://", "_").replace("/", "_").replace("?", "_")
            pdf_path = f"{self.output_dir}/{safe_url}_{context.url.id}.pdf"

            # 生成PDF
            await context.page.pdf(
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

            # 保存PDF信息到上下文
            context.data["pdf_path"] = pdf_path
            context.data["pdf_generated"] = True

            self._pdf_generated = True
            # 注意：不要在这里设置状态，Manager会负责状态管理
            logger.info(f"PDF生成完成: {context.url.url} -> {pdf_path}")

        except Exception as e:
            logger.error(f"PDF生成失败 {context.url.url}: {e}")
            raise

    async def finish(self, context: PageContext) -> None:
        """清理PDF生成处理器"""
        self._set_state(ProcessorState.FINISHED)
        logger.debug(f"PDF生成处理器清理完成: {context.url.url}")


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
