"""
测试截图API功能
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from doc_helper.manager import ChromiumManager
from doc_helper.protocol import PageContext, URL, PageManagerConfig, URLCollection


class TestSnapshotAPI:
    """测试截图API相关功能"""

    @pytest.fixture
    def url_collection(self):
        """创建URL集合"""
        return URLCollection()

    @pytest.fixture
    def manager_config(self):
        """创建管理器配置"""
        return PageManagerConfig(
            max_concurrent_tabs=5,
            page_timeout=30,
            poll_interval=1.0,
            detect_timeout=5.0,
            headless=True
        )

    @pytest.fixture  
    def mock_manager(self, url_collection, manager_config):
        """创建mock的ChromiumManager"""
        processor_factories = []
        manager = ChromiumManager(url_collection, processor_factories, manager_config, verbose=False)
        return manager

    def test_get_active_pages_info_empty(self, mock_manager):
        """测试获取空的活跃页面信息"""
        pages_info = mock_manager.get_active_pages_info()
        assert pages_info == []

    def test_get_active_pages_info_with_pages(self, mock_manager):
        """测试获取有页面的活跃页面信息"""
        # 模拟页面上下文
        mock_page = MagicMock()
        url1 = URL(id="test1", url="https://example.com/page1")
        url2 = URL(id="test2", url="https://example.com/page2")
        
        # 动态设置title属性
        url1.title = "页面1"  
        url2.title = "页面2"
        
        context1 = PageContext(page=mock_page, url=url1, start_time=1234567890.0)
        context2 = PageContext(page=mock_page, url=url2, start_time=1234567891.0)
        
        # 添加到活跃页面
        mock_manager._active_pages["test1"] = context1
        mock_manager._active_pages["test2"] = context2
        
        pages_info = mock_manager.get_active_pages_info()
        
        assert len(pages_info) == 2
        
        # 检查第一个页面信息
        page1_info = pages_info[0]
        assert page1_info["slot"] == 0
        assert page1_info["url_id"] == "test1"
        assert page1_info["url"] == "https://example.com/page1"
        assert page1_info["title"] == "页面1"
        assert page1_info["start_time"] == 1234567890.0
        assert page1_info["processors"] == []
        
        # 检查第二个页面信息
        page2_info = pages_info[1]
        assert page2_info["slot"] == 1
        assert page2_info["url_id"] == "test2"

    @pytest.mark.asyncio
    async def test_get_page_screenshot_empty_pages(self, mock_manager):
        """测试在没有活跃页面时获取截图"""
        screenshot = await mock_manager.get_page_screenshot(0)
        assert screenshot is None

    @pytest.mark.asyncio
    async def test_get_page_screenshot_invalid_slot(self, mock_manager):
        """测试无效槽位号获取截图"""
        # 添加一个页面
        mock_page = MagicMock()
        url = URL(id="test", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        mock_manager._active_pages["test"] = context
        
        # 测试负数槽位
        screenshot = await mock_manager.get_page_screenshot(-1)
        assert screenshot is None
        
        # 测试超出范围的槽位
        screenshot = await mock_manager.get_page_screenshot(10)
        assert screenshot is None

    @pytest.mark.asyncio
    async def test_get_page_screenshot_success(self, mock_manager):
        """测试成功获取页面截图"""
        # 模拟页面和截图数据
        mock_page = AsyncMock()
        mock_screenshot_data = b"fake_png_data"
        mock_page.screenshot.return_value = mock_screenshot_data
        
        url = URL(id="test", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        mock_manager._active_pages["test"] = context
        
        screenshot = await mock_manager.get_page_screenshot(0)
        
        assert screenshot == mock_screenshot_data
        
        # 验证调用参数
        mock_page.screenshot.assert_called_once_with(
            type="png",
            full_page=True,
            timeout=5000
        )

    @pytest.mark.asyncio
    async def test_get_page_screenshot_exception(self, mock_manager):
        """测试截图时发生异常"""
        # 模拟页面截图抛出异常
        mock_page = AsyncMock()
        mock_page.screenshot.side_effect = Exception("截图失败")
        
        url = URL(id="test", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        mock_manager._active_pages["test"] = context
        
        with patch('doc_helper.manager.logger') as mock_logger:
            screenshot = await mock_manager.get_page_screenshot(0)
            
            assert screenshot is None
            # 验证记录了错误日志
            mock_logger.error.assert_called_once()