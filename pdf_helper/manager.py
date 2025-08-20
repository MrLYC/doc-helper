"""
页面管理器实现

该模块实现了基于Chromium的页面管理器，用于并发处理多个网页。
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

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
                 retry_callback: Optional[RetryCallback] = None):
        """
        初始化Chromium页面管理器
        
        Args:
            url_collection: URL集合
            processor_factories: 页面处理器工厂函数列表
            config: 管理器配置
            retry_callback: 重试回调函数
        """
        super().__init__(url_collection, processor_factories, config, retry_callback)
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._active_pages: Dict[str, PageContext] = {}  # url_id -> PageContext
        self._cleanup_queue: Set[str] = set()  # 待清理的URL ID
        self._cancelled_processors: Dict[str, Set[str]] = {}  # url_id -> {processor_name}
    
    async def run(self) -> None:
        """运行页面管理器"""
        logger.info("启动Chromium页面管理器")
        
        async with async_playwright() as p:
            # 1. 创建Chromium浏览器
            await self._create_browser(p)
            
            try:
                while True:
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
                    
            finally:
                await self._cleanup_all()
        
        logger.info("Chromium页面管理器已停止")
    
    async def _create_browser(self, playwright) -> None:
        """创建浏览器和上下文"""
        logger.info("创建Chromium浏览器")
        self._browser = await playwright.chromium.launch(
            headless=self.config.headless
        )
        self._context = await self._browser.new_context()
        logger.info(f"浏览器创建成功，无头模式: {self.config.headless}")
    
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
                page = await self._context.new_page()
                await page.goto(url.url, timeout=self.config.page_timeout * 1000)
                
                # 创建页面上下文
                context = PageContext(page=page, url=url)
                
                # 创建页面处理器
                for factory in self.processor_factories:
                    processor = factory()
                    context.add_processor(processor)
                
                self._active_pages[url.id] = context
                self._cancelled_processors[url.id] = set()
                
                logger.info(f"标签页已打开: {url.url}")
                
            except Exception as e:
                logger.error(f"打开标签页失败 {url.url}: {e}")
                self.url_collection.update_status(url.id, URLStatus.FAILED)
    
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
                new_state = await asyncio.wait_for(
                    processor.detect(context),
                    timeout=self.config.detect_timeout
                )
                processor._set_state(new_state)
                
                if new_state == ProcessorState.READY:
                    # 执行处理器
                    logger.info(f"执行处理器 {processor_name} for {context.url.url}")
                    await processor.run(context)
                    processor._set_state(ProcessorState.COMPLETED)
                    completed_processors.append(processor)
                    
                elif new_state == ProcessorState.COMPLETED:
                    completed_processors.append(processor)
                    
                elif new_state == ProcessorState.CANCELLED:
                    cancelled_processors.add(processor_name)
                    logger.info(f"处理器 {processor_name} 已取消 for {context.url.url}")
                    
                elif new_state == ProcessorState.WAITING:
                    has_waiting_processors = True
                    
            except asyncio.TimeoutError:
                logger.warning(f"处理器 {processor_name} 检测超时 for {context.url.url}")
                has_waiting_processors = True
            except Exception as e:
                logger.error(f"处理器 {processor_name} 执行失败 for {context.url.url}: {e}")
                cancelled_processors.add(processor_name)
        
        self._cancelled_processors[url_id] = cancelled_processors
        
        # 将已完成的处理器放入待清理队列
        for processor in completed_processors:
            self._cleanup_queue.add(f"{url_id}:{processor.name}")
        
        # 5. 检查页面是否完成
        if not has_waiting_processors:
            # 所有处理器都不在等待中，标记URL为已访问并关闭标签页
            logger.info(f"页面处理完成: {context.url.url}")
            self.url_collection.update_status(url_id, URLStatus.VISITED)
            await self._close_page(url_id)
            return
        
        # 6. 检查是否超时
        if current_time - context.start_time > self.config.page_timeout:
            logger.warning(f"页面处理超时: {context.url.url}")
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
        
        # 清理相关数据
        self._cancelled_processors.pop(url_id, None)
        # 清理该页面的待清理项
        items_to_remove = [item for item in self._cleanup_queue if item.startswith(f"{url_id}:")]
        for item in items_to_remove:
            self._cleanup_queue.discard(item)
    
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
        
        # 关闭所有活跃页面
        for url_id in list(self._active_pages.keys()):
            await self._close_page(url_id)
        
        # 关闭浏览器
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        
        logger.info("资源清理完成")


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