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
        
        # 测试运行
        await processor.run(mock_page_context)
        assert processor.state == ProcessorState.COMPLETED
        assert "title" in mock_page_context.data
        assert mock_page_context.data["title"] == "Test Page"
        
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
        
        # 测试运行
        await processor.run(mock_page_context)
        assert processor.state == ProcessorState.COMPLETED
        assert "content" in mock_page_context.data
        
        # 测试完成
        await processor.finish(mock_page_context)
        assert processor.state == ProcessorState.FINISHED
    
    @pytest.mark.asyncio
    async def test_pdf_generate_processor(self, mock_page_context):
        """测试PDF生成处理器"""
        processor = PDFGenerateProcessor("pdf_generator")
        
        # 没有内容数据时应该等待
        state = await processor.detect(mock_page_context)
        assert state == ProcessorState.WAITING
        
        # 添加内容数据
        mock_page_context.data["content"] = "Test Content"
        mock_page_context.data["content_length"] = 12
        
        # 现在应该就绪
        state = await processor.detect(mock_page_context)
        assert state == ProcessorState.READY
        
        # 测试运行
        await processor.run(mock_page_context)
        assert processor.state == ProcessorState.COMPLETED
        assert "pdf_path" in mock_page_context.data
        
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
        
        # 现在extractor应该就绪
        assert await extractor.detect(mock_page_context) == ProcessorState.READY
        assert await pdf_gen.detect(mock_page_context) == ProcessorState.WAITING
        
        # 模拟内容提取
        mock_page_context.page.evaluate.side_effect = ["Test Content", "<body>Test Content</body>"]
        
        # 运行extractor
        await extractor.run(mock_page_context)
        
        # 现在pdf_gen应该就绪
        assert await pdf_gen.detect(mock_page_context) == ProcessorState.READY
        
        # 运行pdf_gen
        await pdf_gen.run(mock_page_context)
        
        # 所有处理器都应该完成
        assert loader.state == ProcessorState.COMPLETED
        assert extractor.state == ProcessorState.COMPLETED
        assert pdf_gen.state == ProcessorState.COMPLETED


if __name__ == "__main__":
    pytest.main([__file__])