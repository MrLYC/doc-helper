# LinksFinder 处理器

## 概述

`LinksFinder` 是一个用于自动发现和收集网页链接的处理器。它可以在页面加载过程中的不同阶段执行链接发现，并将新发现的链接自动添加到URL集合中，支持网站的递归爬取。

## 主要特性

### 🔍 智能链接发现
- 使用CSS选择器精确定位链接容器
- 自动提取HTTP/HTTPS链接
- 支持相对链接到绝对链接的转换
- 智能过滤无效和重复链接

### ⏱️ 双重执行时机
- **页面就绪阶段**: 在DOM加载完成后执行首次链接发现
- **页面完成阶段**: 在所有资源加载完成后执行第二次发现
- 确保捕获动态加载的链接内容

### 🎯 高优先级设计
- 固定优先级为10（低优先级）
- 在页面监控完成后执行
- 不干扰关键页面处理流程

### 📊 监控指标
- Prometheus指标集成
- 实时监控发现的链接数量
- 支持性能分析和优化

## 使用方法

### 基本用法

```python
from doc_helper import LinksFinder, URLCollection

# 创建URL集合
url_collection = URLCollection()

# 创建处理器
links_finder = LinksFinder(
    name="links_finder",
    url_collection=url_collection,
    css_selector="body",  # 搜索整个页面
    priority=10
)
```

### 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | 必需 | 处理器名称 |
| `url_collection` | URLCollection | 必需 | URL集合实例 |
| `css_selector` | str | `"body"` | CSS选择器，用于定位链接容器 |
| `priority` | int | `10` | 处理器优先级（固定值） |

### CSS选择器示例

```python
# 搜索整个页面的链接
LinksFinder(css_selector="body")

# 搜索导航菜单中的链接
LinksFinder(css_selector="nav")

# 搜索特定class的容器
LinksFinder(css_selector=".content-area")

# 搜索特定ID的容器
LinksFinder(css_selector="#main-content")

# 搜索文章中的链接
LinksFinder(css_selector="article")

# 搜索多个容器（CSS组合选择器）
LinksFinder(css_selector="nav, .sidebar, footer")
```

## 工作原理

### 检测条件
LinksFinder在以下条件下激活：
1. 页面状态为 `ready` 或 `completed`
2. 当前URL的状态为 `PROCESSING`

### 执行流程

```
1. 检测阶段 → 2. 运行阶段 → 3. 完成阶段
     ↓             ↓            ↓
   状态检查    →  链接发现   →  状态更新
   优先级判断  →  URL验证   →  指标更新
              →  集合添加   →  上下文传递
```

### 链接发现详情

1. **DOM查询**: 使用CSS选择器定位容器元素
2. **链接提取**: 提取容器中所有`<a>`标签的`href`属性
3. **URL处理**: 
   - 转换相对链接为绝对链接
   - 过滤非HTTP/HTTPS协议
   - 移除fragment（#锚点）
4. **去重验证**: 检查URL是否已存在于集合中
5. **批量添加**: 将新链接添加到URL集合

## 集成使用

### 与其他处理器协作

```python
def create_processors():
    """创建处理器工厂函数"""
    
    def create_page_monitor():
        return PageMonitor(name="monitor", page_timeout=30.0)
    
    def create_links_finder():
        return LinksFinder(
            name="links",
            url_collection=url_collection,
            css_selector="main"  # 只搜索主内容区域
        )
    
    return [create_page_monitor, create_links_finder]
```

### 在管理器中使用

```python
from doc_helper import ChromiumManager, PageManagerConfig

# 配置管理器
config = PageManagerConfig(
    max_concurrent_tabs=3,
    page_timeout=30.0,
    headless=True
)

# 创建管理器
manager = ChromiumManager(
    url_collection=url_collection,
    processor_factories=create_processors(),
    config=config
)

# 运行处理
await manager.run()
```

## 性能考虑

### 最佳实践

1. **选择器优化**
   ```python
   # 推荐：具体的选择器
   LinksFinder(css_selector=".article-content")
   
   # 避免：过于宽泛的选择器可能影响性能
   LinksFinder(css_selector="*")
   ```

2. **优先级设置**
   - 使用默认优先级10，确保在页面监控后执行
   - 不要修改优先级，除非有特殊需求

3. **资源管理**
   - LinksFinder会自动清理临时数据
   - URL集合会自动去重，无需手动处理

### 性能指标

通过Prometheus指标监控性能：

```python
# 查看发现的链接数量
links_found_total

# 按CSS选择器分组的统计
links_found_total{css_selector="nav"}
links_found_total{css_selector=".content"}
```

## 错误处理

LinksFinder具有完善的错误处理机制：

### 常见错误场景

1. **CSS选择器无效**
   ```python
   # 错误的选择器会被忽略，不会中断处理
   LinksFinder(css_selector="invalid:::selector")
   ```

2. **页面加载失败**
   ```python
   # 如果页面无法访问，处理器会优雅地跳过
   # 不会影响其他URL的处理
   ```

3. **网络连接问题**
   ```python
   # 超时或连接失败时，会记录日志但不中断流程
   ```

### 日志输出

```python
import logging
logging.basicConfig(level=logging.INFO)

# 典型日志输出
# INFO - LinksFinder发现了5个新链接
# WARNING - CSS选择器 '.nonexistent' 未找到匹配元素
# ERROR - 处理URL时发生错误: 连接超时
```

## 示例场景

### 场景1：新闻网站爬取

```python
# 爬取新闻网站的文章链接
news_finder = LinksFinder(
    name="news_links",
    url_collection=url_collection,
    css_selector=".article-list"  # 文章列表容器
)
```

### 场景2：文档网站导航

```python
# 爬取文档网站的导航链接
doc_finder = LinksFinder(
    name="doc_navigation",
    url_collection=url_collection,
    css_selector="nav.sidebar"  # 侧边栏导航
)
```

### 场景3：产品目录页面

```python
# 爬取电商网站的产品链接
product_finder = LinksFinder(
    name="products",
    url_collection=url_collection,
    css_selector=".product-grid"  # 产品网格容器
)
```

## 高级用法

### 自定义链接过滤

虽然LinksFinder内置了基本的URL过滤，但可以在URL集合层面实现额外过滤：

```python
class FilteredURLCollection(URLCollection):
    def add(self, url: URL) -> bool:
        # 自定义过滤逻辑
        if 'admin' in url.url or 'login' in url.url:
            return False  # 跳过管理和登录页面
        return super().add(url)

# 使用自定义集合
filtered_collection = FilteredURLCollection()
finder = LinksFinder(
    name="filtered_finder",
    url_collection=filtered_collection,
    css_selector="main"
)
```

### 分阶段链接发现

```python
# 可以创建多个LinksFinder处理不同内容区域
def create_multi_finders():
    finders = []
    
    # 导航链接发现器
    finders.append(lambda: LinksFinder(
        name="nav_finder",
        url_collection=url_collection,
        css_selector="nav"
    ))
    
    # 内容链接发现器  
    finders.append(lambda: LinksFinder(
        name="content_finder", 
        url_collection=url_collection,
        css_selector=".main-content"
    ))
    
    return finders
```

## 故障排除

### 常见问题

**Q: 为什么没有发现任何链接？**
A: 检查以下几点：
- CSS选择器是否正确
- 页面是否包含链接
- 网络连接是否正常
- 页面加载是否完成

**Q: 发现了重复的链接怎么办？**
A: URLCollection会自动去重，重复的链接不会被重复添加。

**Q: 如何限制发现的链接数量？**
A: 可以通过自定义URLCollection实现数量限制。

**Q: 处理器运行时间过长怎么办？**
A: 使用更具体的CSS选择器，避免选择过大的DOM区域。

### 调试技巧

1. **启用详细日志**
   ```python
   import logging
   logging.getLogger('doc_helper.processors').setLevel(logging.DEBUG)
   ```

2. **检查页面状态**
   ```python
   # 确保PageMonitor在LinksFinder之前运行
   # 优先级应该是: PageMonitor(0) < LinksFinder(10)
   ```

3. **验证CSS选择器**
   ```python
   # 在浏览器开发者工具中测试选择器
   # document.querySelectorAll("your-selector")
   ```

## API参考

### LinksFinder类

```python
class LinksFinder(PageProcessor):
    def __init__(
        self,
        name: str,
        url_collection: URLCollection,
        css_selector: str = "body",
        priority: int = 10
    ) -> None
```

### 主要方法

- `async def detect(self, context: PageContext) -> bool`: 检测是否应该运行
- `async def run(self, context: PageContext) -> None`: 执行链接发现
- `async def finish(self, context: PageContext) -> None`: 清理和完成处理

### 上下文数据

LinksFinder会在PageContext中设置以下数据：
- `links_found`: 本次发现的链接数量
- `total_links`: URL集合中的总链接数量

## 更新日志

- **v1.0.0**: 初始实现，支持基本链接发现功能
- **v1.1.0**: 添加双重执行时机支持
- **v1.2.0**: 改进URL验证和去重逻辑
- **v1.3.0**: 添加Prometheus指标集成

## 相关文档

- [PageMonitor 处理器文档](./page_monitor.md)
- [URLCollection 使用指南](./url_collection.md)
- [ChromiumManager 管理器文档](./chromium_manager.md)