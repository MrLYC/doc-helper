#!/usr/bin/env python3
"""
RequestMonitor 使用示例

该示例展示了如何使用 RequestMonitor 处理器监控特殊请求，
并自动屏蔽有问题的URL。
"""

import asyncio
import logging
from pdf_helper import (
    RequestMonitor, PageMonitor, URL, URLCollection, URLStatus, 
    PageContext, ChromiumManager, PageManagerConfig
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def demo_request_monitor():
    """演示 RequestMonitor 的使用"""
    
    # 创建URL集合
    url_collection = URLCollection()
    test_url = URL(id="1", url="https://httpbin.org/delay/1")  # 模拟请求
    url_collection.add(test_url)
    
    # 创建处理器工厂函数
    def create_page_monitor():
        return PageMonitor(
            name="page_monitor",
            page_timeout=15.0  # 15秒超时，慢请求超时为1.5秒
        )
    
    def create_request_monitor():
        return RequestMonitor(
            name="request_monitor",
            url_collection=url_collection,
            slow_request_threshold=2,    # 慢请求阈值较低，便于演示
            failed_request_threshold=1   # 失败请求阈值较低，便于演示
        )
    
    processor_factories = [create_page_monitor, create_request_monitor]
    
    # 创建页面管理器配置
    config = PageManagerConfig(
        max_concurrent_tabs=1,
        poll_interval=1.0,
        page_timeout=15.0,
        headless=True
    )
    
    # 创建并运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=processor_factories,
        config=config
    )
    
    print("开始运行请求监控演示...")
    print("监控配置:")
    print(f"  慢请求阈值: {2}次")
    print(f"  失败请求阈值: {1}次")
    print(f"  目标URL: {test_url.url}")
    
    await manager.run()
    
    # 检查是否有URL被屏蔽
    blocked_urls = url_collection.get_by_status(URLStatus.BLOCKED)
    
    print(f"\n演示完成！")
    print(f"屏蔽的URL数量: {len(blocked_urls)}")
    for blocked_url in blocked_urls:
        print(f"  - {blocked_url.url} (分类: {blocked_url.category})")
    
    print("\nRequestMonitor 能够:")
    print("1. 监控页面进入就绪状态时启动")
    print("2. 检测慢请求数量超过阈值的URL")
    print("3. 检测失败请求数量超过阈值的URL")
    print("4. 自动将问题URL添加到集合并标记为屏蔽")
    print("5. 收集 Prometheus 指标")
    print("6. 智能地等待更高优先级处理器完成")

if __name__ == "__main__":
    asyncio.run(demo_request_monitor())