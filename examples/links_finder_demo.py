#!/usr/bin/env python3
"""
LinksFinder 使用示例

该示例展示了如何使用 LinksFinder 处理器发现页面中的链接，
并自动将其添加到URL集合中以供后续处理。
"""

import asyncio
import logging
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf_helper import (
    PageMonitor, LinksFinder, URL, URLCollection, URLStatus,
    PageContext, ChromiumManager, PageManagerConfig
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def demo_links_finder():
    """演示 LinksFinder 的使用"""
    
    # 创建URL集合
    url_collection = URLCollection()
    
    # 添加初始URL - 一个包含很多链接的页面
    initial_url = URL(id="1", url="https://httpbin.org/links/5/0")  # 包含5个链接的测试页面
    url_collection.add(initial_url)
    
    # 创建处理器工厂函数
    def create_page_monitor():
        return PageMonitor(
            name="page_monitor",
            page_timeout=30.0
        )
    
    def create_links_finder():
        return LinksFinder(
            name="links_finder",
            url_collection=url_collection,
            css_selector="body",  # 搜索整个body
            priority=10
        )
    
    processor_factories = [create_page_monitor, create_links_finder]
    
    # 创建页面管理器配置
    config = PageManagerConfig(
        max_concurrent_tabs=1,
        poll_interval=2.0,
        page_timeout=30.0,
        headless=True
    )
    
    # 创建并运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=processor_factories,
        config=config
    )
    
    print("开始运行链接发现演示...")
    print("\n处理器配置:")
    print("1. PageMonitor:")
    print(f"   - 页面超时: {30.0}秒")
    print(f"   - 优先级: 0 (最高)")
    print("2. LinksFinder:")
    print(f"   - CSS选择器: body")
    print(f"   - 优先级: 10")
    
    print(f"\n初始URL: {initial_url.url}")
    print(f"初始URL集合大小: {len(url_collection._urls_by_id)}")
    
    # 运行处理
    await manager.run()
    
    print("\n" + "="*50)
    print("链接发现结果分析")
    print("="*50)
    
    # 分析处理结果
    all_statuses = url_collection.get_all_statuses()
    
    print(f"\nURL状态统计:")
    for status, count in all_statuses.items():
        if count > 0:
            print(f"  {status.value}: {count}个")
    
    # 显示发现的新链接
    discovered_urls = url_collection.get_by_status(URLStatus.PENDING)
    if discovered_urls:
        print(f"\n发现的新链接 ({len(discovered_urls)}个):")
        for i, url in enumerate(discovered_urls[:10], 1):  # 只显示前10个
            print(f"  {i}. {url.url}")
            print(f"     分类: {url.category}")
            print(f"     ID: {url.id}")
        
        if len(discovered_urls) > 10:
            print(f"  ... 还有 {len(discovered_urls) - 10} 个链接")
    else:
        print(f"\n没有发现新链接")
    
    # 显示已访问的URL
    visited_urls = url_collection.get_by_status(URLStatus.VISITED)
    if visited_urls:
        print(f"\n成功访问的URL:")
        for visited_url in visited_urls:
            print(f"  - {visited_url.url}")
    
    print(f"\n工作流程说明:")
    print("1. PageMonitor (优先级0) 监控页面状态:")
    print("   - 监控页面加载状态变化 (loading -> ready -> completed)")
    print("   - 为LinksFinder提供页面状态信息")
    print("")
    print("2. LinksFinder (优先级10) 在页面就绪后启动:")
    print("   - 在页面就绪(ready)状态执行一次链接发现")
    print("   - 在页面完成(completed)状态再执行一次")
    print("   - 使用CSS选择器定位链接容器")
    print("   - 提取容器中的所有有效HTTP/HTTPS链接")
    print("   - 将新链接添加到URL集合，状态为PENDING")
    print("")
    print("3. 智能去重机制:")
    print("   - URLCollection自动处理重复链接")
    print("   - 每个链接生成唯一ID")
    print("   - 支持增量发现")
    
    total_urls = len(url_collection._urls_by_id)
    print(f"\n演示完成！URL集合从 1 个增长到 {total_urls} 个。")

if __name__ == "__main__":
    asyncio.run(demo_links_finder())