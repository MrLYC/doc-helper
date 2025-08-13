import os
import argparse
import logging
import sys
import time
import tempfile
import re
from multiprocessing import Pool, cpu_count
from weasyprint import HTML, CSS, default_url_fetcher
from weasyprint.text.fonts import FontConfiguration
from PyPDF2 import PdfMerger, PdfReader
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 增强的全局CSS样式表 (专为复杂表格优化)
GLOBAL_CSS = """
@charset "UTF-8";
@page {
    margin: 1cm;  /* 减少边距增加可用宽度 */
    size: A4;
    @top-left {
        content: " ";
    }
    @top-right {
        content: " ";
    }
}
body {
    font-family: "DejaVu Sans", "Noto Sans", "Source Sans Pro", Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: #333;
    margin: 0 auto;
    text-rendering: optimizeLegibility;
}
h1, h2, h3, h4 {
    page-break-after: avoid;
    font-family: "DejaVu Sans", "Noto Sans", sans-serif;
}
pre, code, blockquote {
    page-break-inside: avoid;
}
img, svg {
    max-width: 100%;
    page-break-inside: avoid;
}
a {
    text-decoration: none;
    color: #1a5fb4;
}
/* 增强表格处理 - 解决被截断问题 */
.table-container {
    overflow-x: visible;
    width: 100%;
    margin: 1em -0.5cm; /* 负边距扩展可用空间 */
    display: block;
}
table {
    min-width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
    page-break-inside: avoid;
    table-layout: auto; /* 关键：允许列宽自适应 */
}
th, td {
    padding: 0.5em 0.3em; /* 减少水平填充增加空间 */
    border: 1px solid #ddd;
    text-align: left; /* 左对齐更可读 */
    hyphens: auto; /* 允许自动连字符 */
    word-wrap: break-word;
    font-size: 0.85em; /* 略小字体以适应多列 */
}
tr:nth-child(even) {
    background-color: #f8f8f8;
}
th {
    background-color: #e9ecef;
    font-weight: bold;
    white-space: nowrap; /* 表头不换行 */
}
sup {
    vertical-align: super;
    font-size: 0.8em;
}
footer {
    margin-top: 2rem;
    font-size: 0.8rem;
    color: #666;
    text-align: center;
}
.print-page-break {
    page-break-after: always;
}
/* 针对宽表格的横向模式 */
.landscape-table {
    min-width: 1200px; /* 确保宽表格有足够空间 */
}
.landscape-page {
    size: A4 landscape;
}
"""

def preprocess_html(content):
    """预处理HTML内容修复常见问题并优化表格显示"""
    # 修复错误的HTML实体编码
    content = re.sub(r'%!<(MISSING)|%!<(string=.+?)/td>', '', content)
    content = re.sub(r'%!\((MISSING)\)', '', content)
    content = re.sub(r'%!s\((MISSING)\)', '', content)
    
    # 替换问题引号
    content = content.replace("â€˜", "'").replace("â€™", "'")
    content = content.replace("&lsquo;", "'").replace("&rsquo;", "'")
    
    # 确保正确的meta标签
    meta_tag = '<meta charset="utf-8">'
    if '<head>' in content:
        content = content.replace('<head>', f'<head>{meta_tag}')
    else:
        content = f'<html><head>{meta_tag}</head><body>{content}</body></html>'
    
    # 修复不完整的表格结构
    if '<table>' in content and '</table>' not in content:
        content += '</table>'
    
    # 检测复杂表格并添加优化容器
    complex_table_pattern = r'<table[^>]*>[\s\S]*?<\/table>'
    tables = re.findall(complex_table_pattern, content)
    
    for table in tables:
        # 检测列数
        col_count = len(re.findall(r'<th[^>]*>', table)) or len(re.findall(r'<td[^>]*>', table.split('</tr>')[0]))
        
        # 如果列数较多(如配置表)，添加优化容器
        if col_count >= 5:
            # 添加响应式容器和横向模式类
            enhanced_table = table.replace('<table', '<div class="table-container"><table class="landscape-table"')
            enhanced_table = enhanced_table.replace('</table>', '</table></div>')
            content = content.replace(table, enhanced_table)
    
    return content

def convert_single(args):
    """转换单个HTML文件（工作进程使用）"""
    try:
        idx, html_path, temp_dir, css, landscape_mode = args
        logger.debug(f"Processing #{idx}: {html_path} [Landscape: {'Yes' if landscape_mode else 'No'}]")
        
        # 在子进程内部创建FontConfiguration
        font_config = FontConfiguration()
        
        # 创建临时PDF文件路径
        temp_pdf = os.path.join(temp_dir, f"{idx}_{os.path.basename(html_path)[:50]}.pdf")
        
        # 读取并预处理HTML内容
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # 预处理修复常见问题
        html_content = preprocess_html(html_content)
        
        # 动态CSS - 根据需要添加横向模式
        dynamic_css = css
        if landscape_mode:
            dynamic_css += "\n.landscape-table + table { min-width: 1200px; }"
            dynamic_css += "\n@page { size: A4 landscape; }"
        
        # 使用优化设置生成PDF
        HTML(
            string=html_content,
            base_url=os.path.dirname(html_path),
            url_fetcher=default_url_fetcher
        ).write_pdf(
            temp_pdf,
            stylesheets=[CSS(string=dynamic_css)],
            font_config=font_config,
            presentational_hints=True,
            optimize_size=('images', 'fonts'),
            compression=9
        )
        
        # 获取生成PDF的页数
        with open(temp_pdf, 'rb') as f:
            reader = PdfReader(f)
            num_pages = len(reader.pages)
            
        return (temp_pdf, num_pages)
    except Exception as e:
        logger.exception(f"Failed to convert {html_path}")
        return (None, 0)

class HTMLConverter:
    def __init__(self, output_pdf, max_workers=None, max_page=5000, landscape_mode=False):
        self.output_pdf = output_pdf
        # 自动设置进程数为CPU核心数的75%
        self.max_workers = max_workers or max(1, int(cpu_count() * 0.75))
        logger.info(f"Using {self.max_workers} worker processes")
        self.max_page = max_page
        logger.info(f"Max pages per PDF: {self.max_page}")
        self.landscape_mode = landscape_mode
        if landscape_mode:
            logger.info("Global landscape mode ENABLED")
        self.temp_dir = tempfile.TemporaryDirectory(prefix="html2pdf_")
        logger.debug(f"Temporary directory: {self.temp_dir.name}")
        self.temp_files = []  # 存储元组 (文件路径, 页数)
        self.start_time = time.time()
        self.file_count = 0
        self.output_files = []  # 最终生成的输出文件列表
        self.total_pages = 0  # 所有页数总和

    def process_directory(self, input_dir):
        """处理目录中的所有HTML文件并合并为PDF，按页数拆分"""
        logger.info(f"Scanning directory: {input_dir}")
        
        # 收集所有HTML文件
        html_files = []
        for root, _, files in os.walk(input_dir):
            for file in files:
                if file.lower().endswith(('.html', '.htm')):
                    html_files.append(os.path.join(root, file))
        
        if not html_files:
            logger.warning("No HTML files found in the directory")
            return 0, 0
        
        self.file_count = len(html_files)
        logger.info(f"Found {self.file_count} HTML files to process")
        
        # 创建任务参数
        tasks = []
        for idx, html_path in enumerate(html_files):
            tasks.append((
                idx,
                html_path,
                self.temp_dir.name,  # 临时目录路径
                GLOBAL_CSS,          # CSS字符串
                self.landscape_mode  # 是否全局横向模式
            ))
        
        # 使用进程池并行处理
        logger.info(f"Starting parallel conversion...")
        
        # 创建进程池并处理任务
        with Pool(processes=self.max_workers) as pool:
            results = pool.imap_unordered(convert_single, tasks)
            
            processed = 0
            for result in results:
                processed += 1
                if result[0]:
                    self.temp_files.append(result)
                
                # 更新进度（每10个文件或最后一次）
                if processed % 10 == 0 or processed == self.file_count:
                    elapsed = time.time() - self.start_time
                    rate = processed / max(0.1, elapsed) * 60
                    logger.info(f"Progress: {processed}/{self.file_count} files ({rate:.1f} files/min)")
        
        # 按原始顺序排序
        self.temp_files.sort(key=lambda x: int(os.path.basename(x[0]).split('_')[0]))
        
        # 计算总页数
        self.total_pages = sum(pages for _, pages in self.temp_files)
        logger.info(f"Total pages in all PDFs: {self.total_pages}")
        
        # 拆分并合并PDFs
        if not self.temp_files:
            logger.error("No PDF files created successfully, aborting merge")
            return 0, 0
        
        # 批量合并PDF
        self.merge_pdfs()
        return len(self.temp_files), self.file_count - len(self.temp_files)

    def merge_pdfs(self):
        """合并PDF文件，根据最大页数限制拆分输出"""
        logger.info(f"Merging PDFs with max {self.max_page} pages per file")
        
        current_page_count = 0
        part_num = 1
        merger = PdfMerger()
        base_output, ext = os.path.splitext(self.output_pdf)
        
        for pdf_file, num_pages in self.temp_files:
            # 如果当前页数+新页数超过限制（且当前不是空文件），则结束当前批次
            if current_page_count + num_pages > self.max_page and current_page_count > 0:
                # 生成当前批次的输出文件名
                part_name = f"{base_output}-{part_num}{ext}"
                self.save_merger(merger, part_name)
                part_num += 1
                
                # 重置
                merger = PdfMerger()
                current_page_count = 0
                logger.debug(f"Started new PDF part #{part_num}")
            
            # 添加当前PDF到合并器
            merger.append(pdf_file)
            current_page_count += num_pages
            logger.debug(f"Added {pdf_file} ({num_pages} pages), total pages: {current_page_count}")
            
            # 如果单个文件超过限制，仍然单独成文件
            if num_pages > self.max_page:
                part_name = f"{base_output}-{part_num}{ext}"
                self.save_merger(merger, part_name)
                part_num += 1
                merger = PdfMerger()
                current_page_count = 0
                logger.debug(f"Single large PDF created (#{part_num-1}), resetting merger")
        
        # 处理最后一批次
        if current_page_count > 0:
            part_name = f"{base_output}-{part_num}{ext}"
            self.save_merger(merger, part_name)
        else:
            merger.close()  # 关闭未使用的merger
        
        # 如果只有一个输出文件，重命名为原始输出文件名
        if len(self.output_files) == 1:
            output_file = self.output_files[0]
            if output_file != self.output_pdf:
                logger.info(f"Renaming single output file to {self.output_pdf}")
                os.rename(output_file, self.output_pdf)
                self.output_files = [self.output_pdf]
    
    def save_merger(self, merger, output_file):
        """保存当前的merger到文件并关闭"""
        try:
            with open(output_file, 'wb') as f:
                merger.write(f)
            logger.info(f"Created PDF part: {output_file}")
            self.output_files.append(output_file)
            return True
        except Exception as e:
            logger.exception(f"Failed to write PDF part: {output_file}")
            return False
        finally:
            merger.close()  # 确保关闭文件描述符

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """清理临时文件"""
        try:
            logger.info("Cleaning temporary files...")
            self.temp_dir.cleanup()
        except Exception as e:
            logger.exception("Failed to clean temporary files")
        return False

    def print_summary(self):
        """打印转换摘要"""
        elapsed = time.time() - self.start_time
        files_per_min = self.file_count / (elapsed / 60) if elapsed > 0 else float('inf')
        
        print("\n" + "=" * 50)
        print(f"Conversion Summary:")
        print(f"  HTML files processed: {self.file_count}")
        print(f"  PDF sections created: {len(self.temp_files)}")
        print(f"  Total pages: {self.total_pages}")
        print(f"  Output files: {len(self.output_files)}")
        for i, out_file in enumerate(self.output_files, 1):
            size = os.path.getsize(out_file) / (1024 * 1024)
            print(f"    - File {i}: {out_file} ({size:.2f} MB)")
        print(f"  Total processing time: {elapsed:.1f} seconds")
        print(f"  Average conversion rate: {files_per_min:.1f} files/min")
        print("=" * 50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Optimized HTML to PDF conversion with table support',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('input_dir', help='Input directory containing HTML files')
    parser.add_argument('output_pdf', help='Output PDF file path')
    parser.add_argument('-j', '--jobs', type=int, default=2, 
                        help='Number of parallel processes (0=auto-detect)')
    parser.add_argument('-v', '--verbose', action='store_true', 
                        help='Enable verbose debug logging')
    parser.add_argument('--sentry-dsn', type=str, default=os.getenv('SENTRY_DSN'),
                        help='Sentry DSN for error tracking (default: SENTRY_DSN env var)')
    parser.add_argument('--max-page', type=int, default=8000,
                        help='Maximum pages per output PDF file')
    parser.add_argument('--landscape', action='store_true',
                        help='Force landscape mode for all pages (useful for wide tables)')
    args = parser.parse_args()
    
    try:
        # 初始化 Sentry SDK
        if args.sentry_dsn:
            sentry_logging = LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR
            )
            
            sentry_sdk.init(
                dsn=args.sentry_dsn,
                environment=os.getenv('ENVIRONMENT', 'production'),
                release=os.getenv('RELEASE_VERSION', '1.0.0'),
                traces_sample_rate=1.0,
                integrations=[sentry_logging]
            )
            logger.info("Sentry SDK initialized with logging integration")
        else:
            logger.warning("Sentry DSN not provided, error tracking disabled")
        
        if args.verbose:
            logger.setLevel(logging.DEBUG)
            logging.getLogger('weasyprint').setLevel(logging.INFO)
        
        # 确保输出目录存在
        os.makedirs(os.path.dirname(args.output_pdf), exist_ok=True)
        
        # 添加事务跟踪
        with sentry_sdk.start_transaction(op="html_to_pdf", name="Convert HTML to PDF"):
            with HTMLConverter(args.output_pdf, args.jobs, args.max_page, args.landscape) as converter:
                successful, failed = converter.process_directory(args.input_dir)
                converter.print_summary()
                if failed > 0:
                    logger.warning(f"{failed} files failed conversion")
        
        sys.exit(0 if successful > 0 else 1)
    except Exception as e:
        logger.exception("Critical error occurred")
        sys.exit(1)
    finally:
        # 确保所有事件在退出前发送
        if args.sentry_dsn:
            sentry_sdk.flush()