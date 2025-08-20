"""
页面处理框架使用示例

该文件展示如何使用页面处理框架来批量处理网页。
"""

import asyncio
import hashlib
import logging
import time
from typing import List

from .manager import ChromiumManager
from .processors import (
    ContentExtractProcessor, LinkExtractProcessor, 
    PageLoadProcessor, PDFGenerateProcessor, ScreenshotProcessor
)
from .protocol import (
    PageManagerConfig, RetryCallback, URL, URLCollection, URLStatus
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def create_url_id(url: str) -> str:
    """为URL生成唯一ID"""
    return hashlib.md5(url.encode()).hexdigest()[:8]


def simple_retry_callback(failed_urls: List[URL]) -> bool:
    """简单的重试回调，询问用户是否重试"""
    print(f"\n发现 {len(failed_urls)} 个失败的URL:")
    for url in failed_urls[:5]:  # 只显示前5个
        print(f"  - {url.url}")
    if len(failed_urls) > 5:
        print(f"  ... 还有 {len(failed_urls) - 5} 个")
    
    while True:
        response = input("\n是否重试失败的URL? (y/n): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        else:
            print("请输入 y 或 n")


async def example_basic_usage():
    """基本使用示例"""
    logger.info("=== 基本使用示例 ===")
    
    # 1. 创建URL集合
    url_collection = URLCollection()
    
    # 添加一些测试URL
    test_urls = [
        "https://httpbin.org/html",
        "https://httpbin.org/json", 
        "https://httpbin.org/xml",
        "https://example.com"
    ]
    
    for url_str in test_urls:
        url = URL(
            id=create_url_id(url_str),
            url=url_str,
            category="test"
        )
        url_collection.add(url)
    
    logger.info(f"添加了 {len(test_urls)} 个URL到集合")
    
    # 2. 定义处理器工厂
    def create_processors():
        return [
            lambda: PageLoadProcessor("page_loader"),
            lambda: ContentExtractProcessor("content_extractor", "body"),
            lambda: LinkExtractProcessor("link_extractor"),
            lambda: ScreenshotProcessor("screenshot", "/tmp")
        ]
    
    # 3. 配置管理器
    config = PageManagerConfig(
        max_concurrent_tabs=2,
        poll_interval=1.0,
        page_timeout=30.0,
        detect_timeout=5.0,
        headless=True
    )
    
    # 4. 创建和运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=create_processors(),
        config=config,
        retry_callback=simple_retry_callback
    )
    
    start_time = time.time()
    await manager.run()
    end_time = time.time()
    
    # 5. 显示结果
    logger.info(f"处理完成，耗时: {end_time - start_time:.2f}秒")
    stats = url_collection.get_all_statuses()
    for status, count in stats.items():
        if count > 0:
            logger.info(f"  {status.value}: {count}")


async def example_pdf_generation():
    """PDF生成示例"""
    logger.info("=== PDF生成示例 ===")
    
    # 创建URL集合
    url_collection = URLCollection()
    
    # 添加适合生成PDF的URL
    pdf_urls = [
        "https://httpbin.org/html",
        "https://example.com",
    ]
    
    for url_str in pdf_urls:
        url = URL(
            id=create_url_id(url_str),
            url=url_str,
            category="pdf_test"
        )
        url_collection.add(url)
    
    # 定义处理器工厂（包含PDF生成）
    def create_pdf_processors():
        return [
            lambda: PageLoadProcessor("page_loader"),
            lambda: ContentExtractProcessor("content_extractor", "body"),
            lambda: PDFGenerateProcessor("pdf_generator", "/tmp")
        ]
    
    # 配置管理器
    config = PageManagerConfig(
        max_concurrent_tabs=1,  # PDF生成时使用较少并发
        poll_interval=2.0,
        page_timeout=60.0,
        headless=True
    )
    
    # 运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=create_pdf_processors(),
        config=config
    )
    
    await manager.run()
    
    # 检查结果
    visited_urls = url_collection.get_by_status(URLStatus.VISITED)
    logger.info(f"成功生成 {len(visited_urls)} 个PDF文件")


async def example_link_discovery():
    """链接发现示例"""
    logger.info("=== 链接发现示例 ===")
    
    # 创建URL集合
    url_collection = URLCollection()
    
    # 起始URL
    start_url = "https://httpbin.org/"
    url = URL(
        id=create_url_id(start_url),
        url=start_url,
        category="discovery"
    )
    url_collection.add(url)
    
    # 自定义链接提取处理器，发现新链接时添加到集合
    class DiscoveryLinkExtractor(LinkExtractProcessor):
        def __init__(self, name: str, url_collection: URLCollection):
            super().__init__(name)
            self.url_collection = url_collection
        
        async def run(self, context):
            await super().run(context)
            
            # 处理提取的链接
            links = context.data.get("extracted_links", [])
            new_urls = 0
            for link in links:
                link_url = link["url"]
                # 只添加同域名的链接
                if "httpbin.org" in link_url:
                    new_url = URL(
                        id=create_url_id(link_url),
                        url=link_url,
                        category="discovered"
                    )
                    if self.url_collection.add(new_url):
                        new_urls += 1
            
            logger.info(f"从 {context.url.url} 发现 {new_urls} 个新链接")
    
    # 定义处理器工厂
    def create_discovery_processors():
        return [
            lambda: PageLoadProcessor("page_loader"),
            lambda: DiscoveryLinkExtractor("link_extractor", url_collection)
        ]
    
    # 配置管理器
    config = PageManagerConfig(
        max_concurrent_tabs=2,
        poll_interval=1.0,
        page_timeout=30.0
    )
    
    # 运行管理器
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=create_discovery_processors(),
        config=config
    )
    
    await manager.run()
    
    # 显示发现的链接统计
    total_urls = sum(url_collection.get_all_statuses().values())
    logger.info(f"总共处理了 {total_urls} 个URL")


async def main():
    """主函数，运行所有示例"""
    print("页面处理框架示例")
    print("=" * 50)
    
    examples = [
        ("基本使用", example_basic_usage),
        ("PDF生成", example_pdf_generation),
        ("链接发现", example_link_discovery)
    ]
    
    for name, example_func in examples:
        print(f"\n运行示例: {name}")
        print("-" * 30)
        try:
            await example_func()
        except KeyboardInterrupt:
            print(f"\n示例 {name} 被用户中断")
            break
        except Exception as e:
            logger.error(f"示例 {name} 执行失败: {e}")
        
        print(f"示例 {name} 完成")
        
        # 询问是否继续
        if name != examples[-1][0]:  # 不是最后一个示例
            while True:
                response = input("\n是否继续下一个示例? (y/n): ").strip().lower()
                if response in ['y', 'yes']:
                    break
                elif response in ['n', 'no']:
                    return
                else:
                    print("请输入 y 或 n")


if __name__ == "__main__":
    asyncio.run(main())