# 高级页面处理器文档

本文档描述了用于网页内容处理和PDF生成的高级处理器组件。这些处理器配合使用，可以实现完整的网页到PDF转换工作流程。

## 处理器概览

### 1. PageMonitor - 页面监控处理器

**优先级**: 0 (最高优先级，首先执行)

**功能**: 监控页面加载状态和网络请求，跟踪慢请求和失败请求。

**配置参数**:
- `slow_request_timeout`: 慢请求超时阈值，默认为页面超时的1/10

**主要功能**:
- 监听页面 `load` 和 `networkidle` 事件
- 跟踪网络请求的响应时间和失败情况
- 识别慢请求（超过阈值的请求）
- 识别失败请求（无法连接或超时的请求）
- 将监控数据保存到页面上下文中

**Prometheus 指标**:
- `page_monitor_slow_requests_total`: 慢请求总数
- `page_monitor_failed_requests_total`: 失败请求总数
- `page_monitor_load_duration_seconds`: 页面加载各阶段耗时
- `page_monitor_active_requests`: 活跃请求数量

**使用示例**:
```python
monitor = PageMonitor("page_monitor", slow_request_timeout=5.0)
```

### 2. RequestMonitor - 请求监控处理器

**优先级**: 1

**功能**: 基于网络请求质量自动屏蔽异常URL。

**配置参数**:
- `slow_threshold`: 慢请求数量阈值，默认100
- `failed_threshold`: 失败请求数量阈值，默认10

**主要功能**:
- 分析页面的慢请求和失败请求统计
- 当某个URL的慢请求或失败请求超过阈值时，自动将其标记为已屏蔽
- 防止异常请求拖慢整体页面加载速度

**Prometheus 指标**:
- `request_monitor_blocked_urls_total`: 被屏蔽的URL总数

**使用示例**:
```python
monitor = RequestMonitor("request_monitor", slow_threshold=50, failed_threshold=5)
```

### 3. LinksFinder - 链接发现处理器

**优先级**: 10

**功能**: 在页面中发现并收集链接，扩展爬取范围。

**配置参数**:
- `css_selector`: CSS选择器，用于查找链接元素，默认 `"a[href]"`

**主要功能**:
- 在页面进入就绪和加载完成状态时分别执行一次
- 查找指定CSS选择器匹配的所有链接元素
- 将有效链接转换为绝对URL并添加到URL集合中
- 过滤无效链接（如javascript:、mailto:等）

**Prometheus 指标**:
- `links_finder_links_found_total`: 发现的链接总数

**使用示例**:
```python
finder = LinksFinder("links_finder", css_selector="a.content-link")
```

### 4. ElementCleaner - 元素清理处理器

**优先级**: 20

**功能**: 清理页面中的特定元素，如广告、导航等干扰内容。

**配置参数**:
- `css_selector`: CSS选择器，用于选择要删除的元素

**主要功能**:
- 在页面进入就绪状态时启动
- 删除指定CSS选择器匹配的所有元素
- 统计删除的元素数量

**Prometheus 指标**:
- `element_cleaner_elements_cleaned_total`: 清理的元素总数

**使用示例**:
```python
cleaner = ElementCleaner("ads_cleaner", css_selector=".ads, .sidebar, .header")
```

### 5. ContentFinder - 核心内容发现处理器

**优先级**: 30

**功能**: 提取和优化页面的核心内容，使其适合PDF输出。

**配置参数**:
- `css_selector`: CSS选择器，用于选择核心内容元素
- `target_state`: 目标状态，可选 `"ready"` 或 `"completed"`

**主要功能**:
- 定位核心内容元素
- 从内容元素向上遍历至body，删除所有非核心内容的兄弟节点
- 应用适合A4纸张的CSS样式
- 确保内容在PDF中完整显示

**Prometheus 指标**:
- `content_finder_content_processed_total`: 处理的内容数量
- `content_finder_content_size_bytes`: 处理内容的字节大小

**使用示例**:
```python
finder = ContentFinder("content_finder", css_selector="article.main-content", target_state="ready")
```

### 6. PdfExporter - PDF导出处理器

**优先级**: 40 (最低优先级，最后执行)

**功能**: 将处理后的页面导出为PDF文件。

**配置参数**:
- `output_path`: PDF文件输出路径

**主要功能**:
- 在核心内容处理完成后启动
- 使用A4纸张格式生成PDF
- 包含背景颜色和图片
- 设置适当的页边距

**Prometheus 指标**:
- `pdf_exporter_pdfs_exported_total`: 导出的PDF总数
- `pdf_exporter_export_duration_seconds`: PDF导出耗时
- `pdf_exporter_file_size_bytes`: PDF文件大小

**使用示例**:
```python
exporter = PdfExporter("pdf_exporter", output_path="/tmp/output.pdf")
```

## 完整工作流程示例

以下是一个完整的处理器配置示例，展示如何将这些处理器组合使用：

```python
from pdf_helper.new_processors import (
    PageMonitor, RequestMonitor, LinksFinder, 
    ElementCleaner, ContentFinder, PdfExporter
)

def create_processor_factories():
    """创建处理器工厂函数列表"""
    return [
        # 1. 页面监控 - 优先级0，最先执行
        lambda: PageMonitor("page_monitor", slow_request_timeout=3.0),
        
        # 2. 请求监控 - 优先级1，监控异常请求
        lambda: RequestMonitor("request_monitor", slow_threshold=100, failed_threshold=10),
        
        # 3. 链接发现 - 优先级10，发现更多链接
        lambda: LinksFinder("links_finder", css_selector="a[href]"),
        
        # 4. 清理广告 - 优先级20，清理干扰元素
        lambda: ElementCleaner("ads_cleaner", css_selector=".ads, .sidebar, nav"),
        
        # 5. 核心内容处理 - 优先级30，提取主要内容
        lambda: ContentFinder("content_finder", css_selector="article, .content, main"),
        
        # 6. PDF导出 - 优先级40，最后执行
        lambda: PdfExporter("pdf_exporter", output_path="/tmp/page.pdf")
    ]

# 使用示例
processor_factories = create_processor_factories()
```

## 状态流转

处理器的状态按以下顺序流转：

1. **WAITING** → **READY**: 当检测条件满足时（如页面状态变化）
2. **READY** → **RUNNING**: Manager调用run()方法时
3. **RUNNING** → **COMPLETED**: 处理完成时（由Manager设置）
4. **COMPLETED** → **FINISHED**: 调用finish()方法时

## 错误处理

所有处理器都包含错误处理机制：

- 检测阶段失败会将状态设置为 `CANCELLED`
- 运行阶段失败会抛出异常并将状态设置为 `CANCELLED`
- 失败的处理器不会阻止其他处理器继续执行

## 监控和指标

每个处理器都包含Prometheus指标，用于监控性能和状态：

- **计数器**: 跟踪处理的项目数量
- **直方图**: 测量处理时间和大小
- **标量**: 显示当前状态

可以通过Manager的`get_metrics()`方法获取所有指标数据。

## 性能建议

1. **优先级设置**: 根据依赖关系合理设置处理器优先级
2. **超时配置**: 根据网络环境调整慢请求超时阈值
3. **CSS选择器**: 使用精确的CSS选择器提高匹配效率
4. **错误恢复**: 实现适当的错误恢复机制
5. **资源清理**: 确保所有处理器正确实现finish()方法

## 扩展开发

要开发新的处理器，需要：

1. 继承 `PageProcessor` 基类
2. 实现 `detect()`, `run()`, `finish()` 方法
3. 设置合适的优先级
4. 添加Prometheus指标
5. 编写对应的单元测试
6. 更新文档

参考现有处理器的实现可以快速上手开发新的处理器。
