#!/usr/bin/env python3
"""
服务器使用示例

演示如何使用 PDF 文档爬虫服务器。
"""

import subprocess
import sys
import time
from pathlib import Path


def run_server_example():
    """运行服务器示例"""
    print("=== PDF 文档爬虫服务器使用示例 ===\n")
    
    # 创建输出目录
    output_dir = "/tmp/test_pdf_output"
    Path(output_dir).mkdir(exist_ok=True)
    
    print("示例 1: 基本使用")
    print("命令:")
    cmd1 = [
        "python", "-m", "doc_helper.server",
        "--url", "https://example.com",
        "--output-dir", output_dir,
        "--concurrent-tabs", "2",
        "--page-timeout", "30",
        "--verbose"
    ]
    print(" ".join(cmd1))
    print()
    
    print("示例 2: 高级配置")
    print("命令:")
    cmd2 = [
        "python", "-m", "doc_helper.server",
        "--urls", "https://docs.python.org", "https://fastapi.tiangolo.com",
        "--output-dir", output_dir,
        "--concurrent-tabs", "5",
        "--page-timeout", "120",
        "--max-pages", "1000",
        "--max-file-size", "50",
        "--block-patterns", ".*\\.gif", ".*analytics.*",
        "--clean-selector", "*[id*='ad'], .popup",
        "--content-selector", "main article",
        "--host", "0.0.0.0",
        "--port", "8080"
    ]
    print(" ".join(cmd2))
    print()
    
    print("示例 3: 生产环境配置")
    print("命令:")
    cmd3 = [
        "python", "-m", "doc_helper.server",
        "--url", "https://docs.example.com",
        "--output-dir", "/data/pdfs",
        "--concurrent-tabs", "10",
        "--page-timeout", "180",
        "--temp-dir", "/tmp/pdf_processing",
        "--single-file-template", "documentation_{datetime}.pdf",
        "--multi-file-template", "docs_part_{index:03d}_{date}.pdf",
        "--overwrite",
        "--host", "0.0.0.0",
        "--port", "8080",
        "--log-level", "INFO"
    ]
    print(" ".join(cmd3))
    print()
    
    print("=== API 接口使用 ===")
    print("服务器启动后，可以通过以下接口监控状态：")
    print("- GET /              - 基本信息")
    print("- GET /health        - 健康检查")
    print("- GET /metrics       - Prometheus 指标")
    print("- GET /status        - 详细状态")
    print("- POST /start        - 开始处理（注意：需要额外配置）")
    print("- POST /stop         - 停止处理")
    print()
    
    print("示例 curl 命令：")
    print("curl http://localhost:8000/health")
    print("curl http://localhost:8000/metrics")
    print("curl http://localhost:8000/status")
    print()
    
    choice = input("是否运行一个简单的测试？ (y/N): ").strip().lower()
    if choice == 'y':
        print("\n正在运行测试...")
        test_cmd = [
            "python", "-m", "doc_helper.server",
            "--url", "https://httpbin.org/html",
            "--output-dir", output_dir,
            "--concurrent-tabs", "1",
            "--page-timeout", "30",
            "--port", "8001",
            "--log-level", "INFO"
        ]
        
        print(f"执行命令: {' '.join(test_cmd)}")
        print("注意: 按 Ctrl+C 停止服务器")
        print()
        
        try:
            subprocess.run(test_cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"命令执行失败: {e}")
        except KeyboardInterrupt:
            print("\n测试被用户中断")


if __name__ == "__main__":
    run_server_example()