# 页面截图API功能

## 概述

新增的截图API功能允许用户通过HTTP接口获取当前正在处理的页面的实时截图。这对于监控页面处理进度、调试页面内容和可视化爬取过程非常有用。

## API接口

### 1. 获取活跃页面列表

**端点**: `GET /pages`

**描述**: 获取所有当前活跃页面的信息列表。

**响应示例**:
```json
{
  "status": "success",
  "total_pages": 2,
  "pages": [
    {
      "slot": 0,
      "url_id": "page-001",
      "url": "https://example.com/page1",
      "title": "示例页面1",
      "start_time": 1692345678.123,
      "processors": ["content_finder", "pdf_exporter"]
    },
    {
      "slot": 1,
      "url_id": "page-002", 
      "url": "https://example.com/page2",
      "title": "示例页面2",
      "start_time": 1692345679.456,
      "processors": ["links_finder"]
    }
  ]
}
```

**字段说明**:
- `slot`: 页面槽位号（从0开始）
- `url_id`: 页面的唯一标识符
- `url`: 页面URL地址
- `title`: 页面标题（如果可获取）
- `start_time`: 页面处理开始时间（Unix时间戳）
- `processors`: 当前正在运行的处理器列表

### 2. 获取页面截图

**端点**: `GET /snapshot/{slot}`

**描述**: 获取指定槽位页面的实时截图。

**参数**:
- `slot` (路径参数): 页面槽位号，从0开始

**响应**:
- **成功 (200)**: 返回PNG格式的截图数据
- **未找到 (404)**: 指定槽位不存在或截图失败
- **服务器错误 (500)**: 截图过程中发生错误
- **服务不可用 (503)**: Manager未初始化

**响应头**:
```
Content-Type: image/png
Content-Disposition: inline; filename=page_snapshot_slot_{slot}.png
Cache-Control: no-cache, no-store, must-revalidate
```

## 使用示例

### 命令行工具

```bash
# 启动服务器
python -m doc_helper --server

# 在另一个终端启动页面处理
python -m doc_helper https://example.com --find-links

# 获取页面列表
curl http://localhost:8000/pages

# 获取槽位0的截图
curl http://localhost:8000/snapshot/0 -o screenshot.png
```

### Python代码示例

```python
import aiohttp
import asyncio

async def get_page_screenshot(slot):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://localhost:8000/snapshot/{slot}") as resp:
            if resp.status == 200:
                screenshot_data = await resp.read()
                with open(f"page_{slot}.png", "wb") as f:
                    f.write(screenshot_data)
                print(f"截图已保存到 page_{slot}.png")
            else:
                print(f"获取截图失败: {resp.status}")

# 运行示例
asyncio.run(get_page_screenshot(0))
```

### JavaScript示例

```javascript
// 获取页面列表
async function getActivePages() {
    const response = await fetch('http://localhost:8000/pages');
    const data = await response.json();
    console.log('活跃页面:', data.pages);
    return data.pages;
}

// 获取页面截图
async function getPageScreenshot(slot) {
    const response = await fetch(`http://localhost:8000/snapshot/${slot}`);
    if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        
        // 创建下载链接
        const a = document.createElement('a');
        a.href = url;
        a.download = `page_snapshot_slot_${slot}.png`;
        a.click();
        
        URL.revokeObjectURL(url);
    } else {
        console.error('获取截图失败:', response.status);
    }
}
```

## 技术实现

### ChromiumManager增强

在 `ChromiumManager` 类中新增了两个方法：

1. **`get_active_pages_info()`**: 获取所有活跃页面的信息
2. **`get_page_screenshot(slot)`**: 获取指定槽位页面的截图

### 截图功能特性

- **全页截图**: 使用 `full_page=True` 获取完整页面内容
- **PNG格式**: 输出标准PNG格式图片
- **超时控制**: 5秒截图超时限制
- **错误处理**: 完善的异常处理和日志记录
- **缓存控制**: 设置适当的HTTP缓存头避免缓存

### 安全考虑

- **输入验证**: 验证槽位号的有效性
- **错误隔离**: 单个页面截图失败不影响其他页面
- **资源限制**: 截图操作有超时限制
- **权限控制**: 通过服务器配置控制访问权限

## 常见问题

### Q: 截图是空白的或不完整？
A: 可能的原因：
- 页面还在加载中
- 页面内容需要JavaScript渲染
- 页面有延迟加载的内容

建议等待页面完全加载后再截图。

### Q: 获取截图时返回404错误？
A: 可能的原因：
- 指定的槽位号不存在
- 页面已经处理完成并关闭
- Manager未正确初始化

请先检查 `/pages` 接口确认当前活跃的页面槽位。

### Q: 截图文件很大？
A: PNG格式截图可能较大，特别是高分辨率页面。可以考虑：
- 调整浏览器窗口大小
- 使用JPEG格式（需要修改代码）
- 对图片进行压缩

### Q: 并发获取多个截图会有问题吗？
A: 目前的实现支持并发截图，但为了性能考虑，建议控制并发数量。

## 演示脚本

项目包含了一个完整的演示脚本 `examples/snapshot_demo.py`，展示了如何使用截图API：

```bash
# 运行演示
python examples/snapshot_demo.py
```

演示脚本会：
1. 检查服务器状态
2. 获取活跃页面列表
3. 获取第一个页面的截图
4. 测试错误处理

## 更新日志

### v1.0.0 (2025-01-21)
- ✅ 新增 `/pages` API获取活跃页面列表
- ✅ 新增 `/snapshot/{slot}` API获取页面截图
- ✅ 支持全页PNG截图
- ✅ 完善的错误处理和日志记录
- ✅ 添加截图API单元测试
- ✅ 提供演示脚本和文档