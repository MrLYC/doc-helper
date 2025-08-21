#!/usr/bin/env python3
"""
测试最大并发标签数限制

验证 ChromiumManager 正确限制同时打开的标签页数量。
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, '.')

from doc_helper.manager import ChromiumManager
from doc_helper.protocol import URL, URLCollection, URLStatus, PageManagerConfig

def create_simple_processor_factory():
    """创建一个简单的测试处理器工厂"""
    from doc_helper.processors import PageLoadProcessor
    return lambda: PageLoadProcessor("test_loader")

async def test_concurrent_tabs_limit():
    """测试最大并发标签数限制"""
    print("=== 测试最大并发标签数限制 ===\n")
    
    # 创建URL集合，添加多个URL
    url_collection = URLCollection()
    test_urls = [
        "https://httpbin.org/delay/1",
        "https://httpbin.org/delay/2", 
        "https://httpbin.org/delay/1",
        "https://httpbin.org/delay/2",
        "https://httpbin.org/delay/1"
    ]
    
    for i, url_str in enumerate(test_urls):
        url = URL(id=f"test_{i}", url=url_str)
        url_collection.add(url)
    
    print(f"添加了 {len(test_urls)} 个测试URL")
    
    # 设置较小的最大并发数进行测试
    config = PageManagerConfig(
        max_concurrent_tabs=2,  # 设置最大并发为2
        poll_interval=0.5,
        page_timeout=10.0,
        detect_timeout=2.0
    )
    
    print(f"设置最大并发标签数: {config.max_concurrent_tabs}")
    
    # 创建管理器
    processor_factories = [create_simple_processor_factory()]
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=processor_factories,
        config=config,
        verbose=False
    )
    
    print("开始测试...")
    
    try:
        # 创建一个任务运行管理器
        manager_task = asyncio.create_task(manager.run())
        
        # 监控活跃页面数量
        max_observed_tabs = 0
        monitoring_duration = 15  # 监控15秒
        start_time = asyncio.get_event_loop().time()
        
        while True:
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time > monitoring_duration:
                break
                
            if manager_task.done():
                break
            
            # 获取当前活跃页面信息
            active_pages = manager.get_active_pages_info()
            current_tabs = len(active_pages)
            
            if current_tabs > max_observed_tabs:
                max_observed_tabs = current_tabs
            
            # 检查是否超过限制
            if current_tabs > config.max_concurrent_tabs:
                print(f"❌ 错误: 发现 {current_tabs} 个活跃标签页，超过限制 {config.max_concurrent_tabs}")
                manager_task.cancel()
                return False
            
            if current_tabs > 0:
                print(f"⏱️  当前活跃标签页: {current_tabs}/{config.max_concurrent_tabs}")
                for page_info in active_pages:
                    print(f"    槽位 {page_info['slot']}: {page_info['url']}")
            
            await asyncio.sleep(1)
        
        # 如果管理器还在运行，取消它
        if not manager_task.done():
            manager_task.cancel()
            try:
                await manager_task
            except asyncio.CancelledError:
                pass
        
        print(f"\n✅ 测试完成!")
        print(f"   观察到的最大并发标签数: {max_observed_tabs}")
        print(f"   配置的最大并发限制: {config.max_concurrent_tabs}")
        
        if max_observed_tabs <= config.max_concurrent_tabs:
            print("✅ 最大并发限制正常工作!")
            return True
        else:
            print("❌ 最大并发限制未生效!")
            return False
            
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        return False

async def test_zero_concurrent_tabs():
    """测试最大并发数为0的情况"""
    print("\n=== 测试最大并发数为0的情况 ===\n")
    
    url_collection = URLCollection()
    url = URL(id="test_0", url="https://httpbin.org/delay/1")
    url_collection.add(url)
    
    config = PageManagerConfig(
        max_concurrent_tabs=0,  # 设置为0
        poll_interval=0.1,
        page_timeout=5.0
    )
    
    manager = ChromiumManager(
        url_collection=url_collection,
        processor_factories=[create_simple_processor_factory()],
        config=config,
        verbose=False
    )
    
    try:
        # 运行一小段时间
        manager_task = asyncio.create_task(manager.run())
        await asyncio.sleep(2)
        
        # 检查是否有活跃页面
        active_pages = manager.get_active_pages_info()
        
        if not manager_task.done():
            manager_task.cancel()
            try:
                await manager_task
            except asyncio.CancelledError:
                pass
        
        if len(active_pages) == 0:
            print("✅ 最大并发数为0时正确阻止了页面打开")
            return True
        else:
            print(f"❌ 最大并发数为0时仍然打开了 {len(active_pages)} 个页面")
            return False
            
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        return False

async def main():
    """主测试函数"""
    print("开始测试最大并发标签数限制功能")
    print("=" * 50)
    
    # 测试1: 正常的并发限制
    test1_result = await test_concurrent_tabs_limit()
    
    # 测试2: 零并发数
    test2_result = await test_zero_concurrent_tabs()
    
    print("\n" + "=" * 50)
    print("测试结果总结:")
    print(f"  正常并发限制测试: {'✅ 通过' if test1_result else '❌ 失败'}")
    print(f"  零并发数测试: {'✅ 通过' if test2_result else '❌ 失败'}")
    
    if test1_result and test2_result:
        print("\n🎉 所有测试都通过了! 最大并发标签数限制功能正常工作。")
        return 0
    else:
        print("\n⚠️  有测试失败，请检查最大并发标签数限制的实现。")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"测试运行失败: {e}")
        sys.exit(1)
