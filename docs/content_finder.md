# ContentFinder 处理器

ContentFinder 是一个页面内容查找和清理处理器，专门用于保留核心内容并清理其他兄弟节点，使页面内容适合 A4 纸尺寸的 PDF 生成。

## 功能特性

### 核心功能
- **内容定位**: 使用 CSS 选择器精确定位核心内容区域
- **智能清理**: 从目标元素向上遍历到 body，删除所有非核心内容的兄弟节点
- **布局优化**: 优化页面布局使其适合 A4 纸尺寸
- **状态控制**: 支持多种页面状态触发条件

### 技术特点
- 优先级：30（在页面基本处理完成后执行）
- 支持复杂 CSS 选择器
- JavaScript 驱动的 DOM 操作
- Prometheus 指标集成
- 完整的错误处理机制

## 使用方法

### 基本用法

```python
from doc_helper import ContentFinder, ChromiumManager, PageMonitor

# 创建内容查找器
content_finder = ContentFinder(
    css_selector="main, article, .content",  # 核心内容选择器
    target_states=["ready", "completed"],    # 目标状态
    priority=30                              # 优先级
)

# 使用管理器处理页面
async with ChromiumManager() as manager:
    manager.add_processor(PageMonitor("monitor", priority=0))
    manager.add_processor(content_finder)
    
    # 处理URL
    results = await manager.process_urls(url_collection)
```

### 参数详解

#### `css_selector` (必需)
用于查找核心内容的 CSS 选择器。

**常用选择器示例:**
```python
# 主要内容区域
"main, [role='main'], .main-content"

# 文章内容
"article, .article, .post-content"

# 文档内容
".documentation, .docs-content"

# 复合选择器
"main article, .content article"

# 特定网站
"#content, #main-content"
```

#### `target_states` (可选)
触发处理器的页面状态列表，默认为 `["ready", "completed"]`。

**状态选项:**
- `"ready"`: 页面基本就绪，DOM 构建完成
- `"completed"`: 页面完全加载，包括所有资源

**配置示例:**
```python
# 快速启动 - 页面就绪后立即处理
ContentFinder(".content", target_states=["ready"])

# 完全加载 - 等待页面完全加载
ContentFinder(".content", target_states=["completed"])

# 灵活模式 - 两种状态都可以触发
ContentFinder(".content", target_states=["ready", "completed"])
```

#### `priority` (可选)
处理器优先级，默认为 30。数值越小优先级越高。

## 工作原理

### 检测阶段 (detect)
1. **状态检查**: 验证页面状态是否匹配目标状态
2. **元素查找**: 使用 CSS 选择器查找核心内容元素
3. **存在性验证**: 如果找不到目标元素，标记为取消状态

### 执行阶段 (run)
1. **元素定位**: 重新查找目标内容元素
2. **向上遍历**: 从目标元素开始向上遍历到 body 元素
3. **兄弟清理**: 在每一层删除除当前路径外的所有兄弟节点
4. **统计记录**: 记录删除的元素数量和遍历层数

### JavaScript 清理逻辑
```javascript
(selector) => {
    const targetElement = document.querySelector(selector);
    if (!targetElement) return 0;
    
    let totalRemoved = 0;
    let currentElement = targetElement;
    let level = 0;
    
    // 向上遍历直到body元素
    while (currentElement && currentElement.tagName.toLowerCase() !== 'body') {
        const parent = currentElement.parentElement;
        if (!parent) break;
        
        // 获取所有兄弟节点
        const siblings = Array.from(parent.children);
        
        // 删除除当前元素外的所有兄弟节点
        for (const sibling of siblings) {
            if (sibling !== currentElement) {
                sibling.remove();
                totalRemoved++;
            }
        }
        
        // 移动到父元素继续向上
        currentElement = parent;
        level++;
    }
    
    return { totalRemoved, level };
}
```

## 使用场景

### 1. PDF 生成优化
清理页面布局，使内容适合 A4 纸尺寸：
```python
# 为PDF生成优化页面
pdf_optimizer = ContentFinder(
    css_selector="main, article, .content",
    target_states=["completed"],
    priority=30
)
```

### 2. 内容抓取预处理
在内容提取前清理页面噪音：
```python
# 内容抓取前清理
content_cleaner = ContentFinder(
    css_selector=".post-content, .article-body",
    target_states=["ready"],
    priority=25  # 在内容提取器之前运行
)
```

### 3. 阅读模式
创建专注的阅读体验：
```python
# 阅读模式优化
reading_optimizer = ContentFinder(
    css_selector="article, .reader-content",
    target_states=["ready", "completed"],
    priority=30
)
```

### 4. 特定网站优化
针对特定网站的布局优化：
```python
# 针对特定网站
site_specific = ContentFinder(
    css_selector="#main-content .article-wrapper",
    target_states=["completed"],
    priority=30
)
```

## 最佳实践

### 1. 选择器设计
```python
# ✅ 好的选择器 - 多个备选方案
"main, article, .content, [role='main']"

# ✅ 特定但灵活
".post-content, .article-body, .entry-content"

# ❌ 避免过于具体的选择器
"#very-specific-id .nested .deep .content"
```

### 2. 状态配置
```python
# ✅ 对于静态内容 - 快速启动
target_states=["ready"]

# ✅ 对于动态内容 - 等待完全加载
target_states=["completed"]

# ✅ 通用配置 - 灵活处理
target_states=["ready", "completed"]
```

### 3. 优先级设置
```python
# 典型处理器优先级安排：
PageMonitor(priority=0)           # 最高优先级
ElementCleaner(priority=20)       # 元素清理
ContentFinder(priority=30)        # 内容查找
PDFGenerator(priority=40)         # PDF生成
```

### 4. 错误处理
```python
# 在处理器链中添加后备处理器
primary_finder = ContentFinder(
    css_selector="main, article",
    target_states=["ready"],
    priority=30
)

fallback_finder = ContentFinder(
    css_selector="body",  # 最后的后备选择器
    target_states=["completed"],
    priority=35
)
```

## 监控指标

ContentFinder 提供以下 Prometheus 指标：

### `content_finder_siblings_removed_total`
计数器，记录删除的兄弟节点总数
- 标签: `css_selector` (CSS选择器), `level` (遍历层数)

### `content_finder_processing_seconds`
直方图，记录处理时间分布
- 桶: [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]

### `content_finder_elements_found_total`
计数器，记录元素查找结果
- 标签: `css_selector` (CSS选择器), `found` (found/not_found/initialized)

## 故障排除

### 常见问题

#### 1. 目标元素未找到
```
ContentFinder未找到目标元素，放弃执行
```
**解决方案:**
- 检查 CSS 选择器是否正确
- 确认目标元素在页面中存在
- 尝试更通用的选择器

#### 2. 页面状态不匹配
```
页面状态不符合目标状态要求
```
**解决方案:**
- 调整 `target_states` 配置
- 检查页面加载时机
- 增加 PageMonitor 确保页面状态正确

#### 3. 处理器被跳过
```
ContentFinder 未执行
```
**解决方案:**
- 检查优先级设置
- 确认依赖的处理器已完成
- 验证页面状态转换

### 调试技巧

#### 1. 启用详细日志
```python
import logging
logging.getLogger('doc_helper.processors').setLevel(logging.DEBUG)
```

#### 2. 测试选择器
在浏览器控制台中测试：
```javascript
// 测试选择器是否能找到元素
document.querySelector("main, article, .content")

// 查看元素层次结构
let element = document.querySelector(".content");
while (element && element.tagName !== 'BODY') {
    console.log(element.tagName, element.className);
    element = element.parentElement;
}
```

#### 3. 监控指标
使用 Prometheus 指标监控处理效果：
```python
# 查看删除的兄弟节点数量
content_finder_siblings_removed_total

# 查看处理时间
content_finder_processing_seconds
```

## 性能优化

### 1. 选择器优化
- 使用简单、高效的选择器
- 避免过度复杂的 CSS 表达式
- 优先使用 ID 和类名选择器

### 2. 状态配置
- 对于静态内容使用 "ready" 状态
- 仅在必要时等待 "completed" 状态

### 3. 批处理
- 合理设置处理器优先级
- 避免重复的 DOM 操作

## 相关处理器

- **PageMonitor**: 监控页面状态，为 ContentFinder 提供正确的触发时机
- **ElementCleaner**: 清理特定元素，可以与 ContentFinder 配合使用
- **PDFGenerateProcessor**: PDF 生成，通常在 ContentFinder 之后执行

## 示例代码

完整的使用示例请参考：
- `examples/content_finder_demo.py` - 基本使用演示
- `tests/test_content_finder.py` - 单元测试示例