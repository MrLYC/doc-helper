# URL 集合使用指南

本文档介绍如何使用 `doc_helper.url_collection` 模块中的 `FileCollection` 和 `SimpleCollection`。

## FileCollection - 文件目录扫描器

`FileCollection` 用于扫描指定目录下的文件，并将其转换为本地文件 URL。

### 基本用法

```python
from doc_helper.url_collection import FileCollection
from pathlib import Path

# 创建文件集合，扫描特定扩展名的文件
collection = FileCollection(
    base_directory=Path("/path/to/documents"),
    extensions={'.pdf', '.html', '.txt'},  # 只扫描这些文件类型
    category="documents"
)

# 获取所有待处理的文件
pending_files = collection.get_pending_urls()
print(f"找到 {len(pending_files)} 个文件")

# 获取文件信息
for url_obj in pending_files:
    file_info = collection.get_file_info(url_obj.id)
    relative_path = collection.get_relative_path(url_obj.id)
    print(f"{relative_path}: {file_info['size']} bytes")
```

### 主要方法

- `refresh()` - 重新扫描目录
- `get_file_info(url_id)` - 获取文件详细信息
- `get_relative_path(url_id)` - 获取相对路径
- `filter_by_size(min_size, max_size)` - 按文件大小过滤

## SimpleCollection - 简单 URL 管理器

`SimpleCollection` 提供基本的 URL 管理功能。

### 基本用法

```python
from doc_helper.url_collection import SimpleCollection

# 创建简单集合
collection = SimpleCollection(category="web_urls")

# 添加单个 URL
url_id = collection.add_url("https://example.com")
print(f"添加 URL，ID: {url_id}")

# 批量添加 URL
urls = ["https://github.com", "https://stackoverflow.com"]
url_ids = collection.bulk_add_urls(urls)
print(f"批量添加了 {len(url_ids)} 个 URL")

# 屏蔽 URL
collection.block_url("https://github.com")

# 移除 URL
collection.remove_url("https://stackoverflow.com")
```

### 主要方法

- `add_url(url)` - 添加单个 URL
- `bulk_add_urls(urls)` - 批量添加 URL
- `remove_url(url_or_id)` - 移除 URL
- `block_url(url_or_id)` - 屏蔽 URL
- `unblock_url(url_or_id)` - 解除屏蔽
- `get_pending_urls()` - 获取待处理 URL
- `get_blocked_urls()` - 获取已屏蔽 URL

## 便利函数

模块提供了两个便利函数用于快速创建集合：

```python
from doc_helper.url_collection import create_file_collection, create_simple_collection
from pathlib import Path

# 快速创建文件集合
file_collection = create_file_collection(
    directory=Path("docs"),
    extensions={'.md', '.rst'},
    category="documentation"
)

# 快速创建简单集合
simple_collection = create_simple_collection(category="bookmarks")
```

## 共同方法

两个集合类都继承自 `URLCollection` 协议，提供以下共同方法：

- `count_by_status(status)` - 统计指定状态的 URL 数量
- `get_by_status(status)` - 获取指定状态的 URL 列表
- `update_status(url_id, status)` - 更新 URL 状态
- `get_all_statuses()` - 获取所有状态统计

## URL 状态

系统支持以下 URL 状态：

- `URLStatus.PENDING` - 待处理
- `URLStatus.PROCESSING` - 处理中
- `URLStatus.COMPLETED` - 已完成
- `URLStatus.VISITED` - 已访问 (为向后兼容保留)
- `URLStatus.FAILED` - 处理失败

URL 状态的典型流程：`PENDING` → `PROCESSING` → `COMPLETED`/`FAILED`

## 示例：文档处理流程

```python
from doc_helper.url_collection import FileCollection
from doc_helper.protocol import URLStatus
from pathlib import Path

# 1. 扫描文档目录
collection = FileCollection(
    base_directory=Path("documents"),
    extensions={'.pdf', '.docx'},
    category="office_docs"
)

# 2. 处理所有待处理文件
for url_obj in collection.get_pending_urls():
    try:
        # 处理文件逻辑
        file_info = collection.get_file_info(url_obj.id)
        print(f"处理文件: {file_info['name']}")
        
        # 标记为已访问
        collection.update_status(url_obj.id, URLStatus.VISITED)
        
    except Exception as e:
        # 标记为失败
        collection.update_status(url_obj.id, URLStatus.FAILED)
        print(f"处理失败: {e}")

# 3. 查看处理结果
stats = collection.get_all_statuses()
print(f"处理统计: {dict(stats)}")
```

## 注意事项

1. **文件协议支持**: `FileCollection` 生成的 URL 使用 `file://` 协议
2. **路径处理**: 支持递归扫描子目录
3. **扩展名过滤**: 扩展名比较不区分大小写
4. **内存效率**: 大型目录建议分批处理
5. **线程安全**: 当前实现不是线程安全的，多线程使用需要额外同步

更多详细信息请参考测试文件 `tests/test_url_collection.py` 中的使用示例。