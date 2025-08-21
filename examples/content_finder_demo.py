"""
ContentFinder 处理器演示

演示如何使用 ContentFinder 处理器来保留核心内容并清理其他兄弟节点，
使内容适合 A4 纸尺寸的 PDF 生成。
"""

import asyncio
import logging
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pdf_helper import (
    ChromiumManager,
    PageMonitor,
    ContentFinder,
    URLCollection,
    URL,
    URLStatus,
    PageManagerConfig
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def main():
    print("ContentFinder 处理器演示")
    print("=" * 50)
    
    # 创建URL集合用于测试
    test_urls = [
        "https://docs.python.org/3/tutorial/introduction.html",  # Python文档
        "https://playwright.dev/docs/intro",  # Playwright文档
    ]
    
    url_collection = URLCollection()
    for i, url_str in enumerate(test_urls):
        url = URL(id=str(i+1), url=url_str)
        url_collection.add(url)
    
    print("开始运行内容查找演示...")
    print()
    
    print("处理器配置:")
    print("1. PageMonitor:")
    print("   - 页面超时: 30.0秒")
    print("   - 优先级: 0 (最高)")
    print("2. ContentFinder:")
    print("   - 优先级: 30")
    print("   - 清理目标: 保留核心内容，清理兄弟节点")
    print("   - CSS选择器: main, article, .content, .main-content, [role='main']")
    print("   - 目标状态: ['ready', 'completed']")
    print(f"测试URL数量: {len(test_urls)}")
    for i, url in enumerate(test_urls, 1):
        print(f"  {i}. {url}")
    
    # 创建处理器工厂函数
    def create_page_monitor() -> PageMonitor:
        return PageMonitor("page_monitor", page_timeout=30.0, priority=0)
    
    def create_content_finder() -> ContentFinder:
        return ContentFinder(
            css_selector="main, article, .content, .main-content, [role='main']",
            target_states=["ready", "completed"],
            priority=30
        )
    
    # 处理器工厂列表
    processor_factories = [create_page_monitor, create_content_finder]
    
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
    
    print("开始运行内容查找演示...")
    
    # 运行处理
    await manager.run()
    
    # 分析结果
    print()
    print("=" * 50)
    print("内容查找结果分析")
    print("=" * 50)
    
    # 统计状态
    all_statuses = url_collection.get_all_statuses()
    
    print("\nURL状态统计:")
    for status, count in all_statuses.items():
        if count > 0:
            print(f"  {status.value}: {count}个")
    
    # 显示成功处理的URL
    visited_urls = url_collection.get_by_status(URLStatus.VISITED)
    if visited_urls:
        print("\n成功处理的URL:")
        for url in visited_urls:
            print(f"  ✓ {url.url}")
    
    # 显示失败的URL
    failed_urls = []
    try:
        failed_urls = url_collection.get_by_status(URLStatus.FAILED)
    except AttributeError:
        # URLStatus 可能没有 FAILED 状态，跳过
        pass
    
    if failed_urls:
        print("\n失败的URL:")
        for url in failed_urls:
            print(f"  ✗ {url.url} (状态: {url.status.value})")
    
    print("\n工作流程说明:")
    print("1. PageMonitor (优先级0) 监控页面状态:")
    print("   - 等待页面进入就绪状态")
    print("   - 监控页面加载过程")
    print()
    print("2. ContentFinder (优先级30) 在页面就绪后启动:")
    print("   - 查找核心内容区域 (main, article, .content等)")
    print("   - 从目标元素开始向上遍历到body")
    print("   - 删除所有非核心内容的兄弟节点")
    print("   - 保留内容路径，清理噪音元素")
    print()
    print("3. 内容优化效果:")
    print("   - 移除侧边栏、导航、页脚等干扰元素")
    print("   - 保留文章主体内容")
    print("   - 优化页面布局适合A4纸打印")
    print("   - 减少PDF文件大小")
    
    print(f"\n演示完成！共处理 {len(test_urls)} 个URL。")

def demo_content_selectors():
    """演示不同类型的内容选择器"""
    print("\n" + "=" * 60)
    print("不同内容选择器演示")
    print("=" * 60)
    
    selectors = [
        {
            "name": "主要内容区域",
            "description": "查找主要内容容器",
            "selector": "main, [role='main'], .main-content, .content",
            "use_case": "适用于大多数现代网站的主要内容区域"
        },
        {
            "name": "文章内容",
            "description": "查找文章正文",
            "selector": "article, .article, .post-content, .entry-content",
            "use_case": "适用于博客、新闻网站的文章页面"
        },
        {
            "name": "文档内容",
            "description": "查找文档主体",
            "selector": ".documentation, .docs-content, .doc-body",
            "use_case": "适用于技术文档网站"
        },
        {
            "name": "复合选择器",
            "description": "多种内容类型组合",
            "selector": "main article, .content article, .main-content > .article",
            "use_case": "适用于复杂布局的内容页面"
        },
        {
            "name": "特定元素",
            "description": "基于ID或特定类名",
            "selector": "#content, #main-content, .container .content",
            "use_case": "适用于有固定ID或类名的特定网站"
        }
    ]
    
    for selector_info in selectors:
        print(f"\n{selector_info['name']}:")
        print(f"  选择器: {selector_info['selector']}")
        print(f"  描述: {selector_info['description']}")
        print(f"  适用场景: {selector_info['use_case']}")
        
        # 创建处理器示例
        processor = ContentFinder(
            css_selector=selector_info['selector'],
            target_states=["ready"],
            priority=30
        )
        print(f"  ✓ 处理器已创建，优先级: {processor.priority}")

def demo_target_states():
    """演示不同目标状态配置"""
    print("\n" + "=" * 60)
    print("目标状态配置演示")
    print("=" * 60)
    
    state_configs = [
        {
            "name": "快速启动",
            "states": ["ready"],
            "description": "页面基本就绪后立即启动，处理速度快"
        },
        {
            "name": "完全加载",
            "states": ["completed"],
            "description": "等待页面完全加载后启动，内容更完整"
        },
        {
            "name": "灵活模式",
            "states": ["ready", "completed"],
            "description": "在ready或completed状态都可以启动，平衡速度和完整性"
        }
    ]
    
    for config in state_configs:
        print(f"\n{config['name']} 模式:")
        print(f"  目标状态: {config['states']}")
        print(f"  说明: {config['description']}")
        
        processor = ContentFinder(
            css_selector=".content",
            target_states=config['states'],
            priority=30
        )
        print(f"  ✓ 处理器已配置")

if __name__ == "__main__":
    print("ContentFinder 处理器演示")
    print("=" * 50)
    
    # 运行主要演示
    asyncio.run(main())
    
    # 演示不同配置选项
    demo_content_selectors()
    demo_target_states()
    
    print("\n" + "=" * 50)
    print("演示完成！")
    print("\nContentFinder 的主要优势:")
    print("1. 🎯 精确内容提取: 使用CSS选择器精确定位核心内容")
    print("2. 🧹 智能清理: 向上遍历清理兄弟节点，保留内容路径")
    print("3. 📄 PDF优化: 优化页面布局适合A4纸尺寸")
    print("4. ⚡ 灵活配置: 支持多种目标状态和CSS选择器")
    print("5. 📊 实时监控: 集成Prometheus指标，监控清理效果")
    print("6. 🛡️ 错误处理: 优雅处理元素不存在等异常情况")
    print("\n适用场景:")
    print("• 从复杂网页中提取主要内容生成PDF")
    print("• 清理网页噪音元素提高阅读体验")
    print("• 优化打印效果减少纸张浪费")
    print("• 内容抓取前预处理页面结构")