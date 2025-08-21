# PDF合并器 (pdf_merger.py) 文档

## 概述

PDF合并器是一个功能强大的工具，用于将多个PDF文件合并为少数几个PDF文件。支持按页数和文件大小限制进行智能分组，并提供灵活的文件命名模板系统。

## 主要功能

### ✅ 核心特性

1. **智能分组合并**
   - 按最大页数限制分组
   - 按最大文件大小限制分组
   - 自动规划最优分组策略

2. **灵活的文件命名**
   - 支持模板变量 (`{name}`, `{index}`, `{date}`, `{time}` 等)
   - 单文件和多文件不同命名模板
   - 自动文件名清理和安全处理

3. **高级配置选项**
   - 元数据保留
   - PDF压缩优化
   - 覆盖文件控制
   - 详细日志输出

4. **多种使用方式**
   - Python API
   - 命令行工具
   - 便捷工厂函数

## 使用方法

### Python API

```python
from pdf_helper import PdfMerger, MergeConfig, create_merger

# 方式1: 使用配置类
config = MergeConfig(
    max_pages=100,
    max_file_size_mb=25.0,
    output_dir="/output",
    single_file_template="{name}_complete.pdf",
    multi_file_template="{name}_part_{index:02d}.pdf"
)
merger = PdfMerger(config)

# 方式2: 使用便捷函数
merger = create_merger(
    max_pages=100,
    max_file_size_mb=25.0,
    output_dir="/output"
)

# 执行合并
result = merger.merge_files([
    "/path/to/file1.pdf",
    "/path/to/file2.pdf",
    "/path/to/file3.pdf"
], "merged_docs")

if result.success:
    print(f"✅ 成功合并 {len(result.output_files)} 个文件")
    for file in result.output_files:
        print(f"  - {file}")
else:
    print(f"❌ 合并失败: {result.error_message}")
```

### 命令行使用

```bash
# 基础合并
python pdf_helper/pdf_merger.py *.pdf -o /output -n merged

# 页数限制
python pdf_helper/pdf_merger.py *.pdf --max-pages 100 -o /output -n report

# 文件大小限制
python pdf_helper/pdf_merger.py *.pdf --max-size 25 -o /output -n docs

# 自定义模板
python pdf_helper/pdf_merger.py *.pdf \
    --single-template "Report_{name}_{date}.pdf" \
    --multi-template "Report_{name}_Vol{index:02d}_{date}.pdf" \
    -o /output -n annual_report

# 详细输出
python pdf_helper/pdf_merger.py *.pdf -v -o /output -n combined
```

## 配置选项

### MergeConfig 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_pages` | int | None | 每个输出文件的最大页数 |
| `max_file_size_mb` | float | None | 每个输出文件的最大大小(MB) |
| `output_dir` | str | "/tmp" | 输出目录 |
| `single_file_template` | str | "{name}.pdf" | 单文件输出模板 |
| `multi_file_template` | str | "{name}_{index:03d}.pdf" | 多文件输出模板 |
| `overwrite_existing` | bool | False | 是否覆盖已存在文件 |
| `preserve_metadata` | bool | True | 是否保留PDF元数据 |
| `compression` | bool | True | 是否启用压缩 |

### 模板变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `{name}` | 基础文件名 | "merged_docs" |
| `{index}` | 文件序号(从1开始) | 1, 2, 3 |
| `{total}` | 总文件数 | 5 |
| `{date}` | 日期(YYYYMMDD) | "20250821" |
| `{time}` | 时间(HHMMSS) | "143022" |
| `{datetime}` | 日期时间 | "20250821_143022" |
| `{timestamp}` | Unix时间戳 | 1724235022 |

## 使用场景

### 1. 商务场景 - 邮件友好分发
```python
merger = create_merger(
    max_file_size_mb=10.0,  # 邮件附件限制
    output_dir="/output",
    single_file_template="QuarterlyReport_{name}_{date}.pdf",
    multi_file_template="QuarterlyReport_{name}_Volume{index:02d}_{date}.pdf"
)
```

### 2. 学术场景 - 打印友好分章
```python
merger = create_merger(
    max_pages=100,  # 打印友好页数
    output_dir="/output", 
    single_file_template="Research_{name}_Complete.pdf",
    multi_file_template="Research_{name}_Chapter{index:02d}.pdf"
)
```

### 3. 归档场景 - 按大小分卷
```python
merger = create_merger(
    max_file_size_mb=50.0,  # 50MB分卷
    output_dir="/archive",
    single_file_template="Archive_{name}_{timestamp}.pdf",
    multi_file_template="Archive_{name}_Vol{index:03d}_{timestamp}.pdf"
)
```

## 实用工具方法

### 估算输出信息
```python
info = merger.estimate_output_info(file_list)
print(f"总文件: {info['total_files']}")
print(f"总页数: {info['total_pages']}")
print(f"预计分组: {info['estimated_groups']}")
```

### 获取可用模板变量
```python
variables = merger.get_available_template_variables()
for var, desc in variables.items():
    print(f"{var}: {desc}")
```

## 错误处理

```python
result = merger.merge_files(file_list, "output")

if not result.success:
    print(f"错误: {result.error_message}")
    print(f"源文件数: {result.source_files_count}")
    print(f"成功输出: {len(result.output_files)}")
```

## 依赖要求

- Python 3.7+
- PyPDF2 或 pypdf
- pathlib (内置)
- typing (内置)
- dataclasses (Python 3.7+内置)

## 安装

PDF合并器已集成到 pdf_helper 包中：

```python
from pdf_helper import PdfMerger, MergeConfig, create_merger
```

## 性能优化建议

1. **大文件处理**: 对于大量文件，建议分批处理
2. **内存优化**: 启用压缩可减少内存使用
3. **并行处理**: 可以并行处理多个独立的合并任务
4. **预估计算**: 使用 `estimate_output_info()` 预先规划
5. **临时文件**: 确保有足够的临时存储空间

## 限制和注意事项

1. **文件大小**: 受系统内存限制
2. **PDF格式**: 仅支持标准PDF格式
3. **权限**: 需要输出目录写权限
4. **加密PDF**: 不支持加密的PDF文件
5. **损坏文件**: 自动跳过无法读取的文件

## 测试覆盖

- ✅ 23个专门的PDF合并器测试
- ✅ 164个总测试全部通过
- ✅ 配置验证测试
- ✅ 文件处理测试
- ✅ 模板系统测试
- ✅ 错误处理测试

PDF合并器是一个稳定、可靠的工具，适用于各种PDF合并需求！