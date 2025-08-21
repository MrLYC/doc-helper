# ElementCleaner 处理器

## 概述

`ElementCleaner` 是一个专门用于清理网页中不需要元素的处理器。它可以根据CSS选择器精确定位并删除广告、弹窗、导航栏等元素，为PDF生成、内容提取或页面截图做准备。

## 主要特性

### 🎯 精确元素定位
- 使用强大的CSS选择器语法定位目标元素
- 支持复杂的选择器组合和高级语法
- 可以同时清理多种类型的元素

### 🔧 智能清理机制
- 在页面就绪状态自动启动
- 批量删除匹配元素，提高效率
- 基于删除结果智能判断成功或失败

### 📊 详细监控指标
- Prometheus指标集成
- 实时监控删除的元素数量
- 支持按选择器分组的成功率统计

### 🛡️ 健壮错误处理
- 优雅处理单个元素删除失败
- 部分成功也认为是完成状态
- 完整的异常捕获和日志记录

## 使用方法

### 基本用法

```python
from pdf_helper import ElementCleaner

# 创建基本的元素清理器
cleaner = ElementCleaner(
    name="ad_cleaner",
    css_selector="*[id*='ad'], *[class*='popup']",  # 清理广告和弹窗
    priority=20
)
```

### 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | 必需 | 处理器名称 |
| `css_selector` | str | `"*[id*='ad'], *[class*='popup']"` | CSS选择器，用于定位要删除的元素 |
| `priority` | int | `20` | 处理器优先级（固定值） |

### 常用CSS选择器示例

#### 基础选择器
```python
# 按ID选择
ElementCleaner(css_selector="#advertisement")

# 按类名选择
ElementCleaner(css_selector=".popup, .modal")

# 按标签选择
ElementCleaner(css_selector="aside, nav")

# 按属性选择
ElementCleaner(css_selector="*[data-type='ad']")
```

#### 高级选择器
```python
# 属性包含选择器
ElementCleaner(css_selector="*[class*='banner'], *[id*='popup']")

# 子元素选择器
ElementCleaner(css_selector=".sidebar > *, .footer > .social")

# 否定选择器
ElementCleaner(css_selector="div:not(.content):not(.main)")

# 伪类选择器
ElementCleaner(css_selector="div:empty, img[src='']")
```

#### 实用组合选择器
```python
# 清理广告相关
ad_selector = ", ".join([
    "*[id*='ad']",              # 包含'ad'的ID
    "*[class*='advertisement']", # 广告类名
    "*[class*='banner']",       # 横幅广告
    "iframe[src*='ads']",       # 广告iframe
    ".ad, .ads"                 # 直接广告类
])

# 清理弹窗相关
popup_selector = ", ".join([
    "*[class*='popup']",        # 弹窗类名
    "*[class*='modal']",        # 模态框
    "#popup, #modal",           # 弹窗ID
    ".overlay, .backdrop"       # 遮罩层
])

# 清理导航和辅助元素
ui_selector = ", ".join([
    "nav, .navigation",         # 导航菜单
    "footer, .footer",          # 页脚
    ".sidebar, aside",          # 侧边栏
    ".breadcrumb, .pagination"  # 面包屑和分页
])
```

## 工作原理

### 检测条件
ElementCleaner在以下条件下激活：
1. 页面状态为 `ready` 或 `completed`
2. 当前URL的状态为 `PROCESSING`

### 执行流程

```
1. 检测阶段 → 2. 运行阶段 → 3. 完成阶段
     ↓             ↓            ↓
   状态检查    →  元素查找   →  状态更新
   页面就绪判断 →  批量删除   →  指标更新
              →  结果统计   →  上下文清理
```

### 清理详情

1. **元素查找**: 使用CSS选择器在DOM中查找匹配元素
2. **批量删除**: 
   - 遍历所有匹配元素
   - 调用JavaScript的`element.remove()`方法
   - 统计删除成功和失败的数量
3. **结果判断**:
   - 有元素成功删除 → `COMPLETED`
   - 找到元素但全部删除失败 → `FAILED`
   - 未找到匹配元素 → `COMPLETED`

## 集成使用

### 与其他处理器协作

```python
def create_processors():
    """创建处理器工厂函数"""
    
    def create_page_monitor():
        return PageMonitor(name="monitor", page_timeout=30.0)
    
    def create_element_cleaner():
        return ElementCleaner(
            name="cleaner",
            css_selector=".advertisement, .popup, .banner"
        )
    
    def create_content_extractor():
        return ContentExtractProcessor(name="extractor")
    
    return [
        create_page_monitor,      # 优先级 0
        create_element_cleaner,   # 优先级 20  
        create_content_extractor  # 优先级 30
    ]
```

### 在管理器中使用

```python
from pdf_helper import ChromiumManager, PageManagerConfig

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

## 实用场景

### 场景1：PDF生成前清理

```python
# 为PDF生成清理不需要的视觉元素
pdf_cleaner = ElementCleaner(
    name="pdf_prep",
    css_selector=", ".join([
        "nav, .navigation",          # 导航菜单
        "footer, .footer",           # 页脚
        ".sidebar, aside",           # 侧边栏
        ".advertisement, .ad",       # 广告
        ".social-share, .comments",  # 社交和评论
        ".pagination, .breadcrumb"   # 分页和面包屑
    ])
)
```

### 场景2：内容提取前清理

```python
# 为内容提取清理噪音元素
content_cleaner = ElementCleaner(
    name="content_prep", 
    css_selector=", ".join([
        "*[id*='ad'], *[class*='banner']",  # 广告相关
        ".popup, .modal, .overlay",         # 弹窗相关
        ".related-articles, .suggestions",  # 推荐内容
        ".newsletter-signup, .subscribe"    # 订阅表单
    ])
)
```

### 场景3：移动端适配清理

```python
# 为移动端优化清理桌面专用元素
mobile_cleaner = ElementCleaner(
    name="mobile_prep",
    css_selector=", ".join([
        ".desktop-only, .hide-mobile",    # 桌面专用
        ".large-banner, .wide-sidebar",   # 大尺寸元素
        ".hover-menu, .dropdown",         # 悬停相关
        ".mouse-only, .right-click-menu"  # 鼠标专用
    ])
)
```

### 场景4：可访问性优化

```python
# 清理影响可访问性的元素
a11y_cleaner = ElementCleaner(
    name="accessibility_prep",
    css_selector=", ".join([
        "*[style*='position:fixed']",        # 固定定位元素
        ".auto-play-video, .background-video", # 自动播放视频
        ".flash-animation, .blinking",        # 闪烁动画
        ".sound-notification, .audio-ad"     # 声音相关
    ])
)
```

## 性能优化

### 最佳实践

1. **选择器优化**
   ```python
   # 推荐：具体的选择器
   ElementCleaner(css_selector=".header .advertisement")
   
   # 避免：过于宽泛的选择器
   ElementCleaner(css_selector="*")  # 会匹配所有元素
   ```

2. **批量处理**
   ```python
   # 推荐：组合选择器一次删除多种元素
   ElementCleaner(css_selector=".ad, .popup, .banner")
   
   # 避免：创建多个处理器分别删除
   # 这样会增加不必要的开销
   ```

3. **优先级设置**
   - 使用默认优先级20，确保在页面监控后执行
   - 在内容提取或PDF生成前执行

### 性能指标

通过Prometheus指标监控性能：

```python
# 查看删除的元素数量
elements_removed_total

# 按CSS选择器分组的统计
elements_removed_total{css_selector=".advertisement", success="true"}
elements_removed_total{css_selector=".popup", success="false"}
```

## 错误处理

### 常见错误场景

1. **CSS选择器语法错误**
   ```python
   # 错误的选择器会导致查询失败
   ElementCleaner(css_selector="div[class=invalid")  # 缺少闭合括号
   ```

2. **元素删除失败**
   ```python
   # 某些元素可能由于JavaScript保护无法删除
   # ElementCleaner会记录警告但继续处理其他元素
   ```

3. **页面访问权限**
   ```python
   # 跨域或权限限制可能影响元素操作
   # 会记录错误并标记为失败状态
   ```

### 调试技巧

1. **验证CSS选择器**
   ```javascript
   // 在浏览器控制台中测试选择器
   document.querySelectorAll("your-selector");
   ```

2. **启用详细日志**
   ```python
   import logging
   logging.getLogger('pdf_helper.processors').setLevel(logging.DEBUG)
   ```

3. **检查元素权限**
   ```javascript
   // 在控制台检查元素是否可以删除
   const elements = document.querySelectorAll(".ad");
   elements.forEach(el => {
       try {
           el.remove();
           console.log("删除成功", el);
       } catch (e) {
           console.error("删除失败", el, e);
       }
   });
   ```

## 高级用法

### 条件清理

虽然ElementCleaner本身不支持条件逻辑，但可以通过自定义处理器实现：

```python
class ConditionalElementCleaner(ElementCleaner):
    def __init__(self, name: str, css_selector: str, condition_check: callable):
        super().__init__(name, css_selector)
        self.condition_check = condition_check
    
    async def detect(self, context: PageContext) -> bool:
        # 首先检查基本条件
        if not await super().detect(context):
            return False
        
        # 然后检查自定义条件
        return await self.condition_check(context)

# 使用示例：只在页面包含特定内容时清理
async def has_ads(context):
    page = context.page
    ads = await page.query_selector_all(".advertisement")
    return len(ads) > 0

conditional_cleaner = ConditionalElementCleaner(
    name="conditional_cleaner",
    css_selector=".advertisement",
    condition_check=has_ads
)
```

### 自定义清理逻辑

```python
class AdvancedElementCleaner(ElementCleaner):
    async def run(self, context: PageContext) -> None:
        """扩展的清理逻辑"""
        # 先执行基本清理
        await super().run(context)
        
        # 添加自定义处理
        page = context.page
        if page:
            # 例如：清理空的容器
            await page.evaluate("""
                document.querySelectorAll('div:empty, span:empty').forEach(el => {
                    if (el.children.length === 0 && el.textContent.trim() === '') {
                        el.remove();
                    }
                });
            """)
```

## API参考

### ElementCleaner类

```python
class ElementCleaner(PageProcessor):
    def __init__(
        self,
        name: str,
        css_selector: str = "*[id*='ad'], *[class*='popup']",
        priority: int = 20
    ) -> None
```

### 主要方法

- `async def detect(self, context: PageContext) -> bool`: 检测是否应该运行
- `async def run(self, context: PageContext) -> None`: 执行元素清理
- `async def finish(self, context: PageContext) -> None`: 清理和完成处理

### 上下文数据

ElementCleaner会在PageContext中设置以下数据：
- `elements_removed`: 成功删除的元素数量
- `css_selector_used`: 使用的CSS选择器

## 故障排除

### 常见问题

**Q: 为什么某些元素没有被删除？**
A: 检查以下几点：
- CSS选择器是否正确
- 元素是否受JavaScript保护
- 是否存在跨域限制
- 元素是否在iframe中

**Q: 处理器状态为什么是FAILED？**
A: 可能的原因：
- 找到元素但全部删除失败
- 页面访问权限问题
- CSS选择器语法错误

**Q: 如何确认选择器是否正确？**
A: 在浏览器开发者工具中测试：
```javascript
document.querySelectorAll("your-selector")
```

**Q: 删除元素会影响页面功能吗？**
A: ElementCleaner只删除DOM元素，不会：
- 影响已加载的JavaScript变量
- 破坏现有的事件监听器（除非绑定到被删除元素）
- 影响CSS样式定义

### 最佳实践建议

1. **渐进式清理**: 先用宽泛的选择器测试，再逐步细化
2. **备份策略**: 在生产环境使用前充分测试选择器
3. **监控指标**: 定期检查删除成功率和元素数量
4. **文档记录**: 记录每个选择器的用途和目标元素

## 更新日志

- **v1.0.0**: 初始实现，支持基本元素清理功能
- **v1.1.0**: 添加高级CSS选择器支持
- **v1.2.0**: 改进错误处理和部分失败逻辑
- **v1.3.0**: 添加Prometheus指标集成

## 相关文档

- [PageMonitor 处理器文档](./page_monitor.md)
- [CSS选择器语法参考](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Selectors)
- [ChromiumManager 管理器文档](./chromium_manager.md)