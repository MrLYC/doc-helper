"""
URL 集合使用示例

本文件演示如何使用 FileCollection 和 SimpleCollection 来管理 URL。
"""

import tempfile
from pathlib import Path

from pdf_helper.url_collection import FileCollection, SimpleCollection, create_file_collection, create_simple_collection
from pdf_helper.protocol import URLStatus


def demo_file_collection():
    """演示文件集合的使用"""
    print("=== 文件集合 (FileCollection) 演示 ===")
    
    # 创建临时目录和文件进行演示
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # 创建一些示例文件
        (temp_path / "document1.pdf").write_text("PDF文档1")
        (temp_path / "document2.html").write_text("<html>HTML文档</html>")
        (temp_path / "readme.txt").write_text("说明文档")
        (temp_path / "config.json").write_text('{"setting": "value"}')
        
        # 创建子目录
        sub_dir = temp_path / "subdir"
        sub_dir.mkdir()
        (sub_dir / "nested.pdf").write_text("嵌套PDF")
        
        print(f"创建临时目录: {temp_path}")
        
        # 1. 创建文件集合，只包含特定扩展名的文件
        collection = FileCollection(
            base_directory=temp_path,
            extensions={'.pdf', '.html', '.txt'},
            category="documents"
        )
        
        print(f"\n扫描到 {collection.count_by_status(URLStatus.PENDING)} 个匹配的文件")
        
        # 2. 显示所有文件
        print("\n所有扫描到的文件:")
        for url_obj in collection.get_by_status(URLStatus.PENDING):
            file_info = collection.get_file_info(url_obj.id)
            relative_path = collection.get_relative_path(url_obj.id)
            print(f"  - {relative_path} ({file_info['size']} bytes)")
        
        # 3. 模拟处理一些文件
        pdf_files = [url for url in collection.get_by_status(URLStatus.PENDING) 
                    if url.url.endswith('.pdf')]
        
        if pdf_files:
            # 标记第一个PDF为已访问
            collection.update_status(pdf_files[0].id, URLStatus.VISITED)
            print(f"\n已处理: {collection.get_relative_path(pdf_files[0].id)}")
        
        # 4. 显示状态统计
        stats = collection.get_all_statuses()
        print(f"\n状态统计: {dict(stats)}")
        
        # 5. 演示刷新功能
        print("\n添加新文件后刷新...")
        (temp_path / "new_document.txt").write_text("新文档")
        
        old_count = collection.count_by_status(URLStatus.PENDING)
        collection.refresh()
        new_count = collection.count_by_status(URLStatus.PENDING)
        
        print(f"刷新前: {old_count} 个待处理文件")
        print(f"刷新后: {new_count} 个待处理文件")
        print(f"新增: {new_count - old_count} 个文件")


def demo_simple_collection():
    """演示简单集合的使用"""
    print("\n\n=== 简单集合 (SimpleCollection) 演示 ===")
    
    # 创建简单集合
    collection = SimpleCollection(category="web_urls")
    
    # 1. 单个添加URL
    print("\n1. 添加URL:")
    urls = [
        "https://www.python.org",
        "https://github.com",
        "https://stackoverflow.com",
        "https://docs.python.org"
    ]
    
    for url in urls:
        url_id = collection.add_url(url)
        print(f"  添加: {url} (ID: {url_id})")
    
    # 2. 批量添加URL
    print("\n2. 批量添加URL:")
    more_urls = [
        "https://pypi.org",
        "https://realpython.com",
        "https://fastapi.tiangolo.com"
    ]
    
    url_ids = collection.bulk_add_urls(more_urls, category="tutorial")
    print(f"  批量添加了 {len(url_ids)} 个URL")
    
    # 3. 显示所有URL
    print(f"\n3. 总共有 {collection.count_by_status(URLStatus.PENDING)} 个待处理URL")
    
    # 4. 屏蔽某些URL
    print("\n4. 屏蔽URL:")
    if collection.block_url("https://github.com"):
        print("  已屏蔽: https://github.com")
    
    if collection.block_url(url_ids[0]):  # 通过ID屏蔽
        print(f"  已屏蔽: {more_urls[0]}")
    
    # 5. 显示不同状态的URL
    print(f"\n5. 状态统计:")
    pending_urls = collection.get_pending_urls()
    blocked_urls = collection.get_blocked_urls()
    
    print(f"  待处理: {len(pending_urls)} 个")
    for url in pending_urls[:3]:  # 只显示前3个
        print(f"    - {url.url}")
    
    print(f"  已屏蔽: {len(blocked_urls)} 个")
    for url in blocked_urls:
        print(f"    - {url.url}")
    
    # 6. 解除屏蔽
    print("\n6. 解除屏蔽:")
    if collection.unblock_url("https://github.com"):
        print("  已解除屏蔽: https://github.com")
    
    # 7. 移除URL
    print("\n7. 移除URL:")
    if collection.remove_url("https://stackoverflow.com"):
        print("  已移除: https://stackoverflow.com")
    
    # 8. 最终状态
    final_stats = collection.get_all_statuses()
    print(f"\n8. 最终状态统计: {dict(final_stats)}")


def demo_convenience_functions():
    """演示便利函数的使用"""
    print("\n\n=== 便利函数演示 ===")
    
    # 使用便利函数创建集合
    simple_collection = create_simple_collection()
    simple_collection.add_url("https://example.com")
    print(f"简单集合: {simple_collection.count_by_status(URLStatus.PENDING)} 个URL")
    
    # 如果存在 docs 目录，演示文件集合
    docs_path = Path("docs")
    if docs_path.exists() and docs_path.is_dir():
        try:
            file_collection = create_file_collection(
                directory=docs_path,
                extensions={'.md', '.txt', '.rst'}
            )
            print(f"文档集合: {file_collection.count_by_status(URLStatus.PENDING)} 个文件")
        except Exception as e:
            print(f"创建文档集合失败: {e}")
    else:
        print("docs 目录不存在，跳过文件集合演示")


if __name__ == "__main__":
    # 运行所有演示
    demo_file_collection()
    demo_simple_collection()
    demo_convenience_functions()
    
    print("\n=== 演示完成 ===")
    print("您可以根据需要使用 FileCollection 和 SimpleCollection 来管理URL集合。")