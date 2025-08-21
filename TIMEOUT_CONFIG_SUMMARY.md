# 全局超时配置重构总结

## 修改概述

本次重构在 server.py 中定义了一个全局默认超时值（600秒），并基于此值计算所有时间相关的命令行参数默认值，同时移除了其他地方的硬编码超时/间隔时间。

## 主要变更

### 1. 全局配置定义

**文件**: `doc_helper/server.py`

```python
# 全局默认超时配置（秒）
DEFAULT_GLOBAL_TIMEOUT = 600  # 全局默认超时，页面加载并处理完成的最大超时时间
```

### 2. 基于全局超时的默认值计算

所有时间相关的配置都基于 `DEFAULT_GLOBAL_TIMEOUT` 计算：

| 配置项 | 计算公式 | 默认值 | 说明 |
|--------|----------|---------|------|
| 页面加载超时 | `DEFAULT_GLOBAL_TIMEOUT / 2` | 300秒 | 页面加载的最大等待时间 |
| 轮询间隔 | `DEFAULT_GLOBAL_TIMEOUT / 60` | 10秒 | 页面状态检查间隔 |
| 检测超时 | `DEFAULT_GLOBAL_TIMEOUT / 120` | 5秒 | 处理器状态检测超时 |
| 网络空闲超时 | `DEFAULT_GLOBAL_TIMEOUT / 200` | 3秒 | 等待网络空闲状态超时 |
| 截图超时 | `DEFAULT_GLOBAL_TIMEOUT / 60` | 10秒 | 页面截图操作超时 |

### 3. 配置传递链路

**配置流向**:
1. **server.py** → `ServerConfig` 类默认值
2. **命令行参数** → `parse_config_from_args()` 解析
3. **PageProcessingBuilder** → 设置方法调用
4. **PageManagerConfig** → 传递给 ChromiumManager
5. **处理器实例** → 具体的超时配置使用

### 4. 硬编码移除

**修改的文件和位置**:

#### `doc_helper/protocol.py`
- 添加了 `network_idle_timeout` 和 `screenshot_timeout` 字段到 `PageManagerConfig`

#### `doc_helper/manager.py` 
- 移除硬编码的截图超时 (`10000ms` → `config.screenshot_timeout * 1000`)
- 移除硬编码的网络空闲超时 (`3000ms` → `config.network_idle_timeout * 1000`)

#### `doc_helper/processors.py`
- `PageMonitor` 构造函数添加 `network_idle_timeout` 参数
- 移除 `_wait_for_network_idle` 方法中的硬编码超时
- 移除调用处的硬编码超时值

#### `doc_helper/builder.py`
- 添加 `_network_idle_timeout` 和 `_screenshot_timeout` 实例变量
- 添加 `set_network_idle_timeout()` 和 `set_screenshot_timeout()` 方法
- 更新 `PageManagerConfig` 创建时传递新的超时参数
- 更新 `PageMonitor` 创建时传递网络空闲超时参数

### 5. 命令行参数增强

新增命令行参数：
- `--network-idle-timeout`: 网络空闲超时时间
- `--screenshot-timeout`: 截图超时时间

更新现有参数的默认值计算：
- `--page-timeout`: 基于全局超时计算
- `--poll-interval`: 基于全局超时计算  
- `--detect-timeout`: 基于全局超时计算

## 配置示例

### 使用默认值
```bash
python -m doc_helper -u https://example.com -O /output
```
将使用基于 600秒全局超时计算的所有默认值。

### 自定义超时值
```bash
python -m doc_helper \
  -u https://example.com \
  -O /output \
  --page-timeout 120 \
  --poll-interval 5 \
  --network-idle-timeout 2 \
  --screenshot-timeout 15
```

## 优势

1. **统一配置**: 所有超时配置都从单一来源派生，确保一致性
2. **灵活性**: 可以通过修改 `DEFAULT_GLOBAL_TIMEOUT` 轻松调整整个系统的超时基准
3. **明确性**: 移除了硬编码，所有超时都通过明确的参数传递
4. **可扩展性**: 新增超时配置时有清晰的模式可循

## 向后兼容性

- 所有现有的命令行参数仍然有效
- 默认行为保持不变（除了基于新的全局超时计算的更合理的默认值）
- 现有的代码调用方式无需修改

## 测试验证

- 所有单元测试通过 (49 passed)
- 超时配置功能测试验证成功
- 命令行参数解析测试验证成功
- 自定义参数覆盖测试验证成功