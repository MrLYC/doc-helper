#!/usr/bin/env python3
"""
PDF合并器使用示例

演示PdfMerger的各种功能和使用场景。
"""

import sys
import os
import tempfile
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from doc_helper import (
    PdfMerger, MergeConfig, create_merger
)


def create_dummy_pdf_files(temp_dir: str, count: int = 5) -> list:
    """
    创建虚拟PDF文件用于演示
    注意：这里只是创建文件名，实际使用时需要真实的PDF文件
    """
    dummy_files = []
    for i in range(count):
        file_path = os.path.join(temp_dir, f"document_{i+1:02d}.pdf")
        # 创建空文件作为占位符
        Path(file_path).touch()
        dummy_files.append(file_path)
        print(f"创建虚拟文件: {file_path}")
    
    return dummy_files


def example_1_basic_merge():
    """示例1：基础合并"""
    print("=== 示例1：基础合并 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_files = create_dummy_pdf_files(temp_dir, 3)
        
        # 创建合并器（无限制）
        merger = create_merger(output_dir=temp_dir)
        
        # 估算输出信息
        estimate = merger.estimate_output_info(test_files)
        print(f"估算信息: {estimate}")
        
        print("✅ 基础合并示例完成")


def example_2_page_limit_merge():
    """示例2：页数限制合并"""
    print("=== 示例2：页数限制合并 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_files = create_dummy_pdf_files(temp_dir, 5)
        
        # 创建页数限制的合并器
        merger = create_merger(
            max_pages=50,  # 限制每个输出文件最多50页
            output_dir=temp_dir,
            multi_file_template="{name}_volume_{index:02d}.pdf"
        )
        
        # 显示模板变量
        variables = merger.get_available_template_variables()
        print("可用模板变量:")
        for var, desc in variables.items():
            print(f"  {var}: {desc}")
        
        print("✅ 页数限制合并示例完成")


def example_3_size_limit_merge():
    """示例3：文件大小限制合并"""
    print("=== 示例3：文件大小限制合并 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_files = create_dummy_pdf_files(temp_dir, 4)
        
        # 创建文件大小限制的合并器
        config = MergeConfig(
            max_file_size_mb=25.0,  # 限制每个输出文件最大25MB
            output_dir=temp_dir,
            single_file_template="{name}_{datetime}.pdf",
            multi_file_template="{name}_batch_{index:03d}_{date}.pdf",
            overwrite_existing=True,
            compression=True
        )
        
        merger = PdfMerger(config)
        
        print(f"配置: 最大文件大小 {config.max_file_size_mb}MB")
        print(f"输出目录: {config.output_dir}")
        print(f"单文件模板: {config.single_file_template}")
        print(f"多文件模板: {config.multi_file_template}")
        
        print("✅ 文件大小限制合并示例完成")


def example_4_custom_templates():
    """示例4：自定义模板"""
    print("=== 示例4：自定义模板 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_files = create_dummy_pdf_files(temp_dir, 6)
        
        # 创建自定义模板的合并器
        merger = create_merger(
            max_pages=30,
            output_dir=temp_dir,
            single_file_template="Report_{name}_{date}.pdf",
            multi_file_template="Report_{name}_Part{index:02d}_of_{total}_{time}.pdf"
        )
        
        # 演示路径生成
        print("模板生成示例:")
        print("单文件:", merger.generate_output_path("annual_report", 0, 1))
        print("多文件1:", merger.generate_output_path("annual_report", 0, 3))
        print("多文件2:", merger.generate_output_path("annual_report", 1, 3))
        print("多文件3:", merger.generate_output_path("annual_report", 2, 3))
        
        print("✅ 自定义模板示例完成")


def example_5_advanced_config():
    """示例5：高级配置"""
    print("=== 示例5：高级配置 ===")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_files = create_dummy_pdf_files(temp_dir, 8)
        
        # 创建高级配置的合并器
        config = MergeConfig(
            max_pages=75,
            max_file_size_mb=30.0,
            output_dir=temp_dir,
            single_file_template="{name}_complete_{timestamp}.pdf",
            multi_file_template="{name}_section_{index:03d}_total_{total}_{datetime}.pdf",
            overwrite_existing=True,
            preserve_metadata=True,
            compression=True
        )
        
        merger = PdfMerger(config)
        
        print("高级配置:")
        print(f"  最大页数: {config.max_pages}")
        print(f"  最大文件大小: {config.max_file_size_mb}MB")
        print(f"  覆盖已存在文件: {config.overwrite_existing}")
        print(f"  保留元数据: {config.preserve_metadata}")
        print(f"  启用压缩: {config.compression}")
        
        # 估算输出信息
        estimate = merger.estimate_output_info(test_files)
        print(f"\n估算结果:")
        print(f"  总文件数: {estimate.get('total_files', 0)}")
        print(f"  预计分组数: {estimate.get('estimated_groups', 0)}")
        if 'group_details' in estimate:
            for i, group in enumerate(estimate['group_details']):
                print(f"  组 {i+1}: {group['files']} 个文件, {group['pages']} 页, {group['size_mb']:.2f}MB")
        
        print("✅ 高级配置示例完成")


def example_6_real_world_scenario():
    """示例6：真实世界场景"""
    print("=== 示例6：真实世界场景 ===")
    
    print("场景：将大量报告PDF合并成几个便于分发的文件")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 模拟不同大小的报告文件
        test_files = create_dummy_pdf_files(temp_dir, 12)
        
        # 商务场景：限制文件大小便于邮件发送
        merger = create_merger(
            max_file_size_mb=10.0,  # 邮件附件限制
            output_dir=temp_dir,
            single_file_template="QuarterlyReport_{name}_{date}.pdf",
            multi_file_template="QuarterlyReport_{name}_Volume{index:02d}_{date}.pdf"
        )
        
        print("商务场景配置:")
        print("  - 限制单个文件大小为10MB（邮件友好）")
        print("  - 使用季度报告命名规范")
        print("  - 包含日期用于版本控制")
        
        # 学术场景：限制页数便于打印
        academic_merger = create_merger(
            max_pages=100,  # 打印友好的页数
            output_dir=temp_dir,
            single_file_template="Research_{name}_Complete.pdf",
            multi_file_template="Research_{name}_Chapter{index:02d}.pdf"
        )
        
        print("\n学术场景配置:")
        print("  - 限制单个文件最多100页（打印友好）")
        print("  - 使用研究报告命名规范")
        print("  - 分章节便于阅读")
        
        print("✅ 真实世界场景示例完成")


def main():
    """主函数"""
    print("🚀 PDF合并器功能演示")
    print("=" * 50)
    
    try:
        example_1_basic_merge()
        print()
        
        example_2_page_limit_merge()
        print()
        
        example_3_size_limit_merge()
        print()
        
        example_4_custom_templates()
        print()
        
        example_5_advanced_config()
        print()
        
        example_6_real_world_scenario()
        print()
        
        print("🎉 所有示例运行完成！")
        
        print("\n📖 使用提示:")
        print("1. 在实际使用中，请确保输入文件是有效的PDF文件")
        print("2. 根据需要调整页数和文件大小限制")
        print("3. 使用模板变量创建有意义的文件名")
        print("4. 考虑启用压缩以减小输出文件大小")
        print("5. 在批量处理前先进行小规模测试")
        
        print("\n📋 命令行用法示例:")
        print("python pdf_merger.py *.pdf -o /output -n merged --max-pages 100")
        print("python pdf_merger.py file1.pdf file2.pdf --max-size 25 --multi-template 'report_{index:02d}.pdf'")
        
    except Exception as e:
        print(f"❌ 示例运行失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()