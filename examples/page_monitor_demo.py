#!/usr/bin/env python3
"""
PageMonitor 使用示例

该示例展示了如何使用 PageMonitor 处理器监控页面加载状态、
检测慢请求和失败请求。
"""

import asyncio
import logging
from pdf_helper import (
    PageMonitor, URL, PageContext, ChromiumManager, URLCollection
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def demo_page_monitor():
    """演示 PageMonitor 的使用"""
    
    # 创建URL集合
    url_collection = URLCollection()
    test_url = URL(id="1", url="https://httpbin.org/delay/2")  # 模拟慢请求
    url_collection.add(test_url)
    
    # 创建处理器工厂函数
    def create_page_monitor():
        return PageMonitor(
            name="page_monitor",
            page_timeout=30.0  # 30秒超时，慢请求超时为3秒
        )
    
    processor_factories = [create_page_monitor]
    
    # 创建页面管理器配置
    from pdf_helper import PageManagerConfig
    config = PageManagerConfig(
        max_concurrent_tabs=1,
        poll_interval=1.0,
        page_timeout=30.0,
        headless=True
    )
    
    # 创建并运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=processor_factories,
        config=config
    )
    
    print("开始运行页面监控演示...")
    print("监控配置:")
    print(f"  页面超时: {config.page_timeout}秒")
    print(f"  慢请求超时: {config.page_timeout / 10}秒")
    print(f"  目标URL: {test_url.url}")
    
    await manager.run()
    
    print("\n演示完成！")
    print("PageMonitor 能够:")
    print("1. 监控页面加载状态变化 (loading -> ready -> completed)")
    print("2. 检测并记录慢请求")
    print("3. 检测并记录失败请求")
    print("4. 收集 Prometheus 指标")
    print("5. 优雅地清理资源")

if __name__ == "__main__":
    asyncio.run(demo_page_monitor())