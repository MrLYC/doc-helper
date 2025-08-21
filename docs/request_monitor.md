# RequestMonitor 处理器文档

## 概述

RequestMonitor 是一个请求监控处理器，用于监控特殊请求并自动屏蔽有问题的URL。它基于 PageMonitor 收集的请求统计信息，智能识别慢请求和失败请求过多的URL，并将其添加到URL集合中标记为已屏蔽，从而避免后续访问这些问题URL。

## 核心功能

### 1. 智能启动时机

RequestMonitor 在页面进入就绪状态时自动启动：

- **页面就绪** (ready): DOM加载完成，开始监控分析
- **页面完成** (completed): 网络空闲状态，执行最终检查

### 2. 慢请求监控

基于 PageMonitor 收集的慢请求统计：

- 监控单个URL的慢请求计数器
- 当慢请求次数超过阈值时自动屏蔽
- 默认阈值: 100次慢请求

### 3. 失败请求监控

基于 PageMonitor 收集的失败请求统计：

- 监控单个URL的失败请求计数器
- 当失败请求次数超过阈值时自动屏蔽
- 默认阈值: 10次失败请求

### 4. 自动URL屏蔽

将问题URL添加到URL集合并标记状态：

- 生成唯一ID标识屏蔽的URL
- 设置分类为 `blocked_by_request_monitor`
- 状态标记为 `URLStatus.BLOCKED`
- 记录屏蔽原因和时间戳

### 5. Prometheus 指标

提供详细的监控指标：

```python
# 被屏蔽的URL计数器
request_monitor_blocked_urls_total{reason, domain, path}

# 请求监控处理时间分布
request_monitor_processing_seconds

# 当前活跃的请求监控数量
request_monitor_active_monitors
```

## 使用方法

### 基本用法

```python
from doc_helper import RequestMonitor, URLCollection

# 创建URL集合（必须传递给RequestMonitor）
url_collection = URLCollection()

# 创建请求监控器
monitor = RequestMonitor(
    name="request_monitor",
    url_collection=url_collection,
    slow_request_threshold=50,   # 慢请求阈值
    failed_request_threshold=5   # 失败请求阈值
)

# 在页面管理器中使用
def create_request_monitor():
    return RequestMonitor(
        "request_monitor", 
        url_collection=shared_url_collection,
        slow_request_threshold=100,
        failed_request_threshold=10
    )

processor_factories = [create_page_monitor, create_request_monitor]
```

### 参数配置

- `name`: 处理器名称
- `url_collection`: URL集合对象，用于添加屏蔽的URL
- `slow_request_threshold`: 慢请求数量阈值，默认100
- `failed_request_threshold`: 失败请求数量阈值，默认10
- `priority`: 优先级，固定为1

### 与其他处理器协作

RequestMonitor 必须与 PageMonitor 配合使用：

```python
def create_page_monitor():
    return PageMonitor("page_monitor", page_timeout=60.0)

def create_request_monitor():
    return RequestMonitor(
        "request_monitor",
        url_collection=url_collection,
        slow_request_threshold=50,
        failed_request_threshold=5
    )

# 优先级顺序: PageMonitor(0) -> RequestMonitor(1) -> 其他处理器
processor_factories = [create_page_monitor, create_request_monitor, ...]
```

## 工作流程

### 1. 检测阶段 (detect)

**启动条件**：
- 页面状态为 "ready" 或 "completed"
- 尚未开始监控

**运行条件**：
- 已开始监控但页面未完成

**完成条件**：
- 页面状态为 "completed"
- 无更高优先级(priority < 1)的处理器在运行

### 2. 运行阶段 (run)

**初始化**（首次运行）：
- 设置监控开始标志
- 初始化上下文数据
- 更新 Prometheus 指标

**监控检查**（后续运行）：
- 检查慢请求统计数据
- 检查失败请求统计数据
- 对超过阈值的URL执行屏蔽操作

**屏蔽逻辑**：
```python
# 慢请求检查
for url, count in slow_requests.items():
    if count >= slow_request_threshold:
        block_url(url, f"慢请求次数过多({count}>={threshold})")

# 失败请求检查  
for url, count in failed_requests.items():
    if count >= failed_request_threshold:
        block_url(url, f"失败请求次数过多({count}>={threshold})")
```

### 3. 清理阶段 (finish)

- 更新 Prometheus 指标
- 记录统计信息
- 设置处理器状态为 FINISHED

## 上下文数据

### 输入数据（来自PageMonitor）

```python
{
    "page_state": "ready|completed",
    "slow_requests": {
        "https://example.com/api": 15,  # URL -> 慢请求次数
        # ...
    },
    "failed_requests": {
        "https://example.com/static": 5,  # URL -> 失败次数
        # ...
    }
}
```

### 输出数据（RequestMonitor添加）

```python
{
    "blocked_urls": [
        {
            "url": "https://example.com/problematic",
            "reason": "慢请求次数过多(120>=100)",
            "blocked_at": 1692345678.123
        },
        # ...
    ]
}
```

## 屏蔽机制详解

### URL屏蔽流程

1. **阈值检查**: 比较请求计数与配置的阈值
2. **URL清理**: 移除查询字符串进行统一处理
3. **创建屏蔽记录**: 生成新的URL对象
4. **添加到集合**: 将URL添加到URLCollection
5. **记录日志**: 输出警告日志
6. **更新指标**: 增加Prometheus计数器
7. **上下文记录**: 在PageContext中记录屏蔽信息

### 屏蔽URL属性

```python
blocked_url = URL(
    id=f"blocked_{timestamp}_{hash}",           # 唯一标识符
    url="https://example.com/api/data",         # 清理后的URL
    category="blocked_by_request_monitor",      # 分类标识
    status=URLStatus.BLOCKED                    # 屏蔽状态
)
```

### 去重机制

- URLCollection 会自动去重相同的URL
- 相同URL不会被重复添加到集合中
- 日志会显示"URL已存在于集合中"

## 监控指标详解

### 屏蔽URL计数器

```python
request_monitor_blocked_urls_total{
    reason="慢请求次数过多(120>=100)",
    domain="example.com", 
    path="/api/data"
}
```

**用途**：
- 监控被屏蔽URL的数量和原因
- 分析问题URL的分布情况
- 设置告警阈值

### 处理时间分布

```python
request_monitor_processing_seconds_bucket{le="0.1"} 45
request_monitor_processing_seconds_bucket{le="0.5"} 78
# ...
```

**用途**：
- 监控RequestMonitor的处理性能
- 识别处理瓶颈
- 优化配置参数

### 活跃监控数量

```python
request_monitor_active_monitors 3
```

**用途**：
- 监控并发处理的页面数量
- 资源使用情况分析
- 容量规划参考

## 最佳实践

### 1. 阈值配置

根据应用场景合理设置阈值：

```python
# 严格模式（快速屏蔽问题URL）
RequestMonitor(slow_request_threshold=20, failed_request_threshold=3)

# 宽松模式（容忍更多异常）
RequestMonitor(slow_request_threshold=200, failed_request_threshold=20)

# 生产环境推荐
RequestMonitor(slow_request_threshold=100, failed_request_threshold=10)
```

### 2. 与PageMonitor协调

确保RequestMonitor能获取到完整的统计数据：

```python
# PageMonitor需要足够的时间收集统计信息
page_monitor = PageMonitor(page_timeout=60.0)  # 慢请求超时6秒

# RequestMonitor基于PageMonitor的数据进行分析
request_monitor = RequestMonitor(slow_request_threshold=50)
```

### 3. 监控告警

设置合适的Prometheus告警规则：

```yaml
# 屏蔽URL过多告警
- alert: HighBlockedURLRate
  expr: increase(request_monitor_blocked_urls_total[5m]) > 10
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "大量URL被RequestMonitor屏蔽"

# 处理时间过长告警
- alert: SlowRequestMonitoring
  expr: histogram_quantile(0.95, request_monitor_processing_seconds_bucket) > 5
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "RequestMonitor处理时间过长"
```

### 4. 日志分析

关注RequestMonitor的关键日志：

```bash
# 屏蔽日志
grep "屏蔽问题URL" application.log

# 统计信息
grep "请求监控完成" application.log

# 错误处理
grep "ERROR.*RequestMonitor" application.log
```

### 5. 配置调优

基于运行情况调整参数：

- **慢请求阈值过低**: 导致正常URL被误屏蔽
- **慢请求阈值过高**: 无法及时屏蔽问题URL
- **失败请求阈值过低**: 网络抖动时误屏蔽
- **失败请求阈值过高**: 无法及时发现问题服务

## 注意事项

1. **依赖关系**: RequestMonitor 依赖 PageMonitor 提供的统计数据
2. **URL集合**: 必须传递有效的 URLCollection 实例
3. **优先级**: RequestMonitor 的优先级为1，在 PageMonitor 之后执行
4. **屏蔽持久化**: 屏蔽的URL只存在于当前运行的URL集合中
5. **性能影响**: 大量屏蔽操作可能影响处理性能
6. **清理机制**: 屏蔽的URL不会自动清理，需要手动管理

## 扩展性

RequestMonitor 设计为可扩展的：

- 可以添加新的屏蔽规则（如响应时间、状态码等）
- 支持自定义阈值计算逻辑
- 可以扩展 Prometheus 指标
- 支持自定义屏蔽策略

通过合理配置和监控，RequestMonitor 能够有效提升页面处理系统的稳定性和效率，自动过滤掉有问题的URL，避免资源浪费。