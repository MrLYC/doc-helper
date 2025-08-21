"""
URL集合实现模块

该模块提供了不同类型的URL集合实现，包括文件系统扫描和简单URL管理。
"""

import os
import hashlib
from pathlib import Path
from typing import Set, List, Optional, Union
from urllib.parse import urljoin
from urllib.request import pathname2url

from .protocol import URL, URLCollection, URLStatus


class FileCollection(URLCollection):
    """
    基于文件系统的URL集合
    
    遍历指定目录下的所有匹配文件，将其转换为本地文件URL
    """
    
    def __init__(self, base_directory: Union[str, Path], 
                 extensions: Set[str] = None,
                 category: str = "file"):
        """
        初始化文件集合
        
        Args:
            base_directory: 基础目录路径
            extensions: 允许的文件扩展名集合，如 {'.pdf', '.html', '.txt'}
            category: URL分类标签
        """
        super().__init__()
        self.base_directory = Path(base_directory).resolve()
        self.extensions = extensions or set()
        self.category = category
        
        # 确保目录存在
        if not self.base_directory.exists():
            raise ValueError(f"目录不存在: {self.base_directory}")
        if not self.base_directory.is_dir():
            raise ValueError(f"路径不是目录: {self.base_directory}")
        
        # 扫描文件并添加到集合
        self._scan_files()
    
    def _scan_files(self) -> None:
        """扫描目录下的所有匹配文件"""
        for file_path in self._iter_files():
            file_url = self._path_to_url(file_path)
            url_id = self._generate_url_id(file_url)
            
            url_obj = URL(
                id=url_id,
                url=file_url,
                category=self.category,
                status=URLStatus.PENDING
            )
            
            self.add(url_obj)
    
    def _iter_files(self) -> List[Path]:
        """迭代目录下的所有匹配文件"""
        files = []
        
        for root, dirs, filenames in os.walk(self.base_directory):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for filename in filenames:
                # 跳过隐藏文件
                if filename.startswith('.'):
                    continue
                
                file_path = Path(root) / filename
                
                # 检查文件扩展名
                if self.extensions and file_path.suffix.lower() not in self.extensions:
                    continue
                
                # 检查文件是否可读
                if not file_path.is_file() or not os.access(file_path, os.R_OK):
                    continue
                
                files.append(file_path)
        
        # 按路径排序以确保一致性
        return sorted(files)
    
    def _path_to_url(self, file_path: Path) -> str:
        """将文件路径转换为file://格式的URL"""
        # 使用pathname2url确保正确的URL编码
        encoded_path = pathname2url(str(file_path.resolve()))
        return f"file://{encoded_path}"
    
    def _generate_url_id(self, url: str) -> str:
        """为URL生成唯一ID"""
        # 使用URL的哈希值作为ID
        return hashlib.md5(url.encode('utf-8')).hexdigest()[:12]
    
    def refresh(self) -> None:
        """重新扫描目录，更新文件列表"""
        # 保存当前状态
        current_urls = {url.url: url for url in self._urls_by_url.values()}
        
        # 清空集合
        self._urls_by_id.clear()
        self._urls_by_url.clear()
        for status_set in self._urls_by_status.values():
            status_set.clear()
        
        # 重新扫描
        self._scan_files()
        
        # 恢复之前的状态（如果文件仍然存在）
        for url_obj in self._urls_by_url.values():
            if url_obj.url in current_urls:
                old_url = current_urls[url_obj.url]
                if old_url.status != URLStatus.PENDING:
                    self.update_status(url_obj.id, old_url.status)
    
    def get_relative_path(self, url_id: str) -> Optional[str]:
        """获取URL对应文件的相对路径"""
        url_obj = self.get_by_id(url_id)
        if not url_obj or not url_obj.url.startswith('file://'):
            return None
        
        try:
            # 从file://URL中提取路径
            file_path = Path(url_obj.url[7:])  # 移除 'file://' 前缀
            return str(file_path.relative_to(self.base_directory))
        except (ValueError, OSError):
            return None
    
    def get_file_info(self, url_id: str) -> Optional[dict]:
        """获取文件的详细信息"""
        url_obj = self.get_by_id(url_id)
        if not url_obj or not url_obj.url.startswith('file://'):
            return None
        
        try:
            file_path = Path(url_obj.url[7:])  # 移除 'file://' 前缀
            if not file_path.exists():
                return None
            
            stat_result = file_path.stat()
            return {
                'path': str(file_path),
                'relative_path': self.get_relative_path(url_id),
                'size': stat_result.st_size,
                'modified_time': stat_result.st_mtime,
                'is_file': file_path.is_file(),
                'extension': file_path.suffix,
                'name': file_path.name
            }
        except (OSError, ValueError):
            return None


class SimpleCollection(URLCollection):
    """
    简单的URL集合管理器
    
    提供基本的URL添加、移除和屏蔽功能
    """
    
    def __init__(self, category: str = "simple"):
        """
        初始化简单集合
        
        Args:
            category: URL分类标签
        """
        super().__init__()
        self.category = category
        self._id_counter = 0
    
    def add_url(self, url: str, category: str = None) -> str:
        """
        添加一个URL到集合
        
        Args:
            url: 要添加的URL地址
            category: URL分类，如果不指定则使用默认分类
            
        Returns:
            str: 新添加URL的ID，如果URL已存在则返回现有ID
        """
        # 检查URL是否已存在
        existing_url = self.get_by_url(url)
        if existing_url:
            return existing_url.id
        
        # 生成新的URL ID
        url_id = self._generate_new_id()
        
        # 创建URL对象
        url_obj = URL(
            id=url_id,
            url=url,
            category=category or self.category,
            status=URLStatus.PENDING
        )
        
        # 添加到集合
        self.add(url_obj)
        return url_id
    
    def remove_url(self, url_or_id: str) -> bool:
        """
        从集合中移除一个URL
        
        Args:
            url_or_id: URL地址或URL ID
            
        Returns:
            bool: 移除成功返回True，URL不存在返回False
        """
        # 尝试通过ID查找
        url_obj = self.get_by_id(url_or_id)
        if not url_obj:
            # 尝试通过URL地址查找
            url_obj = self.get_by_url(url_or_id)
        
        if not url_obj:
            return False
        
        # 从所有索引中移除
        self._urls_by_id.pop(url_obj.id, None)
        self._urls_by_url.pop(url_obj.url, None)
        
        # 从状态索引中移除
        for status_set in self._urls_by_status.values():
            status_set.discard(url_obj.id)
        
        return True
    
    def clear_all(self) -> None:
        """清空所有URL"""
        self._urls_by_id.clear()
        self._urls_by_url.clear()
        for status_set in self._urls_by_status.values():
            status_set.clear()
        self._id_counter = 0
    
    def bulk_add_urls(self, urls: List[str], category: str = None) -> List[str]:
        """
        批量添加URL
        
        Args:
            urls: URL地址列表
            category: URL分类
            
        Returns:
            List[str]: 添加的URL ID列表
        """
        url_ids = []
        for url in urls:
            url_id = self.add_url(url, category)
            url_ids.append(url_id)
        return url_ids
    
    def get_pending_urls(self) -> List[URL]:
        """获取所有待处理的URL"""
        return self.get_by_status(URLStatus.PENDING)
    
    def _generate_new_id(self) -> str:
        """生成新的URL ID"""
        self._id_counter += 1
        return f"url_{self._id_counter:06d}"


# 便利函数
def create_file_collection(directory: Union[str, Path], 
                          extensions: Set[str] = None) -> FileCollection:
    """
    创建文件集合的便利函数
    
    Args:
        directory: 目录路径
        extensions: 文件扩展名集合
        
    Returns:
        FileCollection: 文件集合实例
    """
    return FileCollection(directory, extensions)


def create_simple_collection() -> SimpleCollection:
    """
    创建简单集合的便利函数
    
    Returns:
        SimpleCollection: 简单集合实例
    """
    return SimpleCollection()


# 示例用法
if __name__ == "__main__":
    # 创建文件集合示例
    try:
        file_collection = create_file_collection(
            directory="./docs",
            extensions={'.md', '.txt', '.pdf'}
        )
        print(f"找到 {file_collection.count_by_status(URLStatus.PENDING)} 个文件")
        
        # 显示前几个文件
        pending_files = file_collection.get_by_status(URLStatus.PENDING, limit=5)
        for url_obj in pending_files:
            file_info = file_collection.get_file_info(url_obj.id)
            if file_info:
                print(f"- {file_info['relative_path']} ({file_info['size']} bytes)")
    
    except ValueError as e:
        print(f"文件集合创建失败: {e}")
    
    # 创建简单集合示例
    simple_collection = create_simple_collection()
    
    # 添加一些URL
    urls = [
        "https://example.com",
        "https://github.com",
        "https://python.org"
    ]
    
    url_ids = simple_collection.bulk_add_urls(urls)
    print(f"\n添加了 {len(url_ids)} 个URL")
    
    # 显示状态统计
    stats = simple_collection.get_all_statuses()
    print(f"URL状态统计: {dict(stats)}")