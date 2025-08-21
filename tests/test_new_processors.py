"""
新处理器的单元测试
"""

import pytest
import asyncio
import time
import tempfile
import os
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from pdf_helper.new_processors import (
    PageMonitor, RequestMonitor, LinksFinder, ElementCleaner, ContentFinder, PdfExporter
)
from pdf_helper.protocol import URL, PageContext, ProcessorState, URLStatus, URLCollection


class TestPageMonitor:
    """页面监控处理器的测试"""
    
    @pytest.fixture
    def mock_page_context(self):
        """创建模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.on = Mock()
        mock_page.evaluate = AsyncMock()
        
        url = URL(id="1", url="https://example.com", status=URLStatus.PENDING)
        context = PageContext(page=mock_page, url=url)
        context.start_time = time.time()
        return context
    
    @pytest.mark.asyncio
    async def test_page_monitor_initialization(self):
        """测试页面监控器初始化"""
        monitor = PageMonitor("page_monitor", slow_request_timeout=5.0)
        
        assert monitor.name == "page_monitor"
        assert monitor.priority == 0  # 固定优先级
        assert monitor.slow_request_timeout == 5.0
        assert monitor.state == ProcessorState.WAITING
        assert not monitor._monitoring_started
        assert monitor._page_state == "loading"
    
    @pytest.mark.asyncio
    async def test_page_monitor_detect_pending_url(self, mock_page_context):
        """测试页面监控器检测待访问URL"""
        monitor = PageMonitor("page_monitor")
        
        # 有待访问的URL时应该就绪
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_page_monitor_detect_visited_url(self, mock_page_context):
        """测试页面监控器检测已访问URL"""
        monitor = PageMonitor("page_monitor")
        mock_page_context.url.status = URLStatus.VISITED
        
        # 已访问的URL时应该等待
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    async def test_page_monitor_run_starts_monitoring(self, mock_page_context):
        """测试页面监控器启动监控"""
        monitor = PageMonitor("page_monitor", slow_request_timeout=3.0)
        
        await monitor.run(mock_page_context)
        
        assert monitor._monitoring_started
        assert mock_page_context.page.on.call_count >= 5  # 至少注册5个事件监听器
        assert "slow_requests" in mock_page_context.data
        assert "failed_requests" in mock_page_context.data
        assert "page_state" in mock_page_context.data
    
    @pytest.mark.asyncio
    async def test_page_monitor_default_timeout_calculation(self, mock_page_context):
        """测试页面监控器默认超时计算"""
        monitor = PageMonitor("page_monitor")  # 不设置超时
        
        # 模拟页面超时设置
        mock_page_context.page._timeout_settings = {"timeout": 30000}  # 30秒
        
        await monitor.run(mock_page_context)
        
        # 应该是页面超时的1/10
        assert monitor.slow_request_timeout == 3.0
    
    def test_page_monitor_get_domain(self):
        """测试域名提取"""
        monitor = PageMonitor("page_monitor")
        
        assert monitor._get_domain("https://example.com/path") == "example.com"
        assert monitor._get_domain("http://test.org:8080") == "test.org:8080"
        assert monitor._get_domain("invalid-url") == "unknown"
    
    def test_page_monitor_remove_query_string(self):
        """测试查询字符串移除"""
        monitor = PageMonitor("page_monitor")
        
        result = monitor._remove_query_string("https://example.com/path?param=1&other=2")
        assert result == "https://example.com/path"
        
        result = monitor._remove_query_string("https://example.com/")
        assert result == "https://example.com/"


class TestRequestMonitor:
    """请求监控处理器的测试"""
    
    @pytest.fixture
    def mock_page_context_with_url_collection(self):
        """创建带URL集合的模拟页面上下文"""
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        context.url_collection = URLCollection()
        context.data = {
            "page_state": "ready",
            "slow_requests": {"https://slow.example.com/api": 150},
            "failed_requests": {"https://failed.example.com/resource": 15}
        }
        return context
    
    @pytest.mark.asyncio
    async def test_request_monitor_initialization(self):
        """测试请求监控器初始化"""
        monitor = RequestMonitor("request_monitor", slow_threshold=50, failed_threshold=5)
        
        assert monitor.name == "request_monitor"
        assert monitor.priority == 1
        assert monitor.slow_threshold == 50
        assert monitor.failed_threshold == 5
        assert not monitor._monitoring_completed
    
    @pytest.mark.asyncio
    async def test_request_monitor_detect_ready_state(self, mock_page_context_with_url_collection):
        """测试请求监控器检测就绪状态"""
        monitor = RequestMonitor("request_monitor")
        
        state = await monitor.detect(mock_page_context_with_url_collection)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_request_monitor_detect_waiting_state(self, mock_page_context_with_url_collection):
        """测试请求监控器检测等待状态"""
        monitor = RequestMonitor("request_monitor")
        mock_page_context_with_url_collection.data["page_state"] = "loading"
        
        state = await monitor.detect(mock_page_context_with_url_collection)
        assert state == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    async def test_request_monitor_blocks_slow_urls(self, mock_page_context_with_url_collection):
        """测试请求监控器屏蔽慢请求URL"""
        monitor = RequestMonitor("request_monitor", slow_threshold=100, failed_threshold=10)
        
        await monitor.run(mock_page_context_with_url_collection)
        
        # 检查是否有URL被屏蔽
        url_collection = mock_page_context_with_url_collection.url_collection
        blocked_urls = [url for url in url_collection.urls.values() if url.status == URLStatus.BLOCKED]
        
        assert len(blocked_urls) >= 1
        # 验证慢请求URL被屏蔽
        slow_url_blocked = any("slow.example.com" in url.url for url in blocked_urls)
        assert slow_url_blocked
    
    @pytest.mark.asyncio
    async def test_request_monitor_blocks_failed_urls(self, mock_page_context_with_url_collection):
        """测试请求监控器屏蔽失败请求URL"""
        monitor = RequestMonitor("request_monitor", slow_threshold=200, failed_threshold=10)
        
        await monitor.run(mock_page_context_with_url_collection)
        
        # 检查是否有URL被屏蔽
        url_collection = mock_page_context_with_url_collection.url_collection
        blocked_urls = [url for url in url_collection.urls.values() if url.status == URLStatus.BLOCKED]
        
        assert len(blocked_urls) >= 1
        # 验证失败请求URL被屏蔽
        failed_url_blocked = any("failed.example.com" in url.url for url in blocked_urls)
        assert failed_url_blocked


class TestLinksFinder:
    """链接发现处理器的测试"""
    
    @pytest.fixture
    def mock_page_context_with_links(self):
        """创建带链接的模拟页面上下文"""
        mock_page = AsyncMock()
        
        # 模拟链接元素
        mock_elements = [
            Mock(get_attribute=AsyncMock(return_value="https://example.com/page1")),
            Mock(get_attribute=AsyncMock(return_value="/relative/path")),
            Mock(get_attribute=AsyncMock(return_value="javascript:void(0)")),  # 无效链接
        ]
        mock_page.query_selector_all = AsyncMock(return_value=mock_elements)
        mock_page.evaluate = AsyncMock(side_effect=[
            "https://example.com/page1",
            "https://example.com/relative/path"
        ])
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        context.url_collection = URLCollection()
        context.data = {"page_state": "ready"}
        return context
    
    @pytest.mark.asyncio
    async def test_links_finder_initialization(self):
        """测试链接发现器初始化"""
        finder = LinksFinder("links_finder", css_selector="a.link")
        
        assert finder.name == "links_finder"
        assert finder.priority == 10
        assert finder.css_selector == "a.link"
        assert not finder._links_found
        assert len(finder._executed_states) == 0
    
    @pytest.mark.asyncio
    async def test_links_finder_detect_ready_state(self, mock_page_context_with_links):
        """测试链接发现器检测就绪状态"""
        finder = LinksFinder("links_finder")
        
        state = await finder.detect(mock_page_context_with_links)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_links_finder_detect_completed_state(self, mock_page_context_with_links):
        """测试链接发现器检测完成状态"""
        finder = LinksFinder("links_finder")
        mock_page_context_with_links.data["page_state"] = "completed"
        
        state = await finder.detect(mock_page_context_with_links)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_links_finder_finds_links(self, mock_page_context_with_links):
        """测试链接发现器查找链接"""
        finder = LinksFinder("links_finder")
        
        await finder.run(mock_page_context_with_links)
        
        # 检查是否找到了链接
        url_collection = mock_page_context_with_links.url_collection
        found_urls = [url for url in url_collection.urls.values() if url.status == URLStatus.PENDING]
        
        assert len(found_urls) >= 1  # 至少找到一个有效链接
        assert "ready" in finder._executed_states
    
    @pytest.mark.asyncio
    async def test_links_finder_completes_on_final_state(self, mock_page_context_with_links):
        """测试链接发现器在最终状态完成"""
        finder = LinksFinder("links_finder")
        mock_page_context_with_links.data["page_state"] = "completed"
        
        await finder.run(mock_page_context_with_links)
        
        assert finder._links_found
        assert "completed" in finder._executed_states
    
    def test_links_finder_url_validation(self):
        """测试链接发现器URL验证"""
        finder = LinksFinder("links_finder")
        
        assert finder._is_valid_url("https://example.com")
        assert finder._is_valid_url("http://example.com")
        assert finder._is_valid_url("/relative/path")
        assert not finder._is_valid_url("javascript:void(0)")
        assert not finder._is_valid_url("mailto:test@example.com")
        assert not finder._is_valid_url("")
        assert not finder._is_valid_url(None)


class TestElementCleaner:
    """元素清理处理器的测试"""
    
    @pytest.fixture
    def mock_page_context_with_elements(self):
        """创建带元素的模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=5)  # 模拟删除5个元素
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        context.data = {"page_state": "ready"}
        return context
    
    @pytest.mark.asyncio
    async def test_element_cleaner_initialization(self):
        """测试元素清理器初始化"""
        cleaner = ElementCleaner("element_cleaner", css_selector=".ads")
        
        assert cleaner.name == "element_cleaner"
        assert cleaner.priority == 20
        assert cleaner.css_selector == ".ads"
        assert not cleaner._cleaning_completed
    
    @pytest.mark.asyncio
    async def test_element_cleaner_detect_ready_state(self, mock_page_context_with_elements):
        """测试元素清理器检测就绪状态"""
        cleaner = ElementCleaner("element_cleaner", ".ads")
        
        state = await cleaner.detect(mock_page_context_with_elements)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_element_cleaner_detect_waiting_state(self, mock_page_context_with_elements):
        """测试元素清理器检测等待状态"""
        cleaner = ElementCleaner("element_cleaner", ".ads")
        mock_page_context_with_elements.data["page_state"] = "loading"
        
        state = await cleaner.detect(mock_page_context_with_elements)
        assert state == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    async def test_element_cleaner_cleans_elements(self, mock_page_context_with_elements):
        """测试元素清理器清理元素"""
        cleaner = ElementCleaner("element_cleaner", ".ads")
        
        await cleaner.run(mock_page_context_with_elements)
        
        assert cleaner._cleaning_completed
        assert mock_page_context_with_elements.data["elements_cleaned"] == 5
        mock_page_context_with_elements.page.evaluate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_element_cleaner_handles_errors(self, mock_page_context_with_elements):
        """测试元素清理器错误处理"""
        cleaner = ElementCleaner("element_cleaner", ".ads")
        mock_page_context_with_elements.page.evaluate.side_effect = Exception("JavaScript error")
        
        with pytest.raises(Exception):
            await cleaner.run(mock_page_context_with_elements)
        
        assert cleaner.state == ProcessorState.CANCELLED


class TestContentFinder:
    """核心内容发现处理器的测试"""
    
    @pytest.fixture
    def mock_page_context_with_content(self):
        """创建带内容的模拟页面上下文"""
        mock_page = AsyncMock()
        
        # 模拟找到内容元素
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        # 模拟JavaScript执行结果
        mock_page.evaluate = AsyncMock(return_value={
            "success": True,
            "cleanedElements": 10,
            "contentSize": 5000
        })
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        context.data = {"page_state": "ready"}
        return context
    
    @pytest.mark.asyncio
    async def test_content_finder_initialization(self):
        """测试内容发现器初始化"""
        finder = ContentFinder("content_finder", css_selector="article", target_state="completed")
        
        assert finder.name == "content_finder"
        assert finder.priority == 30
        assert finder.css_selector == "article"
        assert finder.target_state == "completed"
        assert not finder._content_processed
    
    @pytest.mark.asyncio
    async def test_content_finder_detect_target_state_with_element(self, mock_page_context_with_content):
        """测试内容发现器检测目标状态且有元素"""
        finder = ContentFinder("content_finder", "article")
        
        state = await finder.detect(mock_page_context_with_content)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_content_finder_detect_target_state_without_element(self, mock_page_context_with_content):
        """测试内容发现器检测目标状态但无元素"""
        finder = ContentFinder("content_finder", "article")
        mock_page_context_with_content.page.query_selector = AsyncMock(return_value=None)
        
        state = await finder.detect(mock_page_context_with_content)
        assert state == ProcessorState.CANCELLED
    
    @pytest.mark.asyncio
    async def test_content_finder_detect_wrong_state(self, mock_page_context_with_content):
        """测试内容发现器检测错误状态"""
        finder = ContentFinder("content_finder", "article", target_state="completed")
        mock_page_context_with_content.data["page_state"] = "ready"
        
        state = await finder.detect(mock_page_context_with_content)
        assert state == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    async def test_content_finder_processes_content(self, mock_page_context_with_content):
        """测试内容发现器处理内容"""
        finder = ContentFinder("content_finder", "article")
        
        await finder.run(mock_page_context_with_content)
        
        assert finder._content_processed
        assert mock_page_context_with_content.data["core_content_processed"] is True
        assert mock_page_context_with_content.data["content_size"] == 5000
        mock_page_context_with_content.page.evaluate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_content_finder_handles_processing_failure(self, mock_page_context_with_content):
        """测试内容发现器处理失败"""
        finder = ContentFinder("content_finder", "article")
        mock_page_context_with_content.page.evaluate = AsyncMock(return_value={
            "success": False,
            "error": "Content processing failed"
        })
        
        await finder.run(mock_page_context_with_content)
        
        assert finder.state == ProcessorState.CANCELLED
        assert not finder._content_processed


class TestPdfExporter:
    """PDF导出处理器的测试"""
    
    @pytest.fixture
    def mock_page_context_with_processed_content(self):
        """创建带已处理内容的模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.pdf = AsyncMock()
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        context.data = {"core_content_processed": True}
        return context
    
    @pytest.fixture
    def temp_pdf_path(self):
        """创建临时PDF文件路径"""
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temp_file.close()
        yield temp_file.name
        # 清理
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
    
    @pytest.mark.asyncio
    async def test_pdf_exporter_initialization(self, temp_pdf_path):
        """测试PDF导出器初始化"""
        exporter = PdfExporter("pdf_exporter", temp_pdf_path)
        
        assert exporter.name == "pdf_exporter"
        assert exporter.priority == 40
        assert exporter.output_path == temp_pdf_path
        assert not exporter._export_completed
    
    @pytest.mark.asyncio
    async def test_pdf_exporter_detect_with_processed_content(self, mock_page_context_with_processed_content, temp_pdf_path):
        """测试PDF导出器检测已处理内容"""
        exporter = PdfExporter("pdf_exporter", temp_pdf_path)
        
        state = await exporter.detect(mock_page_context_with_processed_content)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_pdf_exporter_detect_without_processed_content(self, temp_pdf_path):
        """测试PDF导出器检测未处理内容"""
        exporter = PdfExporter("pdf_exporter", temp_pdf_path)
        
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        context.data = {}  # 没有已处理内容标记
        
        state = await exporter.detect(context)
        assert state == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    @patch('os.path.getsize')
    async def test_pdf_exporter_exports_pdf(self, mock_getsize, mock_page_context_with_processed_content, temp_pdf_path):
        """测试PDF导出器导出PDF"""
        mock_getsize.return_value = 1024  # 模拟文件大小
        exporter = PdfExporter("pdf_exporter", temp_pdf_path)
        
        await exporter.run(mock_page_context_with_processed_content)
        
        assert exporter._export_completed
        assert mock_page_context_with_processed_content.data["pdf_exported"] is True
        assert mock_page_context_with_processed_content.data["pdf_path"] == temp_pdf_path
        assert mock_page_context_with_processed_content.data["pdf_size"] == 1024
        
        # 验证PDF生成方法被调用
        mock_page_context_with_processed_content.page.pdf.assert_called_once()
        
        # 验证PDF参数
        call_args = mock_page_context_with_processed_content.page.pdf.call_args
        assert call_args.kwargs["path"] == temp_pdf_path
        assert call_args.kwargs["format"] == "A4"
        assert call_args.kwargs["print_background"] is True
    
    @pytest.mark.asyncio
    async def test_pdf_exporter_handles_export_failure(self, mock_page_context_with_processed_content, temp_pdf_path):
        """测试PDF导出器处理导出失败"""
        exporter = PdfExporter("pdf_exporter", temp_pdf_path)
        mock_page_context_with_processed_content.page.pdf.side_effect = Exception("PDF generation failed")
        
        with pytest.raises(Exception):
            await exporter.run(mock_page_context_with_processed_content)
        
        assert exporter.state == ProcessorState.CANCELLED
        assert not exporter._export_completed


class TestProcessorIntegration:
    """处理器集成测试"""
    
    @pytest.fixture
    def integrated_context(self):
        """创建集成测试上下文"""
        mock_page = AsyncMock()
        mock_page.on = Mock()
        mock_page.evaluate = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=Mock())
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.pdf = AsyncMock()
        
        url = URL(id="1", url="https://example.com", status=URLStatus.PENDING)
        context = PageContext(page=mock_page, url=url)
        context.url_collection = URLCollection()
        context.start_time = time.time()
        return context
    
    @pytest.mark.asyncio
    async def test_processor_workflow(self, integrated_context):
        """测试处理器工作流程"""
        # 创建处理器链
        page_monitor = PageMonitor("page_monitor")
        request_monitor = RequestMonitor("request_monitor") 
        links_finder = LinksFinder("links_finder")
        element_cleaner = ElementCleaner("element_cleaner", ".ads")
        content_finder = ContentFinder("content_finder", "article")
        
        processors = [page_monitor, request_monitor, links_finder, element_cleaner, content_finder]
        
        # 将处理器添加到上下文
        for processor in processors:
            integrated_context.add_processor(processor)
        
        # 模拟页面监控器启动
        assert await page_monitor.detect(integrated_context) == ProcessorState.READY
        await page_monitor.run(integrated_context)
        
        # 模拟页面状态变化为就绪
        integrated_context.data["page_state"] = "ready"
        
        # 测试其他处理器是否按预期工作
        assert await request_monitor.detect(integrated_context) == ProcessorState.READY
        assert await links_finder.detect(integrated_context) == ProcessorState.READY
        assert await element_cleaner.detect(integrated_context) == ProcessorState.READY
        assert await content_finder.detect(integrated_context) == ProcessorState.READY
        
        # 运行内容处理器并设置内容已处理标记
        integrated_context.page.evaluate = AsyncMock(return_value={
            "success": True,
            "cleanedElements": 5,
            "contentSize": 3000
        })
        await content_finder.run(integrated_context)
        
        assert integrated_context.data.get("core_content_processed") is True


if __name__ == "__main__":
    pytest.main([__file__])
