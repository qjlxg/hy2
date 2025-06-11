import requests
import threading
import json
import os
import time
import random
import re
import base64
import yaml
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, quote
import logging
from concurrent.futures import ThreadPoolExecutor
import hashlib
import uuid

# 禁用不安全请求警告
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# 清空控制台
os.system('cls' if os.name == 'nt' else 'clear')

# --- 配置文件 ---
CONFIG_TG_TXT_FILE = 'configtg.txt'
CONFIG_TG_YAML_FILE = 'configtg.yaml'
TG_CHANNELS_FILE = 'telegramchannels.json'
INV_TG_CHANNELS_FILE = 'invalidtelegramchannels.json'

# --- 全局数据和锁 ---
all_potential_links_data = []
data_lock = threading.Lock()
sem_pars = None

# --- 用户代理列表 ---
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36',
]

# --- 非关键查询参数（用于去重） ---
# 增加了 'sni' 和 'host' (作为查询参数时)
NON_CRITICAL_QUERY_PARAMS = {'ed', 'fp', 'alpn', 'allowInsecure', 'obfsParam', 'protoparam', 'sni', 'host', 'ps'}

# --- 辅助函数 ---

def json_load(path):
    """加载 JSON 文件"""
    if not os.path.exists(path):
        logging.info(f"文件 {path} 不存在，返回空列表。")
        return []
    try:
        with open(path, 'r', encoding="utf-8") as file:
            content = file.read()
            if not content:
                logging.warning(f"文件 {path} 内容为空，返回空列表。")
                return []
            data = json.loads(content)
            logging.info(f"成功加载文件 {path}。")
            return data
    except json.JSONDecodeError:
        logging.warning(f"文件 {path} 内容无效 (JSON 格式错误)，返回空列表。")
        return []
    except Exception as e:
        logging.error(f"加载文件 {path} 时发生错误: {e}")
        return []

def json_dump(data, path):
    """保存 JSON 数据到文件"""
    try:
        with open(path, 'w', encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        logging.info(f"成功保存文件 {path}。")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def write_lines(data, path):
    """将字符串列表写入文件，每行一个"""
    try:
        with open(path, "w", encoding="utf-8") as file:
            for item in data:
                file.write(str(item) + "\n")
        logging.info(f"成功保存文件 {path}。")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def yaml_dump(data, path):
    """保存 YAML 数据到文件"""
    try:
        with open(path, 'w', encoding="utf-8") as file:
            yaml.dump(data, file, allow_unicode=True, sort_keys=False)
        logging.info(f"成功保存文件 {path}。")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def clean_and_urldecode(raw_string):
    """清理并解码 URL 字符串"""
    if not isinstance(raw_string, str):
        return None

    cleaned = raw_string.strip()
    cleaned = re.sub(r'amp;', '', cleaned)
    cleaned = re.sub(r'%0A|%250A|%0D|\\n', '', cleaned, flags=re.IGNORECASE)

    decoded = cleaned
    max_decode_attempts = 5
    for _ in range(max_decode_attempts):
        try:
            new_decoded = requests.utils.unquote(decoded)
            if new_decoded == decoded:
                break
            decoded = new_decoded
        except Exception as e:
            logging.debug(f"URL 解码失败: {decoded[:50]}... 错误: {e}")
            break

    return decoded

def is_valid_link(parsed_url):
    """验证解析后的 URL 是否有效"""
    valid_schemes = ['vmess', 'vless', 'ss', 'trojan', 'tuic', 'hysteria', 'hysteria2', 'hy2', 'juicity', 'nekoray', 'socks4', 'socks5', 'socks', 'naive+', 'ssr']
    if parsed_url.scheme not in valid_schemes:
        logging.debug(f"链接协议不受支持: {parsed_url.scheme}")
        return False

    if not parsed_url.hostname or '.' not in parsed_url.hostname:
        logging.debug(f"链接主机名无效: {parsed_url.hostname}")
        return False

    if parsed_url.port is None or not (1 <= parsed_url.port <= 65535):
        logging.debug(f"链接端口无效: {parsed_url.port}")
        return False

    return True

def is_uuid(s):
    """检查字符串是否为有效的 UUID"""
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False

def normalize_repeated_patterns(text):
    """
    规范化重复的模式，例如 'A-A-A' 变成 'A'，或 'Telegram:@NUFiLTER-Telegram:@NUFiLTER'
    """
    if not isinstance(text, str):
        return text
    
    # 移除 URL 编码的 @ 和 :
    text = re.sub(r'%40', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'%3A', ':', text, flags=re.IGNORECASE)

    # 针对 Telegram 频道名模式进行规范化
    # 例如: Telegram:@NUFiLTER-Telegram:@NUFiLTER-Telegram:@NUFiLTER -> Telegram:@NUFiLTER
    text = re.sub(r'(Telegram:@[a-zA-Z0-9_]+)(?:-\1)+', r'\1', text, flags=re.IGNORECASE)
    # 针对 ZEDMODEON 这样的模式进行规范化
    # 例如: ZEDMODEON-ZEDMODEON-ZEDMODEON -> ZEDMODEON
    text = re.sub(r'([a-zA-Z0-9_]+)(?:-\1)+', r'\1', text, flags=re.IGNORECASE)

    return text

def normalize_path(path):
    """规范化路径，移除重复的频道名称并清理斜杠"""
    if not path:
        return ''
    
    normalized_path = normalize_repeated_patterns(path)
    # 移除路径末尾的斜杠，除非是根路径
    return normalized_path.strip('/')

def generate_node_name(canonical_id, scheme, host, port):
    """生成标准化的节点名称，基于简化后的关键字段"""
    simplified_key = f"{scheme}://{host}:{port}"
    return hashlib.md5(simplified_key.encode('utf-8')).hexdigest()[:8]

def parse_and_canonicalize(link_string):
    """解析、清理、解码并规范化代理链接"""
    if not link_string or not isinstance(link_string, str):
        logging.debug("输入链接字符串为空或非字符串类型。")
        return None

    cleaned_decoded_link = clean_and_urldecode(link_string)
    if not cleaned_decoded_link:
        logging.debug(f"清洗或 URL 解码失败: {link_string[:50]}...")
        return None

    link_parts = cleaned_decoded_link.split('#', 1)
    link_without_fragment = link_parts[0]
    original_remark = link_parts[1] if len(link_parts) > 1 else ''
    scheme = ''
    parsed_payload_for_urlparse = link_without_fragment
    vmess_json_payload = None
    ssr_decoded_parts = None

    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload_str = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            vmess_json_payload = json.loads(decoded_payload_str)
            add = vmess_json_payload.get('add', '')
            port = vmess_json_payload.get('port', '')
            # 规范化 VMess host，移除可能的 @ 符号及后续内容
            if '@' in add and not is_uuid(add): # 只有当add不是UUID时才尝试移除@
                add = add.split('@')[-1] 
            if add and port:
                parsed_payload_for_urlparse = f"vmess://{add}:{port}"
            else:
                logging.debug(f"VMess JSON 缺少 'add' 或 'port' 字段: {decoded_payload_str[:50]}...")
                return None
        except Exception as e:
            logging.debug(f"VMess Base64 解码或 JSON 解析失败: {link_without_fragment[:50]}... 错误: {e}")
            return None

    elif link_without_fragment.startswith('ssr://'):
        scheme = 'ssr'
        try:
            b64_payload = link_without_fragment[6:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload_str = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            
            # SSR 格式：host:port:protocol:method:obfs:password_b64/?params
            if '/?' in decoded_payload_str:
                main_part, query_part = decoded_payload_str.split('/?', 1)
            else:
                main_part = decoded_payload_str
                query_part = ''
            
            ssr_decoded_parts = main_part.split(':')
            
            if len(ssr_decoded_parts) >= 6:
                ssr_host = ssr_decoded_parts[0]
                ssr_port = ssr_decoded_parts[1]
                
                # 重新构建用于 urlparse 的 SSR 链接，简化路径部分
                parsed_payload_for_urlparse = f"ssr://{ssr_host}:{ssr_port}"
                if query_part:
                    parsed_payload_for_urlparse += f"?{query_part}"
            else:
                logging.debug(f"SSR Base64 解码内容格式不符 (缺少必需部分): {decoded_payload_str[:50]}...")
                return None
        except Exception as e:
            logging.debug(f"SSR Base64 解码失败或解析错误: {link_without_fragment[:50]}... 错误: {e}")
            return None

    elif '://' in link_without_fragment:
        scheme = link_without_fragment.split('://')[0].lower()
    else:
        logging.debug(f"链接不包含协议: {link_without_fragment[:50]}...")
        return None

    try:
        parsed = urlparse(parsed_payload_for_urlparse)
        if not is_valid_link(parsed):
            logging.debug(f"链接基本验证失败: {link_without_fragment[:50]}...")
            return None

        host = parsed.hostname.lower()
        port = parsed.port
        userinfo = parsed.username

        if not scheme or not host or not port:
            logging.debug(f"链接缺少必需组件: {link_without_fragment}")
            return None

        canonical_id_components = [scheme]
        ignore_userinfo = os.getenv('IGNORE_USERINFO', 'false').lower() == 'true' and is_uuid(userinfo)
        if userinfo and not ignore_userinfo:
            if scheme == 'ss':
                try:
                    userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8", errors='replace')
                    if ':' in userinfo_decoded:
                        method, password = userinfo_decoded.split(':', 1)
                        canonical_id_components.append(f"{method}:{password}")
                    else:
                        logging.debug(f"SS userinfo 解码后格式错误: {userinfo_decoded}")
                        return None
                except Exception as e:
                    logging.debug(f"SS userinfo Base64 解码失败: {userinfo[:50]}... 错误: {e}")
                    return None
            else:
                canonical_id_components.append(userinfo)
        elif userinfo:
            logging.debug(f"忽略 userinfo 用于去重: {userinfo}")

        canonical_id_components.append(f"{host}:{port}")

        # 规范化 path
        canonical_path = normalize_path(parsed.path)
        if canonical_path:
            canonical_id_components.append(f"path={quote(canonical_path)}")

        query_params = parse_qs(parsed.query, keep_blank_values=True)
        canonical_query_list = []
        for key in sorted(query_params.keys()):
            key_lower = key.lower()
            if key_lower in NON_CRITICAL_QUERY_PARAMS: # 增加对 sni, host, ps 的忽略
                logging.debug(f"忽略非关键查询参数 '{key_lower}' 用于去重。")
                continue

            for value in sorted(query_params[key]):
                # 特殊处理 serviceName 参数
                if key_lower == 'servicename':
                    normalized_value = normalize_repeated_patterns(value)
                    canonical_query_list.append(f"{quote(key_lower)}={quote(normalized_value)}")
                # 特殊处理 alpn 参数，进行排序规范化
                elif key_lower == 'alpn':
                    sorted_alpn_values = sorted([s.strip() for s in value.split(',') if s.strip()])
                    normalized_value = ','.join(sorted_alpn_values)
                    canonical_query_list.append(f"{quote(key_lower)}={quote(normalized_value)}")
                else:
                    canonical_query_list.append(f"{quote(key_lower)}={quote(value)}")
        if canonical_query_list:
            canonical_id_components.append(f"query={';'.join(canonical_query_list)}")

        vmess_params = None
        if scheme == 'vmess' and vmess_json_payload:
            vmess_fields = ['id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'v', 'add', 'port', 'scy', 'fp', 'alpn', 'flow'] # 增加了 flow
            vmess_params = {}
            for field in vmess_fields:
                value = vmess_json_payload.get(field)
                if value is not None and value != '':
                    field_lower = field.lower()
                    if field_lower in NON_CRITICAL_QUERY_PARAMS: # 忽略 VMess 内部的非关键参数
                        logging.debug(f"忽略 VMess 内部非关键参数 '{field_lower}' 用于去重。")
                        continue

                    # 规范化 VMess host
                    if field_lower == 'host' and isinstance(value, str) and '@' in value and not is_uuid(value.split('@')[0]):
                         value = value.split('@')[-1]
                    # 规范化 serviceName 和 path
                    if field_lower in ['servicename', 'path'] and isinstance(value, str):
                        value = normalize_repeated_patterns(value)
                    # 规范化 alpn
                    if field_lower == 'alpn' and isinstance(value, str):
                        sorted_alpn_values = sorted([s.strip() for s in value.split(',') if s.strip()])
                        value = ','.join(sorted_alpn_values)

                    vmess_params[field] = str(value).lower()
            if vmess_params:
                vmess_canonical_parts = [f"{k}={quote(v)}" for k, v in sorted(vmess_params.items())]
                canonical_id_components.append(f"vmess_params={';'.join(vmess_canonical_parts)}")

        ssr_params = None
        if scheme == 'ssr' and ssr_decoded_parts:
            try:
                if len(ssr_decoded_parts) >= 6:
                    ssr_protocol = ssr_decoded_parts[2]
                    ssr_method = ssr_decoded_parts[3]
                    ssr_obfs = ssr_decoded_parts[4]
                    password_part_with_query = ssr_decoded_parts[5]
                    
                    actual_password_b64 = password_part_with_query
                    if '/?' in password_part_with_query:
                        actual_password_b64 = password_part_with_query.split('/?')[0]

                    password = base64.b64decode(actual_password_b64 + '=' * (-len(actual_password_b64) % 4)).decode("utf-8", errors='replace')
                    
                    ssr_params = {
                        'protocol': ssr_protocol.lower(),
                        'method': ssr_method.lower(),
                        'obfs': ssr_obfs.lower(),
                        'password': password.lower()
                    }

                    if '?' in link_without_fragment:
                        full_query_string = link_without_fragment.split('?', 1)[1]
                        ssr_custom_params = parse_qs(full_query_string, keep_blank_values=True)
                        for key in sorted(ssr_custom_params.keys()):
                            key_lower = key.lower()
                            if key_lower in NON_CRITICAL_QUERY_PARAMS: # 忽略 SSR 内部的非关键参数
                                logging.debug(f"忽略 SSR 内部非关键参数 '{key_lower}' 用于去重。")
                                continue

                            for value in sorted(ssr_custom_params[key]):
                                # 规范化 serviceName 或其它可能重复的参数
                                if key_lower == 'servicename':
                                    ssr_params[key_lower] = normalize_repeated_patterns(value)
                                # 规范化 alpn
                                elif key_lower == 'alpn':
                                    sorted_alpn_values = sorted([s.strip() for s in value.split(',') if s.strip()])
                                    ssr_params[key_lower] = ','.join(sorted_alpn_values)
                                else:
                                    ssr_params[key_lower] = value

                    ssr_canonical_parts = [f"{k}={quote(v)}" for k, v in sorted(ssr_params.items())]
                    canonical_id_components.append(f"ssr_params={';'.join(ssr_canonical_parts)}")
                else:
                    logging.debug(f"SSR 规范化失败: ssr_decoded_parts 长度不足 {len(ssr_decoded_parts)}")
                    return None
            except Exception as e:
                logging.debug(f"SSR 规范化失败: {e}")
                return None

        canonical_id = "###".join(canonical_id_components).lower()
        simplified_canonical_id = canonical_id
        if ignore_userinfo and userinfo:
            # 仅当 userinfo 是 UUID 且忽略 userinfo 选项开启时才进行替换
            simplified_canonical_id = canonical_id.replace(f"{userinfo}###", "") 
        
        if canonical_id:
            node_name = generate_node_name(simplified_canonical_id, scheme, host, port)
            return {
                'canonical_id': canonical_id,
                'simplified_canonical_id': simplified_canonical_id,
                'link': cleaned_decoded_link,
                'scheme': scheme,
                'host': host,
                'port': port,
                'userinfo': userinfo,
                'path': canonical_path,
                'query': query_params,
                'vmess_params': vmess_params if scheme == 'vmess' else None,
                'ssr_params': ssr_params if scheme == 'ssr' else None,
                'remark': original_remark,
                'node_name': node_name
            }
        else:
            logging.debug(f"未能生成规范化 ID: {link_without_fragment[:50]}...")
            return None

    except Exception as e:
        logging.error(f"解析或规范化链接错误: {link_string[:50]}... 错误: {e}")
        return None

def process_link(link_data):
    """处理单个链接并返回规范化结果"""
    raw_link, channel_name = link_data
    result = parse_and_canonicalize(raw_link)
    if result:
        return result, channel_name
    return None, channel_name

def process(i_url):
    """处理单个 Telegram 频道以提取代理链接"""
    sem_pars.acquire()
    logging.info(f"开始处理频道: {i_url}")
    html_pages = []
    cur_url = i_url
    found_links_in_channel = False
    selected_user_agent = random.choice(USER_AGENTS)
    headers = {'User-Agent': selected_user_agent}

    try:
        last_datbef = None
        for itter in range(1, pars_dp + 1):
            if itter > 1 and last_datbef is None:
                logging.debug("上一页未找到下一页数据点，停止分页。")
                break

            page_url = f'https://t.me/s/{cur_url}' if itter == 1 else f'https://t.me/s/{cur_url}?before={last_datbef[0]}'
            logging.debug(f"尝试获取页面: {page_url}")

            page_fetched = False
            for attempt in range(3):
                try:
                    response = requests.get(page_url, verify=False, timeout=15, headers=headers)
                    response.raise_for_status()
                    html_pages.append(response.text)
                    match = re.search(r'data-before="(\d+)"', response.text)
                    last_datbef = [match.group(1)] if match else None
                    page_fetched = True
                    logging.debug(f"成功获取页面: {page_url}")
                    break
                except requests.exceptions.RequestException as e:
                    logging.warning(f"获取 {page_url} 失败 (尝试 {attempt + 1}/3): {e}")
                    time.sleep(random.uniform(5, 15))

            if not page_fetched:
                logging.error(f"未能获取 {page_url}，跳过。")
                if itter == 1:
                    break

        if not html_pages:
            logging.warning(f"频道 {i_url} 未获取到任何页面内容。")
            return

        for page in html_pages:
            soup = BeautifulSoup(page, 'html.parser')
            code_tags = soup.find_all(class_=['tgme_widget_message_text', 'tgme_widget_message_service'])

            for code_tag in code_tags:
                potential_links = code_tag.get_text(separator='\n').split('\n')
                for raw_link in potential_links:
                    if re.search(r"(vmess|vless|ss|trojan|tuic|hysteria|hysteria2|hy2|juicity|nekoray|socks4|socks5|socks|naive\+|ssr):\/", raw_link, re.IGNORECASE):
                        with data_lock:
                            all_potential_links_data.append((raw_link, i_url))
                        found_links_in_channel = True
                        logging.debug(f"在频道 {i_url} 中找到潜在链接: {raw_link[:100]}...")

        if found_links_in_channel:
            logging.info(f"在频道 {i_url} 中找到潜在链接。")
        else:
            logging.info(f"在频道 {i_url} 中未找到潜在链接。")

    except Exception as e:
        logging.error(f"处理频道 {i_url} 时发生错误: {e}")
    finally:
        sem_pars.release()
        logging.info(f"完成处理频道: {i_url}")

if __name__ == "__main__":
    # 配置日志
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("脚本开始运行。")

    tg_name_json = json_load(TG_CHANNELS_FILE)
    inv_tg_name_json = json_load(INV_TG_CHANNELS_FILE)

    inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]
    tg_name_json = [x for x in tg_name_json if isinstance(x, str) and len(x) >= 5]
    inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))

    thrd_pars = int(os.getenv('THRD_PARS', '128'))
    pars_dp = int(os.getenv('PARS_DP', '1'))
    use_inv_tc = os.getenv('USE_INV_TC', 'n').lower() == 'y'

    sem_pars = threading.Semaphore(thrd_pars)

    logging.info(f'\n当前配置:')
    logging.info(f'  并发抓取线程数 (THRD_PARS) = {thrd_pars}')
    logging.info(f'  每个频道抓取页面深度 (PARS_DP) = {pars_dp}')
    logging.info(f'  使用无效频道列表 (USE_INV_TC) = {use_inv_tc}')
    logging.info(f'  日志级别 (LOG_LEVEL) = {logging.getLevelName(log_level)}')
    logging.info(f'  忽略 userinfo 去重 (IGNORE_USERINFO) = {os.getenv("IGNORE_USERINFO", "false")}')

    logging.info(f'\n现有频道统计:')
    logging.info(f'  {TG_CHANNELS_FILE} 中的频道总数 - {len(tg_name_json)}')
    logging.info(f'  {INV_TG_CHANNELS_FILE} 中的频道总数 - {len(inv_tg_name_json)}')

    logging.info(f'\n从 {CONFIG_TG_TXT_FILE} 中提取新的 TG 频道名...')
    config_all = []
    if os.path.exists(CONFIG_TG_TXT_FILE):
        try:
            with open(CONFIG_TG_TXT_FILE, "r", encoding="utf-8") as config_all_file:
                config_all = config_all_file.readlines()
            logging.info(f"成功读取 {CONFIG_TG_TXT_FILE}。")
        except Exception as e:
            logging.error(f"读取 {CONFIG_TG_TXT_FILE} 失败: {e}")

    pattern_telegram_user = re.compile(r'(?:https?:\/\/t\.me\/|@|%40|\bt\.me\/)([a-zA-Z0-9_]{5,})', re.IGNORECASE)
    extracted_tg_names = set()

    for config in config_all:
        cleaned_config = clean_and_urldecode(config)
        if not cleaned_config:
            continue

        if cleaned_config.startswith(('vmess://', 'ssr://', 'ss://')):
            try:
                b64_part = ''
                if cleaned_config.startswith('vmess://'):
                    b64_part = cleaned_config[8:]
                elif cleaned_config.startswith('ssr://'):
                    b64_part = cleaned_config[6:]
                elif cleaned_config.startswith('ss://'):
                    parsed_ss = urlparse(cleaned_config)
                    b64_part = parsed_ss.username if parsed_ss.username else ''

                if b64_part:
                    b64_part += '=' * (-len(b64_part) % 4)
                    decoded_payload = base64.b64decode(b64_part).decode("utf-8", errors='replace')

                    if cleaned_config.startswith('vmess://') and decoded_payload:
                        try:
                            vmess_data = json.loads(decoded_payload)
                            if 'ps' in vmess_data:
                                matches = pattern_telegram_user.findall(vmess_data['ps'])
                                for match in matches:
                                    cleaned_name = match.lower().strip('_')
                                    if len(cleaned_name) >= 5:
                                        extracted_tg_names.add(cleaned_name)
                                        logging.debug(f"从 VMess 'ps' 提取频道名: {cleaned_name}")
                            if 'add' in vmess_data:
                                matches = pattern_telegram_user.findall(vmess_data['add'])
                                for match in matches:
                                    cleaned_name = match.lower().strip('_')
                                    if len(cleaned_name) >= 5:
                                        extracted_tg_names.add(cleaned_name)
                                        logging.debug(f"从 VMess 'add' 提取频道名: {cleaned_name}")
                        except Exception as ex:
                            logging.debug(f"处理 VMess 解码内容错误: {ex}")

                    matches = pattern_telegram_user.findall(decoded_payload)
                    for match in matches:
                        cleaned_name = match.lower().strip('_')
                        if len(cleaned_name) >= 5:
                            extracted_tg_names.add(cleaned_name)
                            logging.debug(f"从 Base64 解码内容提取频道名: {cleaned_name}")
            except Exception as e:
                logging.debug(f"从 Base64 提取频道名失败: {e}")

        matches = pattern_telegram_user.findall(cleaned_config)
        for match in matches:
            cleaned_name = match.lower().strip('_')
            if len(cleaned_name) >= 5:
                extracted_tg_names.add(cleaned_name)
                logging.debug(f"从配置提取频道名: {cleaned_name}")

    initial_tg_count = len(tg_name_json)
    tg_name_json = sorted(list(set(tg_name_json).union(extracted_tg_names)))

    logging.info(f'  更新后 {TG_CHANNELS_FILE} 频道总数: {len(tg_name_json)} (新增 {len(tg_name_json) - initial_tg_count})')

    json_dump(tg_name_json, TG_CHANNELS_FILE)

    start_time = datetime.now()
    logging.info(f'\n开始爬取 TG 频道并解析配置...')

    channels_to_process = tg_name_json
    if use_inv_tc:
        channels_to_process = sorted(list(set(tg_name_json).union(inv_tg_name_json)))
        logging.info(f'  处理 {len(channels_to_process)} 个频道（包含无效频道）。')
    else:
        channels_to_process = sorted(list(set(tg_name_json) - set(inv_tg_name_json))) # 仅处理有效频道
        logging.info(f'  处理 {len(channels_to_process)} 个有效频道。')

    threads = []
    for url in channels_to_process:
        thread = threading.Thread(target=process, args=(url,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    end_time_parsing = datetime.now()
    logging.info(f'\n爬取完成 - 耗时 {str(end_time_parsing - start_time).split('.')[0]}')
    logging.info(f'共提取到 {len(all_potential_links_data)} 条潜在链接。')

    logging.info(f'\n开始去重和规范化链接...')
    unique_configs = {}
    channels_that_worked = set()
    invalid_links_count = 0

    with ThreadPoolExecutor(max_workers=thrd_pars) as executor:
        results = list(executor.map(process_link, all_potential_links_data))

    for i, (result, channel_name) in enumerate(results):
        if result:
            canonical_id_for_dedup = result['simplified_canonical_id'] if os.getenv('IGNORE_USERINFO', 'false').lower() == 'true' else result['canonical_id']
            if canonical_id_for_dedup not in unique_configs:
                unique_configs[canonical_id_for_dedup] = result
                channels_that_worked.add(channel_name)
                logging.debug(f"添加唯一配置 (Key: {canonical_id_for_dedup}): {result['link'][:100]}...")
            else:
                logging.debug(f"跳过重复配置 (Key: {canonical_id_for_dedup}): {result['link'][:100]}...")
        else:
            invalid_links_count += 1
            # 原始链接可能很长，只记录部分
            original_link_snippet = all_potential_links_data[i][0][:100] + "..."
            logging.debug(f"跳过无效链接 (来自频道: {channel_name}): {original_link_snippet}")


    logging.info(f'去重完成 - 耗时 {str(datetime.now() - end_time_parsing).split('.')[0]}')
    logging.info(f'最终得到 {len(unique_configs)} 条有效配置，跳过 {invalid_links_count} 条无效链接。')

    logging.info(f'\n更新频道列表...')
    new_tg_name_json = sorted(list(channels_that_worked))
    inv_tg_name_json = sorted(list((set(tg_name_json) - channels_that_worked).union(set(inv_tg_name_json))))
    inv_tg_names = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]

    json_dump(new_tg_name_json, TG_CHANNELS_FILE)
    json_dump(inv_tg_names, INV_TG_CHANNELS_FILE)

    logging.info(f'  更新后 {TG_CHANNELS_FILE} 频道数: {len(new_tg_name_json)}')
    logging.info(f'  更新后 {INV_TG_CHANNELS_FILE} 频道数: {len(inv_tg_names)}')

    logging.info(f'\n保存有效配置到 {CONFIG_TG_TXT_FILE} 和 {CONFIG_TG_YAML_FILE}...')
    processed_codes_list = [config['link'] for config in unique_configs.values()]
    write_lines(processed_codes_list, CONFIG_TG_TXT_FILE)

    yaml_proxies = []
    for config in unique_configs.values():
        proxy = {
            'name': config['node_name'],
            'scheme': config['scheme'],
            'host': config['host'],
            'port': config['port'],
            'userinfo': config['userinfo'] if config['userinfo'] else None,
            'path': config['path'] or None,
            'query': {k: v[0] if len(v) == 1 else v for k, v in sorted(config['query'].items())} if config['query'] else None,
            'original_link': config['link'],
            'remark': config['remark'] or None,
            'dedup_key': config['simplified_canonical_id']
        }
        if config['vmess_params']:
            proxy['vmess_params'] = config['vmess_params']
        if config['ssr_params']:
            proxy['ssr_params'] = config['ssr_params']
        yaml_proxies.append(proxy)

    yaml_data = {'proxies': yaml_proxies}
    yaml_dump(yaml_data, CONFIG_TG_YAML_FILE)

    end_time_total = datetime.now()
    logging.info(f'\n脚本运行完毕！总耗时 - {str(end_time_total - start_time).split('.')[0]}')
