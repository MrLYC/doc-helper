"""
测试服务器认证功能
"""

import pytest
from unittest.mock import MagicMock
from fastapi import Request, HTTPException

from doc_helper.server import verify_auth_token, ServerConfig
import doc_helper.server as server_module


class TestServerAuth:
    """测试服务器认证功能"""

    def test_verify_auth_token_no_config(self):
        """测试无配置时的认证验证"""
        original_config = server_module.server_config
        server_module.server_config = None
        
        try:
            # 创建mock请求
            mock_request = MagicMock(spec=Request)
            mock_request.query_params = {}
            
            # 无配置应该通过验证
            result = verify_auth_token(mock_request)
            assert result is None  # 函数应该正常返回
        finally:
            server_module.server_config = original_config

    def test_verify_auth_token_no_token_required(self):
        """测试未设置认证令牌时的验证"""
        original_config = server_module.server_config
        
        # 设置无认证令牌的配置
        test_config = ServerConfig()
        test_config.auth_token = None
        server_module.server_config = test_config
        
        try:
            # 创建mock请求
            mock_request = MagicMock(spec=Request)
            mock_request.query_params = {}
            
            # 无认证令牌设置应该通过验证
            result = verify_auth_token(mock_request)
            assert result is None
        finally:
            server_module.server_config = original_config

    def test_verify_auth_token_valid_token(self):
        """测试有效令牌的验证"""
        original_config = server_module.server_config
        
        # 设置认证令牌
        test_config = ServerConfig()
        test_config.auth_token = "valid-token"
        server_module.server_config = test_config
        
        try:
            # 创建包含正确token的mock请求
            mock_request = MagicMock(spec=Request)
            mock_query_params = MagicMock()
            mock_query_params.get.return_value = "valid-token"
            mock_request.query_params = mock_query_params
            
            # 有效token应该通过验证
            result = verify_auth_token(mock_request)
            assert result is None
        finally:
            server_module.server_config = original_config

    def test_verify_auth_token_invalid_token(self):
        """测试无效令牌的验证"""
        original_config = server_module.server_config
        
        # 设置认证令牌
        test_config = ServerConfig()
        test_config.auth_token = "valid-token"
        server_module.server_config = test_config
        
        try:
            # 创建包含错误token的mock请求
            mock_request = MagicMock(spec=Request)
            mock_query_params = MagicMock()
            mock_query_params.get.return_value = "invalid-token"
            mock_request.query_params = mock_query_params
            
            # 错误token应该抛出异常
            with pytest.raises(HTTPException) as exc_info:
                verify_auth_token(mock_request)
            
            assert exc_info.value.status_code == 401
            assert "无效的认证令牌" in exc_info.value.detail
        finally:
            server_module.server_config = original_config

    def test_verify_auth_token_missing_token(self):
        """测试缺少令牌的验证"""
        original_config = server_module.server_config
        
        # 设置认证令牌
        test_config = ServerConfig()
        test_config.auth_token = "required-token"
        server_module.server_config = test_config
        
        try:
            # 创建不包含token的mock请求
            mock_request = MagicMock(spec=Request)
            mock_query_params = MagicMock()
            mock_query_params.get.return_value = None
            mock_request.query_params = mock_query_params
            
            # 缺少token应该抛出异常
            with pytest.raises(HTTPException) as exc_info:
                verify_auth_token(mock_request)
            
            assert exc_info.value.status_code == 401
            assert "无效的认证令牌" in exc_info.value.detail
        finally:
            server_module.server_config = original_config

    def test_server_config_auth_token_attribute(self):
        """测试ServerConfig包含auth_token属性"""
        config = ServerConfig()
        
        # 默认应该是None
        assert config.auth_token is None
        
        # 可以设置值
        config.auth_token = "test-token"
        assert config.auth_token == "test-token"