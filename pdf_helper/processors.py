"""
页面处理器实现

该模块包含具体的页面处理器实现，用于处理不同的页面任务。
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .protocol import PageContext, PageProcessor, ProcessorState

logger = logging.getLogger(__name__)


class PageLoadProcessor(PageProcessor):
    """页面加载处理器，确保页面完全加载"""
    
    def __init__(self, name: str):
        super().__init__(name)
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
            else:
                return ProcessorState.WAITING
                
        except Exception as e:
            logger.error(f"页面加载检测失败: {e}")
            return ProcessorState.CANCELLED
    
    async def run(self, context: PageContext) -> None:
        """执行页面加载处理"""
        logger.info(f"页面加载完成: {context.url.url}")
        self._load_completed = True
        self._set_state(ProcessorState.COMPLETED)
        
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
    
    def __init__(self, name: str, content_selector: str = "body"):
        super().__init__(name)
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
            else:
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
            self._set_state(ProcessorState.COMPLETED)
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
    
    def __init__(self, name: str, output_dir: str = "/tmp"):
        super().__init__(name)
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
        else:
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
                    "left": "1cm"
                }
            )
            
            # 保存PDF信息到上下文
            context.data["pdf_path"] = pdf_path
            context.data["pdf_generated"] = True
            
            self._pdf_generated = True
            self._set_state(ProcessorState.COMPLETED)
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
    
    def __init__(self, name: str, link_selector: str = "a[href]"):
        super().__init__(name)
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
                    valid_links.append({
                        "url": href,
                        "text": link.get("text", "")[:100],  # 限制文本长度
                        "title": link.get("title", "")[:100]
                    })
            
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
    
    def __init__(self, name: str, output_dir: str = "/tmp"):
        super().__init__(name)
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
                type="png"
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