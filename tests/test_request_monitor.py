"""
RequestMonitor 处理器的单元测试
"""

import pytest
import time
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
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        return context
    
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
    async def test_request_monitor_finish(self, mock_page_context, mock_url_collection):
        """测试请求监控清理"""
        monitor = RequestMonitor("request_monitor", url_collection=mock_url_collection)
        monitor._monitoring_started = True
        
        # 添加一些测试数据
        mock_page_context.data["blocked_urls"] = [
            {"url": "https://example.com/test1", "reason": "慢请求", "blocked_at": time.time()},
            {"url": "https://example.com/test2", "reason": "失败请求", "blocked_at": time.time()},
        ]
        mock_page_context.data["slow_requests"] = defaultdict(int, {"url1": 5})
        mock_page_context.data["failed_requests"] = defaultdict(int, {"url2": 3})
        
        await monitor.finish(mock_page_context)
        
        # 验证清理
        assert monitor.state == ProcessorState.FINISHED


if __name__ == "__main__":
    pytest.main([__file__])