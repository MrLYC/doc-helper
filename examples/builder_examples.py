"""
Builder模式使用示例

展示如何使用PageProcessingBuilder来构建不同类型的页面处理流水线
"""

import asyncio
import logging
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from doc_helper import (
    PageProcessingBuilder, 
    create_web_scraper,
    create_pdf_generator, 
    create_link_crawler
)# 配置日志
logging.basicConfig(level=logging.INFO)


async def example_basic_pdf_generator():
    """基本的PDF生成器示例"""
    print("=== 基本PDF生成器示例 ===")
    
    # 构建页面处理器
    manager = (PageProcessingBuilder()
        .set_entry_url("https://example.com")
        .set_concurrent_tabs(2)
        .clean_elements("*[id*='ad'], .popup, script[src*='analytics']")
        .find_content("main, article, .content")
        .export_pdf("/tmp/example.pdf")
        .build())
    
    print(f"构建完成，管理器类型: {type(manager).__name__}")
    print("可以通过 await manager.run() 来执行处理")


async def example_advanced_scraper():
    """高级网页爬虫示例"""
    print("\n=== 高级网页爬虫示例 ===")
    
    # 构建高级爬虫
    manager = (PageProcessingBuilder()
        .set_entry_urls([
            "https://example.com",
            "https://example.org"
        ])
        .set_concurrent_tabs(3)
        .set_page_timeout(30.0)
        .set_verbose(True)
        .block_url_patterns([
            ".*\\.gif", ".*\\.jpg", ".*\\.png", ".*\\.css", 
            ".*analytics.*", ".*tracking.*", ".*\\.woff"
        ])
        .find_links("body a[href]")
        .clean_elements("*[id*='ad'], .popup, .banner")
        .find_content("main article, .content")
        .export_pdf(output_dir="/tmp/scraped_pdfs")
        .build())
    
    print(f"构建完成，管理器类型: {type(manager).__name__}")
    print("支持链接发现、内容清理、PDF导出等功能")


async def example_link_crawler():
    """链接爬虫示例"""
    print("\n=== 链接爬虫示例 ===")
    
    # 使用预配置的链接爬虫
    manager = (create_link_crawler()
        .set_entry_url("https://news.ycombinator.com")
        .set_concurrent_tabs(5)
        .find_content("a.storylink")
        .export_pdf("/tmp/hn_stories.pdf")
        .build())
    
    print(f"构建完成，管理器类型: {type(manager).__name__}")
    print("已预配置URL屏蔽和链接发现功能")


async def example_pdf_generator():
    """PDF生成器示例"""
    print("\n=== 预配置PDF生成器示例 ===")
    
    # 使用预配置的PDF生成器
    manager = (create_pdf_generator()
        .set_entry_url("https://docs.python.org")
        .set_concurrent_tabs(2)
        .build())
    
    print(f"构建完成，管理器类型: {type(manager).__name__}")
    print("已预配置内容查找和PDF导出功能")


async def example_custom_processors():
    """自定义处理器示例"""
    print("\n=== 自定义处理器示例 ===")
    
    from doc_helper.processors import ElementCleaner
    
    # 创建自定义处理器
    custom_cleaner = ElementCleaner(
        name="custom_ad_remover",
        css_selector=".advertisement, .sponsored, [data-ad]",
        priority=15
    )
    
    # 构建带自定义处理器的管理器
    manager = (PageProcessingBuilder()
        .set_entry_url("https://example.com")
        .add_processor(custom_cleaner)
        .find_content("article.main-content")
        .export_pdf("/tmp/clean_content.pdf")
        .build())
    
    print(f"构建完成，管理器类型: {type(manager).__name__}")
    print("包含自定义广告清理处理器")


async def example_minimal():
    """最小化示例"""
    print("\n=== 最小化示例 ===")
    
    # 最简单的配置
    manager = (create_web_scraper()
        .set_entry_url("https://example.com")
        .export_pdf()
        .build())
    
    print(f"构建完成，管理器类型: {type(manager).__name__}")
    print("最简单的页面到PDF转换器")


async def main():
    """运行所有示例"""
    print("页面处理器构建器示例")
    print("=" * 50)
    
    await example_basic_pdf_generator()
    await example_advanced_scraper()
    await example_link_crawler()
    await example_pdf_generator()
    await example_custom_processors()
    await example_minimal()
    
    print("\n" + "=" * 50)
    print("所有示例构建完成！")
    print("注意：这些示例只展示了构建过程，实际执行需要调用 manager.run()")


def example_6_full_configuration():
    """示例6：完整配置的构建器"""
    print("=== 示例6：完整配置的构建器 ===")
    
    def custom_retry_callback(url: str, error: Exception) -> bool:
        """自定义重试回调"""
        print(f"重试决策 - URL: {url}, 错误: {error}")
        return True  # 总是重试
    
    try:
        manager = (PageProcessingBuilder()
            .set_entry_url("https://httpbin.org/html")
            .set_concurrent_tabs(2)
            .set_page_timeout(120.0)
            .set_poll_interval(0.5)
            .set_detect_timeout(15.0)
            .set_headless(True)
            .set_verbose(False)
            .set_retry_callback(custom_retry_callback)
            .block_url_patterns([".*\\.gif", ".*analytics.*"])
            .find_links("body a")
            .clean_elements("script, style")
            .find_content("body")
            .export_pdf("/tmp/full_config_output.pdf")
            .build())
        
        print("✅ 完整配置构建器创建成功")
        print(f"并发标签页: {manager.config.max_concurrent_tabs}")
        print(f"页面超时: {manager.config.page_timeout}秒")
        print(f"轮询间隔: {manager.config.poll_interval}秒")
        print(f"检测超时: {manager.config.detect_timeout}秒")
        print(f"无头模式: {manager.config.headless}")
        print(f"可视化模式: {manager.verbose}")
        
    except Exception as e:
        print(f"❌ 完整配置构建器创建失败: {e}")


if __name__ == "__main__":
    example_1_basic_web_scraper()
    print()
    example_2_pdf_generator()
    print()
    example_3_link_crawler()
    print()
    example_4_advanced_processing()
    print()
    example_5_factory_functions()
    print()
    example_6_full_configuration()