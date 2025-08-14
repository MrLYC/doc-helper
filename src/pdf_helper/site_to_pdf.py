import re
import argparse
from pathlib import Path
from collections import deque
import tempfile
import shutil
import time
from urllib.parse import urlparse, urljoin
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Tuple, Dict, Any, Optional, List
import json
import hashlib
import signal
import sys
import os

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PyPDF2 import PdfMerger, PdfReader

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
            'base_url': self.base_url,
            'output_pdf': self.output_pdf,
            'temp_dir': self.temp_dir,
            'visited_urls': list(self.visited_urls),
            'failed_urls': self.failed_urls,
            'processed_urls': self.processed_urls,
            'pdf_files': [str(f) for f in self.pdf_files],
            'queue': list(self.queue),
            'enqueued': list(self.enqueued)
        }
        
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"进度已保存到: {self.progress_file}")
    
    @classmethod
    def load_from_file(cls, progress_file: str):
        """从文件加载进度"""
        if not os.path.exists(progress_file):
            return None
        
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
            
            # 验证临时PDF文件是否存在
            valid_pdf_files = []
            for pdf_file_str in state_data.get('pdf_files', []):
                pdf_path = Path(pdf_file_str)
                if pdf_path.exists():
                    valid_pdf_files.append(pdf_path)
                else:
                    logger.warning(f"临时PDF文件不存在，已从进度中移除: {pdf_file_str}")
            
            progress = cls(
                base_url=state_data.get('base_url', ''),
                output_pdf=state_data.get('output_pdf', ''),
                temp_dir=state_data.get('temp_dir', ''),
                progress_file=progress_file,
                visited_urls=set(state_data.get('visited_urls', [])),
                failed_urls=state_data.get('failed_urls', []),
                processed_urls=state_data.get('processed_urls', []),
                pdf_files=valid_pdf_files,
                queue=deque(state_data.get('queue', [])),
                enqueued=set(state_data.get('enqueued', []))
            )
            
            logger.info(f"从进度文件恢复状态: 已处理 {len(progress.processed_urls)} 个URL，"
                       f"队列中还有 {len(progress.queue)} 个URL")
            
            return progress
            
        except Exception as e:
            logger.error(f"加载进度文件失败: {e}")
            return None

def url_to_filename(url: str) -> str:
    """将URL转换为安全的文件名"""
    # 使用URL的哈希值作为文件名的一部分，确保唯一性
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
    
    # 清理URL用作文件名
    safe_name = re.sub(r'[^\w\-_\.]', '_', url.replace('https://', '').replace('http://', ''))
    safe_name = safe_name[:50]  # 限制长度
    
    return f"{safe_name}_{url_hash}.pdf"

def setup_signal_handlers(progress_state: ProgressState):
    """设置信号处理器，用于优雅退出"""
    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，正在保存进度...")
        progress_state.save_to_file()
        logger.info("进度已保存，程序退出")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 终止信号

def create_progress_file_path(output_pdf: str, base_url: str) -> str:
    """创建进度文件路径"""
    output_path = Path(output_pdf)
    base_name = output_path.stem
    
    # 使用base_url的哈希值确保唯一性
    url_hash = hashlib.md5(base_url.encode('utf-8')).hexdigest()[:8]
    
    progress_file = output_path.parent / f".{base_name}_{url_hash}.progress"
    return str(progress_file)

def cleanup_temp_files(temp_dir: str, progress_file: str = None):
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
        scheme=base_parsed.scheme or 'https',
        path=urllib.parse.unquote(parsed.path) if parsed.path else '',
        fragment='',
        query=parsed.query
    )
    
    # 生成规范化URL字符串
    normalized_url = normalized.geturl()
    
    # 处理重复斜杠
    normalized_url = re.sub(r'([^:])//+', r'\1/', normalized_url)
    
    # 统一协议处理
    if normalized_url.startswith("http://"):
        normalized_url = "https://" + normalized_url[7:]
    
    return normalized_url

def resolve_selector(selector):
    """智能解析选择器"""
    if selector.startswith('/'):
        if not selector.startswith('//'):
            return f'selector=/{selector[1:]}'
        return f'selector={selector}'
    return selector

def check_element_visibility_and_content(page, selector: str) -> Tuple[bool, str, int, Dict[str, Any]]:
    """检查元素是否存在、可见且有足够内容"""
    element = page.query_selector(resolve_selector(selector))
    if not element:
        return False, "元素不存在", 0, {}
    
    element_info = page.evaluate('''(el) => {
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
    }''', element)
    
    # 检查可见性
    is_visible = (element_info['isVisible'] and 
                element_info['display'] != 'none' and 
                element_info['visibility'] != 'hidden' and 
                element_info['opacity'] > 0.1)
    
    if not is_visible:
        reason = f"元素不可见 (display:{element_info['display']}, visibility:{element_info['visibility']}, opacity:{element_info['opacity']}, size:{element_info['width']}x{element_info['height']})"
        return False, reason, element_info['textLength'], element_info
    
    return True, "元素可见", element_info['textLength'], element_info

def wait_for_element_visible(page, selector: str, timeout_config: TimeoutConfig, 
                           strategy: str = "normal") -> bool:
    """等待元素可见的通用函数"""
    if strategy == "fast":
        timeout = timeout_config.fast_mode_timeout
        check_interval = timeout_config.fast_check_interval
        logger.info(f"快速等待元素可见，最大等待时间 {timeout} 秒")
    elif strategy == "thorough":
        # thorough模式由调用方计算剩余时间
        timeout = timeout_config.base_timeout  
        check_interval = timeout_config.element_check_interval
        logger.info(f"彻底模式：持续等待元素可见，剩余等待时间 {timeout:.1f} 秒")
    else:  # normal
        timeout = timeout_config.base_timeout
        check_interval = timeout_config.element_check_interval
        logger.info(f"智能等待模式：持续等待元素可见，最大等待时间 {timeout} 秒")
    
    wait_start_time = time.time()
    consecutive_failures = 0  # 连续失败次数
    max_consecutive_failures = 3  # 最大连续失败次数，超过后快速失败
    
    while time.time() - wait_start_time < timeout:
        is_ready, status_msg, text_length, element_info = check_element_visibility_and_content(page, selector)
        
        if is_ready:
            logger.info(f"内容元素已找到且可见: {status_msg}")
            consecutive_failures = 0  # 重置失败计数
            
            if strategy == "normal":
                # Normal模式有更复杂的内容检查逻辑
                if text_length > 100:  # 如果已经有足够内容，直接成功
                    logger.info(f"内容充足 ({text_length} 字符)，完成等待")
                    return True
                elif text_length > 0:
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
                else:
                    logger.info("元素可见但无文本内容，继续等待...")
            else:
                # Fast和Thorough模式只要元素可见就成功
                return True
        else:
            consecutive_failures += 1
            elapsed = time.time() - wait_start_time
            remaining = timeout - elapsed
            
            # 如果是"元素不存在"且连续失败多次，可能是外部链接，快速失败
            if "元素不存在" in status_msg and consecutive_failures >= max_consecutive_failures:
                logger.warning(f"元素连续 {consecutive_failures} 次不存在，可能是外部链接或无效页面，快速失败")
                return False
            
            logger.info(f"元素状态: {status_msg}, 已等待 {elapsed:.1f}s, 剩余 {remaining:.1f}s, 连续失败: {consecutive_failures}")
        
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

def _setup_slow_request_monitoring(page):
    """设置慢请求监控（仅用于thorough模式）"""
    slow_requests = {}
    
    def on_request(request):
        slow_requests[request.url] = time.time()
    
    def on_response(response):
        request_url = response.url
        if request_url in slow_requests:
            duration = time.time() - slow_requests[request_url]
            if duration > 3.0:  # 超过3秒的请求
                logger.warning(f"加载缓慢的资源 ({duration:.1f}s): {request_url}")
            del slow_requests[request_url]
    
    def on_request_failed(request):
        if request.url in slow_requests:
            del slow_requests[request.url]
    
    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    
    return slow_requests

def _handle_page_loading_with_retries(page, url, content_selector, timeout_config, max_retries, 
                                    verbose_mode, load_strategy, url_blacklist_patterns=None):
    """处理页面加载和重试逻辑"""
    
    def _apply_load_strategy(page, content_selector, timeout_config, load_strategy, slow_requests):
        """应用特定的加载策略"""
        if load_strategy == "fast":
            logger.info("快速加载模式：跳过网络空闲等待，但持续等待元素可见")
            return wait_for_element_visible(page, content_selector, timeout_config, "fast")
        
        elif load_strategy == "thorough":
            logger.info("彻底加载模式：等待完全的网络空闲，然后持续等待元素可见")
            
            # 首先等待网络空闲
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_config.base_timeout*1000)
                logger.info("网络已达到空闲状态")
            except PlaywrightTimeoutError:
                logger.warning("网络空闲等待超时，继续等待元素可见")
                # 在thorough模式下，打印还在加载的慢请求
                if slow_requests:
                    logger.warning(f"仍有 {len(slow_requests)} 个请求未完成:")
                    for req_url in list(slow_requests.keys())[:5]:  # 只显示前5个
                        duration = time.time() - slow_requests[req_url]
                        logger.warning(f"  - {duration:.1f}s: {req_url}")
            
            # 然后等待元素可见（使用剩余时间）
            remaining_timeout = max(timeout_config.base_timeout // 2, timeout_config.thorough_min_timeout)
            timeout_config_remaining = TimeoutConfig(remaining_timeout)
            return wait_for_element_visible(page, content_selector, timeout_config_remaining, "thorough")
        
        else:  # normal strategy (智能等待)
            return wait_for_element_visible(page, content_selector, timeout_config, "normal")
    
    # 设置请求拦截
    _setup_request_blocking(page, url_blacklist_patterns)
    
    # 设置慢请求监控（仅在thorough模式下）
    slow_requests = None
    if load_strategy == "thorough":
        slow_requests = _setup_slow_request_monitoring(page)
    
    for attempt in range(max_retries):
        try:
            logger.info(f"尝试加载页面 ({attempt+1}/{max_retries}): {url}")
            
            if verbose_mode:
                logger.info("可视化模式：等待页面基本加载...")
            
            # 先尝试快速加载到 domcontentloaded 状态
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_config.initial_load_timeout)
            logger.info("页面DOM已加载完成")
            
            if verbose_mode:
                # 在页面标题中显示处理状态
                try:
                    page.evaluate('''() => {
                        document.title = "[检查内容...] " + (document.title || "页面");
                    }''')
                except:
                    pass
            
            # 应用加载策略
            if _apply_load_strategy(page, content_selector, timeout_config, load_strategy, slow_requests):
                return page.url  # 返回最终URL
            elif attempt < max_retries - 1:
                time.sleep(timeout_config.element_check_interval)
            
        except PlaywrightTimeoutError as timeout_err:
            if "Timeout" in str(timeout_err) and "goto" in str(timeout_err):
                logger.warning(f"第 {attempt+1} 次页面加载超时: {timeout_err}")
            else:
                logger.warning(f"第 {attempt+1} 次操作超时: {timeout_err}")
                
            if attempt == max_retries - 1:
                logger.error("所有重试均失败，跳过此页面")
                raise
                
            # 指数退避重试
            wait_time = min(2 ** attempt, timeout_config.retry_backoff_max)
            logger.info(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)
        
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"所有重试均失败: {str(e)}")
                raise
            logger.warning(f"第 {attempt+1} 次页面加载异常: {str(e)}，重试中...")
            wait_time = min(2 ** attempt, timeout_config.retry_backoff_max)
            time.sleep(wait_time)
    else:
        logger.error("所有重试均失败，跳过此页面")
        raise Exception("所有重试均失败")

def _extract_page_links(page, toc_selector, final_url, base_url):
    """提取页面中的导航链接"""
    links = []
    try:
        logger.info(f"开始提取导航链接: {toc_selector}")
        resolved_toc = resolve_selector(toc_selector)
        
        toc_element = page.query_selector(resolved_toc)
        if not toc_element:
            logger.warning(f"导航元素不存在: {resolved_toc}")
            return links
        
        a_elements = toc_element.query_selector_all("a")
        logger.info(f"找到 {len(a_elements)} 个链接元素")
        
        for a in a_elements:
            href = a.get_attribute("href")
            if href and href.strip():
                abs_url = urljoin(final_url, href.strip())
                norm_url = normalize_url(abs_url, base_url)
                links.append(norm_url)
        
        links = list(set(links))
        logger.info(f"提取到 {len(links)} 个唯一链接")
        
    except Exception as e:
        logger.error(f"提取导航链接失败: {e}", exc_info=True)
    
    return links

def _clean_page_content(page, content_element, verbose_mode, timeout_config):
    """清理页面内容，保留主要内容"""
    logger.info("清理页面并保留主要内容...")
    
    # 保存原始内容用于对比
    original_content = page.evaluate('''(element) => {
        return {
            textLength: element.textContent ? element.textContent.trim().length : 0,
            innerHTML: element.innerHTML.substring(0, 200) + '...'
        };
    }''', content_element)
    logger.info(f"清理前内容预览: 文本长度={original_content['textLength']}, HTML片段={original_content['innerHTML']}")
    
    if verbose_mode:
        page.evaluate('''() => {
            document.title = "[清理页面...] " + document.title.replace(/^\[.*?\] /, "");
        }''')
        # 在可视化模式下，稍微延迟一下让用户看到原始页面
        time.sleep(timeout_config.element_check_interval)
    
    # 新的清理逻辑：逐级向上清理DOM
    page.evaluate('''(element) => {
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
    }''', content_element)
    
    # 检查清理后的内容
    after_cleanup = page.evaluate('''(element) => {
        const rect = element.getBoundingClientRect();
        return {
            textLength: element.textContent ? element.textContent.trim().length : 0,
            hasVisibleContent: rect.width > 0 && rect.height > 0,
            width: rect.width,
            height: rect.height,
            innerHTML: element.innerHTML.substring(0, 200) + '...'
        };
    }''', content_element)
    logger.info(f"清理后内容检查: 文本长度={after_cleanup['textLength']}, 可见={after_cleanup['hasVisibleContent']}, 尺寸={after_cleanup['width']}x{after_cleanup['height']}")
    
    # 如果清理后内容明显减少，发出警告
    if after_cleanup['textLength'] < original_content['textLength'] * 0.8:
        logger.warning(f"警告：清理后内容大幅减少！原始: {original_content['textLength']} -> 清理后: {after_cleanup['textLength']}")

def _save_debug_screenshot(page, url, debug_dir):
    """保存调试截图"""
    debug_path = Path(debug_dir)
    debug_path.mkdir(exist_ok=True)
    
    # 清理URL作为文件名
    safe_url = re.sub(r'[^\w\-_\.]', '_', url.replace('https://', '').replace('http://', ''))[:50]
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
        page.evaluate('''() => {
            document.title = "[分析内容...] " + document.title.replace(/^\[.*?\] /, "");
        }''')
    
    logger.info("分析内容元素...")
    
    # 使用统一的元素检查函数
    is_ready, status_msg, text_length, element_info = check_element_visibility_and_content(page, content_selector)
    
    if not is_ready:
        logger.error(f"内容元素不可见，跳过PDF生成！{status_msg}")
        return False
    
    logger.info(f"内容元素信息: {element_info}")
    
    # 如果内容为空，记录警告但继续（可能是动态加载）
    if text_length == 0:
        logger.warning(f"警告：内容元素没有文本内容！可能是动态加载或空页面")
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
        page.evaluate('''() => {
            document.title = "[准备生成PDF...] " + document.title.replace(/^\[.*?\] /, "");
        }''')
        time.sleep(timeout_config.element_check_interval)  # 在可视化模式下给用户更多时间观察
    
    time.sleep(timeout_config.page_render_wait)  # 使用配置的页面渲染等待时间
    
    # 在生成PDF前做最后的内容检查
    final_check = page.evaluate('''() => {
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
    }''')
    logger.info(f"PDF生成前最终检查: {final_check}")
    
    if final_check['bodyTextLength'] == 0:
        logger.error("严重警告：页面内容为空，将生成空白PDF！")
    elif final_check['bodyTextLength'] < 50:
        logger.warning(f"警告：页面内容很少 ({final_check['bodyTextLength']} 字符)，可能生成近似空白的PDF")
    
    # 使用持久化的文件名
    filename = url_to_filename(url)
    temp_file = Path(temp_dir) / filename
    logger.info(f"生成PDF: {temp_file}")
    
    try:
        page.pdf(
            path=str(temp_file),
            format='A4',
            print_background=True,
            margin={'top': '1cm', 'right': '1cm', 'bottom': '1cm', 'left': '1cm'},
            scale=0.95
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

def process_page_with_failure_tracking(context, url, content_selector, toc_selector, base_url, timeout_config: TimeoutConfig, 
                max_retries, debug_mode=False, debug_dir=None, verbose_mode=False, load_strategy="normal", 
                url_blacklist_patterns=None, temp_dir=None):
    """处理单个页面并生成PDF，同时提取该页面内的链接，包含失败跟踪"""
    
    # 检查是否已经处理过这个URL（根据PDF文件是否存在）
    if temp_dir:
        expected_pdf = Path(temp_dir) / url_to_filename(url)
        if expected_pdf.exists() and expected_pdf.stat().st_size > 1000:  # 文件存在且大小合理
            logger.info(f"发现已存在的PDF文件，跳过处理: {url}")
            # 仍然需要提取链接，所以继续处理，但跳过PDF生成
            pass
    
    page = context.new_page()
    pdf_path = None
    links = []
    final_url = url
    failure_reason = None
    
    try:
        logger.info(f"准备处理页面: {url}")
        
        # 处理页面加载和重试逻辑
        try:
            final_url = _handle_page_loading_with_retries(
                page, url, content_selector, timeout_config, max_retries, 
                verbose_mode, load_strategy, url_blacklist_patterns
            )
        except Exception as e:
            failure_reason = f"页面加载失败: {str(e)}"
            logger.warning(f"页面加载失败，将记录为待重试: {url} - {failure_reason}")
            return None, [], url, failure_reason
        
        if final_url != url:
            logger.info(f"重定向: {url} -> {final_url}")
        
        # 提取页面链接
        links = _extract_page_links(page, toc_selector, final_url, base_url)
        
        # 如果PDF已存在，直接返回
        if temp_dir:
            expected_pdf = Path(temp_dir) / url_to_filename(url)
            if expected_pdf.exists() and expected_pdf.stat().st_size > 1000:
                return expected_pdf, links, final_url, None
        
        # 准备页面内容用于PDF生成
        if not _prepare_page_for_pdf(page, content_selector, verbose_mode, timeout_config, debug_mode, debug_dir, url):
            failure_reason = "内容元素不可见或不存在"
            logger.warning(f"页面内容准备失败，将记录为待重试: {url} - {failure_reason}")
            return None, links, final_url, failure_reason
        
        # 生成PDF
        if not temp_dir:
            temp_dir = tempfile.mkdtemp()
            
        pdf_path = _generate_pdf_from_page(page, verbose_mode, timeout_config, temp_dir, url)
        
        if not pdf_path:
            failure_reason = "PDF生成失败"
            logger.warning(f"PDF生成失败，将记录为待重试: {url} - {failure_reason}")
            return None, links, final_url, failure_reason
        
        return pdf_path, links, final_url, None
    
    except Exception as e:
        failure_reason = f"处理页面异常: {str(e)}"
        logger.error(f"处理页面失败: {url}\n错误: {str(e)}", exc_info=True)
        return None, links, final_url, failure_reason
    
    finally:
        try:
            page.close()
            logger.info(f"已关闭页面: {url}")
        except Exception as close_err:
            logger.warning(f"关闭页面时出错: {str(close_err)}")

def process_page(context, url, content_selector, toc_selector, base_url, timeout_config: TimeoutConfig, 
                max_retries, debug_mode=False, debug_dir=None, verbose_mode=False, load_strategy="normal", 
                url_blacklist_patterns=None, temp_dir=None):
    """处理单个页面并生成PDF，同时提取该页面内的链接"""
    pdf_path, links, final_url, _ = process_page_with_failure_tracking(
        context, url, content_selector, toc_selector, base_url, timeout_config,
        max_retries, debug_mode, debug_dir, verbose_mode, load_strategy, url_blacklist_patterns, temp_dir
    )
    return pdf_path, links, final_url

def get_parent_path_pattern(base_url):
    """获取base_url的父目录作为默认URL匹配模式"""
    parsed = urlparse(base_url)
    path = parsed.path.rstrip('/')
    
    # 如果路径为空或者是根路径，使用域名
    if not path or path == '/':
        return f"https?://{re.escape(parsed.netloc)}/.*"
    
    # 获取父目录路径
    parent_path = '/'.join(path.split('/')[:-1])
    if not parent_path:
        parent_path = ''
    
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

def _initialize_or_resume_progress(base_url_normalized, output_file, max_depth):
    """初始化新的进度状态或从文件恢复进度状态"""
    progress_file = create_progress_file_path(base_url_normalized, output_file)
    
    if progress_file.exists():
        logger.info(f"发现进度文件: {progress_file}")
        try:
            progress_state = ProgressState.load_from_file(progress_file)
            logger.info(f"成功恢复进度状态:")
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
        output_file=output_file,
        max_depth=max_depth,
        progress_file=progress_file
    )
    
    # 初始化队列
    progress_state.queue.append((base_url_normalized, 0))
    progress_state.enqueued.add(base_url_normalized)
    
    logger.info("创建新的进度状态")
    return progress_state, False

def _crawl_pages_with_progress(context, args, base_url_normalized, url_pattern, url_blacklist_patterns, 
                              timeout_config, progress_state: ProgressState):
    """执行页面爬取逻辑，支持进度恢复"""
    
    logger.info(f"开始/继续爬取，最大深度: {args.max_depth}")
    
    # 创建临时目录（如果不存在）
    if not progress_state.temp_dir or not os.path.exists(progress_state.temp_dir):
        progress_state.temp_dir = tempfile.mkdtemp(prefix='site_to_pdf_')
        logger.info(f"创建临时目录: {progress_state.temp_dir}")
    
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
                context, 
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
                progress_state.temp_dir  # 传递临时目录
            )
            
            progress_state.visited_urls.add(url)
            progress_state.visited_urls.add(final_url)
            
            if pdf_path and pdf_path.exists():
                progress_state.pdf_files.append(pdf_path)
                progress_state.processed_urls.append(url)
                logger.info(f"✅ 成功生成PDF: {pdf_path}")
            else:
                if failure_reason:
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
            
            # 每处理一个URL就保存进度
            progress_state.save_to_file()
            
        except Exception as e:
            logger.exception(f"处理 {url} 时发生错误")
            progress_state.failed_urls.append((url, f"异常错误: {str(e)}"))
            progress_state.visited_urls.add(url)
            # 即使出错也要保存进度
            progress_state.save_to_file()
    
    # 最终统计
    success_count = len(progress_state.processed_urls)
    failed_count = len(progress_state.failed_urls)
    total_processed = success_count + failed_count
    
    logger.info(f"\n📈 爬取完成统计:")
    logger.info(f"   总共处理: {total_processed} 个URL")
    logger.info(f"   成功: {success_count} 个 ({success_count/total_processed*100:.1f}%)")
    logger.info(f"   失败: {failed_count} 个 ({failed_count/total_processed*100:.1f}%)")
    
    return progress_state

def _interactive_retry_failed_urls(context, failed_urls, args, base_url_normalized, timeout_config):
    """交互式重试失败的URL"""
    if not failed_urls:
        return [], []
    
    print(f"\n=== 发现 {len(failed_urls)} 个失败的URL ===")
    for i, (url, reason) in enumerate(failed_urls, 1):
        print(f"{i}. {url}")
        print(f"   失败原因: {reason}")
    
    # 如果启用了跳过失败重试选项，直接返回
    if args.skip_failed_retry:
        logger.info("启用了跳过失败重试选项，直接处理成功的页面")
        return [], []
    
    while True:
        try:
            choice = input(f"\n是否要重试失败的URL？\n"
                          f"1. 重试所有失败的URL\n"
                          f"2. 选择性重试\n"
                          f"3. 跳过所有失败的URL\n"
                          f"请选择 (1-3): ").strip()
            
            if choice == "3":
                logger.info("用户选择跳过所有失败的URL")
                return [], []
            elif choice == "1":
                urls_to_retry = [url for url, _ in failed_urls]
                break
            elif choice == "2":
                urls_to_retry = []
                for i, (url, reason) in enumerate(failed_urls, 1):
                    retry_choice = input(f"重试 URL {i}: {url} ? (y/n): ").strip().lower()
                    if retry_choice in ['y', 'yes', '是']:
                        urls_to_retry.append(url)
                break
            else:
                print("无效选择，请输入 1、2 或 3")
                continue
        except (EOFError, KeyboardInterrupt):
            logger.info("用户取消重试")
            return [], []
    
    if not urls_to_retry:
        logger.info("没有选择要重试的URL")
        return [], []
    
    # 询问重试次数
    while True:
        try:
            retry_count = input(f"重试次数 (1-10, 默认3): ").strip()
            if not retry_count:
                retry_count = 3
            else:
                retry_count = int(retry_count)
                if retry_count < 1 or retry_count > 10:
                    print("重试次数必须在1-10之间")
                    continue
            break
        except ValueError:
            print("请输入有效的数字")
            continue
        except (EOFError, KeyboardInterrupt):
            logger.info("用户取消重试")
            return [], []
    
    logger.info(f"开始重试 {len(urls_to_retry)} 个失败的URL，重试次数: {retry_count}")
    
    retry_pdf_files = []
    retry_processed_urls = []
    still_failed_urls = []
    
    for i, url in enumerate(urls_to_retry, 1):
        logger.info(f"🔄 重试进度: [{i}/{len(urls_to_retry)}] 处理: {url}")
        success = False
        
        for attempt in range(retry_count):
            try:
                pdf_path, _, final_url, failure_reason = process_page_with_failure_tracking(
                    context, 
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
                    []  # 重试时不应用黑名单，可能之前被误拦
                )
                
                if pdf_path and pdf_path.exists():
                    retry_pdf_files.append(pdf_path)
                    retry_processed_urls.append(url)
                    logger.info(f"✅ 重试成功: {url}")
                    success = True
                    break
                else:
                    logger.warning(f"⚠️ 重试第 {attempt + 1}/{retry_count} 次失败: {url} - {failure_reason}")
                    
            except Exception as e:
                logger.warning(f"⚠️ 重试第 {attempt + 1}/{retry_count} 次异常: {url} - {str(e)}")
        
        if not success:
            still_failed_urls.append((url, "重试后仍然失败"))
            logger.error(f"❌ 重试所有次数后仍然失败: {url}")
    
    # 重试结果统计
    retry_success_count = len(retry_processed_urls)
    retry_failed_count = len(still_failed_urls)
    logger.info(f"\n📊 重试结果统计:")
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
    suffix = base_path.suffix if base_path.suffix else '.pdf'
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
                
            with open(pdf_file, 'rb') as f:
                reader = PdfReader(f)
                num_pages = len(reader.pages)
                logger.debug(f"   文件页数: {num_pages}")
                
                if current_pages > 0 and current_pages + num_pages > args.max_page:
                    output_name = f"{stem}.{file_index}{suffix}"
                    output_path = output_dir / output_name
                    
                    logger.info(f"📚 写入分卷 {output_path} (页数: {current_pages})")
                    with open(output_path, 'wb') as out:
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
        with open(output_path, 'wb') as out:
            merger.write(out)
        merged_files.append(str(output_path))
    
    if merged_files:
        logger.info(f"🎉 处理完成! 共处理 {len(processed_urls)} 个页面，生成 {len(merged_files)} 个PDF文件")
        logger.info(f"📁 输出文件: {', '.join(merged_files)}")
    else:
        logger.error("没有PDF文件生成")
    
    return merged_files

def main():
    parser = argparse.ArgumentParser(description="Webpage to PDF converter")
    parser.add_argument("--base-url", required=True, help="起始URL")
    parser.add_argument("--url-pattern", default=None, help="URL匹配模式正则表达式")
    parser.add_argument("--url-blacklist", action="append", default=[], 
                       help="URL黑名单模式正则表达式，可指定多个，阻止浏览器加载匹配的URL")
    parser.add_argument("--content-selector", required=True, help="内容容器选择器")
    parser.add_argument("--toc-selector", required=True, help="链接提取选择器")
    parser.add_argument("--output-pdf", required=True, help="输出PDF路径")
    parser.add_argument("--max-page", type=int, default=10000, help="单PDF最大页数")
    parser.add_argument("--timeout", type=int, default=120, help="页面加载超时时间（秒）")
    parser.add_argument("--max-depth", type=int, default=10, help="最大爬取深度")
    parser.add_argument("--max-retries", type=int, default=3, help="失败重试次数")
    parser.add_argument("--debug", action="store_true", help="启用调试模式，保存页面截图")
    parser.add_argument("--debug-dir", default="debug_screenshots", help="调试截图保存目录")
    parser.add_argument("--verbose", action="store_true", help="显示浏览器界面，便于观察处理过程")
    parser.add_argument("--fast-load", action="store_true", help="快速加载模式，跳过网络空闲等待")
    parser.add_argument("--load-strategy", choices=["fast", "normal", "thorough"], default="normal", 
                       help="页面加载策略：fast=仅等待DOM, normal=智能等待, thorough=完全等待网络空闲")
    parser.add_argument("--skip-failed-retry", action="store_true", 
                       help="跳过失败URL的交互式重试，直接处理成功的页面")
    parser.add_argument("--resume", action="store_true", 
                       help="自动恢复之前中断的爬取任务（如果存在）")
    parser.add_argument("--cleanup", action="store_true", 
                       help="清理指定URL和输出文件对应的临时文件和进度文件")
    args = parser.parse_args()
    
    # 处理清理命令
    if args.cleanup:
        base_url_normalized = normalize_url(args.base_url)
        cleanup_temp_files(base_url_normalized, args.output_pdf)
        logger.info("清理完成")
        return
    
    logger.info(f"开始执行PDF爬虫程序，超时设置: {args.timeout}秒")
    
    # 创建超时配置对象
    timeout_config = TimeoutConfig(args.timeout)
    logger.info(f"超时配置 - 基础: {timeout_config.base_timeout}s, 快速模式: {timeout_config.fast_mode_timeout}s, "
               f"初始加载: {timeout_config.initial_load_timeout}ms, 页面渲染: {timeout_config.page_render_wait}s")
    
    base_url_normalized = normalize_url(args.base_url, args.base_url)
    logger.info(f"标准化基准URL: {base_url_normalized}")
    
    # 编译URL黑名单模式
    url_blacklist_patterns = compile_blacklist_patterns(args.url_blacklist)
    if url_blacklist_patterns:
        logger.info(f"配置了 {len(url_blacklist_patterns)} 个URL黑名单模式")
    
    temp_dir = tempfile.TemporaryDirectory()
    logger.info(f"临时目录创建: {temp_dir.name}")
    
    # 修改默认URL模式：使用父目录而非域名
    if args.url_pattern:
        url_pattern = re.compile(args.url_pattern)
        logger.info(f"使用自定义URL匹配模式: {url_pattern.pattern}")
    else:
        default_pattern = get_parent_path_pattern(base_url_normalized)
        url_pattern = re.compile(default_pattern)
        logger.info(f"使用默认URL匹配模式（基于父目录）: {url_pattern.pattern}")
    
    with sync_playwright() as p:
        # 根据verbose参数决定是否显示浏览器界面
        headless_mode = not args.verbose
        if args.verbose:
            logger.info("启用可视化模式 - 浏览器界面将显示处理过程")
        else:
            logger.info("使用无头模式 - 浏览器在后台运行")
            
        browser = p.chromium.launch(
            headless=headless_mode, 
            args=[
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled'
            ] if headless_mode else [
                '--disable-blink-features=AutomationControlled'
            ]  # 在可视化模式下减少启动参数，避免影响显示
        )
        context = browser.new_context(
            viewport={'width': 1366, 'height': 768},
            ignore_https_errors=True,
            java_script_enabled=True,
            bypass_csp=True
        )
        
        context.set_default_timeout(args.timeout * 1000)
        
        # 设置信号处理器，支持中断恢复
        setup_signal_handlers()
        
        # 初始化或恢复进度状态
        progress_state, is_resumed = _initialize_or_resume_progress(
            base_url_normalized, args.output_pdf, args.max_depth
        )
        
        if is_resumed and not args.resume:
            response = input("发现未完成的爬取任务，是否继续？[y/N]: ").strip().lower()
            if response not in ['y', 'yes']:
                logger.info("用户选择不继续，退出")
                browser.close()
                return
        
        try:
            # 执行爬取（支持进度恢复）
            progress_state = _crawl_pages_with_progress(
                context, args, base_url_normalized, url_pattern, 
                url_blacklist_patterns, timeout_config, progress_state
            )
            
            # 如果有失败的URL，询问是否重试
            if progress_state.failed_urls and not args.skip_failed_retry:
                retry_pdf_files, retry_processed_urls = _interactive_retry_failed_urls(
                    context, progress_state.failed_urls, args, base_url_normalized, timeout_config
                )
                
                # 合并重试成功的文件
                progress_state.pdf_files.extend(retry_pdf_files)
                progress_state.processed_urls.extend(retry_processed_urls)
            
            logger.info(f"爬取完成，关闭浏览器...")
            browser.close()
            
            # 合并PDF文件
            _merge_pdfs(progress_state.pdf_files, progress_state.processed_urls, args)
            
            # 成功完成后清理临时文件
            if progress_state.temp_dir and os.path.exists(progress_state.temp_dir):
                logger.info("清理临时文件...")
                shutil.rmtree(progress_state.temp_dir)
            
            # 删除进度文件
            if progress_state.progress_file and progress_state.progress_file.exists():
                progress_state.progress_file.unlink()
                logger.info("删除进度文件")
        
        except KeyboardInterrupt:
            logger.info("\n⚠️ 用户中断程序")
            logger.info(f"进度已保存到: {progress_state.progress_file}")
            logger.info(f"临时文件位于: {progress_state.temp_dir}")
            logger.info("下次运行时可使用 --resume 参数继续")
            browser.close()
            return
        except Exception as e:
            logger.exception("程序执行过程中发生错误")
            browser.close()
            raise

if __name__ == "__main__":
    main()
