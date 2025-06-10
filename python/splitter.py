import os
import re
from urllib.parse import urlparse
import logging

# 配置日志，与 tg-parser.py 一致
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 支持的协议列表，与工作流中的 Base64 步骤和 tg-parser.py 一致
SUPPORTED_PROTOCOLS = [
    'vmess', 'vless', 'trojan', 'ss', 'socks', 'hysteria2', 'tuic',
    'hysteria', 'naive', 'ssr'
]

# 输出目录
OUTPUT_DIR = 'python'

def normalize_scheme(scheme):
    """规范化协议，例如将 hy2 转换为 hysteria2"""
    scheme = scheme.lower()
    if scheme == 'hy2':
        return 'hysteria2'
    return scheme

def split_proxies():
    """从本地 configtg.txt 读取代理链接，按协议分割到对应文件"""
    input_file = 'configtg.txt'
    
    # 检查输入文件是否存在
    if not os.path.exists(input_file):
        logging.error(f"{input_file} 不存在，跳过分割。")
        return False

    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 初始化协议文件句柄
    protocol_files = {
        proto: open(os.path.join(OUTPUT_DIR, proto), 'w', encoding='utf-8')
        for proto in SUPPORTED_PROTOCOLS
    }
    unknown_file = open(os.path.join(OUTPUT_DIR, 'unknown'), 'w', encoding='utf-8')

    # 读取 configtg.txt，跟踪已处理链接以确保去重
    seen_links = set()
    link_count = 0
    unique_count = 0

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                link = line.strip()
                if not link or link in seen_links:
                    logging.debug(f"跳过重复或空链接: {link[:50]}...")
                    continue
                link_count += 1
                seen_links.add(link)

                # 提取协议
                try:
                    parsed = urlparse(link)
                    scheme = normalize_scheme(parsed.scheme)
                    
                    # 写入对应协议文件
                    if scheme in protocol_files:
                        protocol_files[scheme].write(link + '\n')
                        unique_count += 1
                        logging.debug(f"写入 {scheme} 链接: {link[:50]}...")
                    else:
                        unknown_file.write(link + '\n')
                        logging.warning(f"未知协议 {scheme}: {link[:50]}...")
                except Exception as e:
                    logging.error(f"解析链接失败: {link[:50]}... 错误: {e}")
                    unknown_file.write(link + '\n')

        logging.info(f"处理 {link_count} 条链接，写入 {unique_count} 条唯一链接。")
        return True

    except Exception as e:
        logging.error(f"读取 {input_file} 失败: {e}")
        return False

    finally:
        # 关闭所有文件句柄
        for f in protocol_files.values():
            f.close()
        unknown_file.close()

        # 删除空文件
        for proto in SUPPORTED_PROTOCOLS + ['unknown']:
            file_path = os.path.join(OUTPUT_DIR, proto)
            if os.path.exists(file_path) and os.path.getsize(file_path) == 0:
                os.remove(file_path)
                logging.info(f"删除空文件: {file_path}")

if __name__ == '__main__':
    logging.info("开始分割代理链接...")
    success = split_proxies()
    if success:
        logging.info("分割完成。")
    else:
        logging.error("分割失败。")
