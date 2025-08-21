"""
页面管理器实现

该模块实现了基于Chromium的页面管理器，用于并发处理多个网页。
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set

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
    
    def get_active_pages_info(self) -> List[Dict[str, Any]]:
        """获取所有活跃页面的信息"""
        logger.info(f"获取活跃页面信息，当前页面数: {len(self._active_pages)}")
        
        pages_info = []
        for i, (url_id, context) in enumerate(self._active_pages.items()):
            # 获取处理器状态
            processor_states = {}
            for proc_name, processor in context.processors.items():
                processor_states[proc_name] = processor.state.value
            
            # 优先使用URL对象的title属性，如果没有则使用URL路径的最后部分
            if hasattr(context.url, 'title') and context.url.title:
                page_title = context.url.title
            else:
                page_title = context.url.url.split('/')[-1] or "页面"
            
            page_info = {
                "slot": i,
                "url_id": url_id,
                "url": context.url.url,
                "title": page_title,
                "start_time": context.start_time,
                "elapsed_time": time.time() - context.start_time if hasattr(context, 'start_time') else 0,
                "processors": list(context.processors.keys()),
                "processor_states": processor_states,
                "page_closed": context.page.is_closed() if context.page and hasattr(context.page, 'is_closed') else True
            }
            pages_info.append(page_info)
            
        logger.info(f"返回 {len(pages_info)} 个页面信息")
        return pages_info
    
    async def get_page_screenshot(self, slot: int) -> Optional[bytes]:
        """获取指定槽位页面的截图"""
        logger.info(f"请求截图，槽位: {slot}, 当前活跃页面数: {len(self._active_pages)}")
        
        active_pages = list(self._active_pages.items())
        
        if len(active_pages) == 0:
            logger.warning("没有活跃页面可截图")
            return None
        
        if slot < 0 or slot >= len(active_pages):
            logger.warning(f"槽位 {slot} 超出范围 [0, {len(active_pages)-1}]")
            return None
        
        url_id, context = active_pages[slot]
        logger.info(f"开始截图槽位 {slot}，URL: {context.url.url}")
        
        try:
            # 检查页面是否可用，考虑测试环境中的mock对象
            if not context.page:
                logger.error(f"页面对象不存在 (slot={slot}, url_id={url_id})")
                return None
                
            # 安全地检查页面是否已关闭
            try:
                if hasattr(context.page, 'is_closed') and context.page.is_closed():
                    logger.error(f"页面已关闭 (slot={slot}, url_id={url_id})")
                    return None
            except Exception as e:
                # 在测试环境中mock对象可能会抛出异常，继续处理
                logger.debug(f"检查页面状态时出现异常，继续处理: {e}")
            
            # 等待页面加载完成
            try:
                await context.page.wait_for_load_state("networkidle", timeout=3000)
                logger.info(f"页面网络空闲状态确认 (slot={slot})")
            except Exception as e:
                logger.warning(f"等待页面网络空闲状态超时，继续截图 (slot={slot}): {e}")
            
            # 获取页面截图
            logger.info(f"开始生成截图 (slot={slot})")
            screenshot_bytes = await context.page.screenshot(
                type="png",
                full_page=True,
                timeout=10000  # 增加到10秒超时
            )
            
            logger.info(f"截图成功，大小: {len(screenshot_bytes)} bytes (slot={slot})")
            return screenshot_bytes
            
        except Exception as e:
            logger.error(f"获取页面截图失败 (slot={slot}, url_id={url_id}): {e}")
            return None
    
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
                    loop_count = 0
                    while True:
                        try:
                            loop_count += 1
                            logger.debug(f"主循环第 {loop_count} 次迭代开始")
                            
                            # 记录当前状态
                            pending_count = len(self.url_collection.get_by_status(URLStatus.PENDING))
                            active_count = len(self._active_pages)
                            logger.debug(f"当前状态 - pending URLs: {pending_count}, active pages: {active_count}")
                            
                            # 2. 获取待访问的URLs并打开标签页
                            await self._open_new_tabs()
                            
                            # 如果没有活跃页面，检查是否需要重试
                            if not self._active_pages:
                                logger.info(f"没有活跃页面，pending URLs: {pending_count}")
                                
                                # 检查是否所有URL都已处理完成
                                total_urls = len(self.url_collection.get_all_urls())
                                visited_urls = len(self.url_collection.get_by_status(URLStatus.VISITED))
                                failed_urls = len(self.url_collection.get_by_status(URLStatus.FAILED))
                                processed_urls = visited_urls + failed_urls
                                
                                logger.info(f"URL处理状态 - 总计: {total_urls}, 已访问: {visited_urls}, 已失败: {failed_urls}, 待处理: {pending_count}")
                                
                                # 如果所有URL都已处理完成，退出主循环
                                if pending_count == 0 and processed_urls == total_urls:
                                    logger.info(f"所有URL都已处理完成，总计: {total_urls}, 成功: {visited_urls}, 失败: {failed_urls}")
                                    break
                                
                                # 如果还有pending URL但没有活跃页面，尝试重试逻辑
                                if pending_count > 0:
                                    if await self._handle_retry():
                                        logger.info("重试逻辑返回True，继续循环")
                                        continue
                                    else:
                                        logger.info("重试逻辑返回False或无重试，但仍有pending URL")
                                        # 继续尝试一段时间
                                        if loop_count < 10:  # 最多尝试10次
                                            logger.warning(f"仍有 {pending_count} 个pending URL，继续尝试 (第{loop_count}次)")
                                            await asyncio.sleep(2)  # 等待2秒再试
                                            continue
                                        else:
                                            logger.warning(f"已尝试10次，仍有 {pending_count} 个pending URL无法处理，强制退出")
                                            break
                                
                                # 如果没有pending URL但也没有处理完所有URL，可能存在异常情况
                                if pending_count == 0 and processed_urls < total_urls:
                                    remaining_urls = total_urls - processed_urls
                                    logger.warning(f"存在 {remaining_urls} 个URL既不是pending也不是processed状态，可能存在问题")
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
                    
                    # 添加最终的处理统计
                    final_total = len(self.url_collection.get_all_urls())
                    final_visited = len(self.url_collection.get_by_status(URLStatus.VISITED))
                    final_failed = len(self.url_collection.get_by_status(URLStatus.FAILED))
                    final_pending = len(self.url_collection.get_by_status(URLStatus.PENDING))
                    
                    logger.info("="*50)
                    logger.info("页面处理任务完成统计:")
                    logger.info(f"  总 URL 数量: {final_total}")
                    logger.info(f"  成功处理: {final_visited}")
                    logger.info(f"  处理失败: {final_failed}")
                    logger.info(f"  未处理: {final_pending}")
                    if final_total > 0:
                        success_rate = (final_visited / final_total) * 100
                        logger.info(f"  成功率: {success_rate:.1f}%")
                    logger.info("="*50)
                    
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
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            }
            
            logger.info(f"创建浏览器上下文，选项: {context_options}")
            
            self._context = await self._browser.new_context(**context_options)
            
            # 设置默认超时
            timeout_ms = self.config.page_timeout * 1000
            self._context.set_default_timeout(timeout_ms)
            logger.info(f"设置默认超时: {timeout_ms}ms ({self.config.page_timeout}s)")
            
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
            logger.debug("没有可用槽位，跳过打开新标签页")
            return
        
        # 获取待访问的URLs
        pending_urls = self.url_collection.get_by_status(
            URLStatus.PENDING, 
            limit=available_slots,
            oldest_first=True
        )
        
        if not pending_urls:
            logger.debug("没有待访问的URLs")
            return
        
        logger.info(f"打开 {len(pending_urls)} 个新标签页，可用槽位: {available_slots}")
        
        # 为每个URL打开标签页并创建页面上下文
        for url in pending_urls:
            start_time = time.time()
            page = None
            try:
                logger.info(f"开始打开标签页: {url.url}")
                
                # 先将URL标记为正在处理，避免重复处理
                # 注意：这里不改变URL状态，只是为了避免重复选择
                
                page = await self._context.new_page()
                logger.info(f"新页面已创建: {url.url}")
                
                # 在verbose模式下，设置页面标题显示状态
                if self.verbose:
                    try:
                        await page.evaluate(f'''() => {{
                            document.title = "[正在加载...] {url.url}";
                        }}''')
                    except Exception as e:
                        logger.warning(f"设置页面标题失败: {e}")
                
                # 设置页面超时和其他选项
                logger.info(f"开始导航到页面: {url.url}, 超时: {self.config.page_timeout}s")
                
                # 先进行简单的网络测试
                try:
                    import aiohttp
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                        async with session.head(url.url) as resp:
                            logger.info(f"网络预检测成功: {url.url} 状态: {resp.status}")
                except Exception as e:
                    logger.warning(f"网络预检测失败 {url.url}: {e}，继续尝试浏览器加载")
                
                # 使用更详细的导航选项
                try:
                    # 先测试网络连接
                    logger.info(f"测试网络连接: {url.url}")
                    
                    response = await page.goto(
                        url.url, 
                        timeout=self.config.page_timeout * 1000,
                        wait_until="domcontentloaded"  # 等待DOM加载完成即可
                    )
                    
                    if response:
                        logger.info(f"页面响应状态: {response.status} for {url.url}")
                        if response.status >= 400:
                            raise Exception(f"HTTP错误: {response.status} {response.status_text}")
                    else:
                        logger.warning(f"页面响应为空: {url.url}")
                        
                except asyncio.TimeoutError as timeout_error:
                    logger.error(f"页面加载超时 {url.url}: {timeout_error}")
                    raise Exception(f"页面加载超时 ({self.config.page_timeout}s)")
                except Exception as goto_error:
                    logger.error(f"页面导航失败 {url.url}: {type(goto_error).__name__}: {goto_error}")
                    raise goto_error
                
                logger.info(f"页面加载成功: {url.url}")
                
                # 创建页面上下文
                context = PageContext(page=page, url=url)
                context.start_time = start_time  # 记录开始时间
                
                # 创建页面处理器
                logger.info(f"开始创建处理器 for {url.url}")
                processor_count = 0
                for factory in self.processor_factories:
                    try:
                        processor = factory()
                        context.add_processor(processor)
                        processor_count += 1
                        logger.debug(f"处理器 {processor.name} 已创建 for {url.url}")
                    except Exception as e:
                        logger.error(f"创建处理器失败 {url.url}: {e}")
                        self.error_counter.labels(error_type="processor_creation", component="manager").inc()
                
                logger.info(f"创建了 {processor_count} 个处理器 for {url.url}")
                
                self._active_pages[url.id] = context
                self._cancelled_processors[url.id] = set()
                
                # 更新活跃页面数量指标
                self.active_pages_gauge.set(len(self._active_pages))
                
                elapsed_time = time.time() - start_time
                logger.info(f"标签页已成功打开: {url.url} (耗时: {elapsed_time:.2f}s)")
                
            except Exception as e:
                logger.error(f"打开标签页失败 {url.url}: {type(e).__name__}: {e}")
                
                # 关闭已创建的页面
                if page:
                    try:
                        await page.close()
                        logger.info(f"已关闭失败的页面: {url.url}")
                    except Exception as close_error:
                        logger.error(f"关闭失败页面时出错: {close_error}")
                
                self.error_counter.labels(error_type="tab_opening", component="manager").inc()
                self.url_collection.update_status(url.id, URLStatus.FAILED)
                
                # 记录失败的处理耗时
                domain = self._get_domain_from_url(url.url)
                elapsed_time = time.time() - start_time
                self.page_processing_duration.labels(status="failed", url_domain=domain).observe(elapsed_time)
                
                logger.info(f"URL已标记为失败: {url.url}")
        
        logger.info(f"标签页打开完成，当前活跃页面数: {len(self._active_pages)}")
    
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
        
        # 按优先级升序获取处理器列表
        processors_by_priority = context.get_processors_by_priority(reverse=False)
        
        # 4. 遍历每个页面的未执行过的处理器（按优先级顺序）
        for processor in processors_by_priority:
            processor_name = processor.name
            if processor_name in cancelled_processors:
                continue
            
            try:
                # 如果处理器处于RUNNING状态，直接调用run方法
                if processor.state == ProcessorState.RUNNING:
                    logger.debug(f"继续执行运行中的处理器 {processor_name} for {context.url.url}")
                    
                    # 在verbose模式下更新页面标题
                    if self.verbose:
                        try:
                            await context.page.evaluate(f'''() => {{
                                document.title = "[运行中 {processor_name}...] " + document.title.replace(/^\\[.*?\\] /, "");
                            }}''')
                        except:
                            pass
                    
                    run_start = time.time()
                    await processor.run(context)
                    run_duration = time.time() - run_start
                    
                    # 运行完成后设置为COMPLETED状态
                    processor._set_state(ProcessorState.COMPLETED)
                    
                    # 记录处理器完成的指标
                    self.processor_state_counter.labels(
                        processor_name=processor_name,
                        state="completed",
                        result="success"
                    ).inc()
                    
                    logger.debug(f"处理器 {processor_name} 运行完成 for {context.url.url} (耗时: {run_duration:.3f}s)")
                    completed_processors.append(processor)
                    continue
                
                # 对于非RUNNING状态的处理器，先检测状态
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
                    # 执行处理器 - 设置为RUNNING状态
                    processor._set_state(ProcessorState.RUNNING)
                    logger.info(f"开始执行处理器 {processor_name} for {context.url.url}")
                    
                    # 记录RUNNING状态
                    self.processor_state_counter.labels(
                        processor_name=processor_name,
                        state="running",
                        result="success"
                    ).inc()
                    
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
                    
                elif new_state == ProcessorState.RUNNING:
                    # RUNNING状态的处理器也需要继续等待处理
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
        # 按URL分组处理器
        url_processors = {}
        for item in list(self._cleanup_queue):
            try:
                url_id, processor_name = item.split(':', 1)
                if url_id not in url_processors:
                    url_processors[url_id] = []
                url_processors[url_id].append((item, processor_name))
            except Exception as e:
                logger.error(f"解析清理项失败 {item}: {e}")
                self._cleanup_queue.discard(item)
        
        # 对每个URL的处理器按优先级降序处理finish
        for url_id, items in url_processors.items():
            context = self._active_pages.get(url_id)
            if not context:
                # 如果上下文不存在，直接移除清理项
                for item, _ in items:
                    self._cleanup_queue.discard(item)
                continue
            
            # 获取需要清理的处理器并按优先级降序排序
            processors_to_finish = []
            for item, processor_name in items:
                processor = context.get_processor(processor_name)
                if processor and processor.state == ProcessorState.COMPLETED:
                    processors_to_finish.append((item, processor))
            
            # 按优先级降序排序（高优先级的处理器最后finish）
            processors_to_finish.sort(key=lambda x: x[1].priority, reverse=True)
            
            # 执行finish操作
            for item, processor in processors_to_finish:
                try:
                    await processor.finish(context)
                    processor._set_state(ProcessorState.FINISHED)
                    logger.debug(f"处理器 {processor.name} 清理完成 for {context.url.url} (优先级: {processor.priority})")
                    self._cleanup_queue.discard(item)
                except Exception as e:
                    logger.error(f"清理处理器失败 {processor.name}: {e}")
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
    from .processors import PDFExporter
    return PDFExporter("pdf_generator", output_dir="/tmp")