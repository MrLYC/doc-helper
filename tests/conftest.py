"""
pytest配置文件，设置测试环境
"""

import sys
from pathlib import Path

# 将项目根目录添加到Python路径
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

# 配置pytest-asyncio
pytest_plugins = ["pytest_asyncio"]