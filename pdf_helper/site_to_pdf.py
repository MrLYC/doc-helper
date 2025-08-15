import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from PyPDF2 import PdfMerger, PdfReader

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class PageTask:
    """页面任务信息"""

    url: str
    depth: int
    page: Any = None
    loaded: bool = False
    error: str | None = None


@dataclass
class ParallelPageState:
    """并行页面状态管理"""
    url: str
    depth: int
    page: Any = None
    is_loading: bool = False
    is_loaded: bool = False
    load_error: str | None = None
    final_url: str | None = None


class TrueParallelProcessor:
    """真正的并行处理器 - 同时打开多个标签页预加载"""

    def __init__(self, context, parallel_count: int):
        """
        初始化并行处理器
        
        Args:
            context: Playwright浏览器上下文
            parallel_count: 并行度，同时打开的标签页数量
        """
        self.context = context
        self.parallel_count = parallel_count
        self.page_states: list[ParallelPageState | None] = [None] * parallel_count
        logger.info(f"创建真正并行处理器，并行度: {parallel_count}")

    def _start_page_loading(self, slot_index: int, url: str, depth: int, args, timeout_config, url_blacklist_patterns):
        """在指定槽位开始加载页面"""
        try:
            # 创建新页面
            page = self.context.new_page()
            
            # 创建页面状态
            page_state = ParallelPageState(
                url=url,
                depth=depth,
                page=page,
                is_loading=True,
                is_loaded=False
            )
            self.page_states[slot_index] = page_state
            
            logger.info(f"🚀 槽位[{slot_index}] 开始预加载: {url}")
            
            # 异步开始页面加载（不等待完成）
            # 这里只是发起导航请求，不等待页面完全加载
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_config.initial_load_timeout)
            logger.info(f"📡 槽位[{slot_index}] DOM已加载: {url}")
            
            return True
            
        except Exception as e:
            logger.warning(f"❌ 槽位[{slot_index}] 预加载失败: {url} - {e!s}")
            if 'page_state' in locals() and page_state.page:
                try:
                    page_state.page.close()
                except:
                    pass
            self.page_states[slot_index] = None
            return False

    def _complete_page_loading(self, slot_index: int, args, timeout_config, url_blacklist_patterns):
        """完成指定槽位的页面加载"""
        page_state = self.page_states[slot_index]
        if not page_state or not page_state.page:
            return False
            
        try:
            logger.info(f"⏳ 槽位[{slot_index}] 完成页面加载: {page_state.url}")
            
            # 设置请求拦截
            _setup_request_blocking(page_state.page, url_blacklist_patterns)
            
            # 设置慢请求监控
            _setup_slow_request_monitoring(page_state.page, timeout_config)
            
            # 完成页面加载
            final_url = _handle_page_loading_with_retries(
                page_state.page,
                page_state.url,
                args.content_selector,
                timeout_config,
                args.max_retries,
                args.verbose,
                args.load_strategy,
                url_blacklist_patterns,
            )
            
            page_state.is_loading = False
            page_state.is_loaded = True
            page_state.final_url = final_url
            logger.info(f"✅ 槽位[{slot_index}] 加载完成: {page_state.url}")
            return True
            
        except Exception as e:
            page_state.is_loading = False
            page_state.load_error = str(e)
            logger.warning(f"❌ 槽位[{slot_index}] 加载失败: {page_state.url} - {e!s}")
            return False

    def _process_page_content(self, slot_index: int, args, base_url_normalized, timeout_config, progress_state):
        """处理页面内容并生成PDF"""
        page_state = self.page_states[slot_index]
        if not page_state or not page_state.page or not page_state.is_loaded:
            return None, []
            
        try:
            logger.info(f"📄 槽位[{slot_index}] 开始内容处理: {page_state.url}")
            
            # 提取页面链接
            links = _extract_page_links(
                page_state.page, 
                args.toc_selector, 
                page_state.final_url or page_state.url, 
                base_url_normalized
            )
            
            # 检查是否已有PDF文件
            existing_pdf = _check_existing_pdf(progress_state.temp_dir, page_state.url)
            if existing_pdf:
                logger.info(f"📋 槽位[{slot_index}] 发现已存在PDF: {page_state.url}")
                return existing_pdf, links
            
            # 生成PDF
            pdf_path = _generate_pdf_with_validation(
                page_state.page,
                args.content_selector,
                args.verbose,
                timeout_config,
                args.debug,
                args.debug_dir,
                progress_state.temp_dir,
                page_state.url,
            )
            
            logger.info(f"✅ 槽位[{slot_index}] 内容处理完成: {page_state.url}")
            return pdf_path, links
            
        except Exception as e:
            logger.error(f"❌ 槽位[{slot_index}] 内容处理失败: {page_state.url} - {e!s}")
            return None, []

    def _close_page_slot(self, slot_index: int):
        """关闭指定槽位的页面"""
        page_state = self.page_states[slot_index]
        if page_state and page_state.page:
            try:
                # 添加超时机制，防止页面关闭时卡住
                page_state.page.close()
                logger.debug(f"🔄 槽位[{slot_index}] 页面已关闭: {page_state.url}")
            except Exception as e:
                logger.debug(f"关闭槽位[{slot_index}]页面时出错: {e}")
        self.page_states[slot_index] = None

    def close_all(self):
        """关闭所有页面"""
        logger.info("🔄 正在关闭所有并行页面...")
        for i in range(self.parallel_count):
            try:
                self._close_page_slot(i)
            except Exception as e:
                logger.warning(f"关闭槽位[{i}]时出错: {e}")
                # 强制清空状态，即使关闭失败
                self.page_states[i] = None
        logger.info("并行页面处理器已关闭")


@dataclass
class TimeoutConfig:
    """超时配置管理"""

    base_timeout: int  # 基础超时时间（来自命令行参数）

    @property
    def initial_load_timeout(self) -> int:
        """初始页面加载超时（毫秒）"""
        return max(self.base_timeout, 30) * 1000

    @property
    def fast_mode_timeout(self) -> int:
        """快速模式超时（秒）"""
        return max(self.base_timeout, 30)

    @property
    def content_additional_wait(self) -> int:
        """内容加载额外等待时间（秒）"""
        return max(5, self.base_timeout // 4)

    @property
    def thorough_min_timeout(self) -> int:
        """彻底模式最小保留超时（秒）"""
        return max(10, self.base_timeout // 2)

    @property
    def retry_backoff_max(self) -> int:
        """重试退避最大等待时间（秒）"""
        return max(10, self.base_timeout // 6)

    @property
    def element_check_interval(self) -> float:
        """元素检查间隔（秒）"""
        return 5.0

    @property
    def fast_check_interval(self) -> float:
        """快速模式检查间隔（秒）"""
        return 0.5

    @property
    def page_render_wait(self) -> float:
        """页面渲染等待时间（秒）"""
        return max(2.0, self.base_timeout * 0.02)

    @property
    def min_pdf_size(self) -> int:
        """最小PDF文件大小（字节）"""
        return 5000

    @property
    def slow_request_threshold(self) -> float:
        """慢请求阈值（超时时间的1/10）"""
        return self.base_timeout / 10.0


@dataclass
class DomainFailureTracker:
    """域名失败跟踪器，用于自动黑名单功能"""

    failure_counts: dict = field(default_factory=dict)  # {domain: failure_count}
    auto_threshold: int = 10
    auto_blacklist_patterns: list = field(default_factory=list)

    def record_failure(self, url: str):
        """记录URL失败，提取域名并增加失败计数"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            if not domain:
                return False

            # 增加失败计数
            self.failure_counts[domain] = self.failure_counts.get(domain, 0) + 1

            # 检查是否达到自动黑名单阈值
            if self.failure_counts[domain] >= self.auto_threshold:
                # 创建域名黑名单模式
                domain_pattern = f"https?://{re.escape(domain)}/.*"

                # 检查是否已经在黑名单中
                pattern_exists = any(pattern.pattern == domain_pattern for pattern in self.auto_blacklist_patterns)

                if not pattern_exists:
                    try:
                        compiled_pattern = re.compile(domain_pattern, re.IGNORECASE)
                        self.auto_blacklist_patterns.append(compiled_pattern)
                        logger.warning(f"🚫 域名 {domain} 失败 {self.failure_counts[domain]} 次，自动加入黑名单")
                        return True
                    except re.error as e:
                        logger.warning(f"创建自动黑名单模式失败: {e}")

            return False

        except Exception as e:
            logger.debug(f"记录域名失败时出错: {e}")
            return False

    def get_all_patterns(self, manual_patterns: list[Any] | None = None):
        """获取所有黑名单模式（手动+自动）"""
        all_patterns = []

        # 添加手动黑名单
        if manual_patterns:
            all_patterns.extend(manual_patterns)

        # 添加自动黑名单
        all_patterns.extend(self.auto_blacklist_patterns)

        return all_patterns

    def get_failure_summary(self):
        """获取失败统计摘要"""
        if not self.failure_counts:
            return "无域名失败记录"

        # 按失败次数排序
        sorted_failures = sorted(
            self.failure_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        summary_lines = [f"域名失败统计 (阈值: {self.auto_threshold}):"]
        for domain, count in sorted_failures[:10]:  # 只显示前10个
            status = "🚫已拉黑" if count >= self.auto_threshold else "⚠️警告"
            summary_lines.append(f"  {status} {domain}: {count} 次")

        if len(sorted_failures) > 10:
            summary_lines.append(f"  ... 还有 {len(sorted_failures) - 10} 个域名")

        return "\n".join(summary_lines)


@dataclass
class ProgressState:
    """进度状态管理"""

    base_url: str
    output_pdf: str
    temp_dir: str
    progress_file: str
    visited_urls: set
    failed_urls: list
    processed_urls: list
    pdf_files: list
    queue: deque
    enqueued: set

    def save_to_file(self):
        """保存进度到文件"""
        state_data = {
            "base_url": self.base_url,
            "output_pdf": self.output_pdf,
            "temp_dir": self.temp_dir,
            "visited_urls": list(self.visited_urls),
            "failed_urls": self.failed_urls,
            "processed_urls": self.processed_urls,
            "pdf_files": [str(f) for f in self.pdf_files],
            "queue": list(self.queue),
            "enqueued": list(self.enqueued),
        }

        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"进度已保存到: {self.progress_file}")

    @classmethod
    def load_from_file(cls, progress_file: str):
        """从文件加载进度"""
        if not os.path.exists(progress_file):
            return None

        try:
            with open(progress_file, encoding="utf-8") as f:
                state_data = json.load(f)

            # 验证临时PDF文件是否存在
            valid_pdf_files = []
            for pdf_file_str in state_data.get("pdf_files", []):
                pdf_path = Path(pdf_file_str)
                if pdf_path.exists():
                    valid_pdf_files.append(pdf_path)
                else:
                    logger.warning(f"临时PDF文件不存在，已从进度中移除: {pdf_file_str}")

            progress = cls(
                base_url=state_data.get("base_url", ""),
                output_pdf=state_data.get("output_pdf", ""),
                temp_dir=state_data.get("temp_dir", ""),
                progress_file=progress_file,
                visited_urls=set(state_data.get("visited_urls", [])),
                failed_urls=state_data.get("failed_urls", []),
                processed_urls=state_data.get("processed_urls", []),
                pdf_files=valid_pdf_files,
                queue=deque(state_data.get("queue", [])),
                enqueued=set(state_data.get("enqueued", [])),
            )

            logger.info(
                f"从进度文件恢复状态: 已处理 {len(progress.processed_urls)} 个URL，"
                f"队列中还有 {len(progress.queue)} 个URL"
            )

            return progress

        except Exception as e:
            logger.error(f"加载进度文件失败: {e}")
            return None


def url_to_filename(url: str) -> str:
    """将URL转换为安全的文件名"""
    # 使用URL的哈希值作为文件名的一部分，确保唯一性
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]

    # 清理URL用作文件名
    safe_name = re.sub(r"[^\w\-_\.]", "_", url.replace("https://", "").replace("http://", ""))
    safe_name = safe_name[:50]  # 限制长度

    return f"{safe_name}_{url_hash}.pdf"


def setup_signal_handlers(progress_state: ProgressState):
    """设置信号处理器，用于优雅退出"""

    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，正在保存进度...")
        progress_state.save_to_file()
        logger.info("进度已保存，程序退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 终止信号


def create_progress_file_path(cache_dir: Path, base_url: str) -> str:
    """创建进度文件路径"""
    # 使用base_url的哈希值确保唯一性
    url_hash = hashlib.md5(base_url.encode("utf-8")).hexdigest()[:8]

    progress_file = cache_dir / f"progress_{url_hash}.json"
    return str(progress_file)


def calculate_cache_id(
    base_url: str, content_selector: str, toc_selector: str, max_depth: int, url_pattern: str | None = None
) -> str:
    """根据关键参数计算缓存ID"""
    # 将关键参数组合成字符串
    key_params = f"{base_url}|{content_selector}|{toc_selector}|{max_depth}|{url_pattern or ''}"

    # 计算MD5哈希
    cache_id = hashlib.md5(key_params.encode("utf-8")).hexdigest()[:12]
    return cache_id


def get_cache_directory(cache_id: str) -> Path:
    """获取缓存目录路径"""
    # 在系统临时目录下创建专用的缓存目录
    base_cache_dir = Path(tempfile.gettempdir()) / "site_to_pdf_cache"
    cache_dir = base_cache_dir / cache_id

    # 确保目录存在
    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir


def cleanup_cache_directory(cache_dir: Path):
    """清理缓存目录"""
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
            logger.info(f"已清理缓存目录: {cache_dir}")
        except Exception as e:
            logger.warning(f"清理缓存目录失败: {e}")
    else:
        logger.debug(f"缓存目录不存在: {cache_dir}")


def cleanup_temp_files(temp_dir: str, progress_file: str | None = None):
    """清理临时文件"""
    cleaned_count = 0

    # 清理临时PDF文件
    if temp_dir and os.path.exists(temp_dir):
        temp_path = Path(temp_dir)
        for pdf_file in temp_path.glob("*.pdf"):
            try:
                pdf_file.unlink()
                cleaned_count += 1
                logger.debug(f"删除临时PDF: {pdf_file}")
            except Exception as e:
                logger.warning(f"删除临时PDF失败 {pdf_file}: {e}")

        # 尝试删除临时目录
        try:
            temp_path.rmdir()
            logger.debug(f"删除临时目录: {temp_path}")
        except Exception as e:
            logger.debug(f"临时目录非空或删除失败 {temp_path}: {e}")

    # 清理进度文件
    if progress_file and os.path.exists(progress_file):
        try:
            os.unlink(progress_file)
            logger.debug(f"删除进度文件: {progress_file}")
        except Exception as e:
            logger.warning(f"删除进度文件失败 {progress_file}: {e}")

    if cleaned_count > 0:
        logger.info(f"清理完成，删除了 {cleaned_count} 个临时PDF文件")

    return cleaned_count


def normalize_url(url, base_url):
    """标准化URL并移除URL片段"""
    parsed = urlparse(url)
    base_parsed = urlparse(base_url)

    # 处理相对URL
    if not parsed.scheme:
        url = urllib.parse.urljoin(base_url, url)
        parsed = urlparse(url)

    # 创建新的URL对象
    normalized = parsed._replace(
        scheme=base_parsed.scheme or "https",
        path=urllib.parse.unquote(parsed.path) if parsed.path else "",
        fragment="",
        query=parsed.query,
    )

    # 生成规范化URL字符串
    normalized_url = normalized.geturl()

    # 处理重复斜杠
    normalized_url = re.sub(r"([^:])//+", r"\1/", normalized_url)

    # 统一协议处理
    if normalized_url.startswith("http://"):
        normalized_url = "https://" + normalized_url[7:]

    return normalized_url


def resolve_selector(selector):
    """智能解析选择器"""
    if selector.startswith("/"):
        if not selector.startswith("//"):
            return f"selector=/{selector[1:]}"
        return f"selector={selector}"
    return selector


def check_element_visibility_and_content(page, selector: str) -> tuple[bool, str, int, dict[str, Any]]:
    """检查元素是否存在、可见且有足够内容"""
    element = page.query_selector(resolve_selector(selector))
    if not element:
        return False, "元素不存在", 0, {}

    element_info = page.evaluate(
        """(el) => {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return {
            textLength: el.textContent ? el.textContent.trim().length : 0,
            isVisible: rect.width > 0 && rect.height > 0,
            width: rect.width,
            height: rect.height,
            display: style.display,
            visibility: style.visibility,
            opacity: parseFloat(style.opacity) || 1
        };
    }""",
        element,
    )

    # 检查可见性
    is_visible = (
        element_info["isVisible"]
        and element_info["display"] != "none"
        and element_info["visibility"] != "hidden"
        and element_info["opacity"] > 0.1
    )

    if not is_visible:
        reason = f"元素不可见 (display:{element_info['display']}, visibility:{element_info['visibility']}, opacity:{element_info['opacity']}, size:{element_info['width']}x{element_info['height']})"
        return False, reason, element_info["textLength"], element_info

    return True, "元素可见", element_info["textLength"], element_info


def _get_wait_config(strategy: str, timeout_config):
    """根据策略获取等待配置"""
    if strategy == "fast":
        return timeout_config.fast_mode_timeout, timeout_config.fast_check_interval
    if strategy == "thorough":
        return timeout_config.base_timeout, timeout_config.element_check_interval
    # normal
    return timeout_config.base_timeout, timeout_config.element_check_interval


def _log_wait_strategy(strategy: str, timeout: float):
    """记录等待策略信息"""
    if strategy == "fast":
        logger.info(f"快速等待元素可见，最大等待时间 {timeout} 秒")
    elif strategy == "thorough":
        logger.info(f"彻底模式：持续等待元素可见，剩余等待时间 {timeout:.1f} 秒")
    else:  # normal
        logger.info(f"智能等待模式：持续等待元素可见，最大等待时间 {timeout} 秒")


def _handle_normal_strategy_content(page, selector, text_length, timeout_config, wait_start_time, timeout):
    """处理normal策略的内容检查逻辑"""
    if text_length > 100:  # 如果已经有足够内容，直接成功
        logger.info(f"内容充足 ({text_length} 字符)，完成等待")
        return True
    if text_length > 0:
        # 有少量内容，再等待一段时间看是否有更多内容加载
        remaining_time = timeout - (time.time() - wait_start_time)
        additional_wait = min(remaining_time, timeout_config.content_additional_wait)

        if additional_wait > 0:
            logger.info(f"内容较少 ({text_length} 字符)，再等待 {additional_wait:.1f} 秒看是否有更多内容...")
            time.sleep(additional_wait)

            # 再次检查
            is_ready_again, _, text_length_again, _ = check_element_visibility_and_content(page, selector)
            if is_ready_again and text_length_again >= text_length:
                logger.info(f"内容已更新到 {text_length_again} 字符，接受当前状态")
            else:
                logger.info(f"内容无明显增加，接受当前状态 ({text_length} 字符)")

        return True
    logger.info("元素可见但无文本内容，继续等待...")
    return False


def _check_consecutive_failures(status_msg, consecutive_failures, max_consecutive_failures):
    """检查连续失败是否需要快速失败"""
    if "元素不存在" in status_msg and consecutive_failures >= max_consecutive_failures:
        logger.warning(f"元素连续 {consecutive_failures} 次不存在，可能是外部链接或无效页面，快速失败")
        return True
    return False


def wait_for_element_visible(page, selector: str, timeout_config: TimeoutConfig, strategy: str = "normal") -> bool:
    """等待元素可见的通用函数"""
    timeout, check_interval = _get_wait_config(strategy, timeout_config)
    _log_wait_strategy(strategy, timeout)

    wait_start_time = time.time()
    consecutive_failures = 0  # 连续失败次数
    max_consecutive_failures = 3  # 最大连续失败次数，超过后快速失败

    while time.time() - wait_start_time < timeout:
        is_ready, status_msg, text_length, element_info = check_element_visibility_and_content(page, selector)

        if is_ready:
            logger.info(f"内容元素已找到且可见: {status_msg}")
            consecutive_failures = 0  # 重置失败计数

            if strategy == "normal":
                return _handle_normal_strategy_content(
                    page, selector, text_length, timeout_config, wait_start_time, timeout
                )
            # Fast和Thorough模式只要元素可见就成功
            return True
        consecutive_failures += 1
        elapsed = time.time() - wait_start_time
        remaining = timeout - elapsed

        # 如果是"元素不存在"且连续失败多次，可能是外部链接，快速失败
        if _check_consecutive_failures(status_msg, consecutive_failures, max_consecutive_failures):
            return False

        logger.info(
            f"元素状态: {status_msg}, 已等待 {elapsed:.1f}s, 剩余 {remaining:.1f}s, 连续失败: {consecutive_failures}"
        )

        time.sleep(check_interval)

    elapsed = time.time() - wait_start_time
    logger.warning(f"{strategy}模式等待超时 ({elapsed:.1f}s)，元素仍不可见")
    return False


def _setup_request_blocking(page, patterns):
    """设置请求拦截器，阻止黑名单URL"""
    if not patterns:
        return

    def handle_route(route):
        request_url = route.request.url
        for pattern in patterns:
            if pattern.match(request_url):
                logger.debug(f"阻止黑名单URL: {request_url}")
                route.abort()
                return
        route.continue_()

    page.route("**/*", handle_route)


def _setup_slow_request_monitoring(page, timeout_config: TimeoutConfig):
    """设置慢请求监控，打印请求时间慢请求"""
    import threading
    
    slow_requests = {}
    # 使用线程安全的锁来保护共享数据
    slow_requests_lock = threading.Lock()
    warned_slow_failed_urls = set()
    warned_slow_response_urls = set()
    warned_lock = threading.Lock()

    # 使用配置的慢请求阈值
    slow_threshold = timeout_config.slow_request_threshold
    logger.info(f"启用请求监控，慢请求阈值: {slow_threshold:.1f}秒")

    def on_request(request):
        with slow_requests_lock:
            slow_requests[request.url] = time.time()

    def on_response(response):
        request_url = response.url
        duration = None
        
        with slow_requests_lock:
            if request_url in slow_requests:
                duration = time.time() - slow_requests[request_url]
                del slow_requests[request_url]
        
        # 检查是否需要警告（在锁外进行，避免死锁）
        if duration is not None and duration > slow_threshold:
            with warned_lock:
                if request_url not in warned_slow_response_urls:
                    logger.warning(f"⏰ 请求过久 ({duration:.1f}s > {slow_threshold:.1f}s): {request_url}")
                    warned_slow_response_urls.add(request_url)

    def on_request_failed(request):
        request_url = request.url
        duration = None
        
        with slow_requests_lock:
            if request_url in slow_requests:
                duration = time.time() - slow_requests[request_url]
                del slow_requests[request_url]
        
        # 检查是否需要警告（在锁外进行，避免死锁）
        if duration is not None and duration > slow_threshold:
            with warned_lock:
                if request_url not in warned_slow_failed_urls:
                    logger.warning(f"⏰ 请求失败前耗时过久 ({duration:.1f}s > {slow_threshold:.1f}s): {request_url}")
                    warned_slow_failed_urls.add(request_url)

    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)

    return slow_requests


def _apply_fast_load_strategy(page, content_selector, timeout_config):
    """应用快速加载策略"""
    logger.info("快速加载模式：跳过网络空闲等待，但持续等待元素可见")
    return wait_for_element_visible(page, content_selector, timeout_config, "fast")


def _apply_thorough_load_strategy(page, content_selector, timeout_config, slow_requests):
    """应用彻底加载策略"""
    logger.info("彻底加载模式：等待完全的网络空闲，然后持续等待元素可见")

    # 首先等待网络空闲
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_config.base_timeout * 1000)
        logger.info("网络已达到空闲状态")
    except PlaywrightTimeoutError:
        logger.warning("网络空闲等待超时，继续等待元素可见")
        # 在thorough模式下，打印还在加载的慢请求
        _log_ongoing_slow_requests(slow_requests)

    # 然后等待元素可见（使用剩余时间）
    remaining_timeout = max(timeout_config.base_timeout // 2, timeout_config.thorough_min_timeout)
    timeout_config_remaining = TimeoutConfig(remaining_timeout)
    return wait_for_element_visible(page, content_selector, timeout_config_remaining, "thorough")


def _apply_normal_load_strategy(page, content_selector, timeout_config):
    """应用正常加载策略"""
    return wait_for_element_visible(page, content_selector, timeout_config, "normal")


def _log_ongoing_slow_requests(slow_requests):
    """记录正在进行的慢请求"""
    if not slow_requests:
        return

    current_time = time.time()
    ongoing_requests = []
    for req_url, start_time in slow_requests.items():
        duration = current_time - start_time
        ongoing_requests.append((req_url, duration))

    if ongoing_requests:
        # 按持续时间排序，显示最慢的前5个
        ongoing_requests.sort(key=lambda x: x[1], reverse=True)
        logger.warning(f"仍有 {len(ongoing_requests)} 个请求未完成:")
        for req_url, duration in ongoing_requests[:5]:
            logger.warning(f"  - {duration:.1f}s: {req_url}")


def _apply_load_strategy(page, content_selector, timeout_config, load_strategy, slow_requests):
    """应用特定的加载策略"""
    if load_strategy == "fast":
        return _apply_fast_load_strategy(page, content_selector, timeout_config)
    if load_strategy == "thorough":
        return _apply_thorough_load_strategy(page, content_selector, timeout_config, slow_requests)
    # normal strategy (智能等待)
    return _apply_normal_load_strategy(page, content_selector, timeout_config)


def _perform_single_load_attempt(
    page, url, content_selector, timeout_config, load_strategy, verbose_mode, slow_requests, attempt, max_retries
):
    """执行单次页面加载尝试"""
    logger.info(f"尝试加载页面 ({attempt+1}/{max_retries}): {url}")

    if verbose_mode:
        logger.info("可视化模式：等待页面基本加载...")

    # 先尝试快速加载到 domcontentloaded 状态
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_config.initial_load_timeout)
    logger.info("页面DOM已加载完成")

    if verbose_mode:
        # 在页面标题中显示处理状态
        try:
            page.evaluate(
                """() => {
                document.title = "[检查内容...] " + (document.title || "页面");
            }"""
            )
        except:
            pass

    # 应用加载策略
    if _apply_load_strategy(page, content_selector, timeout_config, load_strategy, slow_requests):
        return page.url  # 返回最终URL
    if attempt < max_retries - 1:
        time.sleep(timeout_config.element_check_interval)

    return None


def _handle_load_retry(attempt, max_retries, timeout_config, error):
    """处理加载重试逻辑"""
    if attempt == max_retries - 1:
        logger.error("所有重试均失败，跳过此页面")
        raise error

    # 指数退避重试
    wait_time = min(2**attempt, timeout_config.retry_backoff_max)
    logger.info(f"等待 {wait_time} 秒后重试...")
    time.sleep(wait_time)


def _handle_page_loading_with_retries(
    page, url, content_selector, timeout_config, max_retries, verbose_mode, load_strategy, url_blacklist_patterns=None
):
    """处理页面加载和重试逻辑"""
    # 设置请求拦截
    _setup_request_blocking(page, url_blacklist_patterns)

    # 为所有策略启用慢请求监控
    slow_requests = _setup_slow_request_monitoring(page, timeout_config)

    for attempt in range(max_retries):
        try:
            result = _perform_single_load_attempt(
                page,
                url,
                content_selector,
                timeout_config,
                load_strategy,
                verbose_mode,
                slow_requests,
                attempt,
                max_retries,
            )

            if result:
                return result

        except PlaywrightTimeoutError as timeout_err:
            if "Timeout" in str(timeout_err) and "goto" in str(timeout_err):
                logger.warning(f"第 {attempt+1} 次页面加载超时: {timeout_err}")
            else:
                logger.warning(f"第 {attempt+1} 次操作超时: {timeout_err}")

            _handle_load_retry(attempt, max_retries, timeout_config, timeout_err)

        except Exception as e:
            logger.warning(f"第 {attempt+1} 次页面加载异常: {e!s}，重试中...")
            _handle_load_retry(attempt, max_retries, timeout_config, e)

    logger.error("所有重试均失败，跳过此页面")
    raise Exception("所有重试均失败")


def _extract_page_links(page, toc_selectors, final_url, base_url):
    """提取页面中的导航链接，支持多个目录选择器"""
    all_links = []
    
    # 如果传入的是字符串，转换为列表
    if isinstance(toc_selectors, str):
        toc_selectors = [toc_selectors]
    
    logger.info(f"开始提取导航链接，尝试 {len(toc_selectors)} 个目录选择器")
    
    for i, toc_selector in enumerate(toc_selectors, 1):
        try:
            logger.info(f"尝试目录选择器 {i}/{len(toc_selectors)}: {toc_selector}")
            resolved_toc = resolve_selector(toc_selector)

            toc_element = page.query_selector(resolved_toc)
            if not toc_element:
                logger.debug(f"目录选择器 {i} 未找到元素: {resolved_toc}")
                continue

            links_from_selector = []
            
            # 检查选中的元素本身是否是 a 标签
            if toc_element.tag_name.lower() == 'a':
                href = toc_element.get_attribute("href")
                if href and href.strip():
                    abs_url = urljoin(final_url, href.strip())
                    norm_url = normalize_url(abs_url, base_url)
                    links_from_selector.append(norm_url)
                    logger.info(f"目录选择器 {i} 本身是 a 标签，提取到 1 个链接")
            else:
                # 在选中的元素内查找 a 标签
                a_elements = toc_element.query_selector_all("a")
                logger.info(f"目录选择器 {i} 找到 {len(a_elements)} 个链接元素")

                for a in a_elements:
                    href = a.get_attribute("href")
                    if href and href.strip():
                        abs_url = urljoin(final_url, href.strip())
                        norm_url = normalize_url(abs_url, base_url)
                        links_from_selector.append(norm_url)

            unique_links_from_selector = list(set(links_from_selector))
            logger.info(f"目录选择器 {i} 提取到 {len(unique_links_from_selector)} 个唯一链接")
            all_links.extend(unique_links_from_selector)

        except Exception as e:
            logger.warning(f"目录选择器 {i} 提取链接失败: {e}")
            continue

    # 去重所有链接
    unique_links = list(set(all_links))
    logger.info(f"总共从所有目录选择器提取到 {len(unique_links)} 个唯一链接")

    return unique_links


def _clean_page_content(page, content_element, verbose_mode, timeout_config):
    """清理页面内容，保留主要内容"""
    logger.info("清理页面并保留主要内容...")

    # 保存原始内容用于对比
    original_content = page.evaluate(
        """(element) => {
        return {
            textLength: element.textContent ? element.textContent.trim().length : 0,
            innerHTML: element.innerHTML.substring(0, 200) + '...'
        };
    }""",
        content_element,
    )
    logger.info(f"清理前内容预览: 文本长度={original_content['textLength']}, HTML片段={original_content['innerHTML']}")

    if verbose_mode:
        page.evaluate(
            r"""() => {
            document.title = "[清理页面...] " + document.title.replace(/^\[.*?\] /, "");
        }"""
        )
        # 在可视化模式下，稍微延迟一下让用户看到原始页面
        time.sleep(timeout_config.element_check_interval)

    # 新的清理逻辑：逐级向上清理DOM
    page.evaluate(
        """(element) => {
        // 从内容元素开始向上清理
        let current = element;
        
        // 向上遍历直到body元素
        while (current && current !== document.body) {
            const parent = current.parentElement;
            if (!parent) break;
            
            // 删除所有非当前元素的兄弟节点
            for (let i = parent.children.length - 1; i >= 0; i--) {
                const child = parent.children[i];
                if (child !== current) {
                    child.remove();
                }
            }
            
            // 移动到父级元素
            current = parent;
        }
        
        // 清理body元素
        if (current === document.body) {
            // 移除所有脚本
            document.querySelectorAll('script').forEach(s => s.remove());
            
            // 设置body样式
            document.body.style.margin = '0';
            document.body.style.padding = '0';
            
            // 确保内容元素宽度100%
            element.style.width = '100%';
            element.style.boxSizing = 'border-box';
            element.style.padding = '20px';
        }
    }""",
        content_element,
    )

    # 检查清理后的内容
    after_cleanup = page.evaluate(
        """(element) => {
        const rect = element.getBoundingClientRect();
        return {
            textLength: element.textContent ? element.textContent.trim().length : 0,
            hasVisibleContent: rect.width > 0 && rect.height > 0,
            width: rect.width,
            height: rect.height,
            innerHTML: element.innerHTML.substring(0, 200) + '...'
        };
    }""",
        content_element,
    )
    logger.info(
        f"清理后内容检查: 文本长度={after_cleanup['textLength']}, 可见={after_cleanup['hasVisibleContent']}, 尺寸={after_cleanup['width']}x{after_cleanup['height']}"
    )

    # 如果清理后内容明显减少，发出警告
    if after_cleanup["textLength"] < original_content["textLength"] * 0.8:
        logger.warning(
            f"警告：清理后内容大幅减少！原始: {original_content['textLength']} -> 清理后: {after_cleanup['textLength']}"
        )


def _save_debug_screenshot(page, url, debug_dir):
    """保存调试截图"""
    debug_path = Path(debug_dir)
    debug_path.mkdir(exist_ok=True)

    # 清理URL作为文件名
    safe_url = re.sub(r"[^\w\-_\.]", "_", url.replace("https://", "").replace("http://", ""))[:50]
    screenshot_path = debug_path / f"{safe_url}_after_cleanup.png"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info(f"调试截图已保存: {screenshot_path}")
    except Exception as screenshot_err:
        logger.warning(f"保存截图失败: {screenshot_err}")


def _prepare_page_for_pdf(page, content_selector, verbose_mode, timeout_config, debug_mode, debug_dir, url):
    """准备页面内容用于PDF生成"""
    content_element = page.query_selector(resolve_selector(content_selector))
    if not content_element:
        logger.error(f"页面中未找到内容节点: {content_selector}")
        return False

    if verbose_mode:
        page.evaluate(
            r"""() => {
            document.title = "[分析内容...] " + document.title.replace(/^\[.*?\] /, "");
        }"""
        )

    logger.info("分析内容元素...")

    # 使用统一的元素检查函数
    is_ready, status_msg, text_length, element_info = check_element_visibility_and_content(page, content_selector)

    if not is_ready:
        logger.error(f"内容元素不可见，跳过PDF生成！{status_msg}")
        return False

    logger.info(f"内容元素信息: {element_info}")

    # 如果内容为空，记录警告但继续（可能是动态加载）
    if text_length == 0:
        logger.warning("警告：内容元素没有文本内容！可能是动态加载或空页面")
    elif text_length < 50:
        logger.warning(f"警告：内容元素文本很少 ({text_length} 字符)！")

    # 清理页面内容
    _clean_page_content(page, content_element, verbose_mode, timeout_config)

    # 调试模式：保存截图
    if debug_mode and debug_dir:
        _save_debug_screenshot(page, url, debug_dir)

    return True


def _generate_pdf_from_page(page, verbose_mode, timeout_config, temp_dir: str, url: str):
    """从页面生成PDF"""
    logger.info("等待页面渲染...")
    if verbose_mode:
        page.evaluate(
            r"""() => {
            document.title = "[准备生成PDF...] " + document.title.replace(/^\[.*?\] /, "");
        }"""
        )
        time.sleep(timeout_config.element_check_interval)  # 在可视化模式下给用户更多时间观察

    time.sleep(timeout_config.page_render_wait)  # 使用配置的页面渲染等待时间

    # 在生成PDF前做最后的内容检查
    final_check = page.evaluate(
        """() => {
        const body = document.body;
        const rect = body.getBoundingClientRect();
        return {
            bodyTextLength: body.textContent ? body.textContent.trim().length : 0,
            bodyHeight: rect.height,
            visibleElements: Array.from(document.querySelectorAll('*')).filter(el => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && 
                       style.visibility !== 'hidden' && 
                       rect.width > 0 && 
                       rect.height > 0;
            }).length,
            hasImages: document.querySelectorAll('img').length,
            hasTables: document.querySelectorAll('table').length
        };
    }"""
    )
    logger.info(f"PDF生成前最终检查: {final_check}")

    if final_check["bodyTextLength"] == 0:
        logger.error("严重警告：页面内容为空，将生成空白PDF！")
    elif final_check["bodyTextLength"] < 50:
        logger.warning(f"警告：页面内容很少 ({final_check['bodyTextLength']} 字符)，可能生成近似空白的PDF")

    # 使用持久化的文件名
    filename = url_to_filename(url)
    temp_file = Path(temp_dir) / filename
    logger.info(f"生成PDF: {temp_file}")

    try:
        page.pdf(
            path=str(temp_file),
            format="A4",
            margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
            scale=0.99,
        )

        # 检查生成的PDF文件大小
        if temp_file.exists():
            file_size = temp_file.stat().st_size
            logger.info(f"PDF文件生成成功，大小: {file_size} 字节")
            if file_size < timeout_config.min_pdf_size:  # 使用配置的最小PDF大小
                logger.warning(f"警告：PDF文件很小 ({file_size} 字节)，可能是空白页面")

        return temp_file
    except Exception as pdf_err:
        logger.error(f"生成PDF失败: {pdf_err}")
        return None


def _check_existing_pdf(temp_dir, url):
    """检查是否已经存在PDF文件"""
    if not temp_dir:
        return None

    expected_pdf = Path(temp_dir) / url_to_filename(url)
    if expected_pdf.exists() and expected_pdf.stat().st_size > 1000:
        logger.info(f"发现已存在的PDF文件，跳过处理: {url}")
        return expected_pdf
    return None


def _handle_page_loading(
    page, url, content_selector, timeout_config, max_retries, verbose_mode, load_strategy, url_blacklist_patterns
):
    """处理页面加载逻辑"""
    try:
        return _handle_page_loading_with_retries(
            page,
            url,
            content_selector,
            timeout_config,
            max_retries,
            verbose_mode,
            load_strategy,
            url_blacklist_patterns,
        )
    except Exception as e:
        raise Exception(f"页面加载失败: {e!s}")


def _generate_pdf_with_validation(
    page, content_selector, verbose_mode, timeout_config, debug_mode, debug_dir, temp_dir, url
):
    """生成PDF并进行验证"""
    if not temp_dir:
        raise ValueError("temp_dir参数是必需的")

    # 准备页面内容用于PDF生成
    if not _prepare_page_for_pdf(page, content_selector, verbose_mode, timeout_config, debug_mode, debug_dir, url):
        raise Exception("内容元素不可见或不存在")

    # 生成PDF
    pdf_path = _generate_pdf_from_page(page, verbose_mode, timeout_config, temp_dir, url)
    if not pdf_path:
        raise Exception("PDF生成失败")

    return pdf_path


def process_page_with_failure_tracking(
    page,
    url,
    content_selector,
    toc_selectors,
    base_url,
    timeout_config: TimeoutConfig,
    max_retries,
    debug_mode=False,
    debug_dir=None,
    verbose_mode=False,
    load_strategy="normal",
    url_blacklist_patterns=None,
    temp_dir=None,
):
    """处理单个页面并生成PDF，同时提取该页面内的链接，包含失败跟踪"""
    # 检查是否已经处理过这个URL（根据PDF文件是否存在）
    existing_pdf = _check_existing_pdf(temp_dir, url)
    if existing_pdf:
        # 仍然需要提取链接，所以继续处理，但跳过PDF生成
        pass

    pdf_path = None
    links = []
    final_url = url
    failure_reason = None

    try:
        logger.info(f"准备处理页面: {url}")

        # 处理页面加载和重试逻辑
        try:
            final_url = _handle_page_loading(
                page,
                url,
                content_selector,
                timeout_config,
                max_retries,
                verbose_mode,
                load_strategy,
                url_blacklist_patterns,
            )
        except Exception as e:
            failure_reason = str(e)
            logger.warning(f"页面加载失败，将记录为待重试: {url} - {failure_reason}")
            return None, [], url, failure_reason

        if final_url != url:
            logger.info(f"重定向: {url} -> {final_url}")

        # 提取页面链接
        links = _extract_page_links(page, toc_selectors, final_url, base_url)

        # 如果PDF已存在，直接返回
        if existing_pdf:
            return existing_pdf, links, final_url, None

        # 生成PDF
        try:
            pdf_path = _generate_pdf_with_validation(
                page,
                content_selector,
                verbose_mode,
                timeout_config,
                debug_mode,
                debug_dir,
                temp_dir,
                url,
            )
            return pdf_path, links, final_url, None
        except Exception as e:
            failure_reason = str(e)
            logger.warning(f"PDF生成失败，将记录为待重试: {url} - {failure_reason}")
            return None, links, final_url, failure_reason

    except Exception as e:
        failure_reason = f"处理页面异常: {e!s}"
        logger.error(f"处理页面失败: {url}\n错误: {e!s}", exc_info=True)
        return None, links, final_url, failure_reason


def process_page(
    page,
    url,
    content_selector,
    toc_selectors,
    base_url,
    timeout_config: TimeoutConfig,
    max_retries,
    debug_mode=False,
    debug_dir=None,
    verbose_mode=False,
    load_strategy="normal",
    url_blacklist_patterns=None,
    temp_dir=None,
):
    """处理单个页面并生成PDF，同时提取该页面内的链接"""
    pdf_path, links, final_url, _ = process_page_with_failure_tracking(
        page,
        url,
        content_selector,
        toc_selectors,
        base_url,
        timeout_config,
        max_retries,
        debug_mode,
        debug_dir,
        verbose_mode,
        load_strategy,
        url_blacklist_patterns,
        temp_dir,
    )
    return pdf_path, links, final_url


def get_parent_path_pattern(base_url):
    """获取base_url的父目录作为默认URL匹配模式"""
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")

    # 如果路径为空或者是根路径，使用域名
    if not path or path == "/":
        return f"https?://{re.escape(parsed.netloc)}/.*"

    # 获取父目录路径
    parent_path = "/".join(path.split("/")[:-1])
    if not parent_path:
        parent_path = ""

    return f"https?://{re.escape(parsed.netloc)}{re.escape(parent_path)}/.*"


def compile_blacklist_patterns(blacklist_args):
    """编译URL黑名单模式"""
    if not blacklist_args:
        return []

    patterns = []
    for pattern_str in blacklist_args:
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            patterns.append(pattern)
            logger.info(f"添加URL黑名单模式: {pattern_str}")
        except re.error as e:
            logger.warning(f"无效的URL黑名单模式 '{pattern_str}': {e}")

    return patterns


def _initialize_or_resume_progress(base_url_normalized, output_file, max_depth, cache_dir, use_cache=True):
    """初始化新的进度状态或从文件恢复进度状态"""
    progress_file_path = create_progress_file_path(cache_dir, base_url_normalized)
    progress_file = Path(progress_file_path)

    if use_cache and progress_file.exists():
        logger.info(f"发现进度文件: {progress_file}")
        try:
            progress_state = ProgressState.load_from_file(str(progress_file))
            logger.info("成功恢复进度状态:")
            logger.info(f"  - 已访问URL: {len(progress_state.visited_urls)} 个")
            logger.info(f"  - 队列中URL: {len(progress_state.queue)} 个")
            logger.info(f"  - 已生成PDF: {len(progress_state.pdf_files)} 个")
            logger.info(f"  - 失败URL: {len(progress_state.failed_urls)} 个")
            logger.info(f"  - 临时目录: {progress_state.temp_dir}")
            return progress_state, True
        except Exception as e:
            logger.warning(f"恢复进度状态失败: {e}")
            logger.info("将创建新的进度状态")

    # 创建新的进度状态
    progress_state = ProgressState(
        base_url=base_url_normalized,
        output_pdf=output_file,
        temp_dir=str(cache_dir),  # 使用缓存目录作为临时目录
        progress_file=str(progress_file),
        visited_urls=set(),
        failed_urls=[],
        processed_urls=[],
        pdf_files=[],
        queue=deque(),
        enqueued=set(),
    )

    # 初始化队列
    progress_state.queue.append((base_url_normalized, 0))
    progress_state.enqueued.add(base_url_normalized)

    logger.info("创建新的进度状态")
    return progress_state, False


def _crawl_pages_with_progress(
    context,
    args,
    base_url_normalized,
    url_pattern,
    url_blacklist_patterns,
    timeout_config,
    progress_state: ProgressState,
    domain_failure_tracker,
):
    """执行页面爬取逻辑，支持进度恢复和流水线并行处理"""
    logger.info(f"开始/继续爬取，最大深度: {args.max_depth}")

    # 确保临时目录存在（使用已设置的缓存目录）
    if progress_state.temp_dir and not os.path.exists(progress_state.temp_dir):
        os.makedirs(progress_state.temp_dir, exist_ok=True)
        logger.info(f"使用缓存目录: {progress_state.temp_dir}")

    # 根据并行页面数量选择处理方式
    if args.parallel_pages > 1:
        return _crawl_pages_parallel(
            context,
            args,
            base_url_normalized,
            url_pattern,
            url_blacklist_patterns,
            timeout_config,
            progress_state,
            domain_failure_tracker,
        )
    return _crawl_pages_serial(
        context,
        args,
        base_url_normalized,
        url_pattern,
        url_blacklist_patterns,
        timeout_config,
        progress_state,
        domain_failure_tracker,
    )


def _crawl_pages_serial(
    context,
    args,
    base_url_normalized,
    url_pattern,
    url_blacklist_patterns,
    timeout_config,
    progress_state: ProgressState,
    domain_failure_tracker,
):
    """串行处理模式（兼容原有逻辑）"""
    logger.info("启用串行处理模式，创建持久页面用于重用")

    # 创建一个持久的页面，重用以提高性能
    page = context.new_page()

    try:
        processed_count = len(progress_state.visited_urls)  # 已处理的URL数量

        while progress_state.queue:
            url, depth = progress_state.queue.popleft()
            processed_count += 1

            # 显示进度信息
            total_discovered = len(progress_state.enqueued)
            progress_info = f"进度: [{processed_count}/{total_discovered}]"
            if len(progress_state.queue) > 0:
                progress_info += f" (队列中还有 {len(progress_state.queue)} 个)"

            logger.info(f"{progress_info} 处理: {url} (深度: {depth})")

            if depth > args.max_depth:
                logger.warning(f"超过最大深度限制({args.max_depth})，跳过: {url}")
                continue

            if url in progress_state.visited_urls:
                logger.info(f"已访问过，跳过: {url}")
                continue

            try:
                pdf_path, links, final_url, failure_reason = process_page_with_failure_tracking(
                    page,  # 传递页面
                    url,
                    args.content_selector,
                    args.toc_selector,
                    base_url_normalized,
                    timeout_config,  # 传递超时配置对象
                    args.max_retries,
                    args.debug,
                    args.debug_dir,
                    args.verbose,
                    args.load_strategy,
                    url_blacklist_patterns,  # 传递URL黑名单模式
                    progress_state.temp_dir,  # 传递临时目录
                )

                _handle_page_result(
                    progress_state,
                    url,
                    final_url,
                    pdf_path,
                    links,
                    failure_reason,
                    url_pattern,
                    base_url_normalized,
                    depth,
                    args.max_depth,
                )

            except Exception as e:
                logger.exception(f"处理 {url} 时发生错误")
                progress_state.failed_urls.append((url, f"异常错误: {e!s}"))
                progress_state.visited_urls.add(url)

            # 每处理一个URL就保存进度
            progress_state.save_to_file()

    finally:
        # 确保页面被正确关闭
        try:
            page.close()
            logger.info("已关闭重用的页面")
        except Exception as close_err:
            logger.warning(f"关闭重用页面时出错: {close_err!s}")

    # 最终统计
    success_count = len(progress_state.processed_urls)
    failed_count = len(progress_state.failed_urls)
    total_processed = success_count + failed_count

    if total_processed > 0:
        logger.info("\n📈 串行处理完成统计:")
        logger.info(f"   总共处理: {total_processed} 个URL")
        logger.info(f"   成功: {success_count} 个 ({success_count/total_processed*100:.1f}%)")
        logger.info(f"   失败: {failed_count} 个 ({failed_count/total_processed*100:.1f}%)")

    return progress_state


def _check_qos_trigger(loading_tasks, qos_failure_tracker):
    """检查是否触发QoS等待条件"""
    # 检查当前活跃任务中有多少已经失败过
    failed_tasks_in_current_batch = 0

    for task_id in loading_tasks:
        if task_id in qos_failure_tracker:
            failed_tasks_in_current_batch += 1

    # 如果当前批次中超过一半的任务都失败过，认为触发了流控
    total_active_tasks = len(loading_tasks)
    if total_active_tasks >= 2 and failed_tasks_in_current_batch >= total_active_tasks // 2:
        return True

    return False


def _perform_qos_wait(qos_wait_seconds):
    """执行QoS等待"""
    logger.warning("🚨 检测到可能的网站流控，进入QoS等待模式")
    logger.info(f"⏰ 等待 {qos_wait_seconds} 秒（{qos_wait_seconds//60:.1f} 分钟）以避免流控...")

    # 分段显示等待进度
    wait_interval = min(30, qos_wait_seconds // 10)  # 每30秒或总时间的1/10显示一次进度
    elapsed = 0

    while elapsed < qos_wait_seconds:
        remaining = qos_wait_seconds - elapsed
        if remaining <= wait_interval:
            time.sleep(remaining)
            break
        time.sleep(wait_interval)
        elapsed += wait_interval
        progress_percent = (elapsed / qos_wait_seconds) * 100
        logger.info(f"⏰ QoS等待进度: {progress_percent:.1f}% ({elapsed}/{qos_wait_seconds}秒)")

    logger.info("✅ QoS等待完成，恢复正常处理")


def _track_task_failure(task_id, qos_failure_tracker):
    """记录任务失败，用于QoS检测"""
    qos_failure_tracker.add(task_id)
    logger.debug(f"记录任务 #{task_id} 失败，当前失败任务数: {len(qos_failure_tracker)}")


def _process_completed_task_with_qos(
    pipeline_pool,
    loading_tasks,
    completed_task_id,
    progress_state,
    args,
    base_url_normalized,
    url_pattern,
    timeout_config,
    qos_failure_tracker,
    domain_failure_tracker,
):
    """处理已完成的任务，包含QoS失败跟踪"""
    if completed_task_id not in loading_tasks:
        return False

    url, depth = loading_tasks[completed_task_id]
    page, final_url, error = pipeline_pool.get_loaded_page(completed_task_id, timeout=0.1)

    # 显示进度信息
    processed_count = len(progress_state.visited_urls) + 1
    total_discovered = len(progress_state.enqueued)
    remaining_in_queue = len(progress_state.queue)
    active_loading = len(loading_tasks) - 1  # 减去当前正在处理的
    progress_info = f"流水线进度: [{processed_count}/{total_discovered}]"
    if remaining_in_queue > 0 or active_loading > 0:
        progress_info += f" (队列: {remaining_in_queue}, 预加载中: {active_loading})"

    logger.info(f"{progress_info} 处理: {url} (深度: {depth})")

    task_failed = False

    if depth > args.max_depth:
        logger.warning(f"超过最大深度限制({args.max_depth})，跳过: {url}")
    elif url in progress_state.visited_urls:
        logger.info(f"已访问过，跳过: {url}")
    elif page is not None:
        # 页面加载成功，进行内容处理
        try:
            pdf_path, links = _process_loaded_page(
                page,
                url,
                final_url or url,
                args,
                base_url_normalized,
                timeout_config,
                progress_state.temp_dir,
            )

            _handle_page_result(
                progress_state,
                url,
                final_url or url,
                pdf_path,
                links,
                None,
                url_pattern,
                base_url_normalized,
                depth,
                args.max_depth,
            )

        except Exception as e:
            logger.exception(f"处理已加载页面 {url} 时发生错误")
            progress_state.failed_urls.append((url, f"处理异常: {e!s}"))
            progress_state.visited_urls.add(url)
            task_failed = True
    else:
        # 页面加载失败
        failure_reason = error or "页面加载失败"
        logger.warning(f"页面加载失败: {url} - {failure_reason}")
        progress_state.failed_urls.append((url, failure_reason))
        progress_state.visited_urls.add(url)
        task_failed = True

        # 记录域名失败用于自动黑名单
        added_to_blacklist = domain_failure_tracker.record_failure(url)
        if added_to_blacklist:
            logger.info(
                f"🔄 自动黑名单已更新，当前共有 {len(domain_failure_tracker.auto_blacklist_patterns)} 个自动黑名单域名"
            )

    # 记录任务失败用于QoS检测
    if task_failed:
        _track_task_failure(completed_task_id, qos_failure_tracker)

    return task_failed


def _start_initial_loading_tasks(pipeline_pool, progress_state, args, timeout_config, url_blacklist_patterns):
    """启动初始页面预加载任务"""
    loading_tasks = {}  # {task_id: (url, depth)}
    next_task_id = 0

    initial_batch_size = min(args.parallel_pages, len(progress_state.queue))
    for _ in range(initial_batch_size):
        if progress_state.queue:
            url, depth = progress_state.queue.popleft()
            if url not in progress_state.visited_urls and depth <= args.max_depth:
                task_id = pipeline_pool.start_loading(
                    url,
                    depth,
                    args.content_selector,
                    timeout_config,
                    url_blacklist_patterns,
                    args.load_strategy,
                    args.max_retries,
                    args.verbose,
                )
                loading_tasks[task_id] = (url, depth)
                next_task_id = max(next_task_id, task_id + 1)

    logger.info(f"🚀 已启动 {len(loading_tasks)} 个初始预加载任务")
    return loading_tasks


def _find_completed_task(pipeline_pool, loading_tasks):
    """查找已完成的任务"""
    # 选择一个已完成加载的任务进行处理
    completed_task_id = None
    for task_id in loading_tasks:
        # 尝试获取已加载的页面（不等待）
        page, final_url, error = pipeline_pool.get_loaded_page(task_id, timeout=0.1)
        if page is not None or error is not None:
            completed_task_id = task_id
            break

    if completed_task_id is None:
        # 如果没有任务完成，等待最早的任务
        earliest_task_id = min(loading_tasks.keys())
        page, final_url, error = pipeline_pool.get_loaded_page(earliest_task_id, timeout=30)
        completed_task_id = earliest_task_id

    return completed_task_id


def _process_completed_task(
    pipeline_pool,
    loading_tasks,
    completed_task_id,
    progress_state,
    args,
    base_url_normalized,
    url_pattern,
    timeout_config,
):
    """处理已完成的任务"""
    if completed_task_id not in loading_tasks:
        return

    url, depth = loading_tasks[completed_task_id]
    page, final_url, error = pipeline_pool.get_loaded_page(completed_task_id, timeout=0.1)

    # 显示进度信息
    processed_count = len(progress_state.visited_urls) + 1
    total_discovered = len(progress_state.enqueued)
    remaining_in_queue = len(progress_state.queue)
    active_loading = len(loading_tasks) - 1  # 减去当前正在处理的
    progress_info = f"流水线进度: [{processed_count}/{total_discovered}]"
    if remaining_in_queue > 0 or active_loading > 0:
        progress_info += f" (队列: {remaining_in_queue}, 预加载中: {active_loading})"

    logger.info(f"{progress_info} 处理: {url} (深度: {depth})")

    if depth > args.max_depth:
        logger.warning(f"超过最大深度限制({args.max_depth})，跳过: {url}")
    elif url in progress_state.visited_urls:
        logger.info(f"已访问过，跳过: {url}")
    elif page is not None:
        # 页面加载成功，进行内容处理
        try:
            pdf_path, links = _process_loaded_page(
                page,
                url,
                final_url or url,
                args,
                base_url_normalized,
                timeout_config,
                progress_state.temp_dir,
            )

            _handle_page_result(
                progress_state,
                url,
                final_url or url,
                pdf_path,
                links,
                None,
                url_pattern,
                base_url_normalized,
                depth,
                args.max_depth,
            )

        except Exception as e:
            logger.exception(f"处理已加载页面 {url} 时发生错误")
            progress_state.failed_urls.append((url, f"处理异常: {e!s}"))
            progress_state.visited_urls.add(url)
    else:
        # 页面加载失败
        failure_reason = error or "页面加载失败"
        logger.warning(f"页面加载失败: {url} - {failure_reason}")
        progress_state.failed_urls.append((url, failure_reason))
        progress_state.visited_urls.add(url)


def _start_new_loading_task(pipeline_pool, loading_tasks, progress_state, args, timeout_config, url_blacklist_patterns):
    """启动新的预加载任务"""
    if not progress_state.queue:
        return

    next_url, next_depth = progress_state.queue.popleft()
    if next_url not in progress_state.visited_urls and next_depth <= args.max_depth:
        task_id = pipeline_pool.start_loading(
            next_url,
            next_depth,
            args.content_selector,
            timeout_config,
            url_blacklist_patterns,
            args.load_strategy,
            args.max_retries,
            args.verbose,
        )
        loading_tasks[task_id] = (next_url, next_depth)
        logger.info(f"🚀 启动新的预加载任务 #{task_id}: {next_url}")


def _crawl_pages_parallel(
    context,
    args,
    base_url_normalized,
    url_pattern,
    url_blacklist_patterns,
    timeout_config,
    progress_state: ProgressState,
    domain_failure_tracker,
):
    """真正的并行处理模式 - 同时打开多个标签页预加载"""
    logger.info(f"启用真正并行处理模式，并行度: {args.parallel_pages}")
    
    # 创建并行处理器
    processor = TrueParallelProcessor(context, args.parallel_pages)
    
    try:
        # 初始化：为每个槽位分配URL并开始预加载
        logger.info("🚀 初始化并行槽位...")
        for slot_index in range(args.parallel_pages):
            if progress_state.queue:
                url, depth = progress_state.queue.popleft()
                if url not in progress_state.visited_urls and depth <= args.max_depth:
                    processor._start_page_loading(
                        slot_index, url, depth, args, timeout_config, 
                        domain_failure_tracker.get_all_patterns(url_blacklist_patterns)
                    )
        
        # 主处理循环
        current_slot = 0  # 当前处理的槽位
        processed_count = len(progress_state.visited_urls)
        
        while any(state is not None for state in processor.page_states) or progress_state.queue:
            page_state = processor.page_states[current_slot]
            
            if page_state is None:
                # 当前槽位空闲，尝试加载新URL
                if progress_state.queue:
                    url, depth = progress_state.queue.popleft()
                    if url not in progress_state.visited_urls and depth <= args.max_depth:
                        processor._start_page_loading(
                            current_slot, url, depth, args, timeout_config,
                            domain_failure_tracker.get_all_patterns(url_blacklist_patterns)
                        )
                # 切换到下一个槽位
                current_slot = (current_slot + 1) % args.parallel_pages
                continue
            
            # 显示进度信息
            processed_count += 1
            total_discovered = len(progress_state.enqueued)
            active_slots = sum(1 for state in processor.page_states if state is not None)
            remaining_queue = len(progress_state.queue)
            
            progress_info = f"并行进度: [{processed_count}/{total_discovered}]"
            if active_slots > 0 or remaining_queue > 0:
                progress_info += f" (活跃槽位: {active_slots}, 队列: {remaining_queue})"
            
            logger.info(f"{progress_info} 处理槽位[{current_slot}]: {page_state.url} (深度: {page_state.depth})")
            
            # 检查深度和访问状态
            if page_state.depth > args.max_depth:
                logger.warning(f"槽位[{current_slot}] 超过最大深度限制({args.max_depth})，跳过: {page_state.url}")
                processor._close_page_slot(current_slot)
                current_slot = (current_slot + 1) % args.parallel_pages
                continue
                
            if page_state.url in progress_state.visited_urls:
                logger.info(f"槽位[{current_slot}] 已访问过，跳过: {page_state.url}")
                processor._close_page_slot(current_slot)
                current_slot = (current_slot + 1) % args.parallel_pages
                continue
            
            try:
                # 完成页面加载
                if page_state.is_loading:
                    success = processor._complete_page_loading(
                        current_slot, args, timeout_config,
                        domain_failure_tracker.get_all_patterns(url_blacklist_patterns)
                    )
                    if not success:
                        # 加载失败，记录并继续
                        failure_reason = page_state.load_error or "页面加载失败"
                        progress_state.failed_urls.append((page_state.url, failure_reason))
                        progress_state.visited_urls.add(page_state.url)
                        domain_failure_tracker.record_failure(page_state.url)
                        processor._close_page_slot(current_slot)
                        current_slot = (current_slot + 1) % args.parallel_pages
                        continue
                
                # 处理页面内容
                pdf_path, links = processor._process_page_content(
                    current_slot, args, base_url_normalized, timeout_config, progress_state
                )
                
                # 更新进度状态
                _handle_page_result(
                    progress_state,
                    page_state.url,
                    page_state.final_url or page_state.url,
                    pdf_path,
                    links,
                    None,  # 没有失败原因
                    url_pattern,
                    base_url_normalized,
                    page_state.depth,
                    args.max_depth,
                )
                
            except Exception as e:
                logger.exception(f"槽位[{current_slot}] 处理 {page_state.url} 时发生错误")
                progress_state.failed_urls.append((page_state.url, f"异常错误: {e!s}"))
                progress_state.visited_urls.add(page_state.url)
            
            # 关闭当前槽位，准备加载新URL
            processor._close_page_slot(current_slot)
            
            # 尝试为当前槽位加载新URL
            if progress_state.queue:
                url, depth = progress_state.queue.popleft()
                if url not in progress_state.visited_urls and depth <= args.max_depth:
                    processor._start_page_loading(
                        current_slot, url, depth, args, timeout_config,
                        domain_failure_tracker.get_all_patterns(url_blacklist_patterns)
                    )
            
            # 切换到下一个槽位
            current_slot = (current_slot + 1) % args.parallel_pages
            
            # 保存进度
            progress_state.save_to_file()
    
    finally:
        # 确保处理器被正确关闭
        processor.close_all()
    
    # 最终统计
    success_count = len(progress_state.processed_urls)
    failed_count = len(progress_state.failed_urls)
    total_processed = success_count + failed_count
    
    if total_processed > 0:
        logger.info("\n📈 并行处理完成统计:")
        logger.info(f"   总共处理: {total_processed} 个URL")
        logger.info(f"   成功: {success_count} 个 ({success_count/total_processed*100:.1f}%)")
        logger.info(f"   失败: {failed_count} 个 ({failed_count/total_processed*100:.1f}%)")
    
    return progress_state


def _process_loaded_page(page, original_url, final_url, args, base_url_normalized, timeout_config, temp_dir):
    """处理已加载的页面，生成PDF并提取链接"""
    # 提取页面链接
    links = _extract_page_links(page, args.toc_selector, final_url, base_url_normalized)

    # 检查是否已有PDF文件
    if temp_dir:
        expected_pdf = Path(temp_dir) / url_to_filename(original_url)
        if expected_pdf.exists() and expected_pdf.stat().st_size > 1000:
            logger.info(f"发现已存在的PDF文件，跳过生成: {original_url}")
            return expected_pdf, links

    # 准备页面内容用于PDF生成
    if not _prepare_page_for_pdf(
        page, args.content_selector, args.verbose, timeout_config, args.debug, args.debug_dir, original_url
    ):
        return None, links

    # 生成PDF
    pdf_path = _generate_pdf_from_page(page, args.verbose, timeout_config, temp_dir, original_url)

    return pdf_path, links


def _handle_page_result(
    progress_state, url, final_url, pdf_path, links, failure_reason, url_pattern, base_url_normalized, depth, max_depth
):
    """处理页面处理结果，更新进度状态"""
    progress_state.visited_urls.add(url)
    progress_state.visited_urls.add(final_url)

    if pdf_path and pdf_path.exists():
        progress_state.pdf_files.append(pdf_path)
        progress_state.processed_urls.append(url)
        logger.info(f"✅ 成功生成PDF: {pdf_path}")
    elif failure_reason:
        progress_state.failed_urls.append((url, failure_reason))
        logger.warning(f"❌ 页面处理失败，记录待重试: {url} - {failure_reason}")
    else:
        logger.warning(f"❌ 页面未生成PDF: {url}")

    # 处理新发现的链接
    new_links_count = 0
    for link in links:
        if not link:
            continue

        norm_url = normalize_url(link, base_url_normalized)

        if not url_pattern.match(norm_url):
            logger.debug(f"跳过不符合模式的URL: {norm_url}")
            continue

        if norm_url in progress_state.visited_urls or norm_url in progress_state.enqueued:
            logger.debug(f"已存在，跳过URL: {norm_url}")
            continue

        logger.info(f"🔗 添加新URL到队列: {norm_url} (深度: {depth+1})")
        progress_state.queue.append((norm_url, depth + 1))
        progress_state.enqueued.add(norm_url)
        new_links_count += 1

    if new_links_count > 0:
        logger.info(f"📊 从当前页面发现 {new_links_count} 个新链接，队列总数: {len(progress_state.queue)}")


def _prompt_user_choice(failed_urls):
    """提示用户选择重试方式"""
    print(f"\n=== 发现 {len(failed_urls)} 个失败的URL ===")
    for i, (url, reason) in enumerate(failed_urls, 1):
        print(f"{i}. {url}")
        print(f"   失败原因: {reason}")

    while True:
        try:
            choice = input(
                "\n是否要重试失败的URL？\n"
                "1. 重试所有失败的URL\n"
                "2. 选择性重试\n"
                "3. 跳过所有失败的URL\n"
                "请选择 (1-3): "
            ).strip()

            if choice in ["1", "2", "3"]:
                return choice
            print("无效选择，请输入 1、2 或 3")
            continue
        except (EOFError, KeyboardInterrupt):
            logger.info("用户取消重试")
            return "3"


def _get_urls_to_retry(choice, failed_urls):
    """根据用户选择获取要重试的URL列表"""
    if choice == "3":
        logger.info("用户选择跳过所有失败的URL")
        return []
    if choice == "1":
        return [url for url, _ in failed_urls]
    if choice == "2":
        urls_to_retry = []
        for i, (url, reason) in enumerate(failed_urls, 1):
            retry_choice = input(f"重试 URL {i}: {url} ? (y/n): ").strip().lower()
            if retry_choice in ["y", "yes", "是"]:
                urls_to_retry.append(url)
        return urls_to_retry
    return []


def _get_retry_count():
    """获取重试次数"""
    while True:
        try:
            retry_count = input("重试次数 (1-10, 默认3): ").strip()
            if not retry_count:
                return 3
            retry_count = int(retry_count)
            if retry_count < 1 or retry_count > 10:
                print("重试次数必须在1-10之间")
                continue
            return retry_count
        except ValueError:
            print("请输入有效的数字")
            continue
        except (EOFError, KeyboardInterrupt):
            logger.info("用户取消重试")
            return 0


def _retry_single_url(retry_page, url, args, base_url_normalized, timeout_config, url_blacklist_patterns, retry_count):
    """重试单个URL"""
    for attempt in range(retry_count):
        try:
            pdf_path, _, final_url, failure_reason = process_page_with_failure_tracking(
                retry_page,
                url,
                args.content_selector,
                args.toc_selector,
                base_url_normalized,
                timeout_config,
                args.max_retries,
                args.debug,
                args.debug_dir,
                args.verbose,
                args.load_strategy,
                url_blacklist_patterns,
            )

            if pdf_path and pdf_path.exists():
                logger.info(f"✅ 重试成功: {url}")
                return pdf_path, url, True
            logger.warning(f"⚠️ 重试第 {attempt + 1}/{retry_count} 次失败: {url} - {failure_reason}")

        except Exception as e:
            logger.warning(f"⚠️ 重试第 {attempt + 1}/{retry_count} 次异常: {url} - {e!s}")

    logger.error(f"❌ 重试所有次数后仍然失败: {url}")
    return None, url, False


def _interactive_retry_failed_urls(
    context, failed_urls, args, base_url_normalized, timeout_config, url_blacklist_patterns, domain_failure_tracker
):
    """交互式重试失败的URL"""
    if not failed_urls:
        return [], []

    # 如果启用了跳过失败重试选项，直接返回
    if args.skip_failed_retry:
        logger.info("启用了跳过失败重试选项，直接处理成功的页面")
        return [], []

    # 获取用户选择
    choice = _prompt_user_choice(failed_urls)
    urls_to_retry = _get_urls_to_retry(choice, failed_urls)

    if not urls_to_retry:
        logger.info("没有选择要重试的URL")
        return [], []

    # 获取重试次数
    retry_count = _get_retry_count()
    if retry_count == 0:
        return [], []

    logger.info(f"开始重试 {len(urls_to_retry)} 个失败的URL，重试次数: {retry_count}")

    # 重试时总是使用串行模式，避免复杂性
    retry_page = context.new_page()
    logger.info("为重试创建专用页面（串行模式）")

    try:
        retry_pdf_files = []
        retry_processed_urls = []
        still_failed_urls = []

        for i, url in enumerate(urls_to_retry, 1):
            logger.info(f"🔄 重试进度: [{i}/{len(urls_to_retry)}] 处理: {url}")

            pdf_path, processed_url, success = _retry_single_url(
                retry_page,
                url,
                args,
                base_url_normalized,
                timeout_config,
                url_blacklist_patterns,
                retry_count,
            )

            if success:
                retry_pdf_files.append(pdf_path)
                retry_processed_urls.append(processed_url)
            else:
                still_failed_urls.append((url, "重试后仍然失败"))

    finally:
        # 确保重试页面被正确关闭
        try:
            retry_page.close()
            logger.info("已关闭重试专用页面")
        except Exception as close_err:
            logger.warning(f"关闭重试页面时出错: {close_err!s}")

    # 重试结果统计
    retry_success_count = len(retry_processed_urls)
    retry_failed_count = len(still_failed_urls)
    logger.info("\n📊 重试结果统计:")
    logger.info(f"   重试成功: {retry_success_count} 个")
    logger.info(f"   重试后仍失败: {retry_failed_count} 个")

    if still_failed_urls:
        logger.warning(f"仍有 {len(still_failed_urls)} 个URL重试后依然失败:")
        for url, reason in still_failed_urls:
            logger.warning(f"  - {url}: {reason}")

    return retry_pdf_files, retry_processed_urls


def _merge_pdfs(pdf_files, processed_urls, args):
    """合并PDF文件"""
    if not pdf_files:
        logger.error("未生成任何PDF，请检查参数")
        return []

    logger.info(f"📄 准备合并 {len(pdf_files)} 个PDF文件")

    base_path = Path(args.output_pdf)
    stem = base_path.stem
    suffix = base_path.suffix if base_path.suffix else ".pdf"
    output_dir = base_path.parent

    output_dir.mkdir(parents=True, exist_ok=True)

    merger = PdfMerger()
    current_pages = 0
    file_index = 1
    merged_files = []

    for i, pdf_file in enumerate(pdf_files, 1):
        try:
            progress_info = f"合并进度: [{i}/{len(pdf_files)}]"
            logger.info(f"📄 {progress_info} 处理PDF文件: {pdf_file}")

            if not pdf_file.exists():
                logger.warning(f"PDF文件不存在: {pdf_file}")
                continue

            with open(pdf_file, "rb") as f:
                reader = PdfReader(f)
                num_pages = len(reader.pages)
                logger.debug(f"   文件页数: {num_pages}")

                if current_pages > 0 and current_pages + num_pages > args.max_page:
                    output_name = f"{stem}.{file_index}{suffix}"
                    output_path = output_dir / output_name

                    logger.info(f"📚 写入分卷 {output_path} (页数: {current_pages})")
                    with open(output_path, "wb") as out:
                        merger.write(out)
                    merged_files.append(str(output_path))

                    file_index += 1
                    merger = PdfMerger()
                    current_pages = 0

                merger.append(str(pdf_file))
                current_pages += num_pages

                try:
                    pdf_file.unlink()
                    logger.debug(f"删除临时文件: {pdf_file}")
                except Exception as unlink_err:
                    logger.warning(f"删除临时文件失败: {unlink_err}")

        except Exception as e:
            logger.error(f"处理PDF文件失败 {pdf_file}: {e}")

    if current_pages > 0:
        if file_index == 1:
            output_path = base_path
        else:
            output_name = f"{stem}.{file_index}{suffix}"
            output_path = output_dir / output_name

        logger.info(f"📚 写入最终PDF: {output_path} (页数: {current_pages})")
        with open(output_path, "wb") as out:
            merger.write(out)
        merged_files.append(str(output_path))

    if merged_files:
        logger.info(f"🎉 处理完成! 共处理 {len(processed_urls)} 个页面，生成 {len(merged_files)} 个PDF文件")
        logger.info(f"📁 输出文件: {', '.join(merged_files)}")
    else:
        logger.error("没有PDF文件生成")

    return merged_files


def _create_argument_parser():
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(description="Webpage to PDF converter")

    # 必填参数 - 添加短参数
    parser.add_argument("-u", "--base-url", required=True, help="起始URL")
    parser.add_argument("-c", "--content-selector", required=True, help="内容容器选择器")
    parser.add_argument("-t", "--toc-selector", action="append", required=True, help="链接提取选择器，可指定多个")
    parser.add_argument("-o", "--output-pdf", required=True, help="输出PDF路径")

    # URL过滤相关参数
    parser.add_argument("--url-pattern", default=None, help="URL匹配模式正则表达式")
    parser.add_argument(
        "-b", "--url-blacklist",
        action="append",
        default=[
            "https://analytics.twitter.com/",
            "https://connect.facebook.net/",
            "https://t.co/",
            "https://www.google-analytics.com/"
        ],
        help="URL黑名单模式正则表达式，可指定多个，阻止浏览器加载匹配的URL",
    )
    parser.add_argument(
        "-B", "--url-blacklist-auto-threshold",
        type=int,
        default=5,
        help="自动黑名单阈值，当某个域名出现指定次数的请求异常时，自动加入黑名单",
    )

    # 基本配置参数
    parser.add_argument("--max-page", type=int, default=10000, help="单PDF最大页数")
    parser.add_argument("--timeout", type=int, default=120, help="页面加载超时时间（秒）")
    parser.add_argument("--max-depth", type=int, default=10, help="最大爬取深度")
    parser.add_argument("--max-retries", type=int, default=3, help="失败重试次数")

    # 调试和显示参数
    parser.add_argument("-d", "--debug", action="store_true", help="启用调试模式，保存页面截图")
    parser.add_argument("--debug-dir", default="debug_screenshots", help="调试截图保存目录")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示浏览器界面，便于观察处理过程")

    # 加载策略参数
    parser.add_argument("--fast-load", action="store_true", help="快速加载模式，跳过网络空闲等待")
    parser.add_argument(
        "--load-strategy",
        choices=["fast", "normal", "thorough"],
        default="thorough",
        help="页面加载策略：fast=仅等待DOM, normal=智能等待, thorough=完全等待网络空闲",
    )

    # 重试和流控参数
    parser.add_argument("--skip-failed-retry", action="store_true", help="跳过失败URL的交互式重试，直接处理成功的页面")
    parser.add_argument(
        "--parallel-pages",
        type=int,
        default=2,
        help="并行页面数量，同时打开多个标签页预加载提高处理速度。1=串行处理，2+=真正并行处理",
    )
    parser.add_argument(
        "--qos-wait",
        type=int,
        default=600,
        help="QoS等待时间（秒），当检测到多个并行任务都失败时，等待指定时间以避免触发网站流控，默认600秒（10分钟）",
    )

    # 缓存管理参数
    parser.add_argument("--restart", action="store_true", help="重新开始爬取，删除之前的缓存和进度文件")
    parser.add_argument("--cleanup", action="store_true", help="清理指定URL和输出文件对应的临时文件和进度文件")

    return parser


def _handle_cleanup_command(args):
    """处理清理命令"""
    base_url_normalized = normalize_url(args.base_url)
    cache_id = calculate_cache_id(
        base_url_normalized,
        args.content_selector,
        args.toc_selector,
        args.max_depth,
        args.url_pattern,
    )
    cache_dir = get_cache_directory(cache_id)
    cleanup_cache_directory(cache_dir)


def _initialize_configuration(args):
    """初始化程序配置"""
    logger.info(f"开始执行PDF爬虫程序，超时设置: {args.timeout}秒")

    # 创建超时配置对象
    timeout_config = TimeoutConfig(args.timeout)
    logger.info(
        f"超时配置 - 基础: {timeout_config.base_timeout}s, 快速模式: {timeout_config.fast_mode_timeout}s, "
        f"初始加载: {timeout_config.initial_load_timeout}ms, 页面渲染: {timeout_config.page_render_wait}s"
    )

    base_url_normalized = normalize_url(args.base_url, args.base_url)
    logger.info(f"标准化基准URL: {base_url_normalized}")

    # 创建域名失败跟踪器
    domain_failure_tracker = DomainFailureTracker(
        failure_counts={},
        auto_threshold=args.url_blacklist_auto_threshold,
        auto_blacklist_patterns=[],
    )
    logger.info(f"自动黑名单阈值: {args.url_blacklist_auto_threshold} 次")

    # 编译URL黑名单模式
    url_blacklist_patterns = compile_blacklist_patterns(args.url_blacklist)
    if url_blacklist_patterns:
        logger.info(f"配置了 {len(url_blacklist_patterns)} 个手动URL黑名单模式")

    # 修改默认URL模式：使用父目录而非域名
    if args.url_pattern:
        url_pattern = re.compile(args.url_pattern)
        logger.info(f"使用自定义URL匹配模式: {url_pattern.pattern}")
    else:
        default_pattern = get_parent_path_pattern(base_url_normalized)
        url_pattern = re.compile(default_pattern)
        logger.info(f"使用默认URL匹配模式（基于父目录）: {url_pattern.pattern}")

    return timeout_config, base_url_normalized, url_blacklist_patterns, url_pattern, domain_failure_tracker


def _setup_browser_context(p, args):
    """设置浏览器和上下文"""
    headless_mode = not args.verbose
    if args.verbose:
        logger.info("启用可视化模式 - 浏览器界面将显示处理过程")
    else:
        logger.info("使用无头模式 - 浏览器在后台运行")

    browser = p.chromium.launch(
        headless=headless_mode,
        args=(
            [
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
            if headless_mode
            else [
                "--disable-blink-features=AutomationControlled",
            ]
        ),  # 在可视化模式下减少启动参数，避免影响显示
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        ignore_https_errors=True,
        java_script_enabled=True,
        bypass_csp=True,
    )

    context.set_default_timeout(args.timeout * 1000)
    return browser, context


def _setup_cache_and_progress(args, base_url_normalized):
    """设置缓存和进度状态"""
    cache_id = calculate_cache_id(
        base_url_normalized,
        args.content_selector,
        args.toc_selector,
        args.max_depth,
        args.url_pattern,
    )
    cache_dir = get_cache_directory(cache_id)
    
    # 如果指定了 --restart，先清理缓存
    if args.restart:
        logger.info("检测到 --restart 参数，清理之前的缓存和进度...")
        cleanup_cache_directory(cache_dir)
        logger.info("缓存清理完成，将重新开始爬取")
    
    use_cache = True  # 总是使用缓存，但如果指定了 restart 则先清理

    logger.info(f"缓存目录: {cache_dir}")
    logger.info(f"缓存模式: {'重新开始' if args.restart else '启用'}")

    # 初始化或恢复进度状态
    progress_state, is_resumed = _initialize_or_resume_progress(
        base_url_normalized,
        args.output_pdf,
        args.max_depth,
        cache_dir,
        use_cache and not args.restart,  # 如果是重新开始，不恢复进度
    )

    # 设置信号处理器，支持中断恢复
    setup_signal_handlers(progress_state)

    if is_resumed and not args.restart:
        logger.info("发现未完成的爬取任务，自动继续执行...")
    elif args.restart:
        logger.info("重新开始爬取任务...")
    else:
        logger.info("开始新的爬取任务...")

    return cache_dir, use_cache, progress_state


def _execute_crawling_workflow(
    context,
    args,
    base_url_normalized,
    url_pattern,
    url_blacklist_patterns,
    timeout_config,
    progress_state,
    domain_failure_tracker,
):
    """执行爬取工作流"""
    # 执行爬取（支持进度恢复）
    progress_state = _crawl_pages_with_progress(
        context,
        args,
        base_url_normalized,
        url_pattern,
        url_blacklist_patterns,
        timeout_config,
        progress_state,
        domain_failure_tracker,
    )

    # 如果有失败的URL，询问是否重试
    if progress_state.failed_urls and not args.skip_failed_retry:
        retry_pdf_files, retry_processed_urls = _interactive_retry_failed_urls(
            context,
            progress_state.failed_urls,
            args,
            base_url_normalized,
            timeout_config,
            url_blacklist_patterns,
            domain_failure_tracker,
        )

        # 合并重试成功的文件
        progress_state.pdf_files.extend(retry_pdf_files)
        progress_state.processed_urls.extend(retry_processed_urls)

    return progress_state


def main():
    parser = _create_argument_parser()
    args = parser.parse_args()

    # 处理清理命令
    if args.cleanup:
        _handle_cleanup_command(args)
        return

    # 初始化配置
    timeout_config, base_url_normalized, url_blacklist_patterns, url_pattern, domain_failure_tracker = (
        _initialize_configuration(args)
    )

    with sync_playwright() as p:
        browser, context = _setup_browser_context(p, args)
        cache_dir, use_cache, progress_state = _setup_cache_and_progress(args, base_url_normalized)

        try:
            progress_state = _execute_crawling_workflow(
                context,
                args,
                base_url_normalized,
                url_pattern,
                url_blacklist_patterns,
                timeout_config,
                progress_state,
                domain_failure_tracker,
            )

            logger.info("爬取完成，关闭浏览器...")
            browser.close()

            # 显示域名失败统计
            failure_summary = domain_failure_tracker.get_failure_summary()
            if failure_summary != "无域名失败记录":
                logger.info(f"\n📊 {failure_summary}")

            # 合并PDF文件
            _merge_pdfs(progress_state.pdf_files, progress_state.processed_urls, args)

            # 成功完成后自动清理缓存目录
            if use_cache:
                cleanup_cache_directory(cache_dir)

        except KeyboardInterrupt:
            logger.info("\n⚠️ 用户中断程序")
            logger.info(f"进度已保存到: {progress_state.progress_file}")
            logger.info(f"缓存目录: {cache_dir}")
            logger.info("下次运行时将自动继续（除非使用 --restart 参数重新开始）")
            browser.close()
            return
        except Exception:
            logger.exception("程序执行过程中发生错误")
            browser.close()
            raise


if __name__ == "__main__":
    main()
