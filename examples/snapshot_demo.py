#!/usr/bin/env python3
"""
截图API演示

演示如何使用新的截图API获取活跃页面的实时截图。
"""

import asyncio
import aiohttp
import json
import os
import sys


async def demo_snapshot_api(auth_token: str = None):
    """演示截图API的使用"""
    
    # 服务器地址
    base_url = "http://localhost:8000"
    
    # 构建查询参数
    def build_url(endpoint: str) -> str:
        url = f"{base_url}{endpoint}"
        if auth_token:
            separator = "&" if "?" in endpoint else "?"
            url += f"{separator}token={auth_token}"
        return url
    
    async with aiohttp.ClientSession() as session:
        
        print("📊 获取服务器状态...")
        try:
            async with session.get(build_url("/status")) as resp:
                if resp.status == 200:
                    status = await resp.json()
                    print(f"✅ 服务器状态: {status}")
                elif resp.status == 401:
                    print("❌ 认证失败: 无效的token或缺少token参数")
                    print("请使用正确的token运行: python examples/snapshot_demo.py <your-token>")
                    return
                else:
                    print(f"❌ 服务器不可访问 (状态码: {resp.status})")
                    if resp.status == 401:
                        error_text = await resp.text()
                        print(f"   错误信息: {error_text}")
                    return
        except aiohttp.ClientError as e:
            print(f"❌ 无法连接到服务器: {e}")
            print("请确保服务器正在运行：python -m doc_helper --server")
            return
        
        print("\n📋 获取活跃页面列表...")
        try:
            async with session.get(build_url("/pages")) as resp:
                if resp.status == 200:
                    pages_info = await resp.json()
                    total_pages = pages_info.get("total_pages", 0)
                    print(f"✅ 找到 {total_pages} 个活跃页面")
                    
                    if total_pages == 0:
                        print("💡 没有活跃页面，请先启动页面处理：")
                        print("   python -m doc_helper https://example.com --find-links")
                        return
                    
                    # 显示页面信息
                    for page in pages_info.get("pages", []):
                        print(f"   槽位 {page['slot']}: {page['url']} (标题: {page.get('title', '未知')})")
                    
                elif resp.status == 401:
                    print("❌ 认证失败: 无效的token")
                    return
                else:
                    print(f"❌ 获取页面列表失败 (状态码: {resp.status})")
                    return
        except aiohttp.ClientError as e:
            print(f"❌ 获取页面列表失败: {e}")
            return
        
        # 获取第一个页面的截图
        if total_pages > 0:
            slot = 0
            print(f"\n📸 获取槽位 {slot} 的页面截图...")
            try:
                async with session.get(build_url(f"/snapshot/{slot}")) as resp:
                    if resp.status == 200:
                        screenshot_data = await resp.read()
                        filename = f"page_snapshot_slot_{slot}.png"
                        
                        with open(filename, "wb") as f:
                            f.write(screenshot_data)
                        
                        print(f"✅ 截图已保存到: {filename}")
                        print(f"   文件大小: {len(screenshot_data)} 字节")
                        
                    elif resp.status == 404:
                        print(f"❌ 槽位 {slot} 不存在或截图失败")
                    else:
                        print(f"❌ 获取截图失败 (状态码: {resp.status})")
                        error_text = await resp.text()
                        print(f"   错误信息: {error_text}")
            except aiohttp.ClientError as e:
                print(f"❌ 获取截图失败: {e}")
        
        # 测试无效槽位
        print(f"\n🔍 测试无效槽位 (槽位 999)...")
        try:
            async with session.get(build_url("/snapshot/999")) as resp:
                if resp.status == 404:
                    print("✅ 正确返回 404 错误")
                else:
                    print(f"⚠️  意外的状态码: {resp.status}")
        except aiohttp.ClientError as e:
            print(f"❌ 请求失败: {e}")


def main():
    """主函数"""
    print("🚀 截图API演示")
    print("=" * 50)
    
    # 检查命令行参数中是否有token
    auth_token = None
    if len(sys.argv) > 1:
        auth_token = sys.argv[1]
        print(f"🔒 使用认证令牌: {auth_token[:8]}...")
    else:
        print("🔓 未提供认证令牌，假设服务器未启用认证")
    
    try:
        asyncio.run(demo_snapshot_api(auth_token))
    except KeyboardInterrupt:
        print("\n\n👋 演示被用户中断")
    except Exception as e:
        print(f"\n❌ 演示过程中发生错误: {e}")
    
    print("\n" + "=" * 50)
    print("📝 使用说明:")
    print("1. 启动服务器: python -m doc_helper --server")
    print("2. 启用认证: python -m doc_helper --server --auth-token 'your-secret'")
    print("3. 在另一个终端启动页面处理: python -m doc_helper https://example.com --find-links")
    print("4. 运行此演示: python examples/snapshot_demo.py [auth-token]")
    print("\n🌐 API端点:")
    print("- GET /pages - 获取活跃页面列表")
    print("- GET /snapshot/<slot> - 获取指定槽位的页面截图")
    print("- 需要认证时在URL后添加: ?token=<your-token>")


if __name__ == "__main__":
    main()