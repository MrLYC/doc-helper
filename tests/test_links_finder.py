"""
LinksFinder 处理器的单元测试
"""

import pytest
import time
from unittest.mock import AsyncMock, Mock
from collections import defaultdict

from doc_helper.processors import LinksFinder
from doc_helper.protocol import URL, URLCollection, URLStatus, PageContext, ProcessorState


class TestLinksFinder:
    """LinksFinder 处理器的测试"""
    
    @pytest.fixture
    def mock_url_collection(self):
        """创建模拟URL集合"""
        return URLCollection()
    
    @pytest.fixture
    def mock_page_context(self):
        """创建模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.close = AsyncMock()
        mock_page.evaluate = AsyncMock()
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        return context
    
    @pytest.mark.asyncio
    async def test_links_finder_initialization(self, mock_page_context, mock_url_collection):
        """测试链接发现处理器初始化"""
        finder = LinksFinder(
            "links_finder",
            url_collection=mock_url_collection,
            css_selector="main",
            priority=15
        )
        
        # 测试初始状态
        assert finder.priority == 15
        assert finder.css_selector == "main"
        assert finder.url_collection is mock_url_collection
        assert not finder._ready_executed
        assert not finder._completed_executed
    
    @pytest.mark.asyncio
    async def test_links_finder_detect_ready_state(self, mock_page_context, mock_url_collection):
        """测试链接发现检测逻辑 - 页面就绪状态"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 页面未就绪时应该等待
        mock_page_context.data["page_state"] = "loading"
        state = await finder.detect(mock_page_context)
        assert state == ProcessorState.WAITING
        
        # 页面就绪时应该开始
        mock_page_context.data["page_state"] = "ready"
        state = await finder.detect(mock_page_context)
        assert state == ProcessorState.READY
        
        # 页面完成时也应该开始
        mock_page_context.data["page_state"] = "completed"
        state = await finder.detect(mock_page_context)
        assert state == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_links_finder_url_validation(self, mock_page_context, mock_url_collection):
        """测试URL验证功能"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 有效URL
        assert finder._is_valid_url("https://example.com") is True
        assert finder._is_valid_url("http://test.org/path") is True
        
        # 无效URL
        assert finder._is_valid_url("") is False
        assert finder._is_valid_url(None) is False
        assert finder._is_valid_url("javascript:void(0)") is False
        assert finder._is_valid_url("mailto:test@example.com") is False
        assert finder._is_valid_url("/relative/path") is False
        assert finder._is_valid_url("invalid-url") is False
    
    @pytest.mark.asyncio
    async def test_links_finder_extract_links_from_container(self, mock_page_context, mock_url_collection):
        """测试从容器提取链接功能"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 模拟页面返回的链接
        mock_links = [
            "https://example.com/page1",
            "https://example.com/page2",
            "javascript:void(0)",  # 无效链接
            "https://another.com/page",
        ]
        
        mock_page_context.page.evaluate.return_value = mock_links
        
        # 提取链接
        valid_links = await finder._extract_links_from_container(
            mock_page_context.page,
            "body",
            "example.com"
        )
        
        # 验证只返回有效链接
        expected_valid = [
            "https://example.com/page1",
            "https://example.com/page2", 
            "https://another.com/page",
        ]
        assert valid_links == expected_valid
    
    @pytest.mark.asyncio
    async def test_links_finder_add_links_to_collection(self, mock_page_context, mock_url_collection):
        """测试将链接添加到集合功能"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        test_links = [
            "https://example.com/new1",
            "https://example.com/new2",
        ]
        
        # 添加链接到集合
        added_count = await finder._add_links_to_collection(test_links, mock_page_context)
        
        # 验证链接被添加
        assert added_count == 2
        assert mock_url_collection.count_by_status(URLStatus.PENDING) == 2
        
        # 验证上下文记录
        assert "discovered_links" in mock_page_context.data
        discovered = mock_page_context.data["discovered_links"]
        assert len(discovered) == 2
        assert discovered[0]["url"] == "https://example.com/new1"
        assert discovered[1]["url"] == "https://example.com/new2"
    
    @pytest.mark.asyncio
    async def test_links_finder_duplicate_links(self, mock_page_context, mock_url_collection):
        """测试重复链接处理"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 先添加一个链接
        test_links = ["https://example.com/duplicate"]
        added_count1 = await finder._add_links_to_collection(test_links, mock_page_context)
        assert added_count1 == 1
        
        # 再次添加同一个链接
        added_count2 = await finder._add_links_to_collection(test_links, mock_page_context)
        assert added_count2 == 0  # 重复链接不会被添加
        
        # 总数仍然是1
        assert mock_url_collection.count_by_status(URLStatus.PENDING) == 1
    
    @pytest.mark.asyncio
    async def test_links_finder_run_ready_state(self, mock_page_context, mock_url_collection):
        """测试在页面就绪状态运行"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 模拟页面返回链接
        mock_page_context.page.evaluate.return_value = [
            "https://example.com/ready1",
            "https://example.com/ready2",
        ]
        
        # 设置页面状态为就绪
        mock_page_context.data["page_state"] = "ready"
        
        # 运行处理器
        await finder.run(mock_page_context)
        
        # 验证就绪状态被执行
        assert finder._ready_executed is True
        assert finder._completed_executed is False
        
        # 验证链接被添加
        assert mock_url_collection.count_by_status(URLStatus.PENDING) == 2
    
    @pytest.mark.asyncio
    async def test_links_finder_run_completed_state(self, mock_page_context, mock_url_collection):
        """测试在页面完成状态运行"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 模拟页面返回链接
        mock_page_context.page.evaluate.return_value = [
            "https://example.com/completed1",
        ]
        
        # 设置页面状态为完成
        mock_page_context.data["page_state"] = "completed"
        
        # 运行处理器
        await finder.run(mock_page_context)
        
        # 验证完成状态被执行
        assert finder._ready_executed is False
        assert finder._completed_executed is True
        
        # 验证链接被添加
        assert mock_url_collection.count_by_status(URLStatus.PENDING) == 1
    
    @pytest.mark.asyncio
    async def test_links_finder_run_both_states(self, mock_page_context, mock_url_collection):
        """测试在两个状态都运行"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        # 第一次运行 - 就绪状态
        mock_page_context.page.evaluate.return_value = ["https://example.com/ready"]
        mock_page_context.data["page_state"] = "ready"
        await finder.run(mock_page_context)
        
        # 第二次运行 - 完成状态
        mock_page_context.page.evaluate.return_value = ["https://example.com/completed"]
        mock_page_context.data["page_state"] = "completed"
        await finder.run(mock_page_context)
        
        # 验证两个状态都被执行
        assert finder._ready_executed is True
        assert finder._completed_executed is True
        
        # 验证链接被添加
        assert mock_url_collection.count_by_status(URLStatus.PENDING) == 2
    
    @pytest.mark.asyncio
    async def test_links_finder_generate_url_id(self, mock_page_context, mock_url_collection):
        """测试URL ID生成"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        
        test_url = "https://example.com/test"
        
        # 生成两个ID
        id1 = finder._generate_url_id(test_url)
        time.sleep(0.001)  # 确保时间戳不同
        id2 = finder._generate_url_id(test_url)
        
        # 验证ID格式和唯一性
        assert id1.startswith("links_")
        assert id2.startswith("links_")
        assert id1 != id2  # 应该不同（因为时间戳不同）
        assert len(id1.split("_")) == 3  # links_timestamp_hash格式
    
    @pytest.mark.asyncio
    async def test_links_finder_finish(self, mock_page_context, mock_url_collection):
        """测试链接发现清理"""
        finder = LinksFinder("links_finder", url_collection=mock_url_collection)
        finder._start_time = time.time()
        
        # 添加一些测试数据
        mock_page_context.data["discovered_links"] = [
            {"url": "https://example.com/test1", "discovered_at": time.time()},
            {"url": "https://example.com/test2", "discovered_at": time.time()},
        ]
        
        await finder.finish(mock_page_context)
        
        # 验证清理
        assert finder.state == ProcessorState.FINISHED
    
    @pytest.mark.asyncio
    async def test_links_finder_custom_selector(self, mock_page_context, mock_url_collection):
        """测试自定义CSS选择器"""
        finder = LinksFinder(
            "links_finder",
            url_collection=mock_url_collection,
            css_selector="nav.main-menu"
        )
        
        # 模拟页面返回链接
        mock_page_context.page.evaluate.return_value = [
            "https://example.com/nav1",
            "https://example.com/nav2",
        ]
        
        mock_page_context.data["page_state"] = "ready"
        
        # 运行处理器
        await finder.run(mock_page_context)
        
        # 验证JavaScript代码中使用了正确的选择器
        call_args = mock_page_context.page.evaluate.call_args[0][0]
        assert "nav.main-menu" in call_args
        
        # 验证链接被添加
        assert mock_url_collection.count_by_status(URLStatus.PENDING) == 2


if __name__ == "__main__":
    pytest.main([__file__])