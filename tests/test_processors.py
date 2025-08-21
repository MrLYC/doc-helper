"""
页面处理器的单元测试
"""

import pytest
import time
from unittest.mock import AsyncMock, Mock
from collections import defaultdict

from pdf_helper.processors import (
    PageLoadProcessor, ContentExtractProcessor, PDFGenerateProcessor, PageMonitor, RequestMonitor
)
from pdf_helper.protocol import URL, URLCollection, URLStatus, PageContext, ProcessorState


class TestProcessors:
    """处理器的测试"""
    
    @pytest.fixture
    def mock_url_collection(self):
        """创建模拟URL集合"""
        return URLCollection()
    
    @pytest.fixture
    def mock_page_context(self):
        """创建模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.title.return_value = "Test Page"
        mock_page.content.return_value = "<html><body>Test Content</body></html>"
        mock_page.pdf = AsyncMock(return_value=b"fake pdf content")
        mock_page.evaluate.return_value = "complete"  # document.readyState
        mock_page.query_selector.return_value = True  # 元素存在
        mock_page.close = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.on = Mock()  # 事件监听器
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        return context
    
    @pytest.fixture
    def mock_request(self):
        """创建模拟请求对象"""
        mock_request = Mock()
        mock_request.url = "https://example.com/api/data"
        mock_request.failure = None
        return mock_request
    
    @pytest.fixture
    def mock_response(self):
        """创建模拟响应对象"""
        mock_response = Mock()
        mock_response.status = 200
        mock_response.request = Mock()
        mock_response.request.url = "https://example.com/api/data"
        return mock_response
    
    @pytest.mark.asyncio
    async def test_page_load_processor(self, mock_page_context):
        """测试页面加载处理器"""
        processor = PageLoadProcessor("loader")
        
        # 测试初始状态
        assert processor.state == ProcessorState.WAITING
        
        # 测试检测 - 页面应该立即就绪
        state = await processor.detect(mock_page_context)
        assert state == ProcessorState.READY
        
        # 测试运行 - 处理器不再自己设置状态
        await processor.run(mock_page_context)
        # 验证内部完成标志而不是状态
        assert processor._load_completed == True
        assert "title" in mock_page_context.data
        assert mock_page_context.data["title"] == "Test Page"
        
        # 模拟Manager设置COMPLETED状态
        processor._set_state(ProcessorState.COMPLETED)
        assert processor.state == ProcessorState.COMPLETED
        
        # 测试完成
        await processor.finish(mock_page_context)
        assert processor.state == ProcessorState.FINISHED
    
    @pytest.mark.asyncio
    async def test_content_extract_processor(self, mock_page_context):
        """测试内容提取处理器"""
        processor = ContentExtractProcessor("extractor")
        
        # 没有页面加载数据时应该等待
        state = await processor.detect(mock_page_context)
        assert state == ProcessorState.WAITING
        
        # 添加页面加载数据
        mock_page_context.data["title"] = "Test Page"
        
        # 现在应该就绪
        state = await processor.detect(mock_page_context)
        assert state == ProcessorState.READY
        
        # 模拟内容提取的JavaScript执行结果
        mock_page_context.page.evaluate.side_effect = ["Test Content", "<body>Test Content</body>"]
        
        # 测试运行 - 处理器不再自己设置状态
        await processor.run(mock_page_context)
        # 验证内部完成标志而不是状态
        assert processor._content_extracted == True
        assert "content" in mock_page_context.data
        
        # 模拟Manager设置COMPLETED状态
        processor._set_state(ProcessorState.COMPLETED)
        assert processor.state == ProcessorState.COMPLETED
        
        # 测试完成
        await processor.finish(mock_page_context)
        assert processor.state == ProcessorState.FINISHED
    
    @pytest.mark.asyncio
    async def test_processor_dependencies(self, mock_page_context):
        """测试处理器依赖关系"""
        loader = PageLoadProcessor("loader")
        extractor = ContentExtractProcessor("extractor")
        pdf_gen = PDFGenerateProcessor("pdf_generator")
        
        # 初始状态：只有loader就绪
        assert await loader.detect(mock_page_context) == ProcessorState.READY
        assert await extractor.detect(mock_page_context) == ProcessorState.WAITING
        assert await pdf_gen.detect(mock_page_context) == ProcessorState.WAITING
        
        # 运行loader
        await loader.run(mock_page_context)
        # 验证loader的内部状态而不是ProcessorState
        assert loader._load_completed == True
        
        # 现在extractor应该就绪
        assert await extractor.detect(mock_page_context) == ProcessorState.READY
        assert await pdf_gen.detect(mock_page_context) == ProcessorState.WAITING
        
        # 模拟内容提取
        mock_page_context.page.evaluate.side_effect = ["Test Content", "<body>Test Content</body>"]
        
        # 运行extractor
        await extractor.run(mock_page_context)
        # 验证extractor的内部状态
        assert extractor._content_extracted == True
        
        # 现在pdf_gen应该就绪
        assert await pdf_gen.detect(mock_page_context) == ProcessorState.READY
        
        # 运行pdf_gen
        await pdf_gen.run(mock_page_context)
        # 验证pdf_gen的内部状态
        assert pdf_gen._pdf_generated == True
        
        # 验证数据已正确保存到上下文
        assert "title" in mock_page_context.data
        assert "content" in mock_page_context.data
        assert "pdf_generated" in mock_page_context.data
    
    @pytest.mark.asyncio
    async def test_page_monitor_initialization(self, mock_page_context):
        """测试页面监控处理器初始化"""
        monitor = PageMonitor("monitor", page_timeout=30.0)
        
        # 测试初始状态
        assert monitor.priority == 0  # 固定优先级
        assert monitor.page_timeout == 30.0
        assert monitor.slow_request_timeout == 3.0  # 1/10的页面超时
        assert monitor._page_state == "loading"
        assert not monitor._monitoring_started
    
    @pytest.mark.asyncio
    async def test_page_monitor_detect(self, mock_page_context):
        """测试页面监控检测逻辑"""
        monitor = PageMonitor("monitor")
        
        # 初始状态应该就绪
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.READY
        
        # 开始监控后应该运行
        monitor._monitoring_started = True
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.RUNNING
        
        # 完成后应该完成
        monitor._page_state = "completed"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.COMPLETED
    
    @pytest.mark.asyncio
    async def test_page_monitor_run_initialization(self, mock_page_context):
        """测试页面监控运行初始化"""
        monitor = PageMonitor("monitor", page_timeout=20.0)
        
        # 模拟页面还在加载中
        mock_page_context.page.evaluate.return_value = "loading"
        mock_page_context.page.wait_for_load_state.side_effect = Exception("Network not idle")
        
        # 运行监控
        await monitor.run(mock_page_context)
        
        # 验证初始化
        assert monitor._monitoring_started
        assert mock_page_context.data["page_state"] == "loading"
        assert "slow_requests" in mock_page_context.data
        assert "failed_requests" in mock_page_context.data
        
        # 验证页面监听器设置
        mock_page_context.page.on.assert_called()
    
    @pytest.mark.asyncio
    async def test_page_monitor_state_transitions(self, mock_page_context):
        """测试页面状态转换"""
        monitor = PageMonitor("monitor")
        
        # 模拟页面还在加载中
        mock_page_context.page.evaluate.return_value = "loading"
        mock_page_context.page.wait_for_load_state.side_effect = Exception("Network not idle")
        
        # 初始化监控
        await monitor.run(mock_page_context)
        assert monitor._page_state == "loading"
        
        # 模拟页面ready状态
        mock_page_context.page.evaluate.return_value = "complete"
        await monitor.run(mock_page_context)
        assert monitor._page_state == "ready"
        
        # 模拟网络空闲
        mock_page_context.page.wait_for_load_state.side_effect = None
        mock_page_context.page.wait_for_load_state.return_value = None
        await monitor.run(mock_page_context)
        
        # 验证状态转换
        assert monitor._page_state == "completed"
        assert mock_page_context.data["page_state"] == "completed"
    
    @pytest.mark.asyncio
    async def test_page_monitor_slow_request_detection(self, mock_page_context, mock_request, mock_response):
        """测试慢请求检测"""
        monitor = PageMonitor("monitor", page_timeout=10.0)  # 慢请求超时为1秒
        monitor._context = mock_page_context
        
        # 模拟请求开始
        await monitor._on_request(mock_request)
        assert mock_request.url in monitor._request_start_times
        
        # 模拟慢响应(手动设置较早的开始时间)
        import time
        monitor._request_start_times[mock_request.url] = time.time() - 2.0  # 2秒前
        
        await monitor._on_response(mock_response)
        
        # 验证慢请求记录
        expected_url = "https://example.com/api/data"
        assert expected_url in mock_page_context.data["slow_requests"]
        assert mock_page_context.data["slow_requests"][expected_url] == 1
    
    @pytest.mark.asyncio
    async def test_page_monitor_failed_request_detection(self, mock_page_context, mock_request):
        """测试失败请求检测"""
        monitor = PageMonitor("monitor")
        monitor._context = mock_page_context
        
        # 设置请求失败原因
        mock_request.failure = "net::ERR_CONNECTION_REFUSED"
        
        await monitor._on_request_failed(mock_request)
        
        # 验证失败请求记录
        expected_url = "https://example.com/api/data"
        assert expected_url in mock_page_context.data["failed_requests"]
        assert mock_page_context.data["failed_requests"][expected_url] == 1
    
    @pytest.mark.asyncio
    async def test_page_monitor_url_cleaning(self, mock_page_context):
        """测试URL清理功能"""
        monitor = PageMonitor("monitor")
        
        # 测试URL清理
        original_url = "https://example.com/api/data?param1=value1&param2=value2"
        cleaned_url = monitor._remove_query_string(original_url)
        expected_url = "https://example.com/api/data"
        assert cleaned_url == expected_url
        
        # 测试域名和路径提取
        domain, path = monitor._get_domain_path(original_url)
        assert domain == "example.com"
        assert path == "/api/data"
    
    @pytest.mark.asyncio
    async def test_page_monitor_finish(self, mock_page_context):
        """测试页面监控清理"""
        monitor = PageMonitor("monitor")
        monitor._context = mock_page_context
        
        # 添加一些请求时间记录
        monitor._request_start_times["test_url"] = 123456.0
        
        # 添加统计数据
        mock_page_context.data["slow_requests"] = defaultdict(int, {"url1": 2})
        mock_page_context.data["failed_requests"] = defaultdict(int, {"url2": 1})
        
        await monitor.finish(mock_page_context)
        
        # 验证清理
        mock_page_context.page.close.assert_called_once()
        assert len(monitor._request_start_times) == 0
        assert monitor.state == ProcessorState.FINISHED
    
    @pytest.mark.asyncio
    async def test_page_monitor_network_idle_timeout(self, mock_page_context):
        """测试网络空闲超时"""
        monitor = PageMonitor("monitor")
        
        # 模拟网络空闲超时
        from playwright.async_api import TimeoutError
        mock_page_context.page.wait_for_load_state.side_effect = TimeoutError("Timeout")
        
        result = await monitor._wait_for_network_idle(mock_page_context.page, timeout=1.0)
        assert result is False
    
    @pytest.mark.asyncio
    async def test_request_monitor_initialization(self, mock_page_context, mock_url_collection):
        """测试请求监控处理器初始化"""
        monitor = RequestMonitor(
            "request_monitor",
            url_collection=mock_url_collection,
            slow_request_threshold=50,
            failed_request_threshold=5
        )
        
        # 测试初始状态
        assert monitor.priority == 1
        assert monitor.slow_request_threshold == 50
        assert monitor.failed_request_threshold == 5
        assert monitor.url_collection is mock_url_collection
        assert not monitor._monitoring_started
    
    @pytest.mark.asyncio
    async def test_request_monitor_detect_ready_state(self, mock_page_context, mock_url_collection):
        """测试请求监控检测逻辑 - 页面就绪状态"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        # 页面未就绪时应该等待
        mock_page_context.data["page_state"] = "loading"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.WAITING
        
        # 页面就绪时应该开始
        mock_page_context.data["page_state"] = "ready"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.READY
        
        # 页面完成时也应该开始
        mock_page_context.data["page_state"] = "completed"
        monitor._monitoring_started = False  # 重置状态
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_request_monitor_detect_running_state(self, mock_page_context, mock_url_collection):
        """测试请求监控运行状态检测"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        monitor._monitoring_started = True
        
        # 监控已开始但页面未完成
        mock_page_context.data["page_state"] = "ready"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.RUNNING
        
        # 页面完成且无更高优先级处理器
        mock_page_context.data["page_state"] = "completed"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.COMPLETED
    
    @pytest.mark.asyncio
    async def test_request_monitor_detect_with_higher_priority_processors(self, mock_page_context, mock_url_collection):
        """测试请求监控与更高优先级处理器的交互"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        monitor._monitoring_started = True
        
        # 创建一个更高优先级(priority=0)的处理器
        higher_priority_processor = Mock()
        higher_priority_processor.state = ProcessorState.RUNNING
        higher_priority_processor.priority = 0
        
        mock_page_context.processors["higher_priority"] = higher_priority_processor
        mock_page_context.data["page_state"] = "completed"
        
        # 应该继续运行，等待更高优先级处理器完成
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.RUNNING
    
    @pytest.mark.asyncio
    async def test_request_monitor_run_initialization(self, mock_page_context, mock_url_collection):
        """测试请求监控运行初始化"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        # 运行监控
        await monitor.run(mock_page_context)
        
        # 验证初始化
        assert monitor._monitoring_started
        assert "blocked_urls" in mock_page_context.data
        assert isinstance(mock_page_context.data["blocked_urls"], list)
    
    @pytest.mark.asyncio
    async def test_request_monitor_slow_request_blocking(self, mock_page_context, mock_url_collection):
        """测试慢请求屏蔽功能"""
        monitor = RequestMonitor(
            "request_monitor",
            url_collection=mock_url_collection,
            slow_request_threshold=2,
            failed_request_threshold=10
        )
        
        # 设置慢请求数据
        mock_page_context.data["slow_requests"] = defaultdict(int, {
            "https://example.com/api/slow1": 3,  # 超过阈值
            "https://example.com/api/slow2": 1,  # 未超过阈值
        })
        mock_page_context.data["failed_requests"] = defaultdict(int)
        
        # 运行监控
        await monitor.run(mock_page_context)
        
        # 验证只有超过阈值的URL被屏蔽
        blocked_urls = [item["url"] for item in mock_page_context.data.get("blocked_urls", [])]
        assert "https://example.com/api/slow1" in blocked_urls
        assert "https://example.com/api/slow2" not in blocked_urls
        
        # 验证URL被添加到集合中
        assert mock_url_collection.count_by_status(URLStatus.BLOCKED) == 1
    
    @pytest.mark.asyncio
    async def test_request_monitor_failed_request_blocking(self, mock_page_context, mock_url_collection):
        """测试失败请求屏蔽功能"""
        monitor = RequestMonitor(
            "request_monitor",
            url_collection=mock_url_collection,
            slow_request_threshold=100,
            failed_request_threshold=2
        )
        
        # 设置失败请求数据
        mock_page_context.data["slow_requests"] = defaultdict(int)
        mock_page_context.data["failed_requests"] = defaultdict(int, {
            "https://example.com/api/failed1": 3,  # 超过阈值
            "https://example.com/api/failed2": 1,  # 未超过阈值
        })
        
        # 运行监控
        await monitor.run(mock_page_context)
        
        # 验证只有超过阈值的URL被屏蔽
        blocked_urls = [item["url"] for item in mock_page_context.data.get("blocked_urls", [])]
        assert "https://example.com/api/failed1" in blocked_urls
        assert "https://example.com/api/failed2" not in blocked_urls
        
        # 验证URL被添加到集合中
        assert mock_url_collection.count_by_status(URLStatus.BLOCKED) == 1
    
    @pytest.mark.asyncio
    async def test_request_monitor_url_cleaning(self, mock_page_context, mock_url_collection):
        """测试URL清理功能"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        # 测试URL清理
        original_url = "https://example.com/api/data?param1=value1&param2=value2"
        cleaned_url = monitor._remove_query_string(original_url)
        expected_url = "https://example.com/api/data"
        assert cleaned_url == expected_url
        
        # 测试域名和路径提取
        domain, path = monitor._get_domain_path(original_url)
        assert domain == "example.com"
        assert path == "/api/data"
    
    @pytest.mark.asyncio
    async def test_request_monitor_block_problematic_url(self, mock_page_context, mock_url_collection):
        """测试问题URL屏蔽功能"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        test_url = "https://example.com/problematic"
        test_reason = "测试屏蔽"
        
        # 屏蔽URL
        monitor._block_problematic_url(test_url, test_reason, mock_page_context)
        
        # 验证URL被添加到集合
        assert mock_url_collection.count_by_status(URLStatus.BLOCKED) == 1
        
        # 验证被屏蔽的URL信息
        blocked_urls = mock_url_collection.get_by_status(URLStatus.BLOCKED)
        assert len(blocked_urls) == 1
        assert blocked_urls[0].url == test_url
        assert blocked_urls[0].category == "blocked_by_request_monitor"
        
        # 验证上下文记录
        assert "blocked_urls" in mock_page_context.data
        blocked_items = mock_page_context.data["blocked_urls"]
        assert len(blocked_items) == 1
        assert blocked_items[0]["url"] == test_url
        assert blocked_items[0]["reason"] == test_reason
    
    @pytest.mark.asyncio
    async def test_request_monitor_finish(self, mock_page_context, mock_url_collection):
        """Test request monitor cleanup"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        monitor._monitoring_started = True
        
        # Add test data
        mock_page_context.data["blocked_urls"] = [
            {"url": "https://example.com/test1", "reason": "slow request", "blocked_at": time.time()},
            {"url": "https://example.com/test2", "reason": "failed request", "blocked_at": time.time()},
        ]
        mock_page_context.data["slow_requests"] = defaultdict(int, {"url1": 5})
        mock_page_context.data["failed_requests"] = defaultdict(int, {"url2": 3})
        
        await monitor.finish(mock_page_context)
        
        # Verify cleanup
        assert monitor.state == ProcessorState.FINISHED


if __name__ == "__main__":
    pytest.main([__file__])