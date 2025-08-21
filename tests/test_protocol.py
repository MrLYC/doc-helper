"""
协议模块的单元测试
"""

import json
import time
from unittest.mock import Mock, patch

import pytest

from doc_helper.protocol import (
    URL, URLCollection, URLStatus, ProcessorState, PageContext, PageProcessor
)


class TestURL:
    """URL类的测试"""
    
    def test_url_creation(self):
        """测试URL创建"""
        url = URL(id="1", url="https://example.com")
        assert url.id == "1"
        assert url.url == "https://example.com"
        assert url.status == URLStatus.PENDING
        assert url.category == ""
        assert isinstance(url.updated_at, float)
    
    def test_url_invalid_format(self):
        """测试无效URL格式"""
        with pytest.raises(ValueError, match="无效的URL格式"):
            URL(id="1", url="invalid-url")
        
        with pytest.raises(ValueError, match="URL不能为空"):
            URL(id="1", url="")
    
    def test_url_properties(self):
        """测试URL属性"""
        url = URL(id="1", url="https://example.com:8080/path/to/page?query=value#fragment")
        
        assert url.domain == "example.com:8080"
        assert url.path == "/path/to/page"
        assert url.url_without_query == "https://example.com:8080/path/to/page"
    
    def test_url_update_status(self):
        """测试状态更新"""
        url = URL(id="1", url="https://example.com")
        old_time = url.updated_at
        
        time.sleep(0.01)  # 确保时间差异
        url.update_status(URLStatus.VISITED)
        
        assert url.status == URLStatus.VISITED
        assert url.updated_at > old_time
    
    def test_url_serialization(self):
        """测试序列化和反序列化"""
        original = URL(id="1", url="https://example.com", category="test")
        original.update_status(URLStatus.VISITED)
        
        # 测试字典序列化
        data = original.to_dict()
        assert data["id"] == "1"
        assert data["url"] == "https://example.com"
        assert data["status"] == "visited"
        assert data["category"] == "test"
        
        # 测试从字典反序列化
        restored = URL.from_dict(data)
        assert restored.id == original.id
        assert restored.url == original.url
        assert restored.status == original.status
        assert restored.category == original.category
        
        # 测试JSON序列化
        json_str = original.to_json()
        assert isinstance(json_str, str)
        
        # 测试从JSON反序列化
        restored_from_json = URL.from_json(json_str)
        assert restored_from_json.url == original.url
    
    def test_url_equality_and_hash(self):
        """测试相等性和哈希"""
        url1 = URL(id="1", url="https://example.com")
        url2 = URL(id="2", url="https://example.com")  # 不同ID，相同URL
        url3 = URL(id="1", url="https://other.com")    # 相同ID，不同URL
        
        assert url1 == url2  # 基于URL判断相等
        assert url1 != url3
        assert hash(url1) == hash(url2)
        assert hash(url1) != hash(url3)


class TestURLCollection:
    """URL集合类的测试"""
    
    def test_add_url(self):
        """测试添加URL"""
        collection = URLCollection()
        url1 = URL(id="1", url="https://example.com")
        url2 = URL(id="2", url="https://example.com")  # 相同URL
        
        assert collection.add(url1) is True   # 新URL
        assert collection.add(url2) is False  # 重复URL
        
        assert collection.count_by_status(URLStatus.PENDING) == 1
    
    def test_get_by_id_and_url(self):
        """测试按ID和URL获取"""
        collection = URLCollection()
        url = URL(id="1", url="https://example.com")
        collection.add(url)
        
        assert collection.get_by_id("1") == url
        assert collection.get_by_url("https://example.com") == url
        assert collection.get_by_id("nonexistent") is None
        assert collection.get_by_url("https://nonexistent.com") is None
    
    def test_get_by_status(self):
        """测试按状态获取"""
        collection = URLCollection()
        
        # 添加多个URL
        url1 = URL(id="1", url="https://example1.com")
        url2 = URL(id="2", url="https://example2.com")
        url3 = URL(id="3", url="https://example3.com")
        
        collection.add(url1)
        collection.add(url2)
        collection.add(url3)
        
        # 更新状态
        time.sleep(0.01)
        collection.update_status("2", URLStatus.VISITED)
        time.sleep(0.01)
        collection.update_status("3", URLStatus.FAILED)
        
        # 测试获取
        pending_urls = collection.get_by_status(URLStatus.PENDING)
        assert len(pending_urls) == 1
        assert pending_urls[0].id == "1"
        
        visited_urls = collection.get_by_status(URLStatus.VISITED)
        assert len(visited_urls) == 1
        assert visited_urls[0].id == "2"
        
        # 测试限制数量
        all_urls = collection.get_by_status(URLStatus.PENDING, limit=1)
        assert len(all_urls) <= 1
    
    def test_status_operations(self):
        """测试状态操作"""
        collection = URLCollection()
        url = URL(id="1", url="https://example.com")
        collection.add(url)
        
        # 测试状态检查
        assert collection.has_status("1", URLStatus.PENDING) is True
        assert collection.has_status("1", URLStatus.VISITED) is False
        assert collection.has_url_status("https://example.com", URLStatus.PENDING) is True
        
        # 测试状态更新
        assert collection.update_status("1", URLStatus.VISITED) is True
        assert collection.update_status("nonexistent", URLStatus.VISITED) is False
        
        assert collection.has_status("1", URLStatus.VISITED) is True
        assert collection.count_by_status(URLStatus.VISITED) == 1
        assert collection.count_by_status(URLStatus.PENDING) == 0
    
    def test_get_all_statuses(self):
        """测试获取所有状态统计"""
        collection = URLCollection()
        
        # 添加不同状态的URL
        for i in range(3):
            collection.add(URL(id=str(i), url=f"https://example{i}.com"))
        
        collection.update_status("1", URLStatus.VISITED)
        collection.update_status("2", URLStatus.FAILED)
        
        stats = collection.get_all_statuses()
        assert stats[URLStatus.PENDING] == 1
        assert stats[URLStatus.VISITED] == 1
        assert stats[URLStatus.FAILED] == 1


class MockPageProcessor(PageProcessor):
    """用于测试的模拟页面处理器"""
    
    def __init__(self, name: str, detect_result: ProcessorState = ProcessorState.READY):
        super().__init__(name)
        self.detect_result = detect_result
        self.detect_called = False
        self.run_called = False
        self.finish_called = False
    
    async def detect(self, context: PageContext) -> ProcessorState:
        self.detect_called = True
        self._set_state(self.detect_result)
        return self.detect_result
    
    async def run(self, context: PageContext) -> None:
        self.run_called = True
        self._set_state(ProcessorState.COMPLETED)
    
    async def finish(self, context: PageContext) -> None:
        self.finish_called = True
        self._set_state(ProcessorState.FINISHED)


class TestPageProcessor:
    """页面处理器的测试"""
    
    def test_processor_creation(self):
        """测试处理器创建"""
        processor = MockPageProcessor("test")
        assert processor.name == "test"
        assert processor.state == ProcessorState.WAITING
    
    @pytest.mark.asyncio
    async def test_processor_lifecycle(self):
        """测试处理器生命周期"""
        processor = MockPageProcessor("test", ProcessorState.READY)
        
        # 模拟页面上下文
        mock_page = Mock()
        mock_url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=mock_url)
        
        # 测试检测
        state = await processor.detect(context)
        assert state == ProcessorState.READY
        assert processor.detect_called is True
        
        # 测试运行
        await processor.run(context)
        assert processor.run_called is True
        assert processor.state == ProcessorState.COMPLETED
        
        # 测试完成
        await processor.finish(context)
        assert processor.finish_called is True
        assert processor.state == ProcessorState.FINISHED


class TestPageContext:
    """页面上下文的测试"""
    
    def test_context_creation(self):
        """测试上下文创建"""
        mock_page = Mock()
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        
        assert context.page == mock_page
        assert context.url == url
        assert isinstance(context.data, dict)
        assert isinstance(context.processors, dict)
        assert isinstance(context.start_time, float)
    
    def test_processor_management(self):
        """测试处理器管理"""
        mock_page = Mock()
        url = URL(id="1", url="https://example.com")
        context = PageContext(page=mock_page, url=url)
        
        processor = MockPageProcessor("test")
        context.add_processor(processor)
        
        assert context.get_processor("test") == processor
        assert context.get_processor("nonexistent") is None
        assert "test" in context.processors