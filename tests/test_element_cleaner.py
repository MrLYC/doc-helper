"""
ElementCleaner 处理器的单元测试
"""

import pytest
from unittest.mock import AsyncMock, Mock

from doc_helper.processors import ElementCleaner
from doc_helper.protocol import URL, URLCollection, URLStatus, PageContext, ProcessorState


class TestElementCleaner:
    """ElementCleaner处理器的测试类"""
    
    @pytest.fixture
    def mock_url_collection(self):
        """创建模拟URL集合"""
        collection = Mock(spec=URLCollection)
        return collection
    
    @pytest.fixture  
    def mock_page_context(self):
        """创建模拟页面上下文"""
        context = Mock(spec=PageContext)
        context.data = {}
        
        # 模拟当前URL
        mock_url = Mock(spec=URL)
        mock_url.url = "https://example.com/test"
        mock_url.status = URLStatus.PENDING
        context.url = mock_url
        
        # 模拟页面对象
        context.page = AsyncMock()
        
        return context
    
    @pytest.mark.asyncio
    async def test_element_cleaner_initialization(self):
        """测试ElementCleaner初始化"""
        # 使用默认CSS选择器
        cleaner = ElementCleaner("element_cleaner")
        assert cleaner.name == "element_cleaner"
        assert cleaner.priority == 20
        assert cleaner.css_selector == "*[id*='ad'], *[class*='popup']"
        assert cleaner._elements_removed == 0
        assert cleaner.state == ProcessorState.WAITING
        
        # 使用自定义CSS选择器
        custom_cleaner = ElementCleaner("custom_cleaner", css_selector=".advertisement")
        assert custom_cleaner.css_selector == ".advertisement"
        assert custom_cleaner.priority == 20  # 优先级固定为20
    
    @pytest.mark.asyncio
    async def test_element_cleaner_detect_ready_state(self, mock_page_context):
        """测试ElementCleaner在页面就绪状态下的检测逻辑"""
        cleaner = ElementCleaner("element_cleaner")
        
        # 设置页面状态为ready
        mock_page_context.data["page_state"] = "ready"
        mock_page_context.url = Mock()
        mock_page_context.url.url = "https://example.com/test"
        
        result = await cleaner.detect(mock_page_context)
        assert result == ProcessorState.READY
        
        # 设置页面状态为completed
        mock_page_context.data["page_state"] = "completed"
        
        result = await cleaner.detect(mock_page_context)
        assert result == ProcessorState.READY
    
    @pytest.mark.asyncio
    async def test_element_cleaner_detect_wrong_state(self, mock_page_context):
        """测试ElementCleaner在错误状态下不启动"""
        cleaner = ElementCleaner("element_cleaner")
        
        # 页面状态为loading时不应启动
        mock_page_context.data["page_state"] = "loading"
        mock_page_context.url = Mock()
        mock_page_context.url.url = "https://example.com/test"
        
        result = await cleaner.detect(mock_page_context)
        assert result == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_success(self, mock_page_context):
        """测试ElementCleaner成功删除元素"""
        cleaner = ElementCleaner("element_cleaner", css_selector=".ad")
        
        # 模拟找到3个匹配元素
        mock_elements = [AsyncMock(), AsyncMock(), AsyncMock()]
        mock_page_context.page.query_selector_all = AsyncMock(return_value=mock_elements)
        
        # 模拟元素删除成功
        for element in mock_elements:
            element.evaluate = AsyncMock()
        
        await cleaner.run(mock_page_context)
        
        # 验证状态
        assert cleaner.state == ProcessorState.COMPLETED
        assert cleaner._elements_removed == 3
        
        # 验证上下文数据
        assert mock_page_context.data["elements_removed"] == 3
        assert mock_page_context.data["css_selector_used"] == ".ad"
        
        # 验证调用了正确的方法
        mock_page_context.page.query_selector_all.assert_called_once_with(".ad")
        for element in mock_elements:
            element.evaluate.assert_called_once_with("element => element.remove()")
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_no_elements(self, mock_page_context):
        """测试ElementCleaner未找到匹配元素"""
        cleaner = ElementCleaner("element_cleaner", css_selector=".nonexistent")
        
        # 模拟未找到匹配元素
        mock_page_context.page.query_selector_all = AsyncMock(return_value=[])
        
        await cleaner.run(mock_page_context)
        
        # 验证状态 - 未找到元素仍然算成功
        assert cleaner.state == ProcessorState.COMPLETED
        assert cleaner._elements_removed == 0
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_partial_failure(self, mock_page_context):
        """测试ElementCleaner部分元素删除失败"""
        cleaner = ElementCleaner("element_cleaner", css_selector=".ad")
        
        # 模拟找到3个元素，但第2个删除失败
        mock_elements = [AsyncMock(), AsyncMock(), AsyncMock()]
        mock_page_context.page.query_selector_all = AsyncMock(return_value=mock_elements)
        
        # 设置第2个元素删除失败
        mock_elements[0].evaluate = AsyncMock()
        mock_elements[1].evaluate = AsyncMock(side_effect=Exception("删除失败"))
        mock_elements[2].evaluate = AsyncMock()
        
        await cleaner.run(mock_page_context)
        
        # 验证状态 - 有部分成功删除就算完成
        assert cleaner.state == ProcessorState.COMPLETED
        assert cleaner._elements_removed == 2
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_complete_failure(self, mock_page_context):
        """测试ElementCleaner完全删除失败"""
        cleaner = ElementCleaner("element_cleaner", css_selector=".ad")
        
        # 模拟找到元素但全部删除失败
        mock_elements = [AsyncMock(), AsyncMock()]
        mock_page_context.page.query_selector_all = AsyncMock(return_value=mock_elements)
        
        # 设置所有元素删除失败
        for element in mock_elements:
            element.evaluate = AsyncMock(side_effect=Exception("删除失败"))
        
        await cleaner.run(mock_page_context)
        
        # 验证状态
        assert cleaner.state == ProcessorState.CANCELLED
        assert cleaner._elements_removed == 0
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_page_error(self, mock_page_context):
        """测试ElementCleaner页面操作错误"""
        cleaner = ElementCleaner("element_cleaner")
        
        # 模拟页面查询失败
        mock_page_context.page.query_selector_all = AsyncMock(side_effect=Exception("页面错误"))
        
        await cleaner.run(mock_page_context)
        
        # 验证状态
        assert cleaner.state == ProcessorState.CANCELLED
        assert cleaner._elements_removed == 0
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_no_page(self, mock_page_context):
        """测试ElementCleaner无页面对象"""
        cleaner = ElementCleaner("element_cleaner")
        
        # 设置页面对象为None
        mock_page_context.page = None
        
        await cleaner.run(mock_page_context)
        
        # 验证状态
        assert cleaner.state == ProcessorState.CANCELLED
    
    @pytest.mark.asyncio
    async def test_element_cleaner_run_no_url(self, mock_page_context):
        """测试ElementCleaner无当前URL"""
        cleaner = ElementCleaner("element_cleaner")
        
        # 设置当前URL为None
        mock_page_context.url = None
        
        await cleaner.run(mock_page_context)
        
        # 验证状态
        assert cleaner.state == ProcessorState.CANCELLED
    
    @pytest.mark.asyncio
    async def test_element_cleaner_finish(self, mock_page_context):
        """测试ElementCleaner清理"""
        cleaner = ElementCleaner("element_cleaner")
        
        # 设置一些测试数据
        cleaner._elements_removed = 5
        cleaner._set_state(ProcessorState.COMPLETED)
        
        await cleaner.finish(mock_page_context)
        
        # 验证清理
        assert cleaner._elements_removed == 0
        assert cleaner.state == ProcessorState.FINISHED
    
    @pytest.mark.asyncio
    async def test_element_cleaner_custom_selectors(self):
        """测试ElementCleaner自定义选择器"""
        # 测试各种CSS选择器
        selectors = [
            ".advertisement",
            "#popup-modal", 
            "div[class*='banner']",
            "iframe[src*='ads']",
            ".sidebar, .footer-ads, .header-banner"
        ]
        
        for selector in selectors:
            cleaner = ElementCleaner("test_cleaner", css_selector=selector)
            assert cleaner.css_selector == selector
            assert cleaner.priority == 20


if __name__ == "__main__":
    pytest.main([__file__])