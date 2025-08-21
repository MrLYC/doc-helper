# Doc Helper 项目开发规范

本文档描述了 Doc Helper 项目的开发规范、工具使用指南和最佳实践。

## 📋 项目概述

Doc Helper 是一个网页文档转PDF爬虫工具，使用 Python 开发，基于 Playwright 和 PyPDF2 技术栈。

### 核心技术栈
- **Python 3.9+**: 主要编程语言
- **Poetry**: 依赖管理和包管理工具
- **Playwright**: 网页自动化和爬虫引擎
- **PyPDF2**: PDF文件处理库
- **Ruff**: 代码格式化和检查工具
- **MyPy**: 类型检查工具
- **Pytest**: 测试框架

## 🛠️ 开发环境设置

### 1. 依赖管理

本项目使用 **Poetry** 作为包管理工具，所有的依赖管理和命令执行都应该通过 Poetry 进行。

#### 安装依赖
```bash
# 安装基本依赖
poetry install

# 安装包含开发工具的完整依赖
poetry install --with dev,tests,linters

# 安装 Playwright 浏览器（必需）
poetry run playwright install chromium
```

#### 添加新依赖
```bash
# 添加运行时依赖
poetry add package-name

# 添加开发依赖
poetry add --group dev package-name

# 添加测试依赖
poetry add --group tests package-name
```

### 2. 环境激活

使用 Poetry 管理虚拟环境：

```bash
# 激活虚拟环境
poetry shell

# 或者在命令前加 poetry run
poetry run python script.py
poetry run pytest
```

## 🏗️ 代码规范

### 1. 代码格式化和检查

#### Ruff 配置
项目配置了 Ruff 作为代码格式化和检查工具，配置位于 `pyproject.toml` 中。

```bash
# 代码格式化
poetry run ruff format src/

# 代码检查
poetry run ruff check src/

# 自动修复可修复的问题
poetry run ruff check src/ --fix
```

#### 代码规范要点
- 行长度限制：120 字符
- 使用双引号作为字符串引号
- 函数复杂度不超过 10
- 最大参数数量：15 个
- 最大分支数量：20 个

### 2. 类型注解

使用 MyPy 进行类型检查：

```bash
# 类型检查
poetry run mypy src/
```

#### 类型注解要求
- 所有公共函数必须有类型注解
- 复杂的数据结构使用 `typing` 模块的类型
- 使用 `dataclass` 定义数据类

### 3. 文档字符串

使用 Google 风格的文档字符串：

```python
def process_page(url: str, selector: str) -> Optional[str]:
    """处理单个页面并返回内容。
    
    Args:
        url: 要处理的页面URL
        selector: CSS选择器用于提取内容
        
    Returns:
        处理后的页面内容，失败时返回None
        
    Raises:
        ValueError: 当URL格式不正确时
        TimeoutError: 当页面加载超时时
    """
    pass
```

## 🧪 测试规范

### 1. 测试框架

使用 Pytest 作为测试框架：

```bash
# 运行所有测试
poetry run pytest

# 运行特定测试文件
poetry run pytest tests/test_specific.py

# 运行测试并生成覆盖率报告
poetry run pytest --cov=./
```

### 2. 测试组织

```
tests/
├── unit/           # 单元测试
├── integration/    # 集成测试
├── fixtures/       # 测试数据
└── conftest.py     # 测试配置
```

### 3. 测试规范

- 测试文件以 `test_` 开头
- 测试函数以 `test_` 开头
- 使用描述性的测试名称
- 每个测试应该独立且可重复

## 🚀 命令执行规范

### 1. 基本原则

**始终使用 `poetry run` 前缀执行命令**，确保在正确的虚拟环境中运行。

### 2. 常用命令

#### 开发命令
```bash
# 运行主程序
poetry run python src/doc_helper/site_to_pdf.py [args...]

# 或使用安装的脚本命令
poetry run site-to-pdf [args...]

# 代码格式化
poetry run ruff format src/

# 代码检查
poetry run ruff check src/ --fix

# 类型检查
poetry run mypy src/
```

#### 测试命令
```bash
# 运行测试
poetry run pytest

# 运行测试并生成覆盖率报告
poetry run pytest --cov=./

# 运行特定测试
poetry run pytest tests/test_specific.py::test_function
```

#### 依赖管理
```bash
# 更新依赖
poetry update

# 查看依赖树
poetry show --tree

# 导出requirements.txt（如需要）
poetry export -f requirements.txt --output requirements.txt
```

## 📁 项目结构规范

```
doc-helper/
├── .github/                 # GitHub 配置文件
│   ├── workflows/          # CI/CD 工作流
│   ├── ISSUE_TEMPLATE/     # Issue 模板
│   └── PROJECT_GUIDELINES.md  # 本规范文档
├── src/
│   └── doc_helper/         # 主要源码包
│       ├── __init__.py     # 包初始化
│       └── site_to_pdf.py  # 主程序
├── tests/                  # 测试文件
│   ├── unit/               # 单元测试
│   ├── integration/        # 集成测试
│   └── conftest.py         # 测试配置
├── docs/                   # 项目文档
├── pyproject.toml          # Poetry 配置文件
├── README.md               # 项目说明
├── CHANGELOG.md            # 变更日志
├── LICENSE                 # 许可证
└── .gitignore              # Git 忽略规则
```

## 🔄 开发工作流

### 1. 功能开发流程

1. **创建分支**: `git checkout -b feature/feature-name`
2. **开发代码**: 遵循代码规范
3. **运行测试**: `poetry run pytest`
4. **代码检查**: `poetry run ruff check src/ --fix`
5. **类型检查**: `poetry run mypy src/`
6. **提交代码**: 使用清晰的提交信息
7. **推送分支**: `git push origin feature/feature-name`
8. **创建 PR**: 通过 GitHub 界面

### 2. 代码提交规范

#### 提交信息格式
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

#### 类型说明
- `feat`: 新功能
- `fix`: 修复错误
- `docs`: 文档更新
- `style`: 代码格式化
- `refactor`: 代码重构
- `test`: 测试相关
- `chore`: 其他杂项

#### 示例
```bash
git commit -m "feat(crawler): 添加URL黑名单功能"
git commit -m "fix(pdf): 修复PDF合并时的内存泄漏问题"
git commit -m "docs: 更新README中的安装说明"
```

## 🔍 调试和故障排除

### 1. 常见问题

#### Poetry 相关
```bash
# 清理缓存
poetry cache clear --all pypi

# 重新安装依赖
rm poetry.lock
poetry install

# 检查虚拟环境
poetry env info
```

#### Playwright 相关
```bash
# 重新安装浏览器
poetry run playwright install --force chromium

# 检查浏览器安装
poetry run playwright install --dry-run
```

### 2. 日志和调试

```bash
# 启用详细日志
poetry run site-to-pdf --verbose [other-args...]

# 启用调试模式
poetry run site-to-pdf --debug --debug-dir ./debug [other-args...]
```

## 📦 发布规范

### 1. 版本管理

使用语义化版本 (Semantic Versioning):
- `MAJOR.MINOR.PATCH`
- 例如: `1.2.3`

### 2. 发布流程

1. 更新版本号在 `pyproject.toml`
2. 更新 `CHANGELOG.md`
3. 运行完整测试套件
4. 创建 Git 标签
5. 推送到远程仓库

```bash
# 更新版本
poetry version patch  # 或 minor, major

# 运行测试
poetry run pytest

# 提交更改
git add .
git commit -m "chore: bump version to $(poetry version -s)"

# 创建标签
git tag v$(poetry version -s)

# 推送
git push origin main --tags
```

## 🤝 贡献指南

### 1. 贡献流程

1. Fork 项目
2. 创建功能分支
3. 遵循开发规范编写代码
4. 添加相应测试
5. 确保所有检查通过
6. 提交 Pull Request

### 2. Pull Request 检查清单

- [ ] 代码遵循项目规范
- [ ] 添加了适当的测试
- [ ] 所有测试通过
- [ ] 代码检查无错误
- [ ] 更新了相关文档
- [ ] 提交信息清晰明确

## 📞 支持和反馈

如果您对这些规范有任何疑问或建议，请通过以下方式联系：

1. 创建 GitHub Issue
2. 在 Pull Request 中讨论
3. 联系项目维护者

---

**重要提醒**: 在执行任何项目相关命令时，请始终记住使用 `poetry run` 前缀，这确保命令在正确的虚拟环境中执行，避免依赖冲突和环境问题。
