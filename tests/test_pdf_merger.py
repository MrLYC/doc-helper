"""
PDF合并器测试

测试PdfMerger的各种功能和配置选项。
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from pdf_helper.pdf_merger import (
    PdfMerger, MergeConfig, PdfInfo, MergeResult, create_merger
)


class TestMergeConfig:
    """测试MergeConfig配置类"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = MergeConfig()
        assert config.max_pages is None
        assert config.max_file_size_mb is None
        assert config.output_dir == "/tmp"
        assert config.single_file_template == "{name}.pdf"
        assert config.multi_file_template == "{name}_{index:03d}.pdf"
        assert config.overwrite_existing is False
        assert config.preserve_metadata is True
        assert config.compression is True
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = MergeConfig(
            max_pages=100,
            max_file_size_mb=50.0,
            output_dir="/custom/output",
            single_file_template="{name}_merged.pdf",
            multi_file_template="{name}_part_{index:02d}.pdf",
            overwrite_existing=True,
            preserve_metadata=False,
            compression=False
        )
        assert config.max_pages == 100
        assert config.max_file_size_mb == 50.0
        assert config.output_dir == "/custom/output"
        assert config.single_file_template == "{name}_merged.pdf"
        assert config.multi_file_template == "{name}_part_{index:02d}.pdf"
        assert config.overwrite_existing is True
        assert config.preserve_metadata is False
        assert config.compression is False


class TestPdfInfo:
    """测试PdfInfo类"""
    
    @patch('pdf_helper.pdf_merger.PdfReader')
    @patch('os.path.getsize')
    def test_from_file(self, mock_getsize, mock_pdf_reader):
        """测试从文件创建PdfInfo"""
        # 模拟PdfReader
        mock_reader = Mock()
        mock_reader.pages = [Mock(), Mock(), Mock()]  # 3页
        mock_reader.metadata = {'/Title': 'Test PDF', '/Author': 'Test Author'}
        mock_pdf_reader.return_value = mock_reader
        
        # 模拟文件大小
        mock_getsize.return_value = 1024 * 1024  # 1MB
        
        info = PdfInfo.from_file("/test/file.pdf")
        
        assert info.path == "/test/file.pdf"
        assert info.pages == 3
        assert info.size_bytes == 1024 * 1024
        assert info.size_mb == 1.0
        assert info.title == "Test PDF"
        assert info.author == "Test Author"
    
    @patch('pdf_helper.pdf_merger.PdfReader')
    @patch('os.path.getsize')
    def test_from_file_no_metadata(self, mock_getsize, mock_pdf_reader):
        """测试无元数据的PDF文件"""
        mock_reader = Mock()
        mock_reader.pages = [Mock()]
        mock_reader.metadata = None
        mock_pdf_reader.return_value = mock_reader
        mock_getsize.return_value = 512 * 1024  # 0.5MB
        
        info = PdfInfo.from_file("/test/file.pdf")
        
        assert info.title is None
        assert info.author is None


class TestPdfMerger:
    """测试PdfMerger类"""
    
    def setup_method(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.config = MergeConfig(output_dir=self.temp_dir)
        self.merger = PdfMerger(self.config)
    
    def test_initialization(self):
        """测试初始化"""
        assert self.merger.config == self.config
        assert os.path.exists(self.temp_dir)
    
    def test_validate_config_invalid_pages(self):
        """测试无效页数配置"""
        with pytest.raises(ValueError, match="最大页数必须大于0"):
            PdfMerger(MergeConfig(max_pages=0))
    
    def test_validate_config_invalid_size(self):
        """测试无效文件大小配置"""
        with pytest.raises(ValueError, match="最大文件大小必须大于0"):
            PdfMerger(MergeConfig(max_file_size_mb=-1.0))
    
    def test_validate_config_empty_template(self):
        """测试空模板配置"""
        with pytest.raises(ValueError, match="文件名模板不能为空"):
            PdfMerger(MergeConfig(single_file_template=""))
    
    @patch('pdf_helper.pdf_merger.PdfInfo.from_file')
    @patch('os.path.exists')
    def test_analyze_files(self, mock_exists, mock_from_file):
        """测试文件分析"""
        # 模拟文件存在
        mock_exists.return_value = True
        
        # 模拟PdfInfo
        mock_info1 = Mock(path="/test/file1.pdf", pages=10, size_mb=1.0)
        mock_info2 = Mock(path="/test/file2.pdf", pages=20, size_mb=2.0)
        mock_from_file.side_effect = [mock_info1, mock_info2]
        
        files = ["/test/file1.pdf", "/test/file2.pdf"]
        infos = self.merger.analyze_files(files)
        
        assert len(infos) == 2
        assert infos[0] == mock_info1
        assert infos[1] == mock_info2
    
    @patch('os.path.exists')
    def test_analyze_files_nonexistent(self, mock_exists):
        """测试不存在的文件"""
        mock_exists.return_value = False
        
        files = ["/nonexistent/file.pdf"]
        infos = self.merger.analyze_files(files)
        
        assert len(infos) == 0
    
    def test_plan_merge_groups_no_limits(self):
        """测试无限制的合并分组"""
        pdf_infos = [
            Mock(pages=10, size_mb=1.0),
            Mock(pages=20, size_mb=2.0),
            Mock(pages=30, size_mb=3.0)
        ]
        
        groups = self.merger.plan_merge_groups(pdf_infos)
        
        assert len(groups) == 1
        assert len(groups[0]) == 3
    
    def test_plan_merge_groups_page_limit(self):
        """测试页数限制的合并分组"""
        self.merger.config.max_pages = 25
        
        pdf_infos = [
            Mock(pages=10, size_mb=1.0),
            Mock(pages=20, size_mb=2.0),
            Mock(pages=30, size_mb=3.0)
        ]
        
        groups = self.merger.plan_merge_groups(pdf_infos)
        
        # 第一组：10页，第二组：20页，第三组：30页（因为20+30>25）
        assert len(groups) == 3
        assert len(groups[0]) == 1  # 第一个文件
        assert len(groups[1]) == 1  # 第二个文件
        assert len(groups[2]) == 1  # 第三个文件
    
    def test_plan_merge_groups_size_limit(self):
        """测试文件大小限制的合并分组"""
        self.merger.config.max_file_size_mb = 2.5
        
        pdf_infos = [
            Mock(pages=10, size_mb=1.0),
            Mock(pages=20, size_mb=2.0),
            Mock(pages=30, size_mb=3.0)
        ]
        
        groups = self.merger.plan_merge_groups(pdf_infos)
        
        # 第一组：1.0MB，第二组：2.0MB，第三组：3.0MB（因为2.0+3.0>2.5）
        assert len(groups) == 3
        assert len(groups[0]) == 1  # 第一个文件
        assert len(groups[1]) == 1  # 第二个文件  
        assert len(groups[2]) == 1  # 第三个文件
    
    def test_generate_output_path_single_file(self):
        """测试单文件输出路径生成"""
        path = self.merger.generate_output_path("test", 0, 1)
        expected = os.path.join(self.temp_dir, "test.pdf")
        assert path == expected
    
    def test_generate_output_path_multi_files(self):
        """测试多文件输出路径生成"""
        path = self.merger.generate_output_path("test", 1, 3)
        expected = os.path.join(self.temp_dir, "test_002.pdf")
        assert path == expected
    
    def test_sanitize_filename(self):
        """测试文件名清理"""
        unsafe_name = 'test<file>name:with"bad/chars.pdf'
        safe_name = self.merger._sanitize_filename(unsafe_name)
        assert '<' not in safe_name
        assert '>' not in safe_name
        assert ':' not in safe_name
        assert '"' not in safe_name
        assert '/' not in safe_name
        assert safe_name.endswith('.pdf')
    
    def test_merge_group_basic(self):
        """测试基本合并组功能（简化版）"""
        # 临时启用覆盖
        self.merger.config.overwrite_existing = True
        
        with patch('pdf_helper.pdf_merger.PdfReader') as mock_pdf_reader, \
             patch('pdf_helper.pdf_merger.PdfWriter') as mock_pdf_writer, \
             patch('builtins.open'), \
             patch('os.path.exists', return_value=True):
            
            # 模拟PDF读取器
            mock_reader = Mock()
            mock_reader.pages = [Mock(), Mock()]
            mock_reader.metadata = None
            mock_pdf_reader.return_value = mock_reader
            
            # 模拟PDF写入器
            mock_writer_instance = Mock()
            mock_writer_instance.pages = [Mock(), Mock()]
            mock_pdf_writer.return_value = mock_writer_instance
            
            pdf_infos = [Mock(path="/test/file1.pdf", pages=2)]
            output_path = os.path.join(self.temp_dir, "test.pdf")
            
            result = self.merger.merge_group(pdf_infos, output_path)
            
            # 验证调用了写入方法
            assert mock_writer_instance.write.called
    
    def test_get_available_template_variables(self):
        """测试获取可用模板变量"""
        variables = self.merger.get_available_template_variables()
        
        expected_keys = {'name', 'index', 'total', 'date', 'time', 'datetime', 'timestamp'}
        assert set(variables.keys()) == expected_keys
    
    @patch.object(PdfMerger, 'analyze_files')
    def test_estimate_output_info(self, mock_analyze):
        """测试输出信息估算"""
        mock_infos = [
            Mock(pages=10, size_mb=1.0),
            Mock(pages=20, size_mb=2.0)
        ]
        mock_analyze.return_value = mock_infos
        
        info = self.merger.estimate_output_info(["/test1.pdf", "/test2.pdf"])
        
        assert info['total_files'] == 2
        assert info['total_pages'] == 30
        assert info['total_size_mb'] == 3.0
        assert info['estimated_groups'] == 1
    
    @patch.object(PdfMerger, 'merge_group')
    @patch.object(PdfMerger, 'plan_merge_groups')
    @patch.object(PdfMerger, 'analyze_files')
    def test_merge_files_success(self, mock_analyze, mock_plan, mock_merge_group):
        """测试成功合并文件"""
        # 模拟分析结果
        mock_infos = [Mock(pages=10, size_mb=1.0), Mock(pages=20, size_mb=2.0)]
        mock_analyze.return_value = mock_infos
        
        # 模拟分组结果
        mock_plan.return_value = [mock_infos]
        
        # 模拟合并成功
        mock_merge_group.return_value = True
        
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024*1024):
            
            result = self.merger.merge_files(["/test1.pdf", "/test2.pdf"], "output")
        
        assert result.success is True
        assert len(result.output_files) == 1
        assert result.total_pages == 30
        assert result.source_files_count == 2


class TestCreateMerger:
    """测试create_merger便捷函数"""
    
    def test_create_merger_default(self):
        """测试默认参数创建合并器"""
        merger = create_merger()
        
        assert merger.config.max_pages is None
        assert merger.config.max_file_size_mb is None
        assert merger.config.output_dir == "/tmp"
    
    def test_create_merger_custom(self):
        """测试自定义参数创建合并器"""
        with tempfile.TemporaryDirectory() as temp_dir:
            merger = create_merger(
                max_pages=100,
                max_file_size_mb=50.0,
                output_dir=temp_dir
            )
            
            assert merger.config.max_pages == 100
            assert merger.config.max_file_size_mb == 50.0
            assert merger.config.output_dir == temp_dir


# 集成测试
class TestPdfMergerIntegration:
    """PDF合并器集成测试"""
    
    def setup_method(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
    
    def test_end_to_end_basic(self):
        """基础端到端测试"""
        # 创建测试PDF文件
        test_files = []
        for i in range(3):
            test_file = os.path.join(self.temp_dir, f"test_{i}.pdf")
            Path(test_file).touch()
            test_files.append(test_file)
        
        # 创建合并器，启用覆盖
        merger = create_merger(
            output_dir=self.temp_dir,
            single_file_template="merged.pdf",
            multi_file_template="merged_{index:02d}.pdf"
        )
        merger.config.overwrite_existing = True
        
        with patch('pdf_helper.pdf_merger.PdfReader') as mock_pdf_reader, \
             patch('pdf_helper.pdf_merger.PdfWriter') as mock_pdf_writer, \
             patch('builtins.open'), \
             patch('os.path.getsize', return_value=1024*1024):
            
            # 模拟PDF读取器
            mock_reader = Mock()
            mock_reader.pages = [Mock() for _ in range(3)]  # 每个文件3页
            mock_reader.metadata = None
            mock_pdf_reader.return_value = mock_reader
            
            # 模拟PDF写入器
            mock_writer_instance = Mock()
            mock_writer_instance.pages = [Mock() for _ in range(9)]  # 总共9页
            mock_pdf_writer.return_value = mock_writer_instance
            
            # 创建输出文件
            output_file = os.path.join(self.temp_dir, "merged.pdf")
            Path(output_file).touch()
            
            result = merger.merge_files(test_files, "merged")
        
        # 验证基本结果
        assert result.source_files_count == 3