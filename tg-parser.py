import base64
import json
import logging
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs, unquote
import dns.resolver

# 配置日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 线程数配置
thrd_pars = 10

# 输出文件
CONFIG_TG_FILE = "configtg_deduplicated.txt"

# 域名归一化映射
DOMAIN_MAPPINGS = {
    'bypassfilter.wrevdav.workers.dev': 'workers.dev',
    'bypassfilter.nuktsv.workers.dev': 'workers.dev',
    # 可根据实际数据添加更多映射
}

def normalize_hostname(hostname):
    """归一化主机名，处理已知的子域名映射"""
    if not hostname:
        return hostname
    return DOMAIN_MAPPINGS.get(hostname.lower(), hostname.lower())

def clean_and_urldecode(link_string):
    """清洗和解码 URL 编码的链接字符串"""
    if not link_string:
        return None
    try:
        cleaned = unquote(link_string.strip())
        return cleaned
    except Exception as e:
        logging.debug(f"清洗或解码失败: {link_string[:50]}... Error: {e}")
        return None

def is_valid_link(parsed):
    """验证链接是否包含必要的组件"""
    return parsed.scheme and parsed.hostname and parsed.port

def is_config_valid(link, current_time=datetime.now()):
    """检查配置是否有效（不过期或不可靠）"""
    if '#' in link:
        remark = link.split('#', 1)[1]
        if re.search(r'فعال تا ساعت \d+', remark):
            time_str = re.search(r'فعال تا ساعت (\d+)', remark).group(1)
            hour = int(time_str)
            if hour < current_time.hour:
                logging.debug(f"配置已过期: {link[:50]}...")
                return False
        if 'دیسیبل میشه' in remark or 'غیرفعال' in remark:
            logging.debug(f"配置标记为不可靠: {link[:50]}...")
            return False
    return True

def parse_and_canonicalize(link_string):
    """解析并规范化链接，生成唯一的 canonical_id"""
    if not link_string or not isinstance(link_string, str):
        logging.debug("输入链接字符串为空或非字符串类型。")
        return None

    cleaned_decoded_link = clean_and_urldecode(link_string)
    if not cleaned_decoded_link:
        logging.debug(f"清洗或 URL 解码失败: {link_string[:50]}...")
        return None

    link_without_fragment = cleaned_decoded_link.split('#', 1)[0]
    scheme_specific_part = link_without_fragment
    scheme = ''
    decoded_payload = ''

    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            scheme_specific_part = 'vmess://' + decoded_payload
            logging.debug(f"VMess Base64 解码成功: {decoded_payload[:50]}...")
        except Exception as e:
            logging.debug(f"VMess Base64 解码失败: {link_without_fragment[:50]}... Error: {e}")
            return None
    elif link_without_fragment.startswith('ssr://'):
        scheme = 'ssr'
        try:
            b64_payload = link_without_fragment[6:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            scheme_specific_part = 'ssr://' + decoded_payload
            logging.debug(f"SSR Base64 解码成功: {decoded_payload[:50]}...")
        except Exception as e:
            logging.debug(f"SSR Base64 解码失败: {link_without_fragment[:50]}... Error: {e}")
            return None
    elif '://' in link_without_fragment:
        try:
            scheme = link_without_fragment.split('://', 1)[0].lower()
        except Exception as e:
            logging.debug(f"提取协议失败: {link_without_fragment[:50]}... Error: {e}")
            return None
    else:
        logging.debug(f"链接不包含协议: {link_without_fragment[:50]}...")
        return None

    try:
        parsed = urlparse(scheme_specific_part)
        if not is_valid_link(parsed):
            logging.debug(f"链接基本验证失败: {link_without_fragment[:50]}...")
            return None

        host = normalize_hostname(parsed.hostname.lower()) if parsed.hostname else ''
        port = parsed.port
        userinfo = parsed.username
        query_params = parse_qs(parsed.query)
        path = parsed.path.strip('/') or '_'
        sni = query_params.get('sni', ['_'])[0]
        service_name = query_params.get('serviceName', ['_'])[0] if scheme in ['vless', 'trojan'] else '_'

        if not scheme or not host or not port:
            logging.debug(f"链接缺少必需组件 (协议/主机/端口): {link_without_fragment[:50]}...")
            return None

        canonical_netloc = f"{host}:{port}"
        canonical_id = None

        if scheme == 'vmess':
            try:
                payload = json.loads(decoded_payload)
                vmess_id = payload.get('id')
                path = payload.get('path', '_')
                host = payload.get('host', '_')
                if vmess_id:
                    canonical_id = f"{scheme}://{vmess_id}@{canonical_netloc}?path={path}&host={host}"
                    logging.debug(f"VMess 规范化成功: {canonical_id}")
                else:
                    logging.debug(f"VMess JSON 缺少 'id' 字段: {decoded_payload}")
                    return None
            except json.JSONDecodeError:
                logging.debug(f"VMess 解码后内容不是有效的 JSON: {decoded_payload}")
                return None
            except Exception as e:
                logging.debug(f"解析 VMess JSON 错误: {e}")
                return None
        elif scheme == 'vless':
            canonical_id = f"{scheme}://{userinfo or '_'}@{canonical_netloc}?path={path}&sni={sni}&serviceName={service_name}"
            logging.debug(f"VLESS 规范化成功: {canonical_id}")
        elif scheme == 'trojan':
            canonical_id = f"{scheme}://{userinfo or '_'}@{canonical_netloc}?path={path}&sni={sni}&serviceName={service_name}"
            logging.debug(f"Trojan 规范化成功: {canonical_id}")
        elif scheme == 'ss':
            if userinfo:
                try:
                    userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8")
                    if ':' in userinfo_decoded:
                        method, password = userinfo_decoded.split(':', 1)
                        canonical_id = f"{scheme}://{method}:{password}@{canonical_netloc}?path={path}"
                        logging.debug(f"SS 规范化成功: {canonical_id}")
                    else:
                        logging.debug(f"SS userinfo 解码后不是 method:password 格式: {userinfo_decoded}")
                        return None
                except Exception as e:
                    logging.debug(f"SS userinfo Base64 解码失败: {userinfo[:50]}... Error: {e}")
                    return None
            else:
                logging.debug(f"SS 链接缺少用户信息: {link_without_fragment[:50]}...")
                return None
        else:
            canonical_id = f"{scheme}://{userinfo or '_'}@{canonical_netloc}?path={path}"
            logging.debug(f"{scheme.upper()} 规范化成功: {canonical_id}")

        if canonical_id:
            return (canonical_id.lower(), cleaned_decoded_link)
        else:
            logging.debug(f"未能为协议 {scheme} 生成规范化 ID: {link_without_fragment[:50]}...")
            return None

    except Exception as e:
        logging.debug(f"解析或规范化链接时发生未预料的错误 '{link_string[:50]}...': {e}")
        return None

def write_lines(lines, filename):
    """将去重后的配置写入文件"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            for line in lines:
                f.write(line + '\n')
        logging.info(f"成功写入 {len(lines)} 条配置到 {filename}")
    except Exception as e:
        logging.error(f"写入文件 {filename} 失败: {e}")

def deduplicate_configs(all_potential_links_data):
    """去重主函数"""
    unique_configs = {}
    channels_that_worked = set()
    invalid_links_count = 0

    def process_link(link_data):
        raw_link, channel_name = link_data
        if not is_config_valid(raw_link):
            return None, None, channel_name
        result = parse_and_canonicalize(raw_link)
        return result, raw_link, channel_name

    with ThreadPoolExecutor(max_workers=thrd_pars) as executor:
        results = list(executor.map(process_link, all_potential_links_data))

    for result, raw_link, channel_name in results:
        if result:
            canonical_id, cleaned_original_link = result
            if canonical_id not in unique_configs:
                unique_configs[canonical_id] = cleaned_original_link
                channels_that_worked.add(channel_name)
        else:
            invalid_links_count += 1

    logging.info(f"总链接数: {len(all_potential_links_data)}, 唯一配置数: {len(unique_configs)}, 无效链接数: {invalid_links_count}")
    logging.info(f"有效频道: {', '.join(sorted(channels_that_worked))}")
    write_lines(list(unique_configs.values()), CONFIG_TG_FILE)

    return unique_configs, channels_that_worked, invalid_links_count

def read_configtg_file(filename):
    """从 configtg.txt 读取配置数据"""
    configs = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    # 假设每行格式为 "链接 # 频道名" 或只有链接
                    if '#' in line:
                        link, channel = line.split('#', 1)
                        channel = channel.strip() or '@unknown'
                    else:
                        link, channel = line, '@unknown'
                    configs.append((link, channel))
        logging.info(f"从 {filename} 读取到 {len(configs)} 条配置")
        return configs
    except Exception as e:
        logging.error(f"读取文件 {filename} 失败: {e}")
        return []

if __name__ == "__main__":
    input_file = "configtg.txt"
    all_potential_links_data = read_configtg_file(input_file)
    if all_potential_links_data:
        deduplicate_configs(all_potential_links_data)
    else:
        logging.error("没有读取到有效的配置数据")
