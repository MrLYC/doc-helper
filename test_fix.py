#!/usr/bin/env python3
"""
测试修复后的处理器
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from doc_helper.server import main


async def test_fixed_processors():
    """测试修复后的处理器"""
    
    # 设置日志级别
    logging.basicConfig(level=logging.INFO)
    
    # 模拟命令行参数
    test_args = [
        '--url', 'https://httpbin.org/html',
        '--output-dir', '/tmp/test_fix',
        '--concurrent-tabs', '1',
        '--page-timeout', '30',
        '--port', '8001',
        '--log-level', 'INFO',
        '--verbose'
    ]
    
    print("=== 测试修复后的处理器 ===")
    print(f"测试URL: https://httpbin.org/html")
    print(f"输出目录: /tmp/test_fix")
    print()
    
    try:
        # 确保输出目录存在
        os.makedirs('/tmp/test_fix', exist_ok=True)
        
        # 运行服务器（这会启动处理器）
        sys.argv = ['test_fix.py'] + test_args
        await main()
        
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_fixed_processors())