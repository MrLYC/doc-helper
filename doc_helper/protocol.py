"""
页面处理框架的协议定义

该模块定义了用于网页处理的核心协议和数据结构，包括URL管理、页面处理器、页面上下文等。
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set
from urllib.parse import urlparse, urlunparse

from playwright.async_api import Page, BrowserContext


class URLStatus(Enum):
    """URL状态枚举"""
    PENDING = "pending"        # 待访问
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 已完成
    VISITED = "visited"        # 已访问 (为向后兼容保留)
    FAILED = "failed"          # 已失败


class ProcessorState(Enum):
    """页面处理器状态枚举"""
    WAITING = "waiting"      # 等待中
    READY = "ready"          # 已就绪
    RUNNING = "running"      # 运行中
    COMPLETED = "completed"  # 已完成
    FINISHED = "finished"    # 已结束
    CANCELLED = "cancelled"  # 已取消


@dataclass
class URL:
    """URL对象，表示一个网页地址及其相关信息"""
    
    id: str                          # URL的唯一标识符
    url: str                         # URL地址
    category: str = ""               # 分类
    status: URLStatus = URLStatus.PENDING  # 状态
    updated_at: float = field(default_factory=time.time)  # 更新时间戳
    
    def __post_init__(self):
        """初始化后处理，确保URL格式正确"""
        if not self.url:
            raise ValueError("URL不能为空")
        
        parsed = urlparse(self.url)
        if not parsed.scheme:
            raise ValueError(f"无效的URL格式: {self.url}")
        
        # file:// 协议不需要 netloc，其他协议需要
        if parsed.scheme != 'file' and not parsed.netloc:
            raise ValueError(f"无效的URL格式: {self.url}")
    
    @property
    def domain(self) -> str:
        """获取域名"""
        parsed = urlparse(self.url)
        # file:// 协议返回 'localhost' 作为域名
        if parsed.scheme == 'file':
            return 'localhost'
        return parsed.netloc
    
    @property
    def path(self) -> str:
        """获取路径"""
        return urlparse(self.url).path
    
    @property
    def url_without_query(self) -> str:
        """获取不含查询字符串的URL"""
        parsed = urlparse(self.url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
    
    def update_status(self, status: URLStatus) -> None:
        """更新状态"""
        self.status = status
        self.updated_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'URL':
        """从字典反序列化"""
        data = data.copy()
        data['status'] = URLStatus(data['status'])
        return cls(**data)
    
    def to_json(self) -> str:
        """序列化为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'URL':
        """从JSON字符串反序列化"""
        return cls.from_dict(json.loads(json_str))
    
    def __hash__(self) -> int:
        """基于URL计算哈希值，用于去重"""
        return hash(self.url)
    
    def __eq__(self, other) -> bool:
        """基于URL判断相等性"""
        if not isinstance(other, URL):
            return False
        return self.url == other.url


class URLCollection:
    """URL集合，管理一系列URL对象"""
    
    def __init__(self):
        self._urls_by_id: Dict[str, URL] = {}
        self._urls_by_url: Dict[str, URL] = {}
        self._urls_by_status: Dict[URLStatus, Set[str]] = {
            status: set() for status in URLStatus
        }
    
    def add(self, url: URL) -> bool:
        """
        添加URL对象，自动去重
        
        Args:
            url: 要添加的URL对象
            
        Returns:
            bool: 如果是新URL返回True，如果已存在返回False
        """
        if url.url in self._urls_by_url:
            return False
        
        self._urls_by_id[url.id] = url
        self._urls_by_url[url.url] = url
        self._urls_by_status[url.status].add(url.id)
        return True
    
    def get_by_id(self, url_id: str) -> Optional[URL]:
        """根据ID获取URL对象"""
        return self._urls_by_id.get(url_id)
    
    def get_by_url(self, url: str) -> Optional[URL]:
        """根据URL地址获取URL对象"""
        return self._urls_by_url.get(url)
    
    def get_by_status(self, status: URLStatus, limit: Optional[int] = None, 
                     oldest_first: bool = True) -> List[URL]:
        """
        根据状态获取URL对象列表
        
        Args:
            status: 要查询的状态
            limit: 限制返回数量
            oldest_first: 是否按时间正序排列（最旧的在前）
            
        Returns:
            List[URL]: URL对象列表
        """
        url_ids = self._urls_by_status.get(status, set())
        urls = [self._urls_by_id[url_id] for url_id in url_ids]
        
        # 按更新时间排序
        urls.sort(key=lambda u: u.updated_at, reverse=not oldest_first)
        
        if limit:
            urls = urls[:limit]
        
        return urls
    
    def has_status(self, url_id: str, status: URLStatus) -> bool:
        """判断指定ID的URL是否为指定状态"""
        url = self.get_by_id(url_id)
        return url is not None and url.status == status
    
    def has_url_status(self, url: str, status: URLStatus) -> bool:
        """判断指定URL地址是否为指定状态"""
        url_obj = self.get_by_url(url)
        return url_obj is not None and url_obj.status == status
    
    def update_status(self, url_id: str, status: URLStatus) -> bool:
        """
        更新URL状态
        
        Args:
            url_id: URL的ID
            status: 新状态
            
        Returns:
            bool: 更新成功返回True，URL不存在返回False
        """
        url = self.get_by_id(url_id)
        if url is None:
            return False
        
        # 从旧状态集合中移除
        old_status = url.status
        self._urls_by_status[old_status].discard(url_id)
        
        # 更新状态
        url.update_status(status)
        
        # 添加到新状态集合
        self._urls_by_status[status].add(url_id)
        return True
    
    def count_by_status(self, status: URLStatus) -> int:
        """获取指定状态的URL数量"""
        return len(self._urls_by_status.get(status, set()))
    
    def get_all_statuses(self) -> Dict[URLStatus, int]:
        """获取所有状态的URL数量统计"""
        return {status: len(urls) for status, urls in self._urls_by_status.items()}
    
    def get_all_urls(self) -> List[URL]:
        """获取所有URL对象列表"""
        return list(self._urls_by_id.values())


@dataclass
class PageContext:
    """页面上下文，存储页面相关的数据和对象"""
    
    page: Page                              # Playwright页面对象
    url: URL                               # 当前URL对象
    data: Dict[str, Any] = field(default_factory=dict)  # 页面数据字典
    processors: Dict[str, 'PageProcessor'] = field(default_factory=dict)  # 页面处理器
    start_time: float = field(default_factory=time.time)  # 页面处理开始时间
    
    def get_processor(self, name: str) -> Optional['PageProcessor']:
        """根据名称获取页面处理器"""
        return self.processors.get(name)
    
    def add_processor(self, processor: 'PageProcessor') -> None:
        """添加页面处理器"""
        self.processors[processor.name] = processor
    
    def get_processors_by_priority(self, reverse: bool = False) -> List['PageProcessor']:
        """
        按优先级获取处理器列表
        
        Args:
            reverse: 是否反序排列，False为升序（优先级高的在前），True为降序
            
        Returns:
            按优先级排序的处理器列表
        """
        return sorted(self.processors.values(), key=lambda p: p.priority, reverse=reverse)


class PageProcessor(ABC):
    """页面处理器抽象基类"""
    
    def __init__(self, name: str, priority: int = 50):
        """
        初始化页面处理器
        
        Args:
            name: 处理器名称
            priority: 处理器优先级，数值越小优先级越高，默认为50
        """
        self.name = name
        self.priority = priority
        self._state = ProcessorState.WAITING
        self._last_detect_time = 0.0
    
    @property
    def state(self) -> ProcessorState:
        """获取当前状态"""
        return self._state
    
    def _set_state(self, state: ProcessorState) -> None:
        """设置状态（内部使用）"""
        self._state = state
    
    @abstractmethod
    async def detect(self, context: PageContext) -> ProcessorState:
        """
        检测是否应该运行
        
        Args:
            context: 页面上下文
            
        Returns:
            ProcessorState: 检测后的状态
        """
        pass
    
    @abstractmethod
    async def run(self, context: PageContext) -> None:
        """
        执行处理逻辑，仅在状态为READY时调用
        
        Args:
            context: 页面上下文
        """
        pass
    
    @abstractmethod
    async def finish(self, context: PageContext) -> None:
        """
        清理逻辑，在状态为COMPLETED时调用
        
        Args:
            context: 页面上下文
        """
        pass


class RetryCallback(Protocol):
    """重试回调协议"""
    
    def __call__(self, failed_urls: List[URL]) -> bool:
        """
        重试回调函数
        
        Args:
            failed_urls: 失败的URL列表
            
        Returns:
            bool: 是否进行重试
        """
        ...


@dataclass
class PageManagerConfig:
    """页面管理器配置"""
    
    max_concurrent_tabs: int = 4           # 最大并发标签页数
    poll_interval: float = 1.0             # 轮询间隔（秒）
    page_timeout: float = 60.0             # 页面超时时间（秒）
    detect_timeout: float = 5.0            # 检测超时时间（秒）
    network_idle_timeout: float = 3.0      # 网络空闲超时时间（秒）
    screenshot_timeout: float = 10.0       # 截图超时时间（秒）
    headless: bool = True                  # 是否使用无头模式


class PageManager(ABC):
    """页面管理器抽象基类"""
    
    def __init__(self, 
                 url_collection: URLCollection,
                 processor_factories: List[callable],
                 config: PageManagerConfig,
                 retry_callback: Optional[RetryCallback] = None):
        """
        初始化页面管理器
        
        Args:
            url_collection: URL集合
            processor_factories: 页面处理器工厂函数列表
            config: 管理器配置
            retry_callback: 重试回调函数
        """
        self.url_collection = url_collection
        self.processor_factories = processor_factories
        self.config = config
        self.retry_callback = retry_callback
    
    @abstractmethod
    async def run(self) -> None:
        """运行页面管理器"""
        pass