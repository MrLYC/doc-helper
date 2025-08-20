"""
页面处理器的单元测试
"""

import pytest
from unittest.mock import AsyncMock, Mock

from pdf_helper.processors import (
    PageLoadProcessor, ContentExtractProcessor, PDFGenerateProcessor
)
from pdf_helper.protocol import URL, PageContext, ProcessorState


class TestProcessors:
    """处理器的测试"""
    
    @pytest.fixture
    def mock_page_context(self):
        """创建模拟页面上下文"""
        mock_page = AsyncMock()
        mock_page.title.return_value = "Test Page"
        mock_page.content.return_value = "<html><body>Test Content</body></html>"
        mock_page.pdf = AsyncMock(return_value=b"fake pdf content")
        mock_page.evaluate.return_value = "complete"  # document.readyState
        mock_page.query_selector.return_value = True  # 元素存在
        
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        return context
    
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


if __name__ == "__main__":
    pytest.main([__file__])