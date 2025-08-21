#!/usr/bin/env python3
"""
ElementCleaner 使用示例

该示例展示了如何使用 ElementCleaner 处理器清理页面中的不需要元素，
如广告、弹窗、导航栏等，为PDF生成或内容提取做准备。
"""

import asyncio
import logging
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf_helper import (
    PageMonitor, ElementCleaner, URL, URLCollection, URLStatus,
    PageContext, ChromiumManager, PageManagerConfig
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def demo_element_cleaner():
    """演示 ElementCleaner 的使用"""
    
    # 创建URL集合
    url_collection = URLCollection()
    
    # 添加一些测试URL - 包含广告和弹窗的网站
    test_urls = [
        URL(id="1", url="https://httpbin.org/html"),  # 简单HTML页面
        URL(id="2", url="https://example.com"),       # 标准示例页面
    ]
    
    for url in test_urls:
        url_collection.add(url)
    
    # 创建处理器工厂函数
    def create_page_monitor():
        return PageMonitor(
            name="page_monitor",
            page_timeout=30.0
        )
    
    def create_element_cleaner():
        # 定义要清理的元素的CSS选择器
        # 这里演示清理常见的广告和不需要的元素
        css_selector = ", ".join([
            "*[id*='ad']",              # 包含'ad'的ID
            "*[class*='advertisement']", # 包含'advertisement'的class
            "*[class*='popup']",        # 弹窗元素
            "*[class*='banner']",       # 横幅广告
            "*[class*='sidebar']",      # 侧边栏（可选）
            "iframe[src*='ads']",       # 广告iframe
            ".ad, .ads",               # 直接的广告class
            "#popup, #modal",          # 弹窗和模态框
        ])
        
        return ElementCleaner(
            name="element_cleaner",
            css_selector=css_selector,
            priority=20
        )
    
    processor_factories = [create_page_monitor, create_element_cleaner]
    
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
    
    print("开始运行元素清理演示...")
    print("\n处理器配置:")
    print("1. PageMonitor:")
    print(f"   - 页面超时: {30.0}秒")
    print(f"   - 优先级: 0 (最高)")
    print("2. ElementCleaner:")
    print(f"   - 优先级: 20")
    print("   - 清理目标: 广告、弹窗、横幅等不需要的元素")
    
    cleaner_selector = ", ".join([
        "*[id*='ad']", "*[class*='advertisement']", "*[class*='popup']",
        "*[class*='banner']", "iframe[src*='ads']", ".ad, .ads", "#popup, #modal"
    ])
    print(f"   - CSS选择器: {cleaner_selector}")
    
    print(f"\n测试URL数量: {len(test_urls)}")
    for i, url in enumerate(test_urls, 1):
        print(f"  {i}. {url.url}")
    
    # 运行处理
    await manager.run()
    
    print("\n" + "="*50)
    print("元素清理结果分析")
    print("="*50)
    
    # 分析处理结果
    all_statuses = url_collection.get_all_statuses()
    
    print(f"\nURL状态统计:")
    for status, count in all_statuses.items():
        if count > 0:
            print(f"  {status.value}: {count}个")
    
    # 显示已访问的URL
    visited_urls = url_collection.get_by_status(URLStatus.VISITED)
    if visited_urls:
        print(f"\n成功处理的URL:")
        for visited_url in visited_urls:
            print(f"  ✓ {visited_url.url}")
    
    print(f"\n工作流程说明:")
    print("1. PageMonitor (优先级0) 监控页面状态:")
    print("   - 等待页面进入就绪状态")
    print("   - 监控页面加载过程")
    print("")
    print("2. ElementCleaner (优先级20) 在页面就绪后启动:")
    print("   - 检测页面状态为 ready 或 completed")
    print("   - 使用CSS选择器查找目标元素")
    print("   - 删除所有匹配的元素")
    print("   - 根据删除结果标记成功或失败")
    print("")
    print("3. 常见清理目标:")
    print("   - 广告横幅 (*[class*='banner'], *[id*='ad'])")
    print("   - 弹窗和模态框 (*[class*='popup'], #popup, #modal)")
    print("   - 广告iframe (iframe[src*='ads'])")
    print("   - 侧边栏广告 (*[class*='sidebar'])")
    print("   - 其他广告相关元素 (.ad, .ads, *[class*='advertisement'])")
    
    total_urls = len(url_collection._urls_by_id)
    print(f"\n演示完成！共处理 {total_urls} 个URL。")


async def demo_specific_element_cleaning():
    """演示针对特定元素的清理"""
    print("\n" + "="*60)
    print("特定元素清理演示")
    print("="*60)
    
    # 创建URL集合
    url_collection = URLCollection()
    
    # 添加测试URL
    test_url = URL(id="1", url="https://httpbin.org/html")
    url_collection.add(test_url)
    
    # 演示不同的清理场景
    cleaning_scenarios = [
        {
            "name": "清理导航元素",
            "selector": "nav, .navigation, .navbar, #navigation",
            "description": "移除页面导航，专注于主要内容"
        },
        {
            "name": "清理页脚信息", 
            "selector": "footer, .footer, #footer",
            "description": "移除页脚信息，减少PDF页面长度"
        },
        {
            "name": "清理评论区域",
            "selector": ".comments, #comments, .comment-section",
            "description": "移除评论区域，专注于文章内容"
        },
        {
            "name": "清理社交媒体按钮",
            "selector": ".social-share, .social-buttons, *[class*='share']", 
            "description": "移除社交分享按钮"
        }
    ]
    
    for scenario in cleaning_scenarios:
        print(f"\n场景: {scenario['name']}")
        print(f"描述: {scenario['description']}")
        print(f"CSS选择器: {scenario['selector']}")
        
        # 创建专用的ElementCleaner
        def create_specialized_cleaner():
            return ElementCleaner(
                name=f"cleaner_{scenario['name']}",
                css_selector=scenario['selector'],
                priority=20
            )
        
        print(f"✓ 已配置 {scenario['name']} 清理器")


async def demo_advanced_selectors():
    """演示高级CSS选择器用法"""
    print("\n" + "="*60)
    print("高级CSS选择器演示")
    print("="*60)
    
    advanced_selectors = [
        {
            "name": "属性包含选择器",
            "selector": "*[class*='ad'], *[id*='popup'], *[data-type='advertisement']",
            "description": "匹配class包含'ad'、id包含'popup'或data-type为'advertisement'的元素"
        },
        {
            "name": "否定选择器",
            "selector": "div:not(.content):not(.main):not(.article)",
            "description": "选择不是内容、主要区域或文章的div元素"
        },
        {
            "name": "子元素选择器",
            "selector": ".sidebar > *, .advertisement > *",
            "description": "选择侧边栏和广告区域的所有直接子元素"
        },
        {
            "name": "伪类选择器",
            "selector": "div:empty, img[src=''], iframe:not([src])",
            "description": "选择空的div、无src的img和无src的iframe"
        },
        {
            "name": "组合选择器",
            "selector": ".header .ad, .footer .social, aside.sidebar",
            "description": "选择头部中的广告、页脚中的社交元素和侧边栏"
        }
    ]
    
    for selector_info in advanced_selectors:
        print(f"\n{selector_info['name']}:")
        print(f"  选择器: {selector_info['selector']}")
        print(f"  说明: {selector_info['description']}")
        
        # 创建使用高级选择器的清理器
        cleaner = ElementCleaner(
            name=f"advanced_cleaner",
            css_selector=selector_info['selector']
        )
        print(f"  ✓ 清理器已创建，优先级: {cleaner.priority}")


if __name__ == "__main__":
    print("ElementCleaner 处理器演示")
    print("="*50)
    
    # 运行主要演示
    asyncio.run(demo_element_cleaner())
    
    # 运行特定场景演示
    asyncio.run(demo_specific_element_cleaning())
    
    # 运行高级选择器演示
    asyncio.run(demo_advanced_selectors())
    
    print("\n" + "="*50)
    print("演示完成！")
    print("\nElementCleaner 的主要优势:")
    print("1. 🎯 精确定位: 使用CSS选择器精确定位要删除的元素")
    print("2. 🔧 灵活配置: 支持复杂的CSS选择器语法")
    print("3. 📊 实时监控: 集成Prometheus指标，监控清理效果")
    print("4. 🛡️ 错误处理: 优雅处理元素删除失败的情况")
    print("5. 🚀 高性能: 批量删除元素，最小化DOM操作次数")
    print("\n适用场景:")
    print("• PDF生成前清理不需要的视觉元素")
    print("• 内容提取前移除广告和噪音")
    print("• 网页截图前优化页面布局")
    print("• 数据抓取时专注于核心内容")