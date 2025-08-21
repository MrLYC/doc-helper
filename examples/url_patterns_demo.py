#!/usr/bin/env python3
"""
URL 模式功能演示

展示新的多 URL 模式功能：
1. 自动生成每个入口URL对应的目录模式
2. 手动指定多个URL模式
3. 向后兼容性
"""

import asyncio
import tempfile
from pathlib import Path
from doc_helper.builder import PageProcessingBuilder
from doc_helper.url_collection import SimpleCollection

async def demo_auto_url_patterns():
    """演示自动生成URL模式"""
    print("=== 演示：自动生成URL模式 ===")
    
    # 入口URLs
    entry_urls = [
        "https://docs.python.org/3/",
        "https://fastapi.tiangolo.com/tutorial/",
        "https://github.com/MrLYC/doc-helper/docs"
    ]
    
    from doc_helper.server import generate_default_url_patterns
    patterns = generate_default_url_patterns(entry_urls)
    
    print("入口URLs:")
    for url in entry_urls:
        print(f"  • {url}")
    
    print("\n自动生成的URL模式:")
    for i, pattern in enumerate(patterns, 1):
        print(f"  {i}. {pattern}")
    
    return patterns

async def demo_manual_url_patterns():
    """演示手动指定多个URL模式"""
    print("\n=== 演示：手动指定多个URL模式 ===")
    
    # 手动指定的模式
    manual_patterns = [
        ".*docs.*",
        ".*tutorial.*", 
        ".*api.*",
        ".*guide.*"
    ]
    
    print("手动指定的URL模式:")
    for i, pattern in enumerate(manual_patterns, 1):
        print(f"  {i}. {pattern}")
    
    # 测试URLs
    test_urls = [
        "https://docs.python.org/3/library/",
        "https://fastapi.tiangolo.com/tutorial/first-steps/",
        "https://github.com/MrLYC/doc-helper",
        "https://example.com/api/reference/",
        "https://site.com/guide/getting-started/"
    ]
    
    # 创建LinksFinder进行测试
    from doc_helper.processors import LinksFinder
    collection = SimpleCollection()
    
    finder = LinksFinder(
        name="demo_finder",
        url_collection=collection,
        url_patterns=manual_patterns
    )
    
    print("\nURL匹配测试:")
    for url in test_urls:
        matches = finder._matches_url_pattern(url)
        status = "✓ 匹配" if matches else "✗ 不匹配"
        print(f"  {status} {url}")
    
    return manual_patterns

async def demo_builder_integration():
    """演示与PageProcessingBuilder的集成"""
    print("\n=== 演示：Builder集成 ===")
    
    # 使用新的多URL模式API
    with tempfile.TemporaryDirectory() as temp_dir:
        builder = PageProcessingBuilder()
        
        # 配置基本设置
        builder = (builder
                   .set_entry_urls(["https://docs.python.org/3/"])
                   .set_concurrent_tabs(1)
                   .set_page_timeout(30.0)
                   .set_headless(True))
        
        # 使用新的多模式API
        url_patterns = [
            ".*docs\\.python\\.org.*",
            ".*library.*",
            ".*tutorial.*"
        ]
        
        builder = builder.find_links(
            css_selector="main a",
            url_patterns=url_patterns,
            max_depth=2
        )
        
        # 添加其他处理器
        builder = (builder
                   .clean_elements("script, style, nav")
                   .find_content("main")
                   .export_pdf(output_dir=temp_dir))
        
        print("Builder配置完成，URL模式:")
        for i, pattern in enumerate(url_patterns, 1):
            print(f"  {i}. {pattern}")
        
        print(f"输出目录: {temp_dir}")
        print("注意：这是一个演示，实际不会运行网页爬取")

async def demo_backward_compatibility():
    """演示向后兼容性"""
    print("\n=== 演示：向后兼容性 ===")
    
    from doc_helper.processors import LinksFinder
    collection = SimpleCollection()
    
    # 测试旧的单一模式方式（向后兼容）
    old_finder = LinksFinder(
        name="old_style",
        url_collection=collection,
        url_pattern=".*docs.*"  # 旧方式
    )
    
    # 测试新的多模式方式
    new_finder = LinksFinder(
        name="new_style", 
        url_collection=collection,
        url_patterns=[".*docs.*", ".*tutorial.*"]  # 新方式
    )
    
    test_url = "https://docs.python.org/3/tutorial/"
    
    print("向后兼容性测试:")
    print(f"测试URL: {test_url}")
    print(f"旧方式 (单一模式): {old_finder._matches_url_pattern(test_url)}")
    print(f"新方式 (多模式): {new_finder._matches_url_pattern(test_url)}")
    
    print(f"旧方式的模式: {old_finder.url_patterns}")
    print(f"新方式的模式: {new_finder.url_patterns}")

async def main():
    """主演示函数"""
    print("🚀 URL模式功能演示")
    print("=" * 50)
    
    await demo_auto_url_patterns()
    await demo_manual_url_patterns()
    await demo_builder_integration()
    await demo_backward_compatibility()
    
    print("\n" + "=" * 50)
    print("✅ 演示完成！")
    print("\n主要特性:")
    print("1. ✅ 支持多个URL模式")
    print("2. ✅ 自动生成入口URL对应的目录模式")
    print("3. ✅ 向后兼容单一模式")
    print("4. ✅ 集成到PageProcessingBuilder")
    print("5. ✅ 命令行参数支持 --url-patterns")

if __name__ == "__main__":
    asyncio.run(main())