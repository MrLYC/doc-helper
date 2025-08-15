#!/usr/bin/env python3
"""
PDF文件拆分工具

功能：
1. 将大的PDF文件按指定大小拆分成多个较小的PDF文件
2. 支持灵活的输出文件名模板配置
3. 支持变量替换：name, ext, filename, index, dir, path
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Tuple

from PyPDF2 import PdfReader, PdfWriter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """格式化文件大小显示"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def parse_size(size_str: str) -> int:
    """解析大小字符串，支持 KB, MB, GB 等单位"""
    size_str = size_str.strip().upper()
    
    # 提取数字和单位
    import re
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT]?B?)$', size_str)
    if not match:
        raise ValueError(f"无效的大小格式: {size_str}")
    
    value = float(match.group(1))
    unit = match.group(2) or 'B'
    
    # 转换为字节
    multipliers = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'TB': 1024 * 1024 * 1024 * 1024,
    }
    
    return int(value * multipliers.get(unit, 1))


def get_file_variables(file_path: str) -> dict:
    """从文件路径提取变量信息"""
    path_obj = Path(file_path)
    
    return {
        'filename': path_obj.name,
        'name': path_obj.stem,
        'ext': path_obj.suffix.lstrip('.'),
    }


def format_output_path(template: str, variables: dict, index: int, output_dir: str = None) -> str:
    """根据模板和变量生成输出路径"""
    # 添加index变量
    format_vars = variables.copy()
    format_vars['index'] = index
    
    try:
        filename = template.format(**format_vars)
        
        # 如果指定了输出目录，则组合路径
        if output_dir:
            return str(Path(output_dir) / filename)
        else:
            return filename
    except KeyError as e:
        raise ValueError(f"模板中包含未知变量: {e}")


def handle_under_size_file(input_path: str, output_dir: str, action: str) -> str:
    """处理未超过大小限制的文件"""
    input_file = Path(input_path)
    output_file = Path(output_dir) / input_file.name
    
    if action == 'copy':
        import shutil
        shutil.copy2(input_path, output_file)
        logger.info(f"复制文件: {input_path} -> {output_file}")
        return str(output_file)
    elif action == 'link':
        output_file.symlink_to(input_file.resolve())
        logger.info(f"创建符号链接: {input_path} -> {output_file}")
        return str(output_file)
    elif action == 'move':
        import shutil
        shutil.move(input_path, output_file)
        logger.info(f"移动文件: {input_path} -> {output_file}")
        return str(output_file)
    elif action == 'skip':
        logger.info(f"跳过文件: {input_path} (未超过大小限制)")
        return None
    else:
        raise ValueError(f"未知的处理动作: {action}")


def estimate_pdf_size(pages: List) -> int:
    """估算PDF页面的大小（字节）"""
    # 这是一个简单的估算方法，实际大小可能会有差异
    # 基于页面数量和内容复杂度的粗略估算
    
    # 基础大小：每页约1KB的结构开销
    base_size = len(pages) * 1024
    
    # 内容大小估算（这里使用简化方法）
    # 在实际应用中，可能需要更精确的计算
    content_size = len(pages) * 50 * 1024  # 假设每页平均50KB内容
    
    return base_size + content_size


def split_pdf_by_size(input_path: str, max_size: int, output_template: str, output_dir: str = None, under_action: str = 'skip') -> List[str]:
    """按大小拆分PDF文件"""
    logger.info(f"开始处理PDF文件: {input_path}")
    logger.info(f"最大文件大小: {format_size(max_size)}")
    logger.info(f"输出模板: {output_template}")
    if output_dir:
        logger.info(f"输出目录: {output_dir}")
    
    # 检查文件大小
    file_size = os.path.getsize(input_path)
    logger.info(f"原文件大小: {format_size(file_size)}")
    
    # 如果文件未超过大小限制，根据under_action处理
    if file_size <= max_size:
        logger.info(f"文件大小未超过限制，执行动作: {under_action}")
        if output_dir:
            # 确保输出目录存在
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            result = handle_under_size_file(input_path, output_dir, under_action)
            return [result] if result else []
        else:
            logger.info(f"文件大小未超过限制，无需拆分: {input_path}")
            return []
    
    # 读取PDF文件
    try:
        reader = PdfReader(input_path)
        total_pages = len(reader.pages)
        logger.info(f"PDF总页数: {total_pages}")
    except Exception as e:
        raise ValueError(f"无法读取PDF文件: {e}")
    
    if total_pages == 0:
        raise ValueError("PDF文件没有页面")
    
    # 获取文件变量
    file_vars = get_file_variables(input_path)
    
    # 确保输出目录存在
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    output_files = []
    current_writer = PdfWriter()
    current_pages = []
    current_size = 0
    split_index = 1
    
    for page_num, page in enumerate(reader.pages, 1):
        # 添加页面到当前writer
        current_writer.add_page(page)
        current_pages.append(page)
        
        # 估算当前大小
        estimated_size = estimate_pdf_size(current_pages)
        
        # 检查是否需要保存当前分片
        should_save = False
        
        if estimated_size >= max_size:
            # 超过大小限制
            should_save = True
            logger.debug(f"页面 {page_num}: 大小超限 ({format_size(estimated_size)})")
        elif page_num == total_pages:
            # 最后一页
            should_save = True
            logger.debug(f"页面 {page_num}: 最后一页")
        
        if should_save:
            # 生成输出文件路径
            output_path = format_output_path(output_template, file_vars, split_index, output_dir)
            
            # 确保输出目录存在
            output_path_obj = Path(output_path)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            # 保存当前分片
            try:
                with open(output_path, 'wb') as output_file:
                    current_writer.write(output_file)
                
                # 获取实际文件大小
                actual_size = os.path.getsize(output_path)
                page_count = len(current_pages)
                
                logger.info(f"保存分片 {split_index}: {output_path}")
                logger.info(f"  页面数: {page_count}, 大小: {format_size(actual_size)}")
                
                output_files.append(output_path)
                
            except Exception as e:
                raise RuntimeError(f"保存PDF分片失败: {e}")
            
            # 重置状态
            current_writer = PdfWriter()
            current_pages = []
            current_size = 0
            split_index += 1
    
    logger.info(f"拆分完成，共生成 {len(output_files)} 个文件")
    return output_files


def validate_template(template: str) -> None:
    """验证输出模板的有效性"""
    # 检查模板中是否包含必要的变量
    if '{index}' not in template:
        raise ValueError("输出模板必须包含 {index} 变量")
    
    # 检查是否包含不支持的变量
    allowed_vars = {'name', 'ext', 'filename', 'index'}
    import re
    vars_in_template = set(re.findall(r'\{(\w+)(?::[^}]*)?\}', template))
    
    unsupported_vars = vars_in_template - allowed_vars
    if unsupported_vars:
        raise ValueError(f"模板包含不支持的变量: {', '.join(unsupported_vars)}。支持的变量: {', '.join(allowed_vars)}")
    
    # 测试模板格式
    test_vars = {
        'filename': 'test.pdf',
        'name': 'test',
        'ext': 'pdf',
        'index': 1,
    }
    
    try:
        test_output = template.format(**test_vars)
        logger.debug(f"模板测试输出: {test_output}")
    except Exception as e:
        raise ValueError(f"无效的输出模板: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="PDF文件拆分工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模板变量说明：
  {filename}  - 原始文件名，例如 test.pdf
  {name}      - 文件名（无扩展名），例如 test
  {ext}       - 扩展名，例如 pdf
  {index}     - 当前文件拆分的序号，整数（必须包含）

未超过大小的文件处理方式：
  copy - 复制到输出目录，文件名不变
  link - 在输出目录中创建符号链接
  move - 移动到输出目录
  skip - 跳过不处理（默认）

示例：
  %(prog)s file1.pdf file2.pdf -s 10MB -o /tmp/output -t "{name}-{index}.{ext}"
  %(prog)s *.pdf -s 5MB -o ./split/ -t "{name}_part{index:02d}.{ext}" -u copy
        """
    )
    
    parser.add_argument(
        'pdf_files',
        nargs='+',
        help='要拆分的PDF文件路径'
    )
    
    parser.add_argument(
        '-s', '--max-size',
        default="140MB",
        help='单个文件的最大体积（支持单位：B, KB, MB, GB）'
    )
    
    parser.add_argument(
        '-t', '--output-template',
        default='{name}-{index}.{ext}',
        help='输出文件名模板，必须包含 {index} 变量（默认：{name}-{index}.{ext}）'
    )
    
    parser.add_argument(
        '-o', '--output-dir',
        default='./split/',
        help='输出目录，不存在时自动创建'
    )
    
    parser.add_argument(
        '-u', '--under-action',
        choices=['copy', 'link', 'move', 'skip'],
        default='skip',
        help='未超过体积的文件处理方法（默认：skip）'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='显示详细信息'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='仅显示将要执行的操作，不实际拆分文件'
    )
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # 解析最大大小
        max_size = parse_size(args.max_size)
        logger.info(f"最大文件大小: {format_size(max_size)}")
        
        # 验证输出模板
        validate_template(args.output_template)
        
        # 处理每个输入文件
        all_output_files = []
        
        for pdf_file in args.pdf_files:
            if not os.path.exists(pdf_file):
                logger.error(f"文件不存在: {pdf_file}")
                continue
            
            if not pdf_file.lower().endswith('.pdf'):
                logger.warning(f"跳过非PDF文件: {pdf_file}")
                continue
            
            logger.info(f"\n处理文件: {pdf_file}")
            
            if args.dry_run:
                # 仅显示将要执行的操作
                file_vars = get_file_variables(pdf_file)
                logger.info("预览模式 - 将生成的文件：")
                for i in range(1, 4):  # 预览前3个可能的文件名
                    output_path = format_output_path(args.output_template, file_vars, i, args.output_dir)
                    logger.info(f"  分片 {i}: {output_path}")
                logger.info("  ...")
            else:
                try:
                    output_files = split_pdf_by_size(
                        pdf_file, 
                        max_size, 
                        args.output_template, 
                        args.output_dir, 
                        args.under_action
                    )
                    all_output_files.extend(output_files)
                except Exception as e:
                    logger.error(f"处理文件 {pdf_file} 时出错: {e}")
                    continue
        
        if not args.dry_run and all_output_files:
            logger.info(f"\n处理完成！共生成 {len(all_output_files)} 个文件：")
            for output_file in all_output_files:
                if output_file and os.path.exists(output_file):
                    size = os.path.getsize(output_file)
                    logger.info(f"  {output_file} ({format_size(size)})")
        
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()