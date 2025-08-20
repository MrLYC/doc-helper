"""
页面管理器实现

该模块实现了基于Chromium的页面管理器，用于并发处理多个网页。
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest

from .protocol import (
    PageContext, PageManager, PageManagerConfig, PageProcessor,
    ProcessorState, RetryCallback, URL, URLCollection, URLStatus
)

logger = logging.getLogger(__name__)


class ChromiumManager(PageManager):
    """基于Chromium的页面管理器"""
    
    def __init__(self, 
                 url_collection: URLCollection,
                 processor_factories: List[callable],
                 config: PageManagerConfig,
                 retry_callback: Optional[RetryCallback] = None,
                 verbose: bool = False):
        """
        初始化Chromium页面管理器
        
        Args:
            url_collection: URL集合
            processor_factories: 页面处理器工厂函数列表
            config: 管理器配置
            retry_callback: 重试回调函数
            verbose: 是否启用可视化模式（显示浏览器界面）
        """
        super().__init__(url_collection, processor_factories, config, retry_callback)
        self.verbose = verbose
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._active_pages: Dict[str, PageContext] = {}  # url_id -> PageContext
        self._cleanup_queue: Set[str] = set()  # 待清理的URL ID
        self._cancelled_processors: Dict[str, Set[str]] = {}  # url_id -> {processor_name}
        
        # Prometheus指标初始化
        self._setup_metrics()
    
    def _setup_metrics(self) -> None:
        """设置Prometheus指标"""
        
        # 创建自定义注册表
        self.metrics_registry = CollectorRegistry()
        
        # URL状态计数器
        self.url_status_gauge = Gauge(
            'chromium_manager_url_status_count',
            'URL集合各状态的数量',
            ['status'],
            registry=self.metrics_registry
        )
        
        # 页面访问耗时直方图
        self.page_processing_duration = Histogram(
            'chromium_manager_page_processing_duration_seconds',
            '页面处理耗时（秒）',
            ['status', 'url_domain'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, float('inf')],
            registry=self.metrics_registry
        )
        
        # 页面大小直方图
        self.page_content_size = Histogram(
            'chromium_manager_page_content_size_bytes',
            '页面内容大小（字节）',
            ['url_domain'],
            buckets=[1024, 10240, 102400, 1048576, 10485760, 104857600, float('inf')],
            registry=self.metrics_registry
        )
        
        # 活跃页面数量
        self.active_pages_gauge = Gauge(
            'chromium_manager_active_pages_count',
            '当前活跃页面数量',
            registry=self.metrics_registry
        )
        
        # 处理器状态计数器
        self.processor_state_counter = Counter(
            'chromium_manager_processor_state_total',
            '处理器状态变化总数',
            ['processor_name', 'state', 'result'],
            registry=self.metrics_registry
        )
        
        # 错误计数器
        self.error_counter = Counter(
            'chromium_manager_errors_total',
            '错误总数',
            ['error_type', 'component'],
            registry=self.metrics_registry
        )
        
        logger.info("Prometheus指标已设置")
    
    def get_metrics(self) -> bytes:
        """获取Prometheus格式的指标数据"""
        
        # 更新URL状态指标
        self._update_url_status_metrics()
        
        # 更新活跃页面数量
        self.active_pages_gauge.set(len(self._active_pages))
        
        return generate_latest(self.metrics_registry)
    
    def _update_url_status_metrics(self) -> None:
        """更新URL状态指标"""
        try:
            # 获取各状态的URL数量
            for status in URLStatus:
                count = len(self.url_collection.get_by_status(status))
                self.url_status_gauge.labels(status=status.value).set(count)
        except Exception as e:
            logger.error(f"更新URL状态指标失败: {e}")
            self.error_counter.labels(error_type="metrics_update", component="url_status").inc()
    
    def _get_domain_from_url(self, url: str) -> str:
        """从URL提取域名"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or "unknown"
        except Exception:
            return "unknown"
    
    async def run(self) -> None:
        """运行页面管理器"""
        logger.info(f"启动Chromium页面管理器 (verbose={self.verbose})")
        
        try:
            async with async_playwright() as p:
                # 1. 创建Chromium浏览器
                await self._create_browser(p)
                
                try:
                    while True:
                        try:
                            # 2. 获取待访问的URLs并打开标签页
                            await self._open_new_tabs()
                            
                            # 如果没有活跃页面，检查是否需要重试
                            if not self._active_pages:
                                if await self._handle_retry():
                                    continue
                                else:
                                    break
                            
                            # 3-6. 处理活跃页面
                            await self._process_active_pages()
                            
                            # 等待轮询间隔
                            await asyncio.sleep(self.config.poll_interval)
                            
                        except asyncio.CancelledError:
                            logger.info("页面管理器收到取消信号")
                            break
                        except Exception as e:
                            logger.error(f"页面管理器主循环发生错误: {e}")
                            self.error_counter.labels(error_type="main_loop", component="manager").inc()
                            # 继续运行，不因单次错误而退出
                            await asyncio.sleep(1)
                            
                finally:
                    await self._cleanup_all()
                    
        except Exception as e:
            logger.error(f"页面管理器启动失败: {e}")
            self.error_counter.labels(error_type="startup", component="manager").inc()
            raise
        
        logger.info("Chromium页面管理器已停止")
    
    async def _create_browser(self, playwright) -> None:
        """创建浏览器和上下文"""
        try:
            logger.info("创建Chromium浏览器")
            
            # 根据verbose模式决定是否显示浏览器界面
            browser_args = []
            if not self.verbose:
                browser_args.extend([
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--disable-setuid-sandbox',
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled'
                ])
            
            self._browser = await playwright.chromium.launch(
                headless=not self.verbose,  # verbose模式下显示浏览器界面
                args=browser_args
            )
            
            # 创建浏览器上下文
            context_options = {
                'viewport': {'width': 1920, 'height': 1080},
                'ignore_https_errors': True,
                'java_script_enabled': True,
                'bypass_csp': True,
                'extra_http_headers': {
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            }
            
            self._context = await self._browser.new_context(**context_options)
            
            # 设置默认超时
            self._context.set_default_timeout(self.config.page_timeout * 1000)
            
            mode = "可视化" if self.verbose else "无头"
            logger.info(f"浏览器创建成功，模式: {mode}")
            
        except Exception as e:
            logger.error(f"创建浏览器失败: {e}")
            self.error_counter.labels(error_type="browser_creation", component="manager").inc()
            raise
    
    async def _open_new_tabs(self) -> None:
        """获取待访问的URLs并打开新标签页"""
        # 计算还能打开多少个标签页
        available_slots = self.config.max_concurrent_tabs - len(self._active_pages)
        if available_slots <= 0:
            return
        
        # 获取待访问的URLs
        pending_urls = self.url_collection.get_by_status(
            URLStatus.PENDING, 
            limit=available_slots,
            oldest_first=True
        )
        
        if not pending_urls:
            return
        
        logger.info(f"打开 {len(pending_urls)} 个新标签页")
        
        # 为每个URL打开标签页并创建页面上下文
        for url in pending_urls:
            try:
                start_time = time.time()
                page = await self._context.new_page()
                
                # 在verbose模式下，设置页面标题显示状态
                if self.verbose:
                    await page.evaluate(f'''() => {{
                        document.title = "[正在加载...] {url.url}";
                    }}''')
                
                await page.goto(url.url, timeout=self.config.page_timeout * 1000)
                
                # 创建页面上下文
                context = PageContext(page=page, url=url)
                context.start_time = start_time  # 记录开始时间
                
                # 创建页面处理器
                for factory in self.processor_factories:
                    try:
                        processor = factory()
                        context.add_processor(processor)
                    except Exception as e:
                        logger.error(f"创建处理器失败 {url.url}: {e}")
                        self.error_counter.labels(error_type="processor_creation", component="manager").inc()
                
                self._active_pages[url.id] = context
                self._cancelled_processors[url.id] = set()
                
                # 更新活跃页面数量指标
                self.active_pages_gauge.set(len(self._active_pages))
                
                logger.info(f"标签页已打开: {url.url}")
                
            except Exception as e:
                logger.error(f"打开标签页失败 {url.url}: {e}")
                self.error_counter.labels(error_type="tab_opening", component="manager").inc()
                self.url_collection.update_status(url.id, URLStatus.FAILED)
                
                # 记录失败的处理耗时
                domain = self._get_domain_from_url(url.url)
                elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
                self.page_processing_duration.labels(status="failed", url_domain=domain).observe(elapsed_time)
    
    async def _process_active_pages(self) -> None:
        """处理所有活跃页面"""
        current_time = time.time()
        
        for url_id, context in list(self._active_pages.items()):
            try:
                await self._process_single_page(context, current_time)
            except Exception as e:
                logger.error(f"处理页面失败 {context.url.url}: {e}")
                self.url_collection.update_status(url_id, URLStatus.FAILED)
                await self._close_page(url_id)
        
        # 处理清理队列
        await self._process_cleanup_queue()
    
    async def _process_single_page(self, context: PageContext, current_time: float) -> None:
        """处理单个页面"""
        url_id = context.url.id
        cancelled_processors = self._cancelled_processors.get(url_id, set())
        
        has_waiting_processors = False
        completed_processors = []
        
        # 4. 遍历每个页面的未执行过的处理器
        for processor_name, processor in context.processors.items():
            if processor_name in cancelled_processors:
                continue
            
            try:
                # 检测处理器状态
                detect_start = time.time()
                new_state = await asyncio.wait_for(
                    processor.detect(context),
                    timeout=self.config.detect_timeout
                )
                processor._set_state(new_state)
                
                # 记录处理器状态变化
                self.processor_state_counter.labels(
                    processor_name=processor_name,
                    state=new_state.value,
                    result="success"
                ).inc()
                
                if new_state == ProcessorState.READY:
                    # 执行处理器
                    logger.info(f"执行处理器 {processor_name} for {context.url.url}")
                    
                    # 在verbose模式下更新页面标题
                    if self.verbose:
                        try:
                            await context.page.evaluate(f'''() => {{
                                document.title = "[执行 {processor_name}...] " + document.title.replace(/^\\[.*?\\] /, "");
                            }}''')
                        except:
                            pass
                    
                    run_start = time.time()
                    await processor.run(context)
                    run_duration = time.time() - run_start
                    
                    processor._set_state(ProcessorState.COMPLETED)
                    completed_processors.append(processor)
                    
                    logger.info(f"处理器 {processor_name} 执行完成，耗时: {run_duration:.2f}s")
                    
                elif new_state == ProcessorState.COMPLETED:
                    completed_processors.append(processor)
                    
                elif new_state == ProcessorState.CANCELLED:
                    cancelled_processors.add(processor_name)
                    logger.info(f"处理器 {processor_name} 已取消 for {context.url.url}")
                    self.processor_state_counter.labels(
                        processor_name=processor_name,
                        state="cancelled",
                        result="cancelled"
                    ).inc()
                    
                elif new_state == ProcessorState.WAITING:
                    has_waiting_processors = True
                    
            except asyncio.TimeoutError:
                logger.warning(f"处理器 {processor_name} 检测超时 for {context.url.url}")
                has_waiting_processors = True
                self.error_counter.labels(error_type="processor_timeout", component=processor_name).inc()
                self.processor_state_counter.labels(
                    processor_name=processor_name,
                    state="timeout",
                    result="error"
                ).inc()
            except Exception as e:
                logger.error(f"处理器 {processor_name} 执行失败 for {context.url.url}: {e}")
                cancelled_processors.add(processor_name)
                self.error_counter.labels(error_type="processor_error", component=processor_name).inc()
                self.processor_state_counter.labels(
                    processor_name=processor_name,
                    state="error",
                    result="error"
                ).inc()
        
        self._cancelled_processors[url_id] = cancelled_processors
        
        # 将已完成的处理器放入待清理队列
        for processor in completed_processors:
            self._cleanup_queue.add(f"{url_id}:{processor.name}")
        
        # 5. 检查页面是否完成
        if not has_waiting_processors:
            # 所有处理器都不在等待中，标记URL为已访问并关闭标签页
            total_duration = current_time - context.start_time
            domain = self._get_domain_from_url(context.url.url)
            
            # 记录页面处理成功的指标
            self.page_processing_duration.labels(status="success", url_domain=domain).observe(total_duration)
            
            # 记录页面内容大小
            try:
                content_length = context.data.get("content_length", 0)
                if content_length > 0:
                    self.page_content_size.labels(url_domain=domain).observe(content_length)
            except Exception as e:
                logger.debug(f"记录页面大小指标失败: {e}")
            
            logger.info(f"页面处理完成: {context.url.url} (耗时: {total_duration:.2f}s)")
            self.url_collection.update_status(url_id, URLStatus.VISITED)
            await self._close_page(url_id)
            return
        
        # 6. 检查是否超时
        if current_time - context.start_time > self.config.page_timeout:
            total_duration = current_time - context.start_time
            domain = self._get_domain_from_url(context.url.url)
            
            # 记录超时的指标
            self.page_processing_duration.labels(status="timeout", url_domain=domain).observe(total_duration)
            self.error_counter.labels(error_type="page_timeout", component="manager").inc()
            
            logger.warning(f"页面处理超时: {context.url.url} (耗时: {total_duration:.2f}s)")
            self.url_collection.update_status(url_id, URLStatus.FAILED)
            await self._close_page(url_id)
    
    async def _process_cleanup_queue(self) -> None:
        """处理清理队列"""
        for item in list(self._cleanup_queue):
            try:
                url_id, processor_name = item.split(':', 1)
                context = self._active_pages.get(url_id)
                if context:
                    processor = context.get_processor(processor_name)
                    if processor and processor.state == ProcessorState.COMPLETED:
                        await processor.finish(context)
                        processor._set_state(ProcessorState.FINISHED)
                        logger.debug(f"处理器 {processor_name} 清理完成 for {context.url.url}")
                
                self._cleanup_queue.discard(item)
                
            except Exception as e:
                logger.error(f"清理处理器失败 {item}: {e}")
                self._cleanup_queue.discard(item)
    
    async def _close_page(self, url_id: str) -> None:
        """关闭页面并清理资源"""
        context = self._active_pages.pop(url_id, None)
        if context:
            try:
                await context.page.close()
                logger.debug(f"标签页已关闭: {context.url.url}")
            except Exception as e:
                logger.error(f"关闭标签页失败 {context.url.url}: {e}")
                self.error_counter.labels(error_type="page_close", component="manager").inc()
        
        # 清理相关数据
        self._cancelled_processors.pop(url_id, None)
        # 清理该页面的待清理项
        items_to_remove = [item for item in self._cleanup_queue if item.startswith(f"{url_id}:")]
        for item in items_to_remove:
            self._cleanup_queue.discard(item)
        
        # 更新活跃页面数量指标
        self.active_pages_gauge.set(len(self._active_pages))
    
    async def _handle_retry(self) -> bool:
        """处理重试逻辑"""
        # 8. 检查是否有失败的URL需要重试
        failed_urls = self.url_collection.get_by_status(URLStatus.FAILED)
        
        if failed_urls and self.retry_callback:
            logger.info(f"发现 {len(failed_urls)} 个失败的URL，调用重试回调")
            
            try:
                should_retry = self.retry_callback(failed_urls)
                if should_retry:
                    logger.info("重试回调返回True，重新标记失败的URL为待访问")
                    for url in failed_urls:
                        self.url_collection.update_status(url.id, URLStatus.PENDING)
                    return True
                else:
                    logger.info("重试回调返回False，不进行重试")
            except Exception as e:
                logger.error(f"重试回调执行失败: {e}")
        
        return False
    
    async def _cleanup_all(self) -> None:
        """清理所有资源"""
        logger.info("清理所有资源")
        
        try:
            # 关闭所有活跃页面
            for url_id in list(self._active_pages.keys()):
                await self._close_page(url_id)
            
            # 关闭浏览器上下文
            if self._context:
                try:
                    await self._context.close()
                    logger.debug("浏览器上下文已关闭")
                except Exception as e:
                    logger.error(f"关闭浏览器上下文失败: {e}")
                    self.error_counter.labels(error_type="context_close", component="manager").inc()
            
            # 关闭浏览器
            if self._browser:
                try:
                    await self._browser.close()
                    logger.debug("浏览器已关闭")
                except Exception as e:
                    logger.error(f"关闭浏览器失败: {e}")
                    self.error_counter.labels(error_type="browser_close", component="manager").inc()
            
            logger.info("资源清理完成")
            
        except Exception as e:
            logger.error(f"资源清理过程中发生错误: {e}")
            self.error_counter.labels(error_type="cleanup", component="manager").inc()


# 示例处理器工厂函数
def create_page_loader() -> PageProcessor:
    """创建页面加载处理器"""
    from .processors import PageLoadProcessor
    return PageLoadProcessor("page_loader")


def create_content_extractor() -> PageProcessor:
    """创建内容提取处理器"""
    from .processors import ContentExtractProcessor
    return ContentExtractProcessor("content_extractor")


def create_pdf_generator() -> PageProcessor:
    """创建PDF生成处理器"""
    from .processors import PDFGenerateProcessor
    return PDFGenerateProcessor("pdf_generator")