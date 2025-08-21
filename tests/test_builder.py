"""
Builder模块的单元测试
"""

import pytest
from unittest.mock import Mock, AsyncMock

from doc_helper.builder import (
    PageProcessingBuilder, 
    create_web_scraper, 
    create_pdf_generator,
    create_link_crawler
)
from doc_helper.manager import ChromiumManager
from doc_helper.url_collection import SimpleCollection
from doc_helper.processors import (
    PageMonitor, RequestMonitor, LinksFinder, 
    ElementCleaner, ContentFinder, PDFExporter
)


class TestPageProcessingBuilder:
    """PageProcessingBuilder的测试"""
    
    def test_builder_initialization(self):
        """测试构建器初始化"""
        builder = PageProcessingBuilder()
        
        assert builder._url_collection is None
        assert builder._entry_urls == []
        assert builder._concurrent_tabs == 1
        assert builder._page_timeout == 60.0
        assert builder._processors == []
        assert builder._request_monitor is None
        assert builder._content_finder is None
    
    def test_set_entry_url(self):
        """测试设置入口URL"""
        builder = PageProcessingBuilder()
        result = builder.set_entry_url("https://example.com")
        
        assert result is builder  # 支持链式调用
        assert builder._entry_urls == ["https://example.com"]
    
    def test_set_entry_urls(self):
        """测试设置多个入口URL"""
        urls = ["https://example.com", "https://test.com"]
        builder = PageProcessingBuilder()
        result = builder.set_entry_urls(urls)
        
        assert result is builder
        assert builder._entry_urls == urls
    
    def test_set_concurrent_tabs(self):
        """测试设置并发标签页数量"""
        builder = PageProcessingBuilder()
        
        # 正常值
        result = builder.set_concurrent_tabs(5)
        assert result is builder
        assert builder._concurrent_tabs == 5
        
        # 最小值保护
        builder.set_concurrent_tabs(0)
        assert builder._concurrent_tabs == 1
        
        builder.set_concurrent_tabs(-1)
        assert builder._concurrent_tabs == 1
    
    def test_set_page_timeout(self):
        """测试设置页面超时"""
        builder = PageProcessingBuilder()
        result = builder.set_page_timeout(30.0)
        
        assert result is builder
        assert builder._page_timeout == 30.0
    
    def test_set_verbose(self):
        """测试设置可视化模式"""
        builder = PageProcessingBuilder()
        
        # 测试设置为True
        result = builder.set_verbose(True)
        assert result is builder  # 测试链式调用
        assert builder._verbose is True
        
        # 测试设置为False
        builder.set_verbose(False)
        assert builder._verbose is False
    
    def test_set_headless(self):
        """测试设置无头模式"""
        builder = PageProcessingBuilder()
        
        # 测试设置为True
        result = builder.set_headless(True)
        assert result is builder  # 测试链式调用
        assert builder._headless is True
        
        # 测试设置为False
        builder.set_headless(False)
        assert builder._headless is False
    
    def test_set_poll_interval(self):
        """测试设置轮询间隔"""
        builder = PageProcessingBuilder()
        result = builder.set_poll_interval(2.0)
        assert result is builder  # 测试链式调用
        assert builder._poll_interval == 2.0
    
    def test_set_detect_timeout(self):
        """测试设置检测超时时间"""
        builder = PageProcessingBuilder()
        result = builder.set_detect_timeout(10.0)
        assert result is builder  # 测试链式调用
        assert builder._detect_timeout == 10.0
    
    def test_set_retry_callback(self):
        """测试设置重试回调函数"""
        def mock_callback(url, error):
            return True
        
        builder = PageProcessingBuilder()
        result = builder.set_retry_callback(mock_callback)
        assert result is builder  # 测试链式调用
        assert builder._retry_callback is mock_callback
    
    def test_set_url_collection(self):
        """测试设置URL集合"""
        builder = PageProcessingBuilder()
        collection = SimpleCollection()
        
        result = builder.set_url_collection(collection)
        assert result is builder
        assert builder._url_collection is collection
    
    def test_add_processor(self):
        """测试添加自定义处理器"""
        builder = PageProcessingBuilder()
        mock_processor = Mock()
        mock_processor.name = "test_processor"
        
        result = builder.add_processor(mock_processor)
        assert result is builder
        assert mock_processor in builder._processors
    
    def test_block_url_patterns(self):
        """测试添加URL屏蔽模式"""
        builder = PageProcessingBuilder()
        patterns = [".*\\.gif", ".*analytics.*"]
        
        result = builder.block_url_patterns(patterns)
        assert result is builder
        assert builder._request_monitor is not None
        assert builder._request_monitor.block_url_patterns == set(patterns)
        assert builder._url_collection is not None  # 自动创建
    
    def test_block_url_patterns_replace_existing(self):
        """测试替换现有的RequestMonitor"""
        builder = PageProcessingBuilder()
        
        # 添加第一个
        builder.block_url_patterns(["pattern1"])
        first_monitor = builder._request_monitor
        
        # 添加第二个，应该替换第一个
        builder.block_url_patterns(["pattern2"])
        second_monitor = builder._request_monitor
        
        assert first_monitor is not second_monitor
        assert second_monitor.block_url_patterns == {"pattern2"}
    
    def test_find_links(self):
        """测试添加链接发现处理器"""
        builder = PageProcessingBuilder()
        
        result = builder.find_links("a.link")
        assert result is builder
        assert len(builder._processors) == 1
        assert isinstance(builder._processors[0], LinksFinder)
        assert builder._processors[0].css_selector == "a.link"
        assert builder._url_collection is not None  # 自动创建
    
    def test_clean_elements(self):
        """测试添加元素清理处理器"""
        builder = PageProcessingBuilder()
        
        result = builder.clean_elements(".ads")
        assert result is builder
        assert len(builder._processors) == 1
        assert isinstance(builder._processors[0], ElementCleaner)
        assert builder._processors[0].css_selector == ".ads"
    
    def test_find_content(self):
        """测试添加内容查找处理器"""
        builder = PageProcessingBuilder()
        
        result = builder.find_content("main")
        assert result is builder
        assert builder._content_finder is not None
        assert isinstance(builder._content_finder, ContentFinder)
        assert builder._content_finder.css_selector == "main"
    
    def test_find_content_replace_existing(self):
        """测试替换现有的ContentFinder"""
        builder = PageProcessingBuilder()
        
        # 添加第一个
        builder.find_content("main")
        first_finder = builder._content_finder
        
        # 添加第二个，应该替换第一个
        builder.find_content("article")
        second_finder = builder._content_finder
        
        assert first_finder is not second_finder
        assert second_finder.css_selector == "article"
    
    def test_export_pdf(self):
        """测试添加PDF导出处理器"""
        builder = PageProcessingBuilder()
        
        # 测试指定输出路径
        result = builder.export_pdf("/tmp/test.pdf")
        assert result is builder
        assert len(builder._processors) == 1
        assert isinstance(builder._processors[0], PDFExporter)
        assert builder._processors[0].output_path == "/tmp/test.pdf"
        
        # 测试指定输出目录
        builder2 = PageProcessingBuilder()
        builder2.export_pdf(output_dir="/tmp/output")
        assert builder2._processors[0].output_dir == "/tmp/output"
    
    def test_build_without_entry_url(self):
        """测试没有入口URL时构建失败"""
        builder = PageProcessingBuilder()
        
        with pytest.raises(ValueError, match="必须设置至少一个入口URL"):
            builder.build()
    
    def test_build_success(self):
        """测试成功构建"""
        builder = PageProcessingBuilder()
        builder.set_entry_url("https://example.com")
        
        manager = builder.build()
        
        # 验证管理器类型和配置
        assert manager is not None
        assert hasattr(manager, 'run')
        assert builder._url_collection is not None
        
        # 验证URL已添加到集合
        from doc_helper.protocol import URLStatus
        urls = builder._url_collection.get_by_status(URLStatus.PENDING)
        assert len(urls) >= 1
        assert any(url.url == "https://example.com" for url in urls)
    
    def test_build_with_all_processors(self):
        """测试构建包含所有处理器的管理器"""
        builder = (PageProcessingBuilder()
            .set_entry_url("https://example.com")
            .set_concurrent_tabs(3)
            .block_url_patterns([".*\\.gif"])
            .find_links("a")
            .clean_elements(".ads")
            .find_content("main")
            .export_pdf("/tmp/test.pdf"))
        
        manager = builder.build()
        
        assert manager is not None
        assert builder._request_monitor is not None
        assert builder._content_finder is not None
        assert len(builder._processors) == 3  # LinksFinder, ElementCleaner, PDFExporter
    
    def test_build_with_all_config(self):
        """测试构建包含完整配置的管理器"""
        def mock_callback(url, error):
            return False
        
        builder = (PageProcessingBuilder()
            .set_entry_url("https://example.com")
            .set_concurrent_tabs(2)
            .set_page_timeout(120.0)
            .set_poll_interval(2.0)
            .set_detect_timeout(10.0)
            .set_headless(False)
            .set_verbose(True)
            .set_retry_callback(mock_callback)
            .find_links("a")
            .export_pdf("/tmp/test.pdf"))
        
        manager = builder.build()
        
        # 验证管理器创建成功
        assert manager is not None
        assert isinstance(manager, ChromiumManager)
        
        # 验证配置正确传递
        config = manager.config
        assert config.max_concurrent_tabs == 2
        assert config.page_timeout == 120.0
        assert config.poll_interval == 2.0
        assert config.detect_timeout == 10.0
        assert config.headless is False
        
        # 验证其他参数
        assert manager.verbose is True


class TestBuilderFactories:
    """测试构建器工厂函数"""
    
    def test_create_web_scraper(self):
        """测试创建网页爬虫构建器"""
        builder = create_web_scraper()
        
        assert isinstance(builder, PageProcessingBuilder)
        assert builder._entry_urls == []
        assert builder._processors == []
    
    def test_create_pdf_generator(self):
        """测试创建PDF生成器构建器"""
        builder = create_pdf_generator()
        
        assert isinstance(builder, PageProcessingBuilder)
        assert len(builder._processors) == 2  # ElementCleaner + PDFExporter
        assert builder._content_finder is not None
        
        # 验证预配置的处理器
        element_cleaner = None
        pdf_exporter = None
        
        for processor in builder._processors:
            if isinstance(processor, ElementCleaner):
                element_cleaner = processor
            elif isinstance(processor, PDFExporter):
                pdf_exporter = processor
        
        assert element_cleaner is not None
        assert pdf_exporter is not None
        assert isinstance(builder._content_finder, ContentFinder)
    
    def test_create_link_crawler(self):
        """测试创建链接爬虫构建器"""
        builder = create_link_crawler()
        
        assert isinstance(builder, PageProcessingBuilder)
        assert builder._request_monitor is not None
        assert len(builder._processors) == 2  # LinksFinder + ElementCleaner
        
        # 验证预配置的屏蔽模式
        patterns = builder._request_monitor.block_url_patterns
        assert ".*\\.gif" in patterns
        assert ".*analytics.*" in patterns
    
    def test_factory_chaining(self):
        """测试工厂函数的链式调用"""
        manager = (create_pdf_generator()
            .set_entry_url("https://example.com")
            .set_concurrent_tabs(2)
            .build())
        
        assert manager is not None


if __name__ == "__main__":
    pytest.main([__file__])