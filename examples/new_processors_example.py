#!/usr/bin/env python3
"""
新处理器使用示例

展示如何使用新的高级页面处理器进行网页到PDF的转换。
"""

import asyncio
import tempfile
from pdf_helper.new_processors import (
    PageMonitor, RequestMonitor, LinksFinder,
    ElementCleaner, ContentFinder, PdfExporter
)
from pdf_helper.protocol import URL, URLCollection, URLStatus


def create_advanced_processor_factories(output_dir="/tmp"):
    """
    创建高级处理器工厂函数
    
    Args:
        output_dir: PDF输出目录
        
    Returns:
        List: 处理器工厂函数列表
    """
    return [
        # 页面监控器 - 监控页面加载和网络请求
        lambda: PageMonitor(
            name="page_monitor",
            slow_request_timeout=3.0  # 3秒超时阈值
        ),
        
        # 请求监控器 - 自动屏蔽异常请求
        lambda: RequestMonitor(
            name="request_monitor",
            slow_threshold=50,    # 50个慢请求后屏蔽
            failed_threshold=10   # 10个失败请求后屏蔽
        ),
        
        # 链接发现器 - 发现页面中的链接
        lambda: LinksFinder(
            name="links_finder",
            css_selector="a[href]:not(.no-follow)"  # 排除nofollow链接
        ),
        
        # 广告清理器 - 清理广告和导航元素
        lambda: ElementCleaner(
            name="ads_cleaner",
            css_selector=".ads, .advertisement, .sidebar, nav, .navigation, .menu"
        ),
        
        # 内容发现器 - 提取核心内容
        lambda: ContentFinder(
            name="content_finder",
            css_selector="article, .article-content, .post-content, .content, main, .main",
            target_state="ready"  # 在页面就绪时处理
        ),
        
        # PDF导出器 - 导出为PDF
        lambda: PdfExporter(
            name="pdf_exporter",
            output_path=f"{output_dir}/webpage.pdf"
        )
    ]


def create_blog_processor_factories(output_dir="/tmp"):
    """
    创建专门用于博客文章的处理器工厂函数
    
    Args:
        output_dir: PDF输出目录
        
    Returns:
        List: 处理器工厂函数列表
    """
    return [
        # 页面监控器
        lambda: PageMonitor("page_monitor", slow_request_timeout=2.0),
        
        # 请求监控器 - 对博客使用更严格的阈值
        lambda: RequestMonitor("request_monitor", slow_threshold=30, failed_threshold=5),
        
        # 链接发现器 - 查找相关文章链接
        lambda: LinksFinder("links_finder", css_selector="a.related-post, a.next-post"),
        
        # 清理不必要的元素
        lambda: ElementCleaner(
            "blog_cleaner",
            css_selector=".comments, .social-share, .related-posts, .author-bio, .tags"
        ),
        
        # 内容发现器 - 专门针对博客文章结构
        lambda: ContentFinder(
            "blog_content_finder",
            css_selector=".post-content, .entry-content, .article-body, .blog-post",
            target_state="completed"  # 等待页面完全加载
        ),
        
        # PDF导出器
        lambda: PdfExporter("blog_pdf_exporter", f"{output_dir}/blog_post.pdf")
    ]


def create_documentation_processor_factories(output_dir="/tmp"):
    """
    创建专门用于文档页面的处理器工厂函数
    
    Args:
        output_dir: PDF输出目录
        
    Returns:
        List: 处理器工厂函数列表
    """
    return [
        # 页面监控器
        lambda: PageMonitor("page_monitor", slow_request_timeout=5.0),
        
        # 请求监控器 - 文档页面通常比较稳定
        lambda: RequestMonitor("request_monitor", slow_threshold=100, failed_threshold=20),
        
        # 链接发现器 - 发现文档中的内部链接
        lambda: LinksFinder(
            "doc_links_finder",
            css_selector="a[href^='/docs'], a[href^='./'], a.internal-link"
        ),
        
        # 清理文档页面的导航元素
        lambda: ElementCleaner(
            "doc_cleaner",
            css_selector=".toc, .table-of-contents, .breadcrumb, .edit-page"
        ),
        
        # 内容发现器 - 专门针对文档结构
        lambda: ContentFinder(
            "doc_content_finder",
            css_selector=".documentation, .doc-content, .markdown-body, .rst-content",
            target_state="ready"
        ),
        
        # PDF导出器
        lambda: PdfExporter("doc_pdf_exporter", f"{output_dir}/documentation.pdf")
    ]


async def demo_processor_workflow():
    """
    演示处理器工作流程的示例函数
    
    注意：这是一个演示函数，实际使用中需要配合ChromiumManager
    """
    print("=== 新处理器工作流程演示 ===")
    
    # 创建临时输出目录
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"输出目录: {temp_dir}")
        
        # 创建处理器工厂
        factories = create_advanced_processor_factories(temp_dir)
        
        print(f"创建了 {len(factories)} 个处理器工厂:")
        for i, factory in enumerate(factories):
            processor = factory()
            print(f"  {i+1}. {processor.name} (优先级: {processor.priority})")
        
        print("\n处理器执行顺序 (按优先级):")
        processors = [factory() for factory in factories]
        sorted_processors = sorted(processors, key=lambda p: p.priority)
        
        for processor in sorted_processors:
            print(f"  {processor.priority}: {processor.name}")
        
        print("\n=== 演示完成 ===")


def get_processor_metrics_info():
    """
    获取处理器指标信息
    
    Returns:
        Dict: 处理器指标信息
    """
    metrics_info = {
        "PageMonitor": [
            "page_monitor_slow_requests_total - 慢请求总数",
            "page_monitor_failed_requests_total - 失败请求总数",
            "page_monitor_load_duration_seconds - 页面加载耗时",
            "page_monitor_active_requests - 活跃请求数量"
        ],
        "RequestMonitor": [
            "request_monitor_blocked_urls_total - 被屏蔽URL总数"
        ],
        "LinksFinder": [
            "links_finder_links_found_total - 发现链接总数"
        ],
        "ElementCleaner": [
            "element_cleaner_elements_cleaned_total - 清理元素总数"
        ],
        "ContentFinder": [
            "content_finder_content_processed_total - 处理内容总数",
            "content_finder_content_size_bytes - 内容字节大小"
        ],
        "PdfExporter": [
            "pdf_exporter_pdfs_exported_total - 导出PDF总数",
            "pdf_exporter_export_duration_seconds - PDF导出耗时",
            "pdf_exporter_file_size_bytes - PDF文件大小"
        ]
    }
    
    return metrics_info


if __name__ == "__main__":
    print("新处理器使用示例")
    print("=" * 50)
    
    # 运行演示
    asyncio.run(demo_processor_workflow())
    
    print("\n可用的处理器配置:")
    print("1. create_advanced_processor_factories() - 通用高级处理器")
    print("2. create_blog_processor_factories() - 博客文章处理器")
    print("3. create_documentation_processor_factories() - 文档页面处理器")
    
    print("\nPrometheus 指标:")
    metrics = get_processor_metrics_info()
    for processor, metric_list in metrics.items():
        print(f"\n{processor}:")
        for metric in metric_list:
            print(f"  - {metric}")
    
    print("\n使用方法:")
    print("1. 选择合适的处理器工厂函数")
    print("2. 将工厂函数列表传递给ChromiumManager")
    print("3. 运行Manager开始处理页面")
    print("4. 通过Manager.get_metrics()获取监控指标")
