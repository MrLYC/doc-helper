# PageMonitor 处理器文档

## 概述

PageMonitor 是一个页面监控处理器，用于监控页面加载状态、检测慢请求和失败请求。它是整个页面处理流水线中优先级最高的处理器（priority=0），负责页面状态的实时监控和请求性能分析。

## 核心功能

### 1. 页面状态监控

PageMonitor 监控页面的加载状态变化：

- **loading**: 页面正在加载中
- **ready**: 页面 DOM 加载完成（load 事件触发）
- **completed**: 页面网络空闲（networkidle 状态）

状态变化会实时反映在 PageContext 的 data 字段中，其他处理器可以基于这些状态进行决策。

### 2. 慢请求检测

自动检测加载时间超过阈值的请求：

- 慢请求超时 = 页面超时时间 / 10（默认）
- 检测到慢请求时会记录日志并更新统计计数器
- URL 会被清理（移除查询字符串）以便分组统计
- 支持 Prometheus 指标收集

### 3. 失败请求检测

监控网络请求失败情况：

- 连接失败（如 net::ERR_CONNECTION_REFUSED）
- 超时失败
- 其他网络错误
- 失败原因会被分类记录到 Prometheus 指标中

### 4. Prometheus 指标

PageMonitor 提供以下监控指标：

```python
# 慢请求计数器
page_monitor_slow_requests_total{domain, path}

# 失败请求计数器  
page_monitor_failed_requests_total{domain, path, failure_type}

# 页面状态变化计数器
page_monitor_state_changes_total{state}

# 页面监控处理时间分布
page_monitor_processing_seconds

# 当前活跃页面数量
page_monitor_active_pages
```

## 使用方法

### 基本用法

```python
from doc_helper import PageMonitor, PageContext, URL

# 创建页面监控器
monitor = PageMonitor(
    name="page_monitor",
    page_timeout=30.0  # 页面超时30秒，慢请求超时3秒
)

# 在页面管理器中使用
def create_page_monitor():
    return PageMonitor("monitor", page_timeout=60.0)

processor_factories = [create_page_monitor]
```

### 参数配置

- `name`: 处理器名称
- `page_timeout`: 页面加载超时时间（秒），默认60秒
- `priority`: 优先级，固定为0（最高优先级）

慢请求超时时间自动计算为页面超时的1/10。

### 上下文数据

PageMonitor 会在 PageContext.data 中设置以下数据：

```python
{
    "page_state": "loading|ready|completed",
    "slow_requests": {
        "https://example.com/api": 2,  # URL -> 慢请求次数
        # ...
    },
    "failed_requests": {
        "https://example.com/static": 1,  # URL -> 失败次数
        # ...
    }
}
```

## 工作流程

### 1. 检测阶段 (detect)

- 如果页面存在且未开始监控 → 返回 READY
- 如果已开始监控但未完成 → 返回 RUNNING  
- 如果监控完成 → 返回 COMPLETED

### 2. 运行阶段 (run)

**初始化**（首次运行）：
- 设置页面状态为 "loading"
- 初始化请求计数器
- 设置页面事件监听器
- 更新 Prometheus 指标

**状态检查**（后续运行）：
- 检查 document.readyState
- 如果为 "complete" 且当前为 "loading" → 转换为 "ready"
- 如果为 "ready" 状态 → 检查网络空闲
- 如果网络空闲 → 转换为 "completed"

**完成条件**：
- 页面进入 "completed" 状态
- 没有更高优先级的处理器在运行

### 3. 清理阶段 (finish)

- 关闭页面
- 清理请求时间记录
- 更新 Prometheus 指标
- 记录统计信息

## 事件处理

### 请求事件

```python
# 请求开始
async def _on_request(self, request: Request):
    # 记录请求开始时间
    
# 请求响应
async def _on_response(self, response: Response):
    # 计算请求耗时
    # 检测慢请求
    
# 请求失败
async def _on_request_failed(self, request: Request):
    # 记录失败信息
    # 更新失败计数器
```

### 页面事件

```python
# 页面 load 事件
async def _on_load(self):
    # 状态转换: loading -> ready
    
# DOM 内容加载完成
async def _on_dom_content_loaded(self):
    # 记录日志
```

## 最佳实践

### 1. 超时设置

- 根据目标网站性能合理设置页面超时
- 慢请求超时自动为页面超时的1/10
- 考虑网络环境和服务器响应时间

### 2. 监控集成

- 配置 Prometheus 收集指标
- 设置慢请求和失败请求的告警阈值
- 监控页面处理性能趋势

### 3. 日志分析

- 关注慢请求日志，优化页面性能
- 分析失败请求模式，识别网络问题
- 监控页面状态转换时间

### 4. 与其他处理器协作

- PageMonitor 优先级最高，先执行
- 其他处理器可以基于 page_state 决定执行时机
- 利用请求统计信息进行性能分析

## 注意事项

1. **优先级固定**: PageMonitor 的优先级固定为0，确保最先执行
2. **资源清理**: finish 方法会自动关闭页面，其他处理器需要注意
3. **事件监听**: Playwright 的事件监听器在页面关闭时自动清理
4. **指标收集**: 确保 Prometheus 客户端正确配置
5. **异常处理**: 网络异常和页面错误都会被妥善处理

## 扩展性

PageMonitor 设计为可扩展的：

- 可以添加新的请求检测规则
- 支持自定义超时阈值
- 可以扩展 Prometheus 指标
- 支持自定义事件处理器

通过合理配置和监控，PageMonitor 能够为页面处理流水线提供强大的监控和性能分析能力。