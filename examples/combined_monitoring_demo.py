#!/usr/bin/env python3
"""
PageMonitor 和 RequestMonitor 协同工作示例

该示例展示了完整的页面监控和请求分析流水线：
1. PageMonitor 监控页面状态和请求性能
2. RequestMonitor 基于统计数据自动屏蔽问题URL
"""

import asyncio
import logging
from collections import defaultdict
from pdf_helper import (
    PageMonitor, RequestMonitor, URL, URLCollection, URLStatus,
    PageContext, ChromiumManager, PageManagerConfig
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def demo_combined_monitoring():
    """演示 PageMonitor 和 RequestMonitor 的协同工作"""
    
    # 创建URL集合
    url_collection = URLCollection()
    
    # 添加测试URL
    test_urls = [
        URL(id="1", url="https://httpbin.org/get"),           # 正常请求
        URL(id="2", url="https://httpbin.org/delay/2"),       # 慢请求
        URL(id="3", url="https://httpbin.org/status/500"),    # 可能失败的请求
    ]
    
    for url in test_urls:
        url_collection.add(url)
    
    # 创建处理器工厂函数
    def create_page_monitor():
        return PageMonitor(
            name="page_monitor",
            page_timeout=20.0  # 20秒超时，慢请求超时为2秒
        )
    
    def create_request_monitor():
        return RequestMonitor(
            name="request_monitor",
            url_collection=url_collection,
            slow_request_threshold=1,    # 低阈值便于演示
            failed_request_threshold=1   # 低阈值便于演示
        )
    
    processor_factories = [create_page_monitor, create_request_monitor]
    
    # 创建页面管理器配置
    config = PageManagerConfig(
        max_concurrent_tabs=1,
        poll_interval=2.0,
        page_timeout=20.0,
        headless=True
    )
    
    # 创建并运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=processor_factories,
        config=config
    )
    
    print("开始运行协同监控演示...")
    print("\n处理器配置:")
    print("1. PageMonitor:")
    print(f"   - 页面超时: {20.0}秒")
    print(f"   - 慢请求超时: {2.0}秒") 
    print(f"   - 优先级: 0 (最高)")
    print("2. RequestMonitor:")
    print(f"   - 慢请求阈值: {1}次")
    print(f"   - 失败请求阈值: {1}次")
    print(f"   - 优先级: 1")
    
    print(f"\n待处理URL:")
    for url in test_urls:
        print(f"  - {url.url}")
    
    # 运行处理
    await manager.run()
    
    print("\n" + "="*50)
    print("处理结果分析")
    print("="*50)
    
    # 分析处理结果
    all_statuses = url_collection.get_all_statuses()
    
    print(f"\nURL状态统计:")
    for status, count in all_statuses.items():
        if count > 0:
            print(f"  {status.value}: {count}个")
    
    # 显示被屏蔽的URL
    blocked_urls = url_collection.get_by_status(URLStatus.BLOCKED)
    if blocked_urls:
        print(f"\n被屏蔽的URL详情:")
        for blocked_url in blocked_urls:
            print(f"  - URL: {blocked_url.url}")
            print(f"    分类: {blocked_url.category}")
            print(f"    状态: {blocked_url.status.value}")
            print(f"    更新时间: {blocked_url.updated_at}")
    else:
        print(f"\n没有URL被屏蔽")
    
    # 显示已访问的URL
    visited_urls = url_collection.get_by_status(URLStatus.VISITED)
    if visited_urls:
        print(f"\n成功访问的URL:")
        for visited_url in visited_urls:
            print(f"  - {visited_url.url}")
    
    print(f"\n协同工作流程说明:")
    print("1. PageMonitor (优先级0) 首先启动:")
    print("   - 监控页面加载状态变化")
    print("   - 收集慢请求和失败请求统计")
    print("   - 记录到PageContext.data中")
    print("")
    print("2. RequestMonitor (优先级1) 随后启动:")
    print("   - 等待页面进入就绪状态")
    print("   - 分析PageMonitor收集的统计数据")
    print("   - 对超过阈值的URL执行屏蔽操作")
    print("")
    print("3. 智能协调机制:")
    print("   - RequestMonitor等待PageMonitor完成收集")
    print("   - 基于实时数据做出屏蔽决策")
    print("   - 避免重复处理同一问题URL")
    
    print(f"\n演示完成！系统成功识别并处理了问题URL。")

if __name__ == "__main__":
    asyncio.run(demo_combined_monitoring())