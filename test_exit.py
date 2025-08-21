#!/usr/bin/env python3
"""
测试ChromiumManager退出逻辑
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from doc_helper.server import main


async def test_manager_exit():
    """测试管理器退出逻辑"""
    
    # 设置日志级别
    logging.basicConfig(level=logging.INFO)
    
    # 模拟命令行参数 - 使用一个简单的网站测试
    test_args = [
        '--url', 'https://httpbin.org/html',
        '--output-dir', '/tmp/test_exit',
        '--concurrent-tabs', '1',
        '--page-timeout', '20',
        '--port', '8002',
        '--log-level', 'INFO'
    ]
    
    print("=== 测试ChromiumManager退出逻辑 ===")
    print(f"测试URL: https://httpbin.org/html")
    print(f"输出目录: /tmp/test_exit")
    print("预期行为: 处理完页面后应该自动退出并生成PDF")
    print()
    
    try:
        # 运行服务器
        sys.argv = ['test_exit.py'] + test_args
        await main()
        
        print("\n✅ 测试成功: 程序正常退出")
        
        # 检查输出文件
        import os
        output_files = []
        output_dir = Path('/tmp/test_exit')
        if output_dir.exists():
            output_files = list(output_dir.glob('*.pdf'))
        
        if output_files:
            print(f"✅ 生成了 {len(output_files)} 个PDF文件:")
            for file in output_files:
                print(f"   - {file}")
        else:
            print("⚠️  没有找到生成的PDF文件")
        
    except KeyboardInterrupt:
        print("\n❌ 测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_manager_exit())