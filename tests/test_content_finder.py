"""
ContentFinder处理器测试

测试内容查找和兄弟节点清理功能
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from doc_helper.protocol import PageContext, ProcessorState, URL, URLStatus
from doc_helper.processors import ContentFinder


class TestContentFinder:
    """ContentFinder处理器测试类"""

    def test_content_finder_initialization(self):
        """测试ContentFinder初始化"""
        css_selector = ".main-content"
        target_states = ["ready", "completed"]
        priority = 30
        
        processor = ContentFinder(
            css_selector=css_selector,
            target_states=target_states,
            priority=priority
        )
        
        assert processor.css_selector == css_selector
        assert processor.target_states == target_states
        assert processor.priority == priority
        assert processor.state == ProcessorState.WAITING
        assert processor._siblings_removed == 0

    def test_content_finder_default_target_states(self):
        """测试ContentFinder默认目标状态"""
        processor = ContentFinder(".content")
        assert processor.target_states == ["ready", "completed"]

    @pytest.mark.asyncio
    async def test_content_finder_detect_ready_state(self):
        """测试ContentFinder在页面就绪状态下的检测"""
        processor = ContentFinder(".main-content")
        
        # 模拟页面上下文
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.data = {"page_state": "ready"}
        mock_page_context.page = mock_page
        
        # 测试检测
        result = await processor.detect(mock_page_context)
        
        assert result == ProcessorState.READY
        assert processor.state == ProcessorState.READY
        mock_page.query_selector.assert_called_once_with(".main-content")

    @pytest.mark.asyncio
    async def test_content_finder_detect_wrong_state(self):
        """测试ContentFinder在错误状态下的检测"""
        processor = ContentFinder(".main-content", target_states=["ready"])
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.data = {"page_state": "loading"}
        
        result = await processor.detect(mock_page_context)
        
        assert result == ProcessorState.WAITING
        assert processor.state == ProcessorState.WAITING

    @pytest.mark.asyncio
    async def test_content_finder_detect_element_not_found(self):
        """测试ContentFinder元素未找到时的检测"""
        processor = ContentFinder(".non-existent")
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.data = {"page_state": "ready"}
        mock_page_context.page = mock_page
        
        result = await processor.detect(mock_page_context)
        
        assert result == ProcessorState.CANCELLED
        assert processor.state == ProcessorState.CANCELLED

    @pytest.mark.asyncio
    async def test_content_finder_detect_no_page(self):
        """测试ContentFinder在没有页面对象时的检测"""
        processor = ContentFinder(".content")
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.data = {"page_state": "ready"}
        mock_page_context.page = None
        
        result = await processor.detect(mock_page_context)
        
        assert result == ProcessorState.CANCELLED
        assert processor.state == ProcessorState.CANCELLED

    @pytest.mark.asyncio
    async def test_content_finder_run_success(self):
        """测试ContentFinder成功清理兄弟节点"""
        processor = ContentFinder(".main-content")
        processor._set_state(ProcessorState.READY)
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        
        # 模拟JavaScript执行结果
        mock_page.query_selector = AsyncMock(return_value=Mock())  # 找到元素
        mock_page.evaluate = AsyncMock(return_value={"totalRemoved": 5, "level": 3})
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.page = mock_page
        
        await processor.run(mock_page_context)
        
        assert processor.state == ProcessorState.COMPLETED
        assert processor._siblings_removed == 5
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_content_finder_run_no_siblings_removed(self):
        """测试ContentFinder没有兄弟节点需要清理"""
        processor = ContentFinder(".main-content")
        processor._set_state(ProcessorState.READY)
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        
        # 模拟JavaScript执行结果 - 没有兄弟节点被删除
        mock_page.query_selector = AsyncMock(return_value=Mock())
        mock_page.evaluate = AsyncMock(return_value={"totalRemoved": 0, "level": 2})
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.page = mock_page
        
        await processor.run(mock_page_context)
        
        assert processor.state == ProcessorState.COMPLETED
        assert processor._siblings_removed == 0

    @pytest.mark.asyncio
    async def test_content_finder_run_element_not_found(self):
        """测试ContentFinder运行时元素未找到"""
        processor = ContentFinder(".main-content")
        processor._set_state(ProcessorState.READY)
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.page = mock_page
        
        await processor.run(mock_page_context)
        
        assert processor.state == ProcessorState.CANCELLED
        mock_page.evaluate.assert_not_called()

    @pytest.mark.asyncio
    async def test_content_finder_run_page_error(self):
        """测试ContentFinder运行时发生页面错误"""
        processor = ContentFinder(".main-content")
        processor._set_state(ProcessorState.READY)
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(side_effect=Exception("Page error"))
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.page = mock_page
        
        await processor.run(mock_page_context)
        
        assert processor.state == ProcessorState.CANCELLED

    @pytest.mark.asyncio
    async def test_content_finder_run_no_page(self):
        """测试ContentFinder运行时没有页面对象"""
        processor = ContentFinder(".main-content")
        processor._set_state(ProcessorState.READY)
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.page = None
        
        await processor.run(mock_page_context)
        
        assert processor.state == ProcessorState.CANCELLED

    @pytest.mark.asyncio
    async def test_content_finder_finish(self):
        """测试ContentFinder完成处理"""
        processor = ContentFinder(".main-content")
        processor._set_state(ProcessorState.COMPLETED)
        processor._siblings_removed = 3
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        
        await processor.finish(mock_page_context)
        
        assert processor.state == ProcessorState.FINISHED
        assert processor._siblings_removed == 0

    @pytest.mark.asyncio
    async def test_content_finder_different_target_states(self):
        """测试ContentFinder不同目标状态的检测"""
        # 测试只接受completed状态
        processor = ContentFinder(".content", target_states=["completed"])
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.page = mock_page
        
        # 测试ready状态 - 应该返回WAITING
        mock_page_context.data = {"page_state": "ready"}
        result = await processor.detect(mock_page_context)
        assert result == ProcessorState.WAITING
        
        # 测试completed状态 - 应该返回READY
        mock_page_context.data = {"page_state": "completed"}
        result = await processor.detect(mock_page_context)
        assert result == ProcessorState.READY

    @pytest.mark.asyncio
    async def test_content_finder_complex_css_selector(self):
        """测试ContentFinder复杂CSS选择器"""
        complex_selector = "article.main-content, .content-wrapper > .article"
        processor = ContentFinder(complex_selector)
        
        assert processor.css_selector == complex_selector
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.data = {"page_state": "ready"}
        mock_page_context.page = mock_page
        
        result = await processor.detect(mock_page_context)
        
        assert result == ProcessorState.READY
        assert processor.state == ProcessorState.READY

    @pytest.mark.asyncio
    async def test_content_finder_complex_css_selector(self):
        """测试ContentFinder复杂CSS选择器"""
        complex_selector = "article.main-content, .content-wrapper > .article"
        processor = ContentFinder(complex_selector)
        
        assert processor.css_selector == complex_selector
        
        mock_url = URL(id="1", url="https://example.com")
        mock_page = AsyncMock()
        mock_element = Mock()
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        
        mock_page_context = Mock(spec=PageContext)
        mock_page_context.url = mock_url
        mock_page_context.data = {"page_state": "ready"}
        mock_page_context.page = mock_page
        
        result = await processor.detect(mock_page_context)
        
        assert result == ProcessorState.READY
        mock_page.query_selector.assert_called_once_with(complex_selector)