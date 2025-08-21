#!/usr/bin/env python3
"""
Builder模式示例 - 展示如何使用PageProcessingBuilder

这个文件展示了各种Builder使用场景，包括基础用法、高级配置和工厂函数。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pdf_helper import (
    PageProcessingBuilder, 
    create_web_scraper,
    create_pdf_generator, 
    create_link_crawler
)


def example_1_basic_web_scraper():
    """示例1：基础网页爬虫"""
    print("=== 示例1：基础网页爬虫 ===")
    
    try:
        manager = (PageProcessingBuilder()
            .set_entry_url("https://httpbin.org/html")
            .set_concurrent_tabs(2)
            .find_links("a")
            .build())
        
        print("✅ 基础网页爬虫构建成功")
        print(f"并发标签页: {manager.config.max_concurrent_tabs}")
        
    except Exception as e:
        print(f"❌ 基础网页爬虫构建失败: {e}")


def example_2_pdf_generator():
    """示例2：PDF生成器"""
    print("=== 示例2：PDF生成器 ===")
    
    try:
        manager = (PageProcessingBuilder()
            .set_entry_url("https://httpbin.org/html")
            .clean_elements("script, style")
            .export_pdf("/tmp/test_output.pdf")
            .build())
        
        print("✅ PDF生成器构建成功")
        print("✅ 已配置元素清理和PDF导出")
        
    except Exception as e:
        print(f"❌ PDF生成器构建失败: {e}")


def example_3_link_crawler():
    """示例3：链接爬虫"""
    print("=== 示例3：链接爬虫 ===")
    
    try:
        manager = (PageProcessingBuilder()
            .set_entry_url("https://httpbin.org/links/5")
            .set_concurrent_tabs(3)
            .find_links("a[href]")
            .find_content("body")
            .build())
        
        print("✅ 链接爬虫构建成功")
        print(f"并发标签页: {manager.config.max_concurrent_tabs}")
        
    except Exception as e:
        print(f"❌ 链接爬虫构建失败: {e}")


def example_4_advanced_processing():
    """示例4：高级处理流水线"""
    print("=== 示例4：高级处理流水线 ===")
    
    try:
        manager = (PageProcessingBuilder()
            .set_entry_url("https://httpbin.org/html")
            .set_concurrent_tabs(2)
            .set_page_timeout(90.0)
            .block_url_patterns([".*\\.gif", ".*analytics.*"])
            .find_links("body a")
            .clean_elements(".ads, script[src*='analytics']")
            .find_content("main, article, .content")
            .export_pdf("/tmp/advanced_output.pdf")
            .build())
        
        print("✅ 高级处理流水线构建成功")
        print("✅ 包含URL阻止、链接查找、元素清理、内容提取和PDF导出")
        
    except Exception as e:
        print(f"❌ 高级处理流水线构建失败: {e}")


def example_5_factory_functions():
    """示例5：工厂函数"""
    print("=== 示例5：工厂函数 ===")
    
    try:
        # Web爬虫工厂
        scraper = (create_web_scraper()
            .set_entry_url("https://httpbin.org/html")
            .find_links("a")
            .build())
        print("✅ Web爬虫工厂函数成功")
        
        # PDF生成器工厂
        pdf_gen = (create_pdf_generator()
            .set_entry_url("https://httpbin.org/html")
            .build())
        print("✅ PDF生成器工厂函数成功")
        
        # 链接爬虫工厂
        link_crawler = (create_link_crawler()
            .set_entry_url("https://httpbin.org/links/3")
            .build())
        print("✅ 链接爬虫工厂函数成功")
        
    except Exception as e:
        print(f"❌ 工厂函数失败: {e}")


def example_6_full_configuration():
    """示例6：完整配置"""
    print("=== 示例6：完整配置 ===")
    
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
    print("\n🎉 所有示例运行完成！")