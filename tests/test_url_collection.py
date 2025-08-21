"""
URL集合实现的单元测试
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from doc_helper.url_collection import FileCollection, SimpleCollection
from doc_helper.protocol import URLStatus


class TestFileCollection:
    """FileCollection类的测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """创建临时目录和测试文件"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 创建测试文件
            (temp_path / "test1.txt").write_text("测试文件1")
            (temp_path / "test2.pdf").write_text("测试PDF")
            (temp_path / "test3.html").write_text("<html>测试HTML</html>")
            (temp_path / "ignore.log").write_text("日志文件")  # 应该被忽略
            
            # 创建子目录
            sub_dir = temp_path / "subdir"
            sub_dir.mkdir()
            (sub_dir / "sub1.txt").write_text("子目录文件")
            
            # 创建隐藏文件（应该被忽略）
            (temp_path / ".hidden").write_text("隐藏文件")
            
            yield temp_path
    
    def test_file_collection_creation(self, temp_dir):
        """测试文件集合创建"""
        collection = FileCollection(
            base_directory=temp_dir,
            extensions={'.txt', '.pdf', '.html'}
        )
        
        # 应该找到4个文件（test1.txt, test2.pdf, test3.html, subdir/sub1.txt）
        assert collection.count_by_status(URLStatus.PENDING) == 4
        
        # 检查所有URL都是file://格式
        for url_obj in collection.get_by_status(URLStatus.PENDING):
            assert url_obj.url.startswith('file://')
            assert url_obj.category == "file"
    
    def test_file_collection_no_extensions(self, temp_dir):
        """测试不指定扩展名的文件集合"""
        collection = FileCollection(base_directory=temp_dir)
        
        # 应该找到所有非隐藏文件（除了.hidden）
        assert collection.count_by_status(URLStatus.PENDING) == 5
    
    def test_file_collection_invalid_directory(self):
        """测试无效目录"""
        with pytest.raises(ValueError, match="目录不存在"):
            FileCollection("/nonexistent/directory")
        
        # 创建一个文件而不是目录
        with tempfile.NamedTemporaryFile() as temp_file:
            with pytest.raises(ValueError, match="路径不是目录"):
                FileCollection(temp_file.name)
    
    def test_get_relative_path(self, temp_dir):
        """测试获取相对路径"""
        collection = FileCollection(
            base_directory=temp_dir,
            extensions={'.txt'}
        )
        
        # 找到一个txt文件
        txt_files = collection.get_by_status(URLStatus.PENDING)
        assert len(txt_files) >= 1
        
        url_obj = txt_files[0]
        relative_path = collection.get_relative_path(url_obj.id)
        
        assert relative_path is not None
        assert relative_path.endswith('.txt')
        # 应该不包含绝对路径
        assert not os.path.isabs(relative_path)
    
    def test_get_file_info(self, temp_dir):
        """测试获取文件信息"""
        collection = FileCollection(
            base_directory=temp_dir,
            extensions={'.txt'}
        )
        
        txt_files = collection.get_by_status(URLStatus.PENDING)
        url_obj = txt_files[0]
        
        file_info = collection.get_file_info(url_obj.id)
        
        assert file_info is not None
        assert 'path' in file_info
        assert 'relative_path' in file_info
        assert 'size' in file_info
        assert 'extension' in file_info
        assert file_info['extension'] == '.txt'
        assert file_info['is_file'] is True
        assert file_info['size'] > 0
    
    def test_refresh(self, temp_dir):
        """测试刷新文件列表"""
        collection = FileCollection(
            base_directory=temp_dir,
            extensions={'.txt'}
        )
        
        initial_count = collection.count_by_status(URLStatus.PENDING)
        assert initial_count >= 1
        
        # 标记一个文件为已访问
        txt_files = collection.get_by_status(URLStatus.PENDING)
        collection.update_status(txt_files[0].id, URLStatus.VISITED)
        
        assert collection.count_by_status(URLStatus.VISITED) == 1
        
        # 添加新文件
        (temp_dir / "new_file.txt").write_text("新文件")
        
        # 刷新
        collection.refresh()
        
        # 应该发现新文件，并且保持原有状态
        assert collection.count_by_status(URLStatus.PENDING) == initial_count  # 新文件
        assert collection.count_by_status(URLStatus.VISITED) == 1  # 保持原状态


class TestSimpleCollection:
    """SimpleCollection类的测试"""
    
    @pytest.fixture
    def collection(self):
        """创建简单集合实例"""
        return SimpleCollection()
    
    def test_add_url(self, collection):
        """测试添加URL"""
        url = "https://example.com"
        url_id = collection.add_url(url)
        
        assert url_id is not None
        assert url_id.startswith("url_")
        
        # 验证URL被正确添加
        url_obj = collection.get_by_id(url_id)
        assert url_obj is not None
        assert url_obj.url == url
        assert url_obj.status == URLStatus.PENDING
        
        # 重复添加同一个URL应该返回相同的ID
        url_id2 = collection.add_url(url)
        assert url_id == url_id2
    
    def test_remove_url(self, collection):
        """测试移除URL"""
        url = "https://example.com"
        url_id = collection.add_url(url)
        
        # 通过ID移除
        assert collection.remove_url(url_id) is True
        assert collection.get_by_id(url_id) is None
        
        # 重新添加，通过URL移除
        url_id = collection.add_url(url)
        assert collection.remove_url(url) is True
        assert collection.get_by_url(url) is None
        
        # 移除不存在的URL
        assert collection.remove_url("nonexistent") is False
    
    def test_bulk_add_urls(self, collection):
        """测试批量添加URL"""
        urls = [
            "https://example.com",
            "https://github.com",
            "https://python.org"
        ]
        
        url_ids = collection.bulk_add_urls(urls)
        
        assert len(url_ids) == 3
        assert collection.count_by_status(URLStatus.PENDING) == 3
        
        # 验证每个URL都被正确添加
        for i, url in enumerate(urls):
            url_obj = collection.get_by_id(url_ids[i])
            assert url_obj.url == url
    
    def test_clear_all(self, collection):
        """测试清空所有URL"""
        # 添加一些URL
        collection.bulk_add_urls([
            "https://example.com",
            "https://github.com"
        ])
        
        assert collection.count_by_status(URLStatus.PENDING) == 2
        
        # 清空
        collection.clear_all()
        
        assert collection.count_by_status(URLStatus.PENDING) == 0
        stats = collection.get_all_statuses()
        assert all(count == 0 for count in stats.values())
    
    def test_get_pending_urls(self, collection):
        """测试获取待处理的URL"""
        urls = ["https://example.com", "https://github.com"]
        url_ids = collection.bulk_add_urls(urls)
        
        # 标记一个URL为已访问
        collection.update_status(url_ids[0], URLStatus.VISITED)
        
        pending_urls = collection.get_pending_urls()
        assert len(pending_urls) == 1
        assert pending_urls[0].url == urls[1]
    
    def test_custom_category(self, collection):
        """测试自定义分类"""
        url = "https://example.com"
        url_id = collection.add_url(url, category="test_category")
        
        url_obj = collection.get_by_id(url_id)
        assert url_obj.category == "test_category"


class TestConvenienceFunctions:
    """测试便利函数"""
    
    def test_create_file_collection(self, tmp_path):
        """测试创建文件集合的便利函数"""
        # 创建测试文件
        (tmp_path / "test.txt").write_text("test")
        
        from doc_helper.url_collection import create_file_collection
        
        collection = create_file_collection(
            directory=tmp_path,
            extensions={'.txt'}
        )
        
        assert isinstance(collection, FileCollection)
        assert collection.count_by_status(URLStatus.PENDING) == 1
    
    def test_create_simple_collection(self):
        """测试创建简单集合的便利函数"""
        from doc_helper.url_collection import create_simple_collection
        
        collection = create_simple_collection()
        
        assert isinstance(collection, SimpleCollection)
        assert collection.count_by_status(URLStatus.PENDING) == 0


if __name__ == "__main__":
    pytest.main([__file__])