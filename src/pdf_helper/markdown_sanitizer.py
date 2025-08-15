#!/usr/bin/env python3
"""
Markdown敏感信息替换脚本

功能：
1. 根据CSV字典文件中的规则，扫描并替换markdown文件中的敏感信息
2. 支持多种处理动作：manual、ipv4、ipv6、domain、url等
3. 交互式确认替换过程
4. 保留markdown的链接和图片引用格式
"""

import argparse
import csv
import re
import hashlib
import ipaddress
import urllib.parse
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable, Any
from dataclasses import dataclass
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class Rule:
    """替换规则"""
    category: str
    match_type: str  # 'keyword' 或 'regex'
    pattern: str
    priority: int
    action: str
    compiled_pattern: re.Pattern = None
    
    def __post_init__(self):
        """编译正则表达式"""
        if self.match_type == 'keyword':
            # 关键字转换为正则表达式，添加单词边界
            escaped_pattern = re.escape(self.pattern)
            self.compiled_pattern = re.compile(f'\\b{escaped_pattern}\\b', re.IGNORECASE)
        elif self.match_type == 'regex':
            self.compiled_pattern = re.compile(self.pattern, re.IGNORECASE)
        else:
            raise ValueError(f"不支持的匹配方式: {self.match_type}")

@dataclass 
class Match:
    """匹配结果"""
    rule: Rule
    start: int
    end: int
    text: str
    groups: Dict[str, str]
    context_before: str
    context_after: str

class SensitiveDataReplacer:
    """敏感数据替换器"""
    
    def __init__(self, context_chars: int = 20):
        self.context_chars = context_chars
        self.rules: List[Rule] = []
        self.actions: Dict[str, Callable] = {
            'manual': self._action_manual,
            'ipv4': self._action_ipv4,
            'ipv6': self._action_ipv6, 
            'domain': self._action_domain,
            'url': self._action_url,
        }
        
        # IP地址映射缓存
        self.ipv4_cache: Dict[str, str] = {}
        self.ipv6_cache: Dict[str, str] = {}
        self.domain_cache: Dict[str, str] = {}
        
    def load_rules(self, csv_file: str):
        """加载CSV规则文件"""
        logger.info(f"加载规则文件: {csv_file}")
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # 跳过表头
            
            for row_num, row in enumerate(reader, 2):
                if len(row) < 5:
                    logger.warning(f"第{row_num}行格式不正确，跳过: {row}")
                    continue
                    
                category, match_type, pattern, priority_str, action = row[:5]
                
                try:
                    priority = int(priority_str)
                except ValueError:
                    logger.error(f"第{row_num}行优先级无效: {priority_str}")
                    continue
                
                # 检查处理动作是否存在
                if action not in self.actions:
                    logger.error(f"第{row_num}行处理动作不存在: {action}")
                    logger.error(f"可用的处理动作: {', '.join(self.actions.keys())}")
                    raise ValueError(f"不支持的处理动作: {action}")
                
                rule = Rule(category, match_type, pattern, priority, action)
                self.rules.append(rule)
                logger.info(f"加载规则: {category} - {match_type} - {action} (优先级: {priority})")
        
        # 按优先级排序（数值越小优先级越高）
        self.rules.sort(key=lambda r: r.priority)
        logger.info(f"总共加载了 {len(self.rules)} 条规则")
    
    def _get_context(self, text: str, start: int, end: int) -> Tuple[str, str]:
        """获取匹配内容的上下文"""
        context_start = max(0, start - self.context_chars)
        context_end = min(len(text), end + self.context_chars)
        
        context_before = text[context_start:start]
        context_after = text[end:context_end]
        
        return context_before, context_after
    
    def _is_in_markdown_link_or_image(self, text: str, start: int, end: int) -> bool:
        """检查匹配位置是否在markdown链接或图片中"""
        # 查找前面的markdown语法
        before_text = text[:start]
        after_text = text[end:]
        
        # 检查是否在链接中 [text](url) 或 ![alt](url)
        link_pattern = r'!?\[[^\]]*\]\([^)]*$'
        if re.search(link_pattern, before_text):
            # 检查后面是否有闭合的 )
            if ')' in after_text:
                return True
        
        # 检查是否在引用链接中 [text][ref] 或 ![alt][ref]
        ref_pattern = r'!?\[[^\]]*\]\[[^\]]*$'
        if re.search(ref_pattern, before_text):
            if ']' in after_text:
                return True
        
        # 检查是否在链接定义中 [ref]: url
        def_pattern = r'^\s*\[[^\]]+\]:\s*[^\s]*$'
        # 找到当前行
        line_start = before_text.rfind('\n') + 1
        line_end = text.find('\n', end)
        if line_end == -1:
            line_end = len(text)
        current_line = text[line_start:line_end]
        
        if re.match(def_pattern, current_line):
            return True
        
        return False
    
    def find_matches(self, text: str) -> List[Match]:
        """在文本中查找所有匹配项"""
        matches = []
        
        for rule in self.rules:
            for match in rule.compiled_pattern.finditer(text):
                start, end = match.span()
                
                # 检查是否在markdown链接或图片中
                if self._is_in_markdown_link_or_image(text, start, end):
                    logger.debug(f"跳过markdown链接/图片中的匹配: {match.group()}")
                    continue
                
                context_before, context_after = self._get_context(text, start, end)
                
                # 获取命名组
                groups = match.groupdict()
                
                matches.append(Match(
                    rule=rule,
                    start=start,
                    end=end,
                    text=match.group(),
                    groups=groups,
                    context_before=context_before,
                    context_after=context_after
                ))
        
        # 按位置排序，避免重叠替换问题
        matches.sort(key=lambda m: m.start)
        return matches
    
    def _hash_to_range(self, input_str: str, min_val: int, max_val: int) -> int:
        """将字符串哈希到指定范围内的整数"""
        hash_obj = hashlib.md5(input_str.encode('utf-8'))
        hash_int = int(hash_obj.hexdigest(), 16)
        return min_val + (hash_int % (max_val - min_val + 1))
    
    def _action_manual(self, context_before: str, original: str, **kwargs) -> str:
        """手动替换处理动作"""
        print(f"\n=== 手动替换 ===")
        print(f"上下文: ...{context_before}[{original}]...")
        print(f"原始内容: {original}")
        
        if kwargs:
            print(f"命名组参数: {kwargs}")
            print("可用变量名:")
            for key in kwargs.keys():
                print(f"  - {{{key}}}")
        
        while True:
            template = input("请输入替换模板 (留空跳过): ").strip()
            if not template:
                return original
            
            try:
                result = template.format(**kwargs)
                print(f"替换结果: {result}")
                confirm = input("确认替换? [y/N]: ").strip().lower()
                if confirm in ['y', 'yes', 'Y']:
                    return result
                elif confirm in ['n', 'no', 'N', '']:
                    continue
            except KeyError as e:
                print(f"模板错误: 未知变量 {e}")
            except Exception as e:
                print(f"模板错误: {e}")
    
    def _action_ipv4(self, context_before: str, original: str, **kwargs) -> str:
        """IPv4地址处理动作"""
        if original in self.ipv4_cache:
            return self.ipv4_cache[original]
        
        try:
            ip = ipaddress.IPv4Address(original)
            ip_int = int(ip)
            
            # 将IPv4地址映射到240.0.0.0-255.255.255.254范围
            # 保持网段概念：使用原IP的网段结构
            octets = str(ip).split('.')
            
            # 基于原始IP生成一致的映射
            hash_seed = f"ipv4_{original}"
            
            # 第一个八位组：240-255
            first_octet = self._hash_to_range(f"{hash_seed}_1", 240, 255)
            
            # 其他八位组：基于原始值进行映射
            second_octet = self._hash_to_range(f"{hash_seed}_2_{octets[1]}", 0, 255)
            third_octet = self._hash_to_range(f"{hash_seed}_3_{octets[2]}", 0, 255)  
            fourth_octet = self._hash_to_range(f"{hash_seed}_4_{octets[3]}", 1, 254)  # 避免.0和.255
            
            fake_ip = f"{first_octet}.{second_octet}.{third_octet}.{fourth_octet}"
            self.ipv4_cache[original] = fake_ip
            
            logger.info(f"IPv4映射: {original} -> {fake_ip}")
            return fake_ip
            
        except ipaddress.AddressValueError:
            logger.warning(f"无效的IPv4地址: {original}")
            return original
    
    def _action_ipv6(self, context_before: str, original: str, **kwargs) -> str:
        """IPv6地址处理动作"""
        if original in self.ipv6_cache:
            return self.ipv6_cache[original]
        
        try:
            ip = ipaddress.IPv6Address(original)
            
            # 映射到FC00::/8范围
            hash_seed = f"ipv6_{original}"
            
            # 生成FC00::/8范围内的地址
            # FC00::/8 = FC00:0000:0000:0000:0000:0000:0000:0000 到 FDFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF:FFFF
            
            # 保留原始地址的结构特征
            parts = str(ip.exploded).split(':')
            fake_parts = ['fc00']  # 固定前缀
            
            for i in range(1, 8):
                if i < len(parts):
                    part_hash = self._hash_to_range(f"{hash_seed}_{i}_{parts[i]}", 0, 0xFFFF)
                else:
                    part_hash = self._hash_to_range(f"{hash_seed}_{i}", 0, 0xFFFF)
                fake_parts.append(f"{part_hash:04x}")
            
            fake_ip = ':'.join(fake_parts)
            # 压缩表示
            fake_ip = str(ipaddress.IPv6Address(fake_ip))
            
            self.ipv6_cache[original] = fake_ip
            logger.info(f"IPv6映射: {original} -> {fake_ip}")
            return fake_ip
            
        except ipaddress.AddressValueError:
            logger.warning(f"无效的IPv6地址: {original}")
            return original
    
    def _action_domain(self, context_before: str, original: str, **kwargs) -> str:
        """域名处理动作"""
        if original in self.domain_cache:
            return self.domain_cache[original]
        
        # 解析域名
        domain_lower = original.lower()
        parts = domain_lower.split('.')
        
        if len(parts) < 2:
            return original
        
        # 基于原始域名生成假域名
        hash_seed = f"domain_{domain_lower}"
        
        # 生成子域名
        if len(parts) > 2:
            # 多级域名，保留结构
            subdomain_parts = []
            for i, part in enumerate(parts[:-2]):
                fake_part = f"sub{self._hash_to_range(f'{hash_seed}_{i}_{part}', 1, 999)}"
                subdomain_parts.append(fake_part)
            fake_domain = '.'.join(subdomain_parts) + '.example.com'
        else:
            # 二级域名
            fake_name = f"site{self._hash_to_range(hash_seed, 1, 9999)}"
            fake_domain = f"{fake_name}.example.com"
        
        self.domain_cache[original] = fake_domain
        logger.info(f"域名映射: {original} -> {fake_domain}")
        return fake_domain
    
    def _action_url(self, context_before: str, original: str, **kwargs) -> str:
        """URL处理动作"""
        try:
            parsed = urllib.parse.urlparse(original)
            
            # 处理域名部分
            if parsed.netloc:
                fake_domain = self._action_domain("", parsed.netloc)
            else:
                fake_domain = "example.com"
            
            # 处理路径
            fake_path = parsed.path
            if fake_path:
                # 保留文件扩展名
                path_parts = fake_path.split('/')
                fake_path_parts = []
                
                for part in path_parts:
                    if not part:
                        fake_path_parts.append("")
                        continue
                    
                    # 检查是否有扩展名
                    if '.' in part:
                        name, ext = part.rsplit('.', 1)
                        hash_seed = f"path_{name}"
                        fake_name = f"page{self._hash_to_range(hash_seed, 1, 999)}"
                        fake_path_parts.append(f"{fake_name}.{ext}")
                    else:
                        hash_seed = f"path_{part}"
                        fake_name = f"dir{self._hash_to_range(hash_seed, 1, 999)}"
                        fake_path_parts.append(fake_name)
                
                fake_path = '/'.join(fake_path_parts)
            
            # 处理查询参数（保留键名，混淆值）
            fake_query = ""
            if parsed.query:
                query_params = urllib.parse.parse_qsl(parsed.query)
                fake_params = []
                
                for key, value in query_params:
                    # 保留键名，混淆值
                    if value:
                        hash_seed = f"query_{key}_{value}"
                        fake_value = f"val{self._hash_to_range(hash_seed, 1, 999)}"
                    else:
                        fake_value = ""
                    fake_params.append(f"{key}={fake_value}")
                
                fake_query = '&'.join(fake_params)
            
            # 重构URL
            fake_url = urllib.parse.urlunparse((
                parsed.scheme or 'https',
                fake_domain,
                fake_path,
                parsed.params,
                fake_query,
                parsed.fragment
            ))
            
            logger.info(f"URL映射: {original} -> {fake_url}")
            return fake_url
            
        except Exception as e:
            logger.warning(f"URL解析失败: {original} - {e}")
            return original
    
    def replace_interactive(self, text: str) -> str:
        """交互式替换文本中的敏感信息"""
        matches = self.find_matches(text)
        
        if not matches:
            logger.info("未找到需要替换的内容")
            return text
        
        logger.info(f"找到 {len(matches)} 个匹配项")
        
        # 从后往前替换，避免位置偏移
        matches.reverse()
        result_text = text
        
        for i, match in enumerate(matches):
            print(f"\n=== 匹配项 {len(matches) - i}/{len(matches)} ===")
            print(f"分类: {match.rule.category}")
            print(f"规则: {match.rule.pattern} ({match.rule.match_type})")
            print(f"处理动作: {match.rule.action}")
            print(f"匹配内容: {match.text}")
            print(f"上下文: ...{match.context_before}[{match.text}]{match.context_after}...")
            
            # 应用处理动作
            action_func = self.actions[match.rule.action]
            replacement = action_func(match.context_before, match.text, **match.groups)
            
            if replacement != match.text:
                print(f"建议替换为: {replacement}")
                
                while True:
                    choice = input("选择操作 [r]替换 [s]跳过 [q]退出 [e]编辑: ").strip().lower()
                    
                    if choice in ['r', 'replace', '']:
                        # 执行替换（注意要调整位置，因为前面可能有替换）
                        result_text = result_text[:match.start] + replacement + result_text[match.end:]
                        print(f"✅ 已替换: {match.text} -> {replacement}")
                        break
                    elif choice in ['s', 'skip']:
                        print("⏭️ 已跳过")
                        break
                    elif choice in ['q', 'quit']:
                        print("🛑 用户退出")
                        return result_text
                    elif choice in ['e', 'edit']:
                        custom_replacement = input(f"请输入自定义替换内容 (原内容: {match.text}): ").strip()
                        if custom_replacement:
                            result_text = result_text[:match.start] + custom_replacement + result_text[match.end:]
                            print(f"✅ 已替换: {match.text} -> {custom_replacement}")
                            break
                        else:
                            print("输入为空，请重新选择")
                    else:
                        print("无效选择，请输入 r/s/q/e")
            else:
                print("📝 处理动作未产生替换")
        
        return result_text
    
    def process_file(self, input_file: str, output_file: str = None):
        """处理markdown文件"""
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_file}")
        
        logger.info(f"处理文件: {input_file}")
        
        # 读取文件
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 交互式替换
        result_content = self.replace_interactive(content)
        
        # 输出文件
        if output_file:
            output_path = Path(output_file)
        else:
            output_path = input_path.with_suffix('.sanitized.md')
        
        # 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result_content)
        
        logger.info(f"处理完成，输出文件: {output_path}")
        return str(output_path)

def main():
    parser = argparse.ArgumentParser(description="Markdown敏感信息替换工具")
    parser.add_argument("--rules", "-r", required=True, help="CSV规则文件路径")
    parser.add_argument("--input", "-i", required=True, help="输入Markdown文件路径")
    parser.add_argument("--output", "-o", help="输出文件路径 (默认为输入文件名.sanitized.md)")
    parser.add_argument("--context", "-c", type=int, default=20, help="上下文字符数量 (默认: 20)")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # 创建替换器
        replacer = SensitiveDataReplacer(context_chars=args.context)
        
        # 加载规则
        replacer.load_rules(args.rules)
        
        # 处理文件
        output_file = replacer.process_file(args.input, args.output)
        
        print(f"\n✅ 处理完成!")
        print(f"📁 输出文件: {output_file}")
        
    except Exception as e:
        logger.error(f"处理失败: {e}")
        raise

if __name__ == "__main__":
    main()
