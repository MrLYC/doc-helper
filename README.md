# Doc Helper

一个强大的网页文档转PDF爬虫工具，支持自动抓取网站内容并生成PDF文档。

## ✨ 特性

- 🚀 **智能爬取**: 自动发现并爬取网站中的相关页面
- 📄 **PDF生成**: 将网页内容转换为高质量的PDF文档
- 🔄 **断点续传**: 支持中断后恢复爬取，避免重复工作
- 🎯 **精确控制**: 支持CSS选择器精确提取内容
- 🚫 **智能过滤**: 支持URL黑名单，避免加载不必要的资源
- ⚡ **并行处理**: 支持多页面并行处理，提高效率
- 📊 **进度跟踪**: 实时显示爬取进度和状态
- 🛠️ **灵活配置**: 丰富的命令行参数，适应不同需求

## 🔧 安装

本项目使用 [Poetry](https://python-poetry.org/) 进行依赖管理。

### 前置要求

- Python 3.9+
- Poetry (推荐) 或 pip

### 使用 Poetry 安装 (推荐)

```bash
# 克隆项目
git clone https://github.com/MrLYC/doc-helper.git
cd doc-helper

# 安装依赖
poetry install

# 安装 Playwright 浏览器
poetry run playwright install chromium
```

### 使用 pip 安装

```bash
# 克隆项目
git clone https://github.com/MrLYC/doc-helper.git
cd doc-helper

# 安装依赖
pip install -e .

# 安装 Playwright 浏览器
playwright install chromium
```

## 🚀 快速开始

### 基本用法

```bash
# 使用 Poetry (推荐)
poetry run site-to-pdf \
    --base-url "https://example.com/docs/" \
    --content-selector "main.content" \
    --toc-selector "nav a" \
    --output-pdf "example-docs.pdf"

# 或直接使用 Python
poetry run python src/pdf_helper/site_to_pdf.py \
    --base-url "https://example.com/docs/" \
    --content-selector "main.content" \
    --toc-selector "nav a" \
    --output-pdf "example-docs.pdf"
```

### 高级用法

```bash
# 带更多配置的爬取
poetry run site-to-pdf \
    --base-url "https://example.com/docs/" \
    --content-selector "article.content" \
    --toc-selector "nav.sidebar a" \
    --output-pdf "docs.pdf" \
    --max-depth 5 \
    --timeout 30 \
    --parallel-pages 3 \
    --url-pattern "https://example.com/docs/.*" \
    --url-blacklist ".*\\.css.*" \
    --url-blacklist ".*\\.js.*" \
    --load-strategy "thorough"
```

## 📋 命令行参数

| 参数 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `--base-url` | ✅ | 起始URL | - |
| `--content-selector` | ✅ | 内容容器CSS选择器 | - |
| `--toc-selector` | ✅ | 链接提取CSS选择器 | - |
| `--output-pdf` | ✅ | 输出PDF文件路径 | - |
| `--url-pattern` | ❌ | URL匹配正则表达式 | 自动生成 |
| `--url-blacklist` | ❌ | URL黑名单模式（可多个） | [] |
| `--max-depth` | ❌ | 最大爬取深度 | 10 |
| `--max-page` | ❌ | 单PDF最大页数 | 10000 |
| `--timeout` | ❌ | 页面加载超时（秒） | 60 |
| `--max-retries` | ❌ | 失败重试次数 | 3 |
| `--parallel-pages` | ❌ | 并行页面数（1-4） | 2 |
| `--load-strategy` | ❌ | 页面加载策略 | normal |
| `--no-cache` | ❌ | 禁用缓存，强制重新爬取 | false |
| `--cleanup` | ❌ | 清理缓存文件 | false |
| `--verbose` | ❌ | 显示浏览器界面 | false |
| `--debug` | ❌ | 启用调试模式 | false |

### 加载策略说明

- `fast`: 仅等待DOM加载完成
- `normal`: 智能等待（默认，平衡速度和稳定性）
- `thorough`: 完全等待网络空闲

## 💡 使用技巧

### 1. 缓存和断点续传

工具默认启用智能缓存，中断后自动续传：

```bash
# 正常执行，中断后会保存进度
poetry run site-to-pdf --base-url "..." --content-selector "..." --toc-selector "..." --output-pdf "docs.pdf"

# 再次执行相同命令会自动继续
poetry run site-to-pdf --base-url "..." --content-selector "..." --toc-selector "..." --output-pdf "docs.pdf"

# 强制重新开始
poetry run site-to-pdf --no-cache --base-url "..." --content-selector "..." --toc-selector "..." --output-pdf "docs.pdf"

# 清理缓存
poetry run site-to-pdf --cleanup --base-url "..." --content-selector "..." --toc-selector "..." --output-pdf "docs.pdf"
```

### 2. 性能优化

```bash
# 提高并行度（适合服务器性能好的情况）
poetry run site-to-pdf --parallel-pages 4 ...

# 快速模式（适合简单页面）
poetry run site-to-pdf --load-strategy fast ...

# 跳过失败页面的交互式重试
poetry run site-to-pdf --skip-failed-retry ...
```

### 3. 调试和故障排除

```bash
# 显示浏览器界面，观察处理过程
poetry run site-to-pdf --verbose ...

# 启用调试模式，保存页面截图
poetry run site-to-pdf --debug --debug-dir ./debug ...
```

## 🛠️ 开发

### 环境设置

```bash
# 安装开发依赖
poetry install --with dev,tests,linters

# 运行测试
poetry run pytest

# 代码格式化
poetry run ruff format src/

# 代码检查
poetry run ruff check src/

# 类型检查
poetry run mypy src/
```

### 项目结构

```
doc-helper/
├── src/
│   └── pdf_helper/
│       ├── __init__.py
│       └── site_to_pdf.py    # 主程序
├── tests/                    # 测试文件
├── docs/                     # 文档
├── pyproject.toml           # Poetry配置
└── README.md               # 项目说明
```

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📞 支持

如果您遇到问题或有建议，请：

1. 查看 [文档](docs/)
2. 搜索已有的 [Issues](https://github.com/MrLYC/doc-helper/issues)
3. 创建新的 [Issue](https://github.com/MrLYC/doc-helper/issues/new)

---

⭐ 如果这个项目对您有帮助，请给它一个星标！
