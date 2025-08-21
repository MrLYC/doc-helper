#!/usr/bin/env python3
"""
PDF 文档爬虫服务器

该模块提供一个基于 FastAPI 的 HTTP 服务器，用于运行页面处理流水线。
通过命令行参数配置页面处理器，自动爬取网页内容并生成 PDF 文档。

主要功能：
- 通过 PageMonitor 监控页面状态
- 使用 LinksFinder 发现更多链接
- 通过 ElementCleaner 清理页面元素
- 使用 ContentFinder 处理页面内容
- 通过 PdfExporter 导出 PDF
- 使用 RequestMonitor 监控和屏蔽异常请求
- 处理完成后自动合并 PDF 文件
- 提供 Prometheus 指标监控接口
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Response, Request, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST

from .builder import PageProcessingBuilder
from .manager import ChromiumManager
from .pdf_merger import PdfMerger, MergeConfig
from .protocol import URLCollection, URLStatus
from .url_collection import SimpleCollection

logger = logging.getLogger(__name__)

# 全局默认超时配置（秒）
DEFAULT_GLOBAL_TIMEOUT = 600  # 全局默认超时，页面加载并处理完成的最大超时时间

# 全局变量
manager: Optional[ChromiumManager] = None
processing_task: Optional[asyncio.Task] = None
shutdown_event = asyncio.Event()
server_config = None  # 将在main函数中设置为ServerConfig实例


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理"""
    logger.info("启动 PDF 文档爬虫服务器")
    
    # 启动时的初始化工作
    yield
    
    # 关闭时的清理工作
    logger.info("关闭 PDF 文档爬虫服务器")
    if processing_task:
        processing_task.cancel()
        try:
            await processing_task
        except asyncio.CancelledError:
            pass


# 创建 FastAPI 应用
app = FastAPI(
    title="PDF 文档爬虫服务器",
    description="自动爬取网页内容并生成 PDF 文档的服务器",
    version="1.0.0",
    lifespan=lifespan
)


class ServerConfig:
    """服务器配置"""
    
    def __init__(self):
        """初始化配置"""
        # 网络配置
        self.entry_urls: List[str] = []
        self.block_patterns: List[str] = []
        
        # 页面处理配置
        self.concurrent_tabs: int = 3
        self.page_timeout: float = DEFAULT_GLOBAL_TIMEOUT / 2  # 页面加载超时为全局超时的一半
        self.poll_interval: float = DEFAULT_GLOBAL_TIMEOUT / 60  # 轮询间隔为全局超时的1/60
        self.detect_timeout: float = DEFAULT_GLOBAL_TIMEOUT / 120  # 检测超时为全局超时的1/120
        self.network_idle_timeout: float = DEFAULT_GLOBAL_TIMEOUT / 200  # 网络空闲超时
        self.screenshot_timeout: float = DEFAULT_GLOBAL_TIMEOUT / 60  # 截图超时
        self.headless: bool = True
        self.verbose: bool = False
        
        # 处理器配置
        self.links_selector: str = "body a"
        self.clean_selector: str = "*[id*='ad'], *[class*='popup'], script[src*='analytics']"
        self.content_selector: str = "main, article, .content, #content"
        self.url_patterns: List[str] = []
        self.max_depth: int = 12
        
        # 请求监控配置
        self.slow_request_threshold: int = 100
        self.failed_request_threshold: int = 10
        
        # 输出配置
        self.output_dir: str = "/tmp/pdf_output"
        self.temp_dir: str = "/tmp/pdf_temp"
        
        # PDF 合并配置
        self.max_pages: Optional[int] = None
        self.max_file_size_mb: Optional[float] = None
        self.single_file_template: str = "{name}.pdf"
        self.multi_file_template: str = "{name}_{index:03d}.pdf"
        self.overwrite_existing: bool = False
        
        # 服务器配置
        self.host: str = "127.0.0.1"
        self.port: int = 8000
        self.log_level: str = "INFO"
        self.auth_token: Optional[str] = None


def verify_auth_token(request: Request) -> None:
    """验证认证令牌"""
    global server_config
    
    if not server_config or not server_config.auth_token:
        # 如果没有设置认证令牌，则跳过验证
        return
    
    # 从查询参数中获取token
    token = request.query_params.get('token')
    
    if not token or token != server_config.auth_token:
        raise HTTPException(
            status_code=401,
            detail="访问被拒绝：无效的认证令牌。请在URL中添加 ?token=<your_token> 参数。"
        )


def create_argument_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="PDF 文档爬虫服务器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基本使用
  python -m doc_helper -u https://example.com -o /output/docs.pdf

  # 使用输出目录
  python -m doc_helper -u https://example.com -O /output

  # 启动服务器模式
  python -m doc_helper --server --host 0.0.0.0 --port 8080

  # 启用认证的服务器模式
  python -m doc_helper --server --auth-token "your-secret-token"

  # 高级配置
  python -m doc_helper \\
    --urls https://site1.com https://site2.com \\
    --concurrent-tabs 5 \\
    --page-timeout 120 \\
    -o /output/combined_docs.pdf \\
    --max-pages 1000 \\
    --max-file-size 50 \\
    --url-patterns ".*\\/docs\\/.*" ".*\\/api\\/.*" \\
    --max-depth 3 \\
    --block-patterns ".*\\.gif" ".*analytics.*" \\
    --clean-selector "*[id*='ad'], .popup" \\
    --find-links \\
    --auth-token "api-secret-123"

  # 服务器模式API访问（启用认证时）：
  curl "http://localhost:8000/status?token=api-secret-123"
  curl "http://localhost:8000/snapshot/0?token=api-secret-123" -o screenshot.png
    --content-selector "main article" \\
    --verbose

  # 生产环境
  python server.py \\
    -u https://docs.example.com \\
    -o /data/documentation.pdf \\
    -c 10 \\
    -t 180 \\
    --url-patterns ".*\\/api\\/.*" ".*\\/guide\\/.*" \\
    --max-depth 5 \\
    --host 0.0.0.0 \\
    --port 8080
        """
    )
    
    # 必需参数
    parser.add_argument(
        "-u", "--url", "--urls",
        dest="urls",
        nargs="+",
        required=True,
        help="入口 URL 地址（必需）"
    )
    
    parser.add_argument(
        "-O", "--output-dir",
        dest="output_dir",
        help="PDF 输出目录"
    )
    
    parser.add_argument(
        "-o", "--output",
        dest="output",
        help="输出文件路径（自动设置输出目录和文件模板）"
    )
    
    # 页面处理配置
    parser.add_argument(
        "-T", "--concurrent-tabs",
        type=int,
        default=3,
        help="并发标签页数量 (默认: 3)"
    )
    
    parser.add_argument(
        "-t", "--page-timeout",
        type=float,
        default=DEFAULT_GLOBAL_TIMEOUT / 2,
        help=f"页面超时时间（秒） (默认: {DEFAULT_GLOBAL_TIMEOUT / 2})"
    )
    
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_GLOBAL_TIMEOUT / 60,
        help=f"轮询间隔（秒） (默认: {DEFAULT_GLOBAL_TIMEOUT / 60})"
    )
    
    parser.add_argument(
        "--detect-timeout",
        type=float,
        default=DEFAULT_GLOBAL_TIMEOUT / 120,
        help=f"检测超时时间（秒） (默认: {DEFAULT_GLOBAL_TIMEOUT / 120})"
    )
    
    parser.add_argument(
        "--network-idle-timeout",
        type=float,
        default=DEFAULT_GLOBAL_TIMEOUT / 200,
        help=f"网络空闲超时时间（秒） (默认: {DEFAULT_GLOBAL_TIMEOUT / 200})"
    )
    
    parser.add_argument(
        "--screenshot-timeout",
        type=float,
        default=DEFAULT_GLOBAL_TIMEOUT / 60,
        help=f"截图超时时间（秒） (默认: {DEFAULT_GLOBAL_TIMEOUT / 60})"
    )
    
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="使用无头模式 (默认: True)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="启用可视化模式（显示浏览器界面）"
    )
    
    # 处理器配置
    parser.add_argument(
        "-l", "--links-selector",
        default="body a",
        help="链接发现的 CSS 选择器 (默认: 'body a')"
    )
    
    parser.add_argument(
        "-C", "--clean-selector",
        default="*[id*='ad'], *[class*='popup'], script[src*='analytics']",
        help="元素清理的 CSS 选择器 (默认: 清理广告和弹窗)"
    )
    
    parser.add_argument(
        "-c", "--content-selector", 
        default="main, article, .content, #content",
        help="内容查找的 CSS 选择器 (默认: 'main, article, .content, #content')"
    )
    
    parser.add_argument(
        "-p", "--url-patterns",
        dest="url_patterns",
        nargs="*",
        help="LinksFinder 可以选择的 URL 正则表达式模式列表。如果未指定，将自动为每个入口URL生成对应的目录模式"
    )
    
    parser.add_argument(
        "--max-depth",
        type=int,
        default=12,
        help="LinksFinder 基于根目录的最大链接深度 (默认: 12)"
    )
    
    # 请求监控配置
    parser.add_argument(
        "-P", "--block-patterns",
        nargs="*",
        default=[
            ".*\\.gif", ".*\\.jpg", ".*\\.png", ".*\\.css", ".*\\.js",
            ".*analytics.*", ".*tracking.*", ".*\\.woff", ".*\\.ico"
        ],
        help="屏蔽的 URL 正则表达式模式"
    )
    
    parser.add_argument(
        "--slow-request-threshold",
        type=int,
        default=100,
        help="慢请求数量阈值 (默认: 100)"
    )
    
    parser.add_argument(
        "--failed-request-threshold",
        type=int,
        default=10,
        help="失败请求数量阈值 (默认: 10)"
    )
    
    # PDF 合并配置
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10000,
        help="每个输出 PDF 的最大页数限制"
    )
    
    parser.add_argument(
        "--max-file-size",
        type=float,
        default=140,
        help="每个输出 PDF 的最大文件大小（MB）"
    )
    
    parser.add_argument(
        "--single-file-template",
        default="{name}.pdf",
        help="单文件输出模板 (默认: '{name}.pdf')"
    )
    
    parser.add_argument(
        "--multi-file-template",
        default="{name}_{index:03d}.pdf",
        help="多文件输出模板 (默认: '{name}_{index:03d}.pdf')"
    )
    
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在的文件"
    )
    
    parser.add_argument(
        "--temp-dir",
        default="/tmp/pdf_temp",
        help="临时文件目录 (默认: '/tmp/pdf_temp')"
    )
    
    # 服务器配置
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="服务器监听地址 (默认: '0.0.0.0')"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="服务器监听端口 (默认: 8000)"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)"
    )
    
    parser.add_argument(
        "-a", "--auth-token",
        default="doc-helper",
        help="API访问认证令牌。设置后，所有API请求都需要包含 ?token=<value> 参数"
    )
    
    return parser


def generate_default_url_patterns(entry_urls: List[str]) -> List[str]:
    """为入口URL生成默认的URL模式（基于目录路径）"""
    import re
    from urllib.parse import urlparse
    
    patterns = []
    
    for url in entry_urls:
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                continue
            
            # 获取域名
            domain = parsed.netloc
            # 获取路径，取父目录
            path = parsed.path.rstrip('/')
            
            # 获取父目录路径
            if path:
                # 移除最后一个路径段，保留父目录
                path_parts = path.split('/')
                if len(path_parts) > 1:
                    path = '/'.join(path_parts[:-1])
                else:
                    path = ''
            
            # 确保路径以 / 开头（如果不为空）
            if path and not path.startswith('/'):
                path = '/' + path
            elif not path:
                path = ''
            
            # 转义特殊字符，生成正则表达式模式
            domain_escaped = re.escape(domain)
            path_escaped = re.escape(path) if path else ''
            
            # 生成模式：^协议://域名/路径/.*
            pattern = f"^https?://{domain_escaped}{path_escaped}/.*"
            patterns.append(pattern)
            
            logger.info(f"为 {url} 生成URL模式: {pattern}")
            
        except Exception as e:
            logger.warning(f"无法为URL {url} 生成模式: {e}")
            continue
    
    return patterns


def parse_config_from_args(args: argparse.Namespace) -> ServerConfig:
    """从命令行参数解析配置"""
    config = ServerConfig()
    
    # 网络配置
    config.entry_urls = args.urls
    config.block_patterns = args.block_patterns or []
    
    # 页面处理配置
    config.concurrent_tabs = args.concurrent_tabs
    config.page_timeout = args.page_timeout
    config.poll_interval = args.poll_interval
    config.detect_timeout = args.detect_timeout
    config.network_idle_timeout = args.network_idle_timeout
    config.screenshot_timeout = args.screenshot_timeout
    config.headless = not args.verbose  # verbose 模式下使用非无头模式
    config.verbose = args.verbose
    
    # 处理器配置
    config.links_selector = args.links_selector
    config.clean_selector = args.clean_selector
    config.content_selector = args.content_selector
    
    # URL模式配置
    if hasattr(args, 'url_patterns') and args.url_patterns is not None:
        config.url_patterns = args.url_patterns
        logger.info(f"使用用户指定的URL模式: {config.url_patterns}")
    else:
        # 生成默认的URL模式
        config.url_patterns = generate_default_url_patterns(config.entry_urls)
        logger.info(f"自动生成URL模式: {config.url_patterns}")
    
    config.max_depth = args.max_depth
    
    # 请求监控配置
    config.slow_request_threshold = args.slow_request_threshold
    config.failed_request_threshold = args.failed_request_threshold
    
    # 输出配置处理和验证
    if hasattr(args, 'output') and args.output and hasattr(args, 'output_dir') and args.output_dir:
        raise ValueError("不能同时指定 -o/--output 和 -O/--output-dir 参数")
    
    if hasattr(args, 'output') and args.output:
        # 如果指定了 -o/--output，自动设置相关参数
        output_path = Path(args.output)
        config.output_dir = str(output_path.parent)
        name = output_path.stem
        ext = output_path.suffix if output_path.suffix else '.pdf'
        
        config.single_file_template = f"{name}{ext}"
        config.multi_file_template = f"{name}-{{index}}{ext}"
    elif hasattr(args, 'output_dir') and args.output_dir:
        # 使用传统的参数
        config.output_dir = args.output_dir
        config.single_file_template = args.single_file_template
        config.multi_file_template = args.multi_file_template
    else:
        # 默认输出配置
        config.output_dir = "/tmp/pdf_output"
        config.single_file_template = args.single_file_template
        config.multi_file_template = args.multi_file_template
    
    config.temp_dir = args.temp_dir
    
    # PDF 合并配置
    config.max_pages = args.max_pages
    config.max_file_size_mb = args.max_file_size
    config.overwrite_existing = args.overwrite
    
    # 服务器配置
    config.host = args.host
    config.port = args.port
    config.log_level = args.log_level
    config.auth_token = getattr(args, 'auth_token', None)
    
    return config


def setup_logging(log_level: str):
    """设置日志配置"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("pdf_crawler.log", encoding="utf-8")
        ]
    )


def create_manager_from_config(config: ServerConfig) -> ChromiumManager:
    """从配置创建 ChromiumManager"""
    # 创建构建器
    builder = PageProcessingBuilder()
    
    # 设置基本配置
    builder = (builder
               .set_entry_urls(config.entry_urls)
               .set_concurrent_tabs(config.concurrent_tabs)
               .set_page_timeout(config.page_timeout)
               .set_poll_interval(config.poll_interval)
               .set_detect_timeout(config.detect_timeout)
               .set_network_idle_timeout(config.network_idle_timeout)
               .set_screenshot_timeout(config.screenshot_timeout)
               .set_headless(config.headless)
               .set_verbose(config.verbose))
    
    # 添加请求监控和 URL 屏蔽
    if config.block_patterns:
        builder = builder.block_url_patterns(
            patterns=config.block_patterns,
            slow_request_threshold=config.slow_request_threshold,
            failed_request_threshold=config.failed_request_threshold
        )
    
    # 添加链接发现
    builder = builder.find_links(
        css_selector=config.links_selector,
        url_patterns=config.url_patterns,
        max_depth=config.max_depth
    )
    
    # 添加元素清理
    if config.clean_selector:
        builder = builder.clean_elements(css_selector=config.clean_selector)
    
    # 添加内容查找
    builder = builder.find_content(css_selector=config.content_selector)
    
    # 添加 PDF 导出（导出到临时目录）
    builder = builder.export_pdf(output_dir=config.temp_dir)
    
    # 构建管理器
    return builder.build()


async def process_pages(config: ServerConfig) -> List[str]:
    """处理页面并返回生成的 PDF 文件路径列表"""
    global manager
    
    # 确保输出目录存在
    os.makedirs(config.output_dir, exist_ok=True)
    os.makedirs(config.temp_dir, exist_ok=True)
    
    logger.info(f"开始处理页面，入口 URLs: {config.entry_urls}")
    logger.info(f"临时目录: {config.temp_dir}")
    logger.info(f"输出目录: {config.output_dir}")
    
    # 创建管理器
    manager = create_manager_from_config(config)
    
    # 运行页面处理
    await manager.run()
    
    # 查找生成的 PDF 文件
    temp_path = Path(config.temp_dir)
    pdf_files = list(temp_path.glob("*.pdf"))
    
    logger.info(f"找到 {len(pdf_files)} 个 PDF 文件: {[str(f) for f in pdf_files]}")
    
    return [str(f) for f in pdf_files]


async def merge_pdfs(pdf_files: List[str], config: ServerConfig) -> List[str]:
    """合并 PDF 文件"""
    if not pdf_files:
        logger.warning("没有找到需要合并的 PDF 文件")
        return []
    
    logger.info(f"开始合并 {len(pdf_files)} 个 PDF 文件")
    
    # 创建合并配置
    merge_config = MergeConfig(
        max_pages=config.max_pages,
        max_file_size_mb=config.max_file_size_mb,
        output_dir=config.output_dir,
        single_file_template=config.single_file_template,
        multi_file_template=config.multi_file_template,
        overwrite_existing=config.overwrite_existing,
        preserve_metadata=True,
        compression=True
    )
    
    # 创建 PDF 合并器
    merger = PdfMerger(merge_config)
    
    # 执行合并
    try:
        output_files = await asyncio.get_event_loop().run_in_executor(
            None, merger.merge_files, pdf_files, "merged_docs"
        )
        
        logger.info(f"PDF 合并完成，输出文件: {output_files}")
        return output_files
        
    except Exception as e:
        logger.error(f"PDF 合并失败: {e}")
        raise


# API 路由

@app.get("/")
async def root(_: None = Depends(verify_auth_token)):
    """根路径"""
    return {
        "message": "PDF 文档爬虫服务器",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check(_: None = Depends(verify_auth_token)):
    """健康检查"""
    global manager, processing_task
    
    status = {
        "status": "healthy",
        "timestamp": time.time(),
        "manager_active": manager is not None,
        "processing_active": processing_task is not None and not processing_task.done()
    }
    
    if manager and hasattr(manager, 'url_collection'):
        url_collection = manager.url_collection
        status["url_stats"] = {
            "pending": len(url_collection.get_by_status(URLStatus.PENDING)),
            "visited": len(url_collection.get_by_status(URLStatus.VISITED)),
            "failed": len(url_collection.get_by_status(URLStatus.FAILED)),
            "total": len(url_collection.get_all_urls())
        }
    
    return status


@app.get("/metrics")
async def get_metrics(_: None = Depends(verify_auth_token)):
    """获取 Prometheus 指标"""
    global manager
    
    if manager and hasattr(manager, 'get_metrics'):
        try:
            metrics_data = manager.get_metrics()
            return PlainTextResponse(
                content=metrics_data.decode('utf-8'),
                media_type=CONTENT_TYPE_LATEST
            )
        except Exception as e:
            logger.error(f"获取指标失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取指标失败: {e}")
    else:
        return PlainTextResponse(
            content="# 管理器未初始化或不支持指标\n",
            media_type=CONTENT_TYPE_LATEST
        )


@app.get("/status")
async def get_status(_: None = Depends(verify_auth_token)):
    """获取详细状态信息"""
    global manager, processing_task
    
    if not manager:
        return {"status": "not_started", "message": "管理器未初始化"}
    
    status = {
        "status": "running" if processing_task and not processing_task.done() else "idle",
        "timestamp": time.time()
    }
    
    # URL 集合状态
    if hasattr(manager, 'url_collection'):
        url_collection = manager.url_collection
        all_urls = url_collection.get_all_urls()
        
        status["urls"] = {
            "total": len(all_urls),
            "pending": len(url_collection.get_by_status(URLStatus.PENDING)),
            "visited": len(url_collection.get_by_status(URLStatus.VISITED)),
            "failed": len(url_collection.get_by_status(URLStatus.FAILED))
        }
        
        # 最近的 URLs
        status["recent_urls"] = [
            {"url": url.url, "status": url.status.value, "category": url.category}
            for url in all_urls[-10:]  # 最近 10 个 URL
        ]
    
    # 活跃页面状态
    if hasattr(manager, '_active_pages'):
        status["active_pages"] = len(manager._active_pages)
        status["active_page_urls"] = [
            context.url.url for context in manager._active_pages.values()
        ]
    
    return status


@app.get("/pages")
async def get_active_pages(_: None = Depends(verify_auth_token)):
    """获取所有活跃页面的信息"""
    global manager
    
    logger.info("收到获取活跃页面请求")
    
    if not manager:
        logger.error("Manager 未初始化")
        return {"status": "error", "message": "Manager 未初始化"}
    
    try:
        pages_info = manager.get_active_pages_info()
        logger.info(f"返回 {len(pages_info)} 个页面信息")
        return {
            "status": "success", 
            "total_pages": len(pages_info),
            "pages": pages_info
        }
    except Exception as e:
        logger.error(f"获取活跃页面信息失败: {e}")
        return {"status": "error", "message": f"获取页面信息失败: {str(e)}"}


@app.get("/debug")
async def get_debug_info(_: None = Depends(verify_auth_token)):
    """获取调试信息"""
    global manager, processing_task
    
    logger.info("收到调试信息请求")
    
    debug_info = {
        "manager_initialized": manager is not None,
        "processing_task_active": processing_task is not None and not processing_task.done() if processing_task else False,
        "server_uptime": time.time()
    }
    
    if manager:
        try:
            pages_info = manager.get_active_pages_info()
            debug_info.update({
                "active_pages_count": len(pages_info),
                "active_pages": pages_info
            })
            
            # 获取URL集合状态
            if hasattr(manager, 'url_collection'):
                url_collection = manager.url_collection
                debug_info["url_stats"] = {
                    "pending": len(url_collection.get_by_status(URLStatus.PENDING)),
                    "visited": len(url_collection.get_by_status(URLStatus.VISITED)),
                    "failed": len(url_collection.get_by_status(URLStatus.FAILED)),
                    "total": len(url_collection.get_all_urls())
                }
        except Exception as e:
            debug_info["manager_error"] = str(e)
    
    return debug_info


@app.get("/snapshot/{slot}")
async def get_page_snapshot(slot: int, _: None = Depends(verify_auth_token)):
    """获取指定槽位页面的截图"""
    global manager
    
    logger.info(f"收到截图请求，槽位: {slot}")
    
    if not manager:
        logger.error("Manager 未初始化")
        raise HTTPException(status_code=503, detail="Manager 未初始化")
    
    if slot < 0:
        logger.error(f"无效的槽位号: {slot}")
        raise HTTPException(status_code=400, detail="槽位号不能为负数")
    
    try:
        # 先获取页面信息来调试
        pages_info = manager.get_active_pages_info()
        logger.info(f"当前活跃页面数: {len(pages_info)}")
        
        if len(pages_info) == 0:
            logger.warning("当前没有活跃页面")
            raise HTTPException(
                status_code=404, 
                detail=f"当前没有活跃页面。请等待页面加载完成后重试。"
            )
        
        if slot >= len(pages_info):
            logger.warning(f"槽位 {slot} 超出范围，当前有 {len(pages_info)} 个页面")
            raise HTTPException(
                status_code=404, 
                detail=f"槽位 {slot} 不存在。当前有 {len(pages_info)} 个页面 (槽位范围: 0-{len(pages_info)-1})"
            )
        
        screenshot_bytes = await manager.get_page_screenshot(slot)
        
        if screenshot_bytes is None:
            logger.error(f"截图失败，槽位: {slot}")
            raise HTTPException(status_code=500, detail=f"槽位 {slot} 截图失败，请稍后重试")
        
        logger.info(f"截图成功，槽位: {slot}，大小: {len(screenshot_bytes)} bytes")
        return Response(
            content=screenshot_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f"inline; filename=page_snapshot_slot_{slot}.png",
                "Cache-Control": "no-cache, no-store, must-revalidate"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取页面截图失败 (slot={slot}): {e}")
        raise HTTPException(status_code=500, detail=f"获取截图失败: {str(e)}")


async def main_processing_loop(config: ServerConfig):
    """主处理循环"""
    global processing_task, shutdown_event
    
    try:
        logger.info("开始主处理循环")
        
        # 处理页面
        pdf_files = await process_pages(config)
        
        if not shutdown_event.is_set():
            # 合并 PDF 文件
            output_files = await merge_pdfs(pdf_files, config)
            
            logger.info(f"处理完成，输出文件: {output_files}")
            
            # 清理临时文件
            try:
                temp_path = Path(config.temp_dir)
                for temp_file in temp_path.glob("*.pdf"):
                    temp_file.unlink()
                    logger.debug(f"删除临时文件: {temp_file}")
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")
        
    except asyncio.CancelledError:
        logger.info("处理循环被取消")
        raise
    except Exception as e:
        logger.error(f"处理循环发生错误: {e}")
        raise
    finally:
        logger.info("主处理循环结束")


def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"收到信号 {signum}，准备优雅关闭")
    shutdown_event.set()


async def run_server(config: ServerConfig):
    """运行服务器和处理任务"""
    global processing_task
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动主处理任务
    processing_task = asyncio.create_task(main_processing_loop(config))
    
    # 配置 uvicorn
    uvicorn_config = uvicorn.Config(
        app=app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=True
    )
    
    server = uvicorn.Server(uvicorn_config)
    
    try:
        # 同时运行服务器和处理任务
        await asyncio.gather(
            server.serve(),
            processing_task,
            return_exceptions=True
        )
    except Exception as e:
        logger.error(f"服务器运行错误: {e}")
    finally:
        logger.info("服务器已关闭")


def main():
    """主函数"""
    global server_config
    
    # 解析命令行参数
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # 解析配置
    config = parse_config_from_args(args)
    server_config = config  # 设置全局配置
    
    # 设置日志
    setup_logging(config.log_level)
    
    # 打印配置信息
    logger.info("=== PDF 文档爬虫服务器启动 ===")
    logger.info(f"入口 URLs: {config.entry_urls}")
    logger.info(f"并发标签页: {config.concurrent_tabs}")
    logger.info(f"页面超时: {config.page_timeout}s")
    logger.info(f"输出目录: {config.output_dir}")
    logger.info(f"临时目录: {config.temp_dir}")
    logger.info(f"可视化模式: {config.verbose}")
    logger.info(f"服务器地址: http://{config.host}:{config.port}")
    if config.auth_token:
        logger.info(f"认证已启用，需要token参数访问API")
    else:
        logger.info("未设置认证，API可自由访问")
    
    if config.max_pages:
        logger.info(f"最大页数限制: {config.max_pages}")
    if config.max_file_size_mb:
        logger.info(f"最大文件大小: {config.max_file_size_mb}MB")
    
    logger.info("=== 配置完成，开始运行 ===")
    
    # 运行服务器
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        logger.info("收到键盘中断，正在关闭...")
    except Exception as e:
        logger.error(f"运行时错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()