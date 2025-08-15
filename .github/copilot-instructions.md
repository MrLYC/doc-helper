# GitHub Copilot 仓库指令

本文档为 GitHub Copilot 提供项目特定的上下文和指导原则。

## 项目概述

Doc Helper 是一个基于 Python 的网页文档转PDF爬虫工具。项目使用 Poetry 进行依赖管理，基于 Playwright 进行网页自动化，使用 PyPDF2 处理PDF文件。

## 技术栈

- **语言**: Python 3.9+
- **包管理**: Poetry
- **网页自动化**: Playwright
- **PDF处理**: PyPDF2
- **代码质量**: Ruff (格式化和检查)
- **类型检查**: MyPy
- **测试框架**: Pytest
- **CI/CD**: GitHub Actions + Tox

## 开发规范
- 代码需要保证可读性和可维护性，有合理的日志打印，圈复杂度不应该超过 10

### 依赖管理
- 使用 Poetry 管理所有依赖
- 执行命令时必须使用 `poetry run` 前缀
- 添加新依赖使用 `poetry add package-name`
- 开发依赖使用 `poetry add --group dev package-name`

### 代码风格
- 使用 Ruff 进行代码格式化和检查
- 行长度限制: 120 字符
- 使用双引号作为字符串引号
- 所有公共函数必须有类型注解
- 使用 Google 风格的文档字符串

### 项目结构
```
src/pdf_helper/          # 主要源码包
tests/                   # 测试文件
docs/                    # 项目文档
.github/                 # GitHub 配置文件
```

### 命令执行规范
- 运行主程序: `poetry run site-to-pdf` 或 `poetry run python src/pdf_helper/site_to_pdf.py`
- 代码格式化: `poetry run ruff format src/`
- 代码检查: `poetry run ruff check src/ --fix`
- 类型检查: `poetry run mypy src/`
- 运行测试: `poetry run pytest`

## 代码生成指导

### 函数设计原则
- 保持函数复杂度在 10 以下
- 最大参数数量: 15 个
- 最大分支数量: 20 个
- 使用描述性的函数和变量名
- 优先使用类型注解和文档字符串

### 错误处理
- 使用具体的异常类型
- 提供有意义的错误信息
- 支持优雅的错误恢复
- 记录适当的日志信息

### 异步编程
- 项目使用 Playwright 的同步API (`sync_playwright`)
- 避免混用异步和同步代码
- 使用适当的超时设置

### 配置和参数
- 使用 argparse 处理命令行参数
- 使用 dataclass 定义配置对象
- 支持通过参数自定义行为
- 提供合理的默认值

## 特定功能指导

### 网页爬虫相关
- 使用 Playwright 进行页面自动化
- 支持页面加载策略配置 (fast/normal/thorough)
- 实现URL黑名单过滤功能
- 支持并行页面处理
- 实现断点续传功能

### PDF处理相关
- 使用 PyPDF2 进行PDF操作
- 支持PDF文件合并
- 处理PDF页数限制
- 临时文件管理

### 缓存和状态管理
- 使用基于参数哈希的缓存ID
- JSON序列化进度状态
- 支持缓存清理功能
- 实现信号处理用于优雅中断

## 测试指导

- 为新功能编写单元测试
- 使用 pytest 框架
- 测试文件命名: `test_*.py`
- 使用描述性的测试函数名
- 包含边界条件和错误情况的测试

## 文档要求

- 所有公共函数需要文档字符串
- 使用 Google 风格的文档字符串格式
- 更新 README.md 中的相关内容
- 保持代码注释简洁明了

## 性能考虑

- 支持并行页面处理以提高性能
- 实现页面重用减少浏览器开销
- 使用适当的超时设置
- 考虑内存使用和文件清理

## 安全考虑

- 验证URL格式和安全性
- 处理网络请求超时
- 避免路径遍历攻击
- 安全地处理临时文件

## 提交信息规范

使用语义化提交信息:
- `feat`: 新功能
- `fix`: 修复错误
- `docs`: 文档更新
- `style`: 代码格式化
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 其他杂项

示例: `feat(crawler): 添加URL黑名单功能`

## 中文支持

- 项目支持中文，日志消息和用户界面使用中文
- 代码注释和文档字符串可以使用中文
- 变量名和函数名使用英文
- 错误信息和用户提示使用中文
