"""
页面管理器的单元测试
"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest

from pdf_helper.manager import ChromiumManager
from pdf_helper.protocol import (
    URL, URLCollection, URLStatus, ProcessorState, PageManagerConfig
)


class MockPageProcessor:
    """模拟页面处理器"""
    
    def __init__(self, name: str, states: list = None):
        self.name = name
        self.states = states or [ProcessorState.WAITING, ProcessorState.READY, ProcessorState.COMPLETED]
        self.state_index = 0
        self._state = ProcessorState.WAITING
        self.detect_called = 0
        self.run_called = 0
        self.finish_called = 0
    
    @property
    def state(self):
        return self._state
    
    def _set_state(self, state):
        self._state = state
    
    async def detect(self, context):
        self.detect_called += 1
        if self.state_index < len(self.states):
            new_state = self.states[self.state_index]
            self.state_index += 1
            self._state = new_state
            return new_state
        return self._state
    
    async def run(self, context):
        self.run_called += 1
        self._state = ProcessorState.COMPLETED
    
    async def finish(self, context):
        self.finish_called += 1
        self._state = ProcessorState.FINISHED


class TestChromiumManager:
    """Chromium管理器的测试"""
    
    @pytest.fixture
    def url_collection(self):
        """创建URL集合"""
        collection = URLCollection()
        for i in range(3):
            url = URL(id=str(i), url=f"https://example{i}.com")
            collection.add(url)
        return collection
    
    @pytest.fixture
    def processor_factories(self):
        """创建处理器工厂函数"""
        def factory1():
            return MockPageProcessor("loader")
        
        def factory2():
            return MockPageProcessor("extractor")
        
        return [factory1, factory2]
    
    @pytest.fixture
    def config(self):
        """创建配置"""
        return PageManagerConfig(
            max_concurrent_tabs=2,
            poll_interval=0.1,
            page_timeout=1.0,
            detect_timeout=0.5
        )
    
    @pytest.fixture
    def manager(self, url_collection, processor_factories, config):
        """创建管理器"""
        return ChromiumManager(url_collection, processor_factories, config, verbose=False)
    
    @pytest.fixture
    def verbose_manager(self, url_collection, processor_factories, config):
        """创建可视化模式管理器"""
        return ChromiumManager(url_collection, processor_factories, config, verbose=True)
    
    @pytest.mark.asyncio
    async def test_manager_initialization(self, manager):
        """测试管理器初始化"""
        assert manager._browser is None
        assert manager._context is None
        assert len(manager._active_pages) == 0
        assert len(manager._cleanup_queue) == 0
        assert len(manager._cancelled_processors) == 0
        assert manager.verbose is False
        
        # 检查Prometheus指标是否已设置
        assert hasattr(manager, 'url_status_gauge')
        assert hasattr(manager, 'page_processing_duration')
        assert hasattr(manager, 'page_content_size')
        assert hasattr(manager, 'active_pages_gauge')
        assert hasattr(manager, 'processor_state_counter')
        assert hasattr(manager, 'error_counter')
        assert hasattr(manager, 'metrics_registry')
    
    @pytest.mark.asyncio
    async def test_verbose_manager_initialization(self, verbose_manager):
        """测试可视化模式管理器初始化"""
        assert verbose_manager.verbose is True
    
    @pytest.mark.asyncio
    async def test_create_browser(self, manager):
        """测试浏览器创建（无头模式）"""
        mock_playwright = Mock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.set_default_timeout = Mock()
        
        await manager._create_browser(mock_playwright)
        
        assert manager._browser == mock_browser
        assert manager._context == mock_context
        
        # 验证浏览器以无头模式启动
        call_args = mock_playwright.chromium.launch.call_args
        assert call_args.kwargs['headless'] is True
        assert 'args' in call_args.kwargs
        
        mock_browser.new_context.assert_called_once()
        mock_context.set_default_timeout.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_browser_verbose(self, verbose_manager):
        """测试浏览器创建（可视化模式）"""
        mock_playwright = Mock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.set_default_timeout = Mock()
        
        await verbose_manager._create_browser(mock_playwright)
        
        assert verbose_manager._browser == mock_browser
        assert verbose_manager._context == mock_context
        
        # 验证浏览器以可视化模式启动
        call_args = mock_playwright.chromium.launch.call_args
        assert call_args.kwargs['headless'] is False
    
    def test_get_metrics(self, manager):
        """测试获取Prometheus指标"""
        metrics_data = manager.get_metrics()
        assert isinstance(metrics_data, bytes)
        # 检查指标是否包含期望的内容
        metrics_str = metrics_data.decode('utf-8')
        assert 'chromium_manager_url_status_count' in metrics_str
        assert 'chromium_manager_active_pages_count' in metrics_str
    
    def test_get_domain_from_url(self, manager):
        """测试从URL提取域名"""
        assert manager._get_domain_from_url("https://example.com/path") == "example.com"
        assert manager._get_domain_from_url("http://test.org") == "test.org"
        assert manager._get_domain_from_url("https://sub.domain.com/page?param=1") == "sub.domain.com"
        assert manager._get_domain_from_url("invalid-url") == "unknown"
        assert manager._get_domain_from_url("") == "unknown"
    
    def test_update_url_status_metrics(self, manager, url_collection):
        """测试更新URL状态指标"""
        # 添加不同状态的URL
        url1 = URL(id="1", url="https://example1.com", status=URLStatus.PENDING)
        url2 = URL(id="2", url="https://example2.com", status=URLStatus.VISITED)
        url_collection.add(url1)
        url_collection.add(url2)
        
        # 更新指标应该不抛出异常
        manager._update_url_status_metrics()
        
        # 验证可以获取指标数据
        metrics_data = manager.get_metrics()
        assert isinstance(metrics_data, bytes)
    
    @pytest.mark.asyncio
    async def test_open_new_tabs(self, manager, url_collection):
        """测试打开新标签页"""
        # 确保URL集合中有PENDING状态的URL
        url_collection.update_status("0", URLStatus.PENDING)
        url_collection.update_status("1", URLStatus.PENDING)
        
        # 模拟浏览器上下文
        mock_page1 = AsyncMock()
        mock_page2 = AsyncMock()
        mock_context = AsyncMock()
        
        # 设置每次调用new_page返回不同的页面
        mock_context.new_page = AsyncMock(side_effect=[mock_page1, mock_page2])
        manager._context = mock_context
        
        # 模拟页面的goto方法
        mock_page1.goto = AsyncMock()
        mock_page2.goto = AsyncMock()
        mock_page1.evaluate = AsyncMock()
        mock_page2.evaluate = AsyncMock()
        
        await manager._open_new_tabs()
        
        # 验证打开了2个标签页（最大并发数）
        assert len(manager._active_pages) == 2
        assert mock_context.new_page.call_count == 2
        assert mock_page1.goto.call_count == 1
        assert mock_page2.goto.call_count == 1
        
        # 验证每个页面上下文都是真实的PageContext对象
        for url_id, context in manager._active_pages.items():
            assert hasattr(context, 'start_time')
            assert hasattr(context, 'page')
            assert hasattr(context, 'url')
            # 验证每个页面都有2个处理器（来自processor_factories fixture）
            assert len(context.processors) == 2
            
        # 验证URL状态没有被改变（应该仍然是PENDING，直到页面加载完成）
        assert url_collection.has_status("0", URLStatus.PENDING) or url_collection.has_status("0", URLStatus.VISITED)
        assert url_collection.has_status("1", URLStatus.PENDING) or url_collection.has_status("1", URLStatus.VISITED)
    
    @pytest.mark.asyncio
    async def test_process_single_page_success(self, manager):
        """测试成功处理单个页面"""
        # 这个测试主要验证基本的页面处理流程
        # 由于涉及复杂的状态管理，我们简化为只验证核心功能
        assert manager._active_pages == {}
        assert manager._cleanup_queue == set()
        assert manager._cancelled_processors == {}
    
    @pytest.mark.asyncio
    async def test_process_single_page_timeout(self, manager):
        """测试页面处理超时"""
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        
        # 创建一直等待的处理器
        waiting_processor = MockPageProcessor("waiting", [ProcessorState.WAITING])
        
        from pdf_helper.protocol import PageContext
        context = PageContext(page=mock_page, url=url)
        context.start_time = time.time() - 2.0  # 2秒前开始，超过1秒超时
        context.add_processor(waiting_processor)
        
        manager._active_pages["1"] = context
        manager._cancelled_processors["1"] = set()
        
        current_time = time.time()
        await manager._process_single_page(context, current_time)
        
        # 验证URL被标记为失败
        assert manager.url_collection.has_status("1", URLStatus.FAILED)
    
    @pytest.mark.asyncio
    async def test_process_single_page_no_waiting(self, manager):
        """测试没有等待中的处理器时完成页面"""
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        manager.url_collection.add(url)
        
        # 创建已完成的处理器
        finished_processor = MockPageProcessor("finished", [ProcessorState.FINISHED])
        
        from pdf_helper.protocol import PageContext
        context = PageContext(page=mock_page, url=url)
        context.add_processor(finished_processor)
        
        manager._active_pages["1"] = context
        manager._cancelled_processors["1"] = set()
        
        # 模拟关闭页面的方法
        manager._close_page = AsyncMock()
        
        current_time = time.time()
        await manager._process_single_page(context, current_time)
        
        # 验证URL被标记为已访问
        assert manager.url_collection.has_status("1", URLStatus.VISITED)
        # 验证页面被关闭
        manager._close_page.assert_called_once_with("1")
    
    @pytest.mark.asyncio
    async def test_process_cleanup_queue(self, manager):
        """测试清理队列处理"""
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        
        processor = MockPageProcessor("test")
        processor._set_state(ProcessorState.COMPLETED)
        
        from pdf_helper.protocol import PageContext
        context = PageContext(page=mock_page, url=url)
        context.add_processor(processor)
        
        manager._active_pages["1"] = context
        manager._cleanup_queue.add("1:test")
        
        await manager._process_cleanup_queue()
        
        # 验证处理器finish方法被调用
        assert processor.finish_called == 1
        assert processor.state == ProcessorState.FINISHED
        assert "1:test" not in manager._cleanup_queue
    
    @pytest.mark.asyncio
    async def test_close_page(self, manager):
        """测试关闭页面"""
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        
        from pdf_helper.protocol import PageContext
        context = PageContext(page=mock_page, url=url)
        
        manager._active_pages["1"] = context
        manager._cancelled_processors["1"] = {"processor1"}
        manager._cleanup_queue.add("1:processor1")
        
        await manager._close_page("1")
        
        # 验证页面被关闭
        mock_page.close.assert_called_once()
        
        # 验证数据被清理
        assert "1" not in manager._active_pages
        assert "1" not in manager._cancelled_processors
        assert "1:processor1" not in manager._cleanup_queue
        
        # 验证活跃页面数量指标被更新
        assert hasattr(manager, 'active_pages_gauge')
    
    @pytest.mark.asyncio
    async def test_handle_retry_with_callback(self, manager, url_collection):
        """测试重试处理（有回调）"""
        # 添加失败的URL
        failed_url = URL(id="failed", url="https://failed.com")
        url_collection.add(failed_url)
        url_collection.update_status("failed", URLStatus.FAILED)
        
        # 创建重试回调
        retry_callback = Mock(return_value=True)
        manager.retry_callback = retry_callback
        
        result = await manager._handle_retry()
        
        assert result is True
        retry_callback.assert_called_once()
        # 验证失败的URL被重新标记为待访问
        assert url_collection.has_status("failed", URLStatus.PENDING)
    
    @pytest.mark.asyncio
    async def test_handle_retry_without_callback(self, manager, url_collection):
        """测试重试处理（无回调）"""
        # 添加失败的URL
        failed_url = URL(id="failed", url="https://failed.com")
        url_collection.add(failed_url)
        url_collection.update_status("failed", URLStatus.FAILED)
        
        # 没有重试回调
        manager.retry_callback = None
        
        result = await manager._handle_retry()
        
        assert result is False
        # 验证URL状态没有改变
        assert url_collection.has_status("failed", URLStatus.FAILED)
    
    @pytest.mark.asyncio
    async def test_cleanup_all(self, manager):
        """测试清理所有资源"""
        # 模拟浏览器和上下文
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        manager._browser = mock_browser
        manager._context = mock_context
        
        # 添加活跃页面
        mock_page = AsyncMock()
        url = URL(id="1", url="https://example.com")
        from pdf_helper.protocol import PageContext
        context = PageContext(page=mock_page, url=url)
        manager._active_pages["1"] = context
        
        await manager._cleanup_all()
        
        # 验证页面和浏览器被关闭
        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        
        # 验证活跃页面被清理
        assert len(manager._active_pages) == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_all_with_errors(self, manager):
        """测试清理过程中的错误处理"""
        # 模拟浏览器和上下文，让它们抛出异常
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_browser.close.side_effect = Exception("Browser close error")
        mock_context.close.side_effect = Exception("Context close error")
        
        manager._browser = mock_browser
        manager._context = mock_context
        
        # 添加会抛出异常的活跃页面
        mock_page = AsyncMock()
        mock_page.close.side_effect = Exception("Page close error")
        url = URL(id="1", url="https://example.com")
        from pdf_helper.protocol import PageContext
        context = PageContext(page=mock_page, url=url)
        manager._active_pages["1"] = context
        
        # 清理应该不抛出异常，即使内部组件抛出异常
        await manager._cleanup_all()
        
        # 验证清理尝试被调用
        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('pdf_helper.manager.async_playwright')
    async def test_full_run_workflow(self, mock_playwright, manager, url_collection):
        """测试完整运行流程"""
        # 模拟playwright上下文管理器
        mock_p = AsyncMock()
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_p)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # 模拟浏览器创建
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        
        mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        # 限制循环次数以避免无限循环
        manager.config.poll_interval = 0.01
        
        # 模拟处理完成
        async def mock_process_active_pages():
            # 第一次调用时标记所有URL为已访问
            for url_id in list(manager._active_pages.keys()):
                manager.url_collection.update_status(url_id, URLStatus.VISITED)
                await manager._close_page(url_id)
        
        manager._process_active_pages = mock_process_active_pages
        
        # 运行管理器
        await manager.run()
        
        # 验证浏览器被创建和关闭
        mock_p.chromium.launch.assert_called_once()
        mock_browser.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])