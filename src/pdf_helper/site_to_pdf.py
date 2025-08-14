import re
import argparse
from pathlib import Path
from collections import deque
import tempfile
import time
from urllib.parse import urlparse, urljoin
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Tuple, Dict, Any, Optional

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
    
    while time.time() - wait_start_time < timeout:
        is_ready, status_msg, text_length, element_info = check_element_visibility_and_content(page, selector)
        
        if is_ready:
            logger.info(f"内容元素已找到且可见: {status_msg}")
            
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
            elapsed = time.time() - wait_start_time
            remaining = timeout - elapsed
            logger.info(f"元素状态: {status_msg}, 已等待 {elapsed:.1f}s, 剩余 {remaining:.1f}s")
        
        time.sleep(check_interval)
    
    elapsed = time.time() - wait_start_time
    logger.warning(f"{strategy}模式等待超时 ({elapsed:.1f}s)，元素仍不可见")
    return False

def process_page(context, url, content_selector, toc_selector, base_url, timeout_config: TimeoutConfig, 
                max_retries, debug_mode=False, debug_dir=None, verbose_mode=False, load_strategy="normal"):
    """处理单个页面并生成PDF，同时提取该页面内的链接"""
    page = context.new_page()
    pdf_path = None
    links = []
    final_url = url
    
    try:
        logger.info(f"准备处理页面: {url}")
        
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
                
                # 根据加载策略决定后续行为
                if load_strategy == "fast":
                    logger.info("快速加载模式：跳过网络空闲等待，但持续等待元素可见")
                    
                    if wait_for_element_visible(page, content_selector, timeout_config, "fast"):
                        break
                    elif attempt < max_retries - 1:
                        time.sleep(timeout_config.element_check_interval)
                
                elif load_strategy == "thorough":
                    logger.info("彻底加载模式：等待完全的网络空闲，然后持续等待元素可见")
                    
                    # 首先等待网络空闲
                    try:
                        page.wait_for_load_state("networkidle", timeout=timeout_config.base_timeout*1000)
                        logger.info("网络已达到空闲状态")
                    except PlaywrightTimeoutError:
                        logger.warning("网络空闲等待超时，继续等待元素可见")
                    
                    # 然后等待元素可见（使用剩余时间）
                    remaining_timeout = max(timeout_config.base_timeout // 2, timeout_config.thorough_min_timeout)
                    timeout_config_remaining = TimeoutConfig(remaining_timeout)
                    
                    if wait_for_element_visible(page, content_selector, timeout_config_remaining, "thorough"):
                        break
                
                else:  # normal strategy (智能等待)
                    if wait_for_element_visible(page, content_selector, timeout_config, "normal"):
                        break
                
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
            return None, links, url
        
        final_url = page.url
        if final_url != url:
            logger.info(f"重定向: {url} -> {final_url}")
        
        try:
            logger.info(f"开始提取导航链接: {toc_selector}")
            resolved_toc = resolve_selector(toc_selector)
            
            toc_element = page.query_selector(resolved_toc)
            if not toc_element:
                logger.warning(f"导航元素不存在: {resolved_toc}")
            else:
                a_elements = toc_element.query_selector_all("a")
                logger.info(f"找到 {len(a_elements)} 个链接元素")
                
                links = []
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
        
        content_element = page.query_selector(resolve_selector(content_selector))
        if content_element:
            if verbose_mode:
                page.evaluate('''() => {
                    document.title = "[分析内容...] " + document.title.replace(/^\[.*?\] /, "");
                }''')
            
            logger.info("分析内容元素...")
            
            # 使用统一的元素检查函数
            is_ready, status_msg, text_length, element_info = check_element_visibility_and_content(page, content_selector)
            
            if not is_ready:
                logger.error(f"内容元素不可见，跳过PDF生成！{status_msg}")
                return None, links, final_url
            
            logger.info(f"内容元素信息: {element_info}")
            
            # 如果内容为空，记录警告但继续（可能是动态加载）
            if text_length == 0:
                logger.warning(f"警告：内容元素没有文本内容！可能是动态加载或空页面")
            elif text_length < 50:
                logger.warning(f"警告：内容元素文本很少 ({text_length} 字符)！")
                
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
            
            # 调试模式：保存截图
            if debug_mode and debug_dir:
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
                
        else:
            logger.error(f"页面 {final_url} 中未找到内容节点: {content_selector}")
            return None, links, final_url
        
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
        
        temp_file = Path(tempfile.mktemp(suffix='.pdf'))
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
            
            return temp_file, links, final_url
        except Exception as pdf_err:
            logger.error(f"生成PDF失败: {pdf_err}")
            return None, links, final_url
    
    except Exception as e:
        logger.error(f"处理页面失败: {url}\n错误: {str(e)}", exc_info=True)
        return None, links, final_url
    
    finally:
        try:
            page.close()
            logger.info(f"已关闭页面: {url}")
        except Exception as close_err:
            logger.warning(f"关闭页面时出错: {str(close_err)}")

def main():
    parser = argparse.ArgumentParser(description="Webpage to PDF converter")
    parser.add_argument("--base-url", required=True, help="起始URL")
    parser.add_argument("--url-pattern", default=None, help="URL匹配模式正则表达式")
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
    args = parser.parse_args()
    
    logger.info(f"开始执行PDF爬虫程序，超时设置: {args.timeout}秒")
    
    # 创建超时配置对象
    timeout_config = TimeoutConfig(args.timeout)
    logger.info(f"超时配置 - 基础: {timeout_config.base_timeout}s, 快速模式: {timeout_config.fast_mode_timeout}s, "
               f"初始加载: {timeout_config.initial_load_timeout}ms, 页面渲染: {timeout_config.page_render_wait}s")
    
    base_url_normalized = normalize_url(args.base_url, args.base_url)
    logger.info(f"标准化基准URL: {base_url_normalized}")
    
    temp_dir = tempfile.TemporaryDirectory()
    logger.info(f"临时目录创建: {temp_dir.name}")
    
    base_domain = urlparse(base_url_normalized).netloc
    default_pattern = f"https?://{re.escape(base_domain)}/.*"
    url_pattern = re.compile(args.url_pattern or default_pattern)
    logger.info(f"使用URL匹配模式: {url_pattern.pattern}")
    
    visited = set()
    enqueued = set()
    queue = deque([(base_url_normalized, 0)])
    enqueued.add(base_url_normalized)
    
    pdf_files = []
    processed_urls = []
    
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
        logger.info(f"开始爬取，最大深度: {args.max_depth}")
        
        while queue:
            url, depth = queue.popleft()
            logger.info(f"处理: {url} (深度: {depth})")
            
            if depth > args.max_depth:
                logger.warning(f"超过最大深度限制({args.max_depth})，跳过: {url}")
                continue
                
            if url in visited:
                logger.info(f"已访问过，跳过: {url}")
                continue
                
            try:
                pdf_path, links, final_url = process_page(
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
                    args.load_strategy
                )
                
                visited.add(url)
                visited.add(final_url)
                
                if pdf_path and pdf_path.exists():
                    pdf_files.append(pdf_path)
                    processed_urls.append(url)
                    logger.info(f"成功生成PDF: {pdf_path}")
                else:
                    logger.warning(f"页面未生成PDF: {url}")
                
                for link in links:
                    if not link:
                        continue
                        
                    norm_url = normalize_url(link, base_url_normalized)
                    
                    if not url_pattern.match(norm_url):
                        logger.debug(f"跳过不符合模式的URL: {norm_url}")
                        continue
                    
                    if norm_url in visited or norm_url in enqueued:
                        logger.debug(f"已存在，跳过URL: {norm_url}")
                        continue
                    
                    logger.info(f"添加新URL到队列: {norm_url} (深度: {depth+1})")
                    queue.append((norm_url, depth + 1))
                    enqueued.add(norm_url)
                
            except Exception as e:
                logger.exception(f"处理 {url} 时发生错误")
                visited.add(url)
    
        logger.info(f"爬取完成，关闭浏览器...")
        browser.close()
    
    if not pdf_files:
        logger.error("未生成任何PDF，请检查参数")
        return
    
    logger.info(f"准备合并 {len(pdf_files)} 个PDF文件")
    
    base_path = Path(args.output_pdf)
    stem = base_path.stem
    suffix = base_path.suffix if base_path.suffix else '.pdf'
    output_dir = base_path.parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    merger = PdfMerger()
    current_pages = 0
    file_index = 1
    merged_files = []

    for i, pdf_file in enumerate(pdf_files):
        try:
            if not pdf_file.exists():
                logger.warning(f"PDF文件不存在: {pdf_file}")
                continue
                
            with open(pdf_file, 'rb') as f:
                reader = PdfReader(f)
                num_pages = len(reader.pages)
                logger.debug(f"处理PDF文件: {pdf_file}, 页数: {num_pages}")
                
                if current_pages > 0 and current_pages + num_pages > args.max_page:
                    output_name = f"{stem}.{file_index}{suffix}"
                    output_path = output_dir / output_name
                    
                    logger.info(f"写入分卷 {output_path} (页数: {current_pages})")
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
        
        logger.info(f"写入最终PDF: {output_path} (页数: {current_pages})")
        with open(output_path, 'wb') as out:
            merger.write(out)
        merged_files.append(str(output_path))
    
    if merged_files:
        logger.info(f"处理完成! 共处理 {len(processed_urls)} 个页面，生成长 {len(merged_files)} 个PDF文件")
        logger.info(f"输出文件: {', '.join(merged_files)}")
    else:
        logger.error("没有PDF文件生成")

if __name__ == "__main__":
    main()