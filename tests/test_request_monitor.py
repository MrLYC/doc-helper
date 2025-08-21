"""
RequestMonitor 处理器的单元测试
"""

import pytest
import time
import re
from unittest.mock import AsyncMock, Mock
from collections import defaultdict

from pdf_helper.processors import RequestMonitor
from pdf_helper.protocol import URL, URLCollection, URLStatus, PageContext, ProcessorState


class TestRequestMonitor:
    """RequestMonitor 处理器的测试"""
    
    @pytest.fixture
    def mock_url_collection(self):
        """创建模拟URL集合"""
        return URLCollection()
    
    @pytest.fixture
    def mock_page_context(self):
        """创建模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.close = AsyncMock()
        
        # 模拟pending_requests
        mock_request1 = Mock()
        mock_request1.url = "https://example.com/slow-api"
        mock_request1.is_finished = Mock(return_value=False)
        mock_request1.abort = AsyncMock()
        
        mock_request2 = Mock()
        mock_request2.url = "https://other.com/api"
        mock_request2.is_finished = Mock(return_value=False) 
        mock_request2.abort = AsyncMock()
        
        mock_page.context.pending_requests = [mock_request1, mock_request2]
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        return context
    
    @pytest.mark.asyncio
    async def test_request_monitor_initialization(self, mock_page_context, mock_url_collection):
        """测试请求监控处理器初始化"""
        monitor = RequestMonitor(
            "request_monitor",
            url_collection=mock_url_collection
        )
        
        # 设置屏蔽模式
        monitor.block_url_patterns = {".*slow.*", ".*error.*"}
        
        # 测试初始状态
        assert monitor.priority == 1
        assert monitor.url_collection is mock_url_collection
        assert monitor.block_url_patterns == {".*slow.*", ".*error.*"}
        assert hasattr(monitor, '_compiled_patterns')
    
    @pytest.mark.asyncio
    async def test_request_monitor_detect_ready_state(self, mock_page_context, mock_url_collection):
        """测试请求监控检测逻辑"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        # 页面未就绪时应该等待
        mock_page_context.data["page_state"] = "loading"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.WAITING
        
        # 页面就绪时应该开始
        mock_page_context.data["page_state"] = "ready"
        state = await monitor.detect(mock_page_context)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_request_monitor_pattern_blocking(self, mock_page_context, mock_url_collection):
        """测试基于模式的请求屏蔽功能"""
        monitor = RequestMonitor(
            "request_monitor",
            url_collection=mock_url_collection
        )
        monitor.block_url_patterns = {".*slow.*"}
        
        # 运行监控
        await monitor.run(mock_page_context)
        
        # 验证匹配模式的请求被取消
        pending_requests = mock_page_context.page.context.pending_requests
        slow_request = pending_requests[0]  # https://example.com/slow-api
        other_request = pending_requests[1]  # https://other.com/api
        
        # slow-api 请求应该被取消
        slow_request.abort.assert_called_once()
        # other 请求不应该被取消
        other_request.abort.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_request_monitor_multiple_patterns(self, mock_page_context, mock_url_collection):
        """测试多个模式的屏蔽功能"""
        # 修改mock请求
        mock_request3 = Mock()
        mock_request3.url = "https://example.com/error-handler"
        mock_request3.is_finished = Mock(return_value=False)
        mock_request3.abort = AsyncMock()
        
        mock_page_context.page.context.pending_requests.append(mock_request3)
        
        monitor = RequestMonitor(
            "request_monitor", 
            url_collection=mock_url_collection
        )
        monitor.block_url_patterns = {".*slow.*", ".*error.*"}
        
        await monitor.run(mock_page_context)
        
        # 验证多个模式都生效
        requests = mock_page_context.page.context.pending_requests
        slow_request = requests[0]  # https://example.com/slow-api
        other_request = requests[1]  # https://other.com/api  
        error_request = requests[2]  # https://example.com/error-handler
        
        slow_request.abort.assert_called_once()
        error_request.abort.assert_called_once()
        other_request.abort.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_request_monitor_finished_requests_not_aborted(self, mock_page_context, mock_url_collection):
        """测试已完成的请求不会被取消"""
        # 设置第一个请求为已完成
        mock_page_context.page.context.pending_requests[0].is_finished = Mock(return_value=True)
        
        monitor = RequestMonitor(
            "request_monitor",
            url_collection=mock_url_collection
        )
        monitor.block_url_patterns = {".*slow.*"}
        
        await monitor.run(mock_page_context)
        
        # 验证已完成的请求不会被取消
        slow_request = mock_page_context.page.context.pending_requests[0]
        slow_request.abort.assert_not_called()
    
    @pytest.mark.asyncio  
    async def test_request_monitor_no_patterns(self, mock_page_context, mock_url_collection):
        """测试没有屏蔽模式时的行为"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        await monitor.run(mock_page_context)
        
        # 验证没有请求被取消
        for request in mock_page_context.page.context.pending_requests:
            request.abort.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_request_monitor_finish(self, mock_page_context, mock_url_collection):
        """测试请求监控清理"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        
        await monitor.finish(mock_page_context)
        
        # 验证状态设置为完成
        assert monitor.state == ProcessorState.FINISHED


if __name__ == "__main__":
    pytest.main([__file__])