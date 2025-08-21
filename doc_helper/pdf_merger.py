"""
PDF合并器

该模块提供PDF文件合并功能，支持按页数和文件大小限制进行智能合并，
并提供灵活的文件命名模板系统。
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

try:
    from PyPDF2 import PdfReader, PdfWriter
except ImportError:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise ImportError("需要安装 PyPDF2 或 pypdf: pip install PyPDF2 或 pip install pypdf")

logger = logging.getLogger(__name__)


@dataclass
class MergeConfig:
    """PDF合并配置"""
    max_pages: Optional[int] = None          # 最大页数限制
    max_file_size_mb: Optional[float] = None # 最大文件大小限制（MB）
    output_dir: str = "/tmp"                 # 输出目录
    single_file_template: str = "{name}.pdf" # 单文件输出模板
    multi_file_template: str = "{name}_{index:03d}.pdf"  # 多文件输出模板
    overwrite_existing: bool = False         # 是否覆盖已存在的文件
    preserve_metadata: bool = True           # 是否保留元数据
    compression: bool = True                 # 是否启用压缩


@dataclass
class PdfInfo:
    """PDF文件信息"""
    path: str
    pages: int
    size_bytes: int
    size_mb: float
    title: Optional[str] = None
    author: Optional[str] = None
    
    @classmethod
    def from_file(cls, file_path: str) -> 'PdfInfo':
        """从文件创建PDF信息"""
        try:
            reader = PdfReader(file_path)
            pages = len(reader.pages)
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            
            # 尝试获取元数据
            metadata = reader.metadata
            title = metadata.get('/Title') if metadata else None
            author = metadata.get('/Author') if metadata else None
            
            return cls(
                path=file_path,
                pages=pages,
                size_bytes=size_bytes,
                size_mb=size_mb,
                title=title,
                author=author
            )
        except Exception as e:
            logger.error(f"读取PDF文件失败: {file_path}, 错误: {e}")
            raise


@dataclass
class MergeResult:
    """合并结果"""
    success: bool
    output_files: List[str]
    total_pages: int
    total_size_mb: float
    source_files_count: int
    error_message: Optional[str] = None


class PdfMerger:
    """
    PDF合并器
    
    支持功能：
    - 按页数限制合并
    - 按文件大小限制合并
    - 灵活的文件命名模板
    - 元数据保留
    - 压缩优化
    
    示例:
        merger = PdfMerger(MergeConfig(
            max_pages=100,
            max_file_size_mb=50.0,
            output_dir="/output",
            single_file_template="{name}_merged.pdf",
            multi_file_template="{name}_part_{index:02d}.pdf"
        ))
        
        result = merger.merge_files([
            "/path/to/file1.pdf",
            "/path/to/file2.pdf"
        ], "combined_docs")
    """
    
    def __init__(self, config: MergeConfig):
        """
        初始化PDF合并器
        
        Args:
            config: 合并配置
        """
        self.config = config
        self._validate_config()
        
        # 确保输出目录存在
        Path(self.config.output_dir).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"PDF合并器初始化完成，输出目录: {self.config.output_dir}")
    
    def _validate_config(self) -> None:
        """验证配置"""
        if self.config.max_pages is not None and self.config.max_pages <= 0:
            raise ValueError("最大页数必须大于0")
        
        if self.config.max_file_size_mb is not None and self.config.max_file_size_mb <= 0:
            raise ValueError("最大文件大小必须大于0")
        
        if not self.config.single_file_template or not self.config.multi_file_template:
            raise ValueError("文件名模板不能为空")
    
    def analyze_files(self, file_paths: List[str]) -> List[PdfInfo]:
        """
        分析PDF文件信息
        
        Args:
            file_paths: PDF文件路径列表
            
        Returns:
            PDF文件信息列表
        """
        pdf_infos = []
        
        for file_path in file_paths:
            if not os.path.exists(file_path):
                logger.warning(f"文件不存在，跳过: {file_path}")
                continue
            
            if not file_path.lower().endswith('.pdf'):
                logger.warning(f"非PDF文件，跳过: {file_path}")
                continue
            
            try:
                info = PdfInfo.from_file(file_path)
                pdf_infos.append(info)
                logger.debug(f"分析文件: {file_path}, 页数: {info.pages}, 大小: {info.size_mb:.2f}MB")
            except Exception as e:
                logger.error(f"分析文件失败: {file_path}, 错误: {e}")
        
        logger.info(f"成功分析 {len(pdf_infos)} 个PDF文件")
        return pdf_infos
    
    def plan_merge_groups(self, pdf_infos: List[PdfInfo]) -> List[List[PdfInfo]]:
        """
        规划合并分组
        
        Args:
            pdf_infos: PDF文件信息列表
            
        Returns:
            合并分组列表
        """
        if not pdf_infos:
            return []
        
        groups = []
        current_group = []
        current_pages = 0
        current_size_mb = 0.0
        
        for pdf_info in pdf_infos:
            # 检查是否可以添加到当前组
            can_add = True
            
            if self.config.max_pages is not None:
                if current_pages + pdf_info.pages > self.config.max_pages:
                    can_add = False
            
            if self.config.max_file_size_mb is not None:
                if current_size_mb + pdf_info.size_mb > self.config.max_file_size_mb:
                    can_add = False
            
            # 如果当前组为空，强制添加（即使超出限制）
            if not current_group:
                can_add = True
            
            if can_add:
                current_group.append(pdf_info)
                current_pages += pdf_info.pages
                current_size_mb += pdf_info.size_mb
            else:
                # 开始新的组
                if current_group:
                    groups.append(current_group)
                
                current_group = [pdf_info]
                current_pages = pdf_info.pages
                current_size_mb = pdf_info.size_mb
        
        # 添加最后一组
        if current_group:
            groups.append(current_group)
        
        logger.info(f"规划完成，共 {len(groups)} 个合并组")
        for i, group in enumerate(groups):
            total_pages = sum(pdf.pages for pdf in group)
            total_size = sum(pdf.size_mb for pdf in group)
            logger.debug(f"组 {i+1}: {len(group)} 个文件, {total_pages} 页, {total_size:.2f}MB")
        
        return groups
    
    def generate_output_path(self, base_name: str, group_index: int, total_groups: int) -> str:
        """
        生成输出文件路径
        
        Args:
            base_name: 基础文件名
            group_index: 当前组索引（从0开始）
            total_groups: 总组数
            
        Returns:
            输出文件路径
        """
        # 准备模板变量
        now = datetime.now()
        variables = {
            'name': base_name,
            'index': group_index + 1,
            'total': total_groups,
            'date': now.strftime('%Y%m%d'),
            'time': now.strftime('%H%M%S'),
            'datetime': now.strftime('%Y%m%d_%H%M%S'),
            'timestamp': int(now.timestamp()),
            'ext': '.pdf'
        }
        
        # 选择模板
        if total_groups == 1:
            template = self.config.single_file_template
        else:
            template = self.config.multi_file_template
        
        # 渲染文件名
        try:
            filename = template.format(**variables)
        except KeyError as e:
            logger.error(f"模板变量不存在: {e}")
            # 使用默认模板
            if total_groups == 1:
                filename = f"{base_name}.pdf"
            else:
                filename = f"{base_name}_{group_index + 1:03d}.pdf"
        
        # 确保文件名安全
        filename = self._sanitize_filename(filename)
        
        return os.path.join(self.config.output_dir, filename)
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除不安全字符"""
        # 移除或替换不安全字符
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # 移除多余的点和空格
        filename = re.sub(r'\.+', '.', filename)
        filename = filename.strip('. ')
        
        # 确保有扩展名
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        
        return filename
    
    def merge_group(self, pdf_infos: List[PdfInfo], output_path: str) -> bool:
        """
        合并一组PDF文件
        
        Args:
            pdf_infos: PDF文件信息列表
            output_path: 输出文件路径
            
        Returns:
            是否成功
        """
        try:
            # 检查输出文件是否已存在
            if os.path.exists(output_path) and not self.config.overwrite_existing:
                logger.error(f"输出文件已存在且不允许覆盖: {output_path}")
                return False
            
            writer = PdfWriter()
            
            # 合并所有PDF
            for pdf_info in pdf_infos:
                try:
                    reader = PdfReader(pdf_info.path)
                    
                    # 添加所有页面
                    for page in reader.pages:
                        writer.add_page(page)
                    
                    # 保留元数据（从第一个文件）
                    if self.config.preserve_metadata and len(writer.pages) == len(reader.pages):
                        if reader.metadata:
                            writer.add_metadata(reader.metadata)
                    
                    logger.debug(f"已添加文件: {pdf_info.path}, 页数: {pdf_info.pages}")
                    
                except Exception as e:
                    logger.error(f"处理文件失败: {pdf_info.path}, 错误: {e}")
                    continue
            
            # 写入输出文件
            if len(writer.pages) == 0:
                logger.error("没有页面可写入")
                return False
            
            with open(output_path, 'wb') as output_file:
                if self.config.compression:
                    # 尝试压缩
                    try:
                        writer.compress_identical_objects()
                        writer.remove_duplicated_streams()
                    except AttributeError:
                        # 旧版本PyPDF2可能没有这些方法
                        pass
                
                writer.write(output_file)
            
            # 验证输出文件
            if os.path.exists(output_path):
                output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                logger.info(f"合并完成: {output_path}, 页数: {len(writer.pages)}, 大小: {output_size_mb:.2f}MB")
                return True
            else:
                logger.error(f"输出文件创建失败: {output_path}")
                return False
                
        except Exception as e:
            logger.error(f"合并过程失败: {e}")
            return False
    
    def merge_files(self, file_paths: List[str], base_name: str) -> MergeResult:
        """
        合并PDF文件
        
        Args:
            file_paths: PDF文件路径列表
            base_name: 输出文件基础名称
            
        Returns:
            合并结果
        """
        try:
            logger.info(f"开始合并 {len(file_paths)} 个PDF文件，基础名称: {base_name}")
            
            # 分析文件
            pdf_infos = self.analyze_files(file_paths)
            if not pdf_infos:
                return MergeResult(
                    success=False,
                    output_files=[],
                    total_pages=0,
                    total_size_mb=0.0,
                    source_files_count=0,
                    error_message="没有有效的PDF文件"
                )
            
            # 规划合并分组
            groups = self.plan_merge_groups(pdf_infos)
            if not groups:
                return MergeResult(
                    success=False,
                    output_files=[],
                    total_pages=0,
                    total_size_mb=0.0,
                    source_files_count=len(pdf_infos),
                    error_message="无法创建合并分组"
                )
            
            # 执行合并
            output_files = []
            total_pages = 0
            total_source_files = len(pdf_infos)
            
            for i, group in enumerate(groups):
                output_path = self.generate_output_path(base_name, i, len(groups))
                
                if self.merge_group(group, output_path):
                    output_files.append(output_path)
                    group_pages = sum(pdf.pages for pdf in group)
                    total_pages += group_pages
                else:
                    logger.error(f"合并组 {i+1} 失败")
            
            # 计算总大小
            total_size_mb = 0.0
            for output_file in output_files:
                if os.path.exists(output_file):
                    total_size_mb += os.path.getsize(output_file) / (1024 * 1024)
            
            success = len(output_files) > 0
            
            if success:
                logger.info(
                    f"合并完成 - 输出文件: {len(output_files)} 个, "
                    f"总页数: {total_pages}, 总大小: {total_size_mb:.2f}MB"
                )
            
            return MergeResult(
                success=success,
                output_files=output_files,
                total_pages=total_pages,
                total_size_mb=total_size_mb,
                source_files_count=total_source_files,
                error_message=None if success else "部分或全部合并失败"
            )
            
        except Exception as e:
            error_msg = f"合并过程异常: {e}"
            logger.error(error_msg)
            return MergeResult(
                success=False,
                output_files=[],
                total_pages=0,
                total_size_mb=0.0,
                source_files_count=len(file_paths),
                error_message=error_msg
            )
    
    def get_available_template_variables(self) -> Dict[str, str]:
        """
        获取可用的模板变量
        
        Returns:
            模板变量说明字典
        """
        return {
            'name': '基础文件名',
            'index': '文件序号（从1开始）',
            'total': '总文件数',
            'date': '日期 (YYYYMMDD)',
            'time': '时间 (HHMMSS)',
            'datetime': '日期时间 (YYYYMMDD_HHMMSS)',
            'timestamp': 'Unix时间戳',
            'ext': '文件扩展名（默认 .pdf）'
        }
    
    def estimate_output_info(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        估算输出信息
        
        Args:
            file_paths: PDF文件路径列表
            
        Returns:
            估算信息字典
        """
        try:
            pdf_infos = self.analyze_files(file_paths)
            if not pdf_infos:
                return {
                    'total_files': 0,
                    'total_pages': 0,
                    'total_size_mb': 0.0,
                    'estimated_groups': 0,
                    'error': '没有有效的PDF文件'
                }
            
            groups = self.plan_merge_groups(pdf_infos)
            
            total_pages = sum(pdf.pages for pdf in pdf_infos)
            total_size_mb = sum(pdf.size_mb for pdf in pdf_infos)
            
            return {
                'total_files': len(pdf_infos),
                'total_pages': total_pages,
                'total_size_mb': total_size_mb,
                'estimated_groups': len(groups),
                'group_details': [
                    {
                        'files': len(group),
                        'pages': sum(pdf.pages for pdf in group),
                        'size_mb': sum(pdf.size_mb for pdf in group)
                    }
                    for group in groups
                ]
            }
            
        except Exception as e:
            return {
                'total_files': 0,
                'total_pages': 0,
                'total_size_mb': 0.0,
                'estimated_groups': 0,
                'error': str(e)
            }


def create_merger(
    max_pages: Optional[int] = None,
    max_file_size_mb: Optional[float] = None,
    output_dir: str = "/tmp",
    single_file_template: str = "{name}.pdf",
    multi_file_template: str = "{name}_{index:03d}.pdf"
) -> PdfMerger:
    """
    创建PDF合并器的便捷函数
    
    Args:
        max_pages: 最大页数限制
        max_file_size_mb: 最大文件大小限制（MB）
        output_dir: 输出目录
        single_file_template: 单文件输出模板
        multi_file_template: 多文件输出模板
        
    Returns:
        PDF合并器实例
    """
    config = MergeConfig(
        max_pages=max_pages,
        max_file_size_mb=max_file_size_mb,
        output_dir=output_dir,
        single_file_template=single_file_template,
        multi_file_template=multi_file_template
    )
    return PdfMerger(config)


if __name__ == "__main__":
    # 示例用法
    import argparse
    import glob
    
    def main():
        parser = argparse.ArgumentParser(description="PDF合并工具")
        parser.add_argument("files", nargs="+", help="PDF文件路径（支持通配符）")
        parser.add_argument("-o", "--output-dir", default="/tmp", help="输出目录")
        parser.add_argument("-n", "--name", default="merged", help="输出文件基础名称")
        parser.add_argument("--max-pages", type=int, help="最大页数限制")
        parser.add_argument("--max-size", type=float, help="最大文件大小限制（MB）")
        parser.add_argument("--single-template", default="{name}.pdf", help="单文件输出模板")
        parser.add_argument("--multi-template", default="{name}_{index:03d}.pdf", help="多文件输出模板")
        parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
        
        args = parser.parse_args()
        
        # 设置日志级别
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
        # 展开通配符
        file_paths = []
        for pattern in args.files:
            matched_files = glob.glob(pattern)
            if matched_files:
                file_paths.extend(matched_files)
            else:
                file_paths.append(pattern)  # 可能是具体的文件路径
        
        # 创建合并器
        merger = create_merger(
            max_pages=args.max_pages,
            max_file_size_mb=args.max_size,
            output_dir=args.output_dir,
            single_file_template=args.single_template,
            multi_file_template=args.multi_template
        )
        
        # 执行合并
        result = merger.merge_files(file_paths, args.name)
        
        if result.success:
            print(f"✅ 合并成功！")
            print(f"输出文件: {len(result.output_files)} 个")
            for output_file in result.output_files:
                print(f"  - {output_file}")
            print(f"总页数: {result.total_pages}")
            print(f"总大小: {result.total_size_mb:.2f}MB")
        else:
            print(f"❌ 合并失败: {result.error_message}")
            exit(1)
    
    main()