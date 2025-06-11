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
# 这些参数的变动通常不影响节点功能，因此在去重时可以忽略
NON_CRITICAL_QUERY_PARAMS = {'ed', 'fp', 'allowInsecure', 'obfsParam', 'protoparam', 'ps', 'sid'}

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
    # 移除 URL 编码的换行符和空字节
    cleaned = re.sub(r'%0A|%250A|%0D|\\n|%00', '', cleaned, flags=re.IGNORECASE)

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
    也会尝试去除常见的广告词或多余的短语，并确保长度不会过长
    """
    if not isinstance(text, str):
        return text
    
    # 移除 URL 编码的 @ 和 :
    text = re.sub(r'%40', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'%3A', ':', text, flags=re.IGNORECASE)

    # 针对 Telegram 频道名模式进行规范化
    # 例如: Telegram:@NUFiLTER-Telegram:@NUFiLTER-Telegram:@NUFiLTER -> Telegram:@NUFiLTER
    # 使用非贪婪匹配和重复组来处理多重重复
    text = re.sub(r'((?:Telegram:)?@[a-zA-Z0-9_]+)(?:-\1)+', r'\1', text, flags=re.IGNORECASE)
    
    # 针对 ZEDMODEON 这样的模式进行规范化
    # 例如: ZEDMODEON-ZEDMODEON-ZEDMODEON -> ZEDMODEON
    # 增加单词边界，避免误伤
    text = re.sub(r'([a-zA-Z0-9_]+)(?:-\1)+', r'\1', text, flags=re.IGNORECASE)

    # 移除多余的连字符（如果规范化后出现 A--B 这样的情况）
    text = re.sub(r'-+', '-', text)
    # 移除开头和结尾的连字符
    text = text.strip('-')

    # 移除常见的广告或不相关短语
    text = re.sub(r'(?:Join--VPNCUSTOMIZE\.V2ray\.re)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:telegram:)?@?[a-zA-Z0-9_]+(?:-|$)','',text,flags=re.IGNORECASE) # 移除独立的频道名，如果它们只是噪音

    # 再次清理多余连字符和斜杠
    text = re.sub(r'-+', '-', text).strip('-')
    text = re.sub(r'/+', '/', text).strip('/')

    # 如果处理后仍然非常长，可以考虑截断或哈希，但需谨慎
    # 目前不强制截断，因为可能丢失信息
    return text

def normalize_domain(domain):
    """
    规范化域名，统一小写，移除 www. 前缀，并尝试处理 vXX. 模式
    例如：v16.vxlimir.com -> vxlimir.com
    """
    if not isinstance(domain, str):
        return domain
    normalized = domain.lower()
    if normalized.startswith('www.'):
        normalized = normalized[4:]
    
    # 尝试移除 vXX. 模式 (例如 v16.example.com -> example.com)
    # 避免误伤合法子域名，只针对 v+数字.
    # 也会尝试处理类似 "v2ray-fark2.ddns.net" -> "v2ray-fark.ddns.net" 这种可能
    normalized = re.sub(r'^v\d+\.', '', normalized)
    normalized = re.sub(r'-fark\d+\.', '-fark.', normalized) # 针对 v2ray-farkN.ddns.net

    # 移除末尾的 . （如果存在）
    normalized = normalized.strip('.')

    return normalized

def normalize_path(path):
    """规范化路径，移除重复的频道名称，清理斜杠，并去除路径中的查询参数"""
    if not path:
        return ''
    
    # 分离路径和可能的查询参数
    path_without_query = path.split('?', 1)[0].split('#', 1)[0]
    
    normalized_path = normalize_repeated_patterns(path_without_query)
    # 移除路径末尾的斜杠，除非是根路径
    return normalized_path.strip('/')

def normalize_remark(remark_text):
    """
    规范化节点备注，去除常见噪音、广告词、序号、时间戳、国旗、随机字符、传输协议等，
    以提高去重准确性。
    """
    if not isinstance(remark_text, str):
        return ''
    
    normalized = remark_text.lower()
    
    # 移除常见的频道名和广告词
    normalized = re.sub(r'(@[a-zA-Z0-9_]+)', '', normalized) # 移除 @开头的频道名
    normalized = re.sub(r'(telegram|channel|proxy|free|v2ray|vpn|config|official|server|test|speed|modeon|nufilter|zedmodeon|rkvps|limproxy|vpnlime|rayx|foxnt|bede|vps)', '', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'(?:[🇦🇧🇨🇩🇪🇫🇬🇭🇮🇯🇰🇱🇲🇳🇴🇵🇶🇷🇸🇹🇺🇻🇼🇽🇾🇿\U0001F1E6-\U0001F1FF]+)', '', normalized) # 移除国旗 emoji

    # 移除数字和可能的序号 (例如 1, 01, #1, -1)
    normalized = re.sub(r'(?<![a-zA-Z])\b\d{1,4}\b(?![a-zA-Z])', '', normalized) # 移除独立数字
    normalized = re.sub(r'#\d+', '', normalized)
    
    # 移除时间戳、日期格式
    normalized = re.sub(r'\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}', '', normalized) # MM-DD-YYYY, DD.MM.YY etc.
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '', normalized) # YYYY-MM-DD
    
    # 移除常见的传输协议和安全特性
    normalized = re.sub(r'(tls|ssl|tcp|ws|grpc|http|h2|h1\.1|none|reality|xtls|vless|vmess|trojan|ss|ssr|hysteria|hysteria2|hy2|tuic|juicity|socks|naive\+)', '', normalized)
    
    # 移除随机字符串或哈希值（通常是8-32位字母数字混合）
    normalized = re.sub(r'\b[a-f0-9]{8,32}\b', '', normalized) # 移除看起来像hash的字符串
    
    # 移除特殊字符和多余的空格/连字符/下划线
    normalized = re.sub(r'[^\w\s-]', '', normalized) # 只保留字母数字，空格和连字符
    normalized = re.sub(r'[\s_-]+', ' ', normalized).strip() # 将多个空白、连字符、下划线替换为一个空格，并去除首尾空格

    # 移除开头和结尾的特殊标记
    normalized = normalized.strip('+-*/#_')

    # 如果清理后字符串非常短，可能失去意义，可以考虑直接返回空或特定标记
    if len(normalized) < 3: # 避免空字符串或者只有一两个字符的备注
        return ''

    return normalized

def generate_node_name(canonical_id_hash):
    """根据规范化 ID 的哈希值生成一个短节点名称"""
    return hashlib.md5(canonical_id_hash.encode('utf-8')).hexdigest()[:8]

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
            
            # 使用 VMess 内部的 add 和 port 来构建一个临时的 URL 用于 urlparse
            add = vmess_json_payload.get('add', '')
            port = vmess_json_payload.get('port', '')
            
            # 规范化 VMess host for temporary URL
            if '@' in add and not is_uuid(add):
                add = add.split('@')[-1]
            add = normalize_domain(add) # 统一 host 格式
            
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
                ssr_host = normalize_domain(ssr_decoded_parts[0]) # 规范化 SSR host
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
        # 对 URL 进行初步解析
        parsed = urlparse(parsed_payload_for_urlparse)
        if not is_valid_link(parsed):
            logging.debug(f"链接基本验证失败: {link_without_fragment[:50]}...")
            return None

        # 规范化 host 和 port
        host = normalize_domain(parsed.hostname) # 使用增强的 normalize_domain
        port = parsed.port
        userinfo = parsed.username

        if not scheme or not host or not port:
            logging.debug(f"链接缺少必需组件: {link_without_fragment}")
            return None

        canonical_id_components = [scheme]
        ignore_userinfo = os.getenv('IGNORE_USERINFO', 'false').lower() == 'true'
        
        # 针对 userinfo 的更严格规范化
        if userinfo:
            if ignore_userinfo and is_uuid(userinfo):
                logging.debug(f"忽略 UUID userinfo 用于去重: {userinfo}")
            elif ignore_userinfo and not is_uuid(userinfo):
                # 如果不是 UUID 且配置为忽略 userinfo，则对 userinfo 进行规范化处理
                # 这会处理如 TELEGRAM_BYA_Rk_Vps_Rk_Vps 这样的 userinfo
                normalized_userinfo = normalize_repeated_patterns(userinfo)
                if normalized_userinfo:
                    canonical_id_components.append(normalized_userinfo)
                logging.debug(f"规范化非 UUID userinfo 用于去重: '{userinfo}' -> '{normalized_userinfo}'")
            elif not ignore_userinfo: # 如果不忽略 userinfo
                if scheme == 'ss':
                    try:
                        # SS userinfo 解码后是 method:password
                        userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8", errors='replace')
                        if ':' in userinfo_decoded:
                            method, password = userinfo_decoded.split(':', 1)
                            canonical_id_components.append(f"{method.lower()}:{password.lower()}") # SS method和password小写参与去重
                        else:
                            logging.debug(f"SS userinfo 解码后格式错误: {userinfo_decoded}")
                            return None
                    except Exception as e:
                        logging.debug(f"SS userinfo Base64 解码失败: {userinfo[:50]}... 错误: {e}")
                        return None
                else:
                    canonical_id_components.append(userinfo)

        canonical_id_components.append(f"{host}:{port}")

        # 规范化 path
        canonical_path = normalize_path(parsed.path) # 使用增强的 normalize_path
        if canonical_path:
            canonical_id_components.append(f"path={quote(canonical_path)}")

        query_params = parse_qs(parsed.query, keep_blank_values=True)
        canonical_query_list = []
        for key in sorted(query_params.keys()):
            key_lower = key.lower()
            
            # 特殊处理 host 参数（如果存在于 query 中）
            if key_lower == 'host':
                for value in sorted(query_params[key]):
                    # 规范化 host 值，移除 www. 并转小写
                    normalized_value = normalize_domain(value) # 使用增强的 normalize_domain
                    if normalized_value: # 只有非空才加入
                        canonical_query_list.append(f"{quote(key_lower)}={quote(normalized_value)}")
                continue # 已处理，跳过后续通用逻辑

            # 特殊处理 sni 参数
            if key_lower == 'sni':
                for value in sorted(query_params[key]):
                    normalized_value = normalize_domain(value) # 使用增强的 normalize_domain
                    if normalized_value: # 只有非空才加入
                        canonical_query_list.append(f"{quote(key_lower)}={quote(normalized_value)}")
                continue # 已处理，跳过后续通用逻辑

            if key_lower in NON_CRITICAL_QUERY_PARAMS:
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
                    if normalized_value: # 只有非空才加入
                        canonical_query_list.append(f"{quote(key_lower)}={quote(normalized_value)}")
                else:
                    canonical_query_list.append(f"{quote(key_lower)}={quote(value)}")
        if canonical_query_list:
            canonical_id_components.append(f"query={';'.join(canonical_query_list)}")

        vmess_params = None
        if scheme == 'vmess' and vmess_json_payload:
            # 增加了 'flow' 参数，这在 VMess Reality 中很重要
            vmess_fields = ['id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'v', 'add', 'port', 'scy', 'fp', 'alpn', 'flow'] 
            vmess_params = {}
            for field in vmess_fields:
                value = vmess_json_payload.get(field)
                if value is not None and value != '':
                    field_lower = field.lower()
                    if field_lower in NON_CRITICAL_QUERY_PARAMS: # 忽略 VMess 内部的非关键参数
                        logging.debug(f"忽略 VMess 内部非关键参数 '{field_lower}' 用于去重。")
                        continue

                    # 规范化 VMess host (add) 和 sni
                    if field_lower in ['add', 'host', 'sni'] and isinstance(value, str):
                        # 如果 add 包含 @ 并且不是 UUID，则只取 @ 后面的部分
                        if field_lower == 'add' and '@' in value and not is_uuid(value.split('@')[0]):
                             value = value.split('@')[-1]
                        value = normalize_domain(value) # 统一 host/sni 格式，使用增强的 normalize_domain
                    
                    # 规范化 serviceName 和 path
                    if field_lower in ['servicename', 'path'] and isinstance(value, str):
                        value = normalize_repeated_patterns(value) # 使用增强的 normalize_repeated_patterns
                    
                    # 规范化 alpn
                    if field_lower == 'alpn' and isinstance(value, str):
                        sorted_alpn_values = sorted([s.strip() for s in value.split(',') if s.strip()])
                        value = ','.join(sorted_alpn_values)
                        if not value: # 如果规范化后为空，则跳过
                            continue
                    
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
                                    ssr_params[key_lower] = normalize_repeated_patterns(value) # 使用增强的 normalize_repeated_patterns
                                # 规范化 alpn
                                elif key_lower == 'alpn':
                                    sorted_alpn_values = sorted([s.strip() for s in value.split(',') if s.strip()])
                                    normalized_value = ','.join(sorted_alpn_values)
                                    if normalized_value:
                                        ssr_params[key_lower] = normalized_value
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
        
        # 规范化备注并添加到去重键中
        normalized_remark = normalize_remark(original_remark)
        # 可以选择是否将规范化后的备注加入去重键
        # 默认加入，如果希望不加入，可以将环境变量 INCLUDE_REMARK_IN_DEDUP_KEY 设置为 false
        include_remark_in_dedup_key = os.getenv('INCLUDE_REMARK_IN_DEDUP_KEY', 'true').lower() == 'true'
        if include_remark_in_dedup_key and normalized_remark:
            # 使用备注的哈希值，避免过长的备注导致去重键过长
            remark_hash = hashlib.md5(normalized_remark.encode('utf-8')).hexdigest()[:8]
            canonical_id_components.append(f"remark_hash={remark_hash}")
            logging.debug(f"包含规范化备注哈希 '{remark_hash}' ({normalized_remark}) 到去重键。")
        elif include_remark_in_dedup_key and not normalized_remark:
            # 如果备注为空，也记录一下，避免为空的备注被忽略
            canonical_id_components.append("remark_hash=none")
            logging.debug("备注规范化后为空，记录 'remark_hash=none' 到去重键。")
        else:
            logging.debug("配置为不包含备注到去重键。")


        canonical_id = "###".join(canonical_id_components).lower()
        simplified_canonical_id = canonical_id
        
        if ignore_userinfo and userinfo and is_uuid(userinfo):
            # 仅当 userinfo 是 UUID 且忽略 userinfo 选项开启时才进行替换
            # 找到并替换 userinfo 部分
            simplified_canonical_id = simplified_canonical_id.replace(f"{userinfo.lower()}###", "")
            logging.debug(f"去重时忽略 UUID userinfo，简化后的 ID: {simplified_canonical_id}")
        
        if canonical_id:
            node_name = generate_node_name(simplified_canonical_id) # 根据简化后的 ID 生成名称
            return {
                'canonical_id': canonical_id,
                'simplified_canonical_id': simplified_canonical_id,
                'link': cleaned_decoded_link,
                'scheme': scheme,
                'host': host, # 返回规范化后的 host
                'port': port,
                'userinfo': userinfo, # 原始 userinfo
                'path': canonical_path,
                'query': query_params, # 原始 query_params，用于保存
                'vmess_params': vmess_params if scheme == 'vmess' else None,
                'ssr_params': ssr_params if scheme == 'ssr' else None,
                'remark': original_remark, # 原始备注
                'normalized_remark': normalized_remark, # 规范化后的备注
                'node_name': node_name # 新生成的节点名称
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
    ignore_userinfo = os.getenv('IGNORE_USERINFO', 'false').lower() == 'true' # 获取 IGNORE_USERINFO
    include_remark_in_dedup_key = os.getenv('INCLUDE_REMARK_IN_DEDUP_KEY', 'true').lower() == 'true' # 获取 INCLUDE_REMARK_IN_DEDUP_KEY

    sem_pars = threading.Semaphore(thrd_pars)

    logging.info(f'\n当前配置:')
    logging.info(f'  并发抓取线程数 (THRD_PARS) = {thrd_pars}')
    logging.info(f'  每个频道抓取页面深度 (PARS_DP) = {pars_dp}')
    logging.info(f'  使用无效频道列表 (USE_INV_TC) = {use_inv_tc}')
    logging.info(f'  日志级别 (LOG_LEVEL) = {logging.getLevelName(log_level)}')
    logging.info(f'  忽略 UUID userinfo 去重 (IGNORE_USERINFO) = {ignore_userinfo}')
    logging.info(f'  规范化备注并包含到去重键 (INCLUDE_REMARK_IN_DEDUP_KEY) = {include_remark_in_dedup_key}')


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

        # 尝试从 Base64 编码的链接中提取频道名 (vmess, ssr, ss)
        if cleaned_config.startswith(('vmess://', 'ssr://', 'ss://')):
            try:
                b64_part = ''
                if cleaned_config.startswith('vmess://'):
                    b64_part = cleaned_config[8:]
                elif cleaned_config.startswith('ssr://'):
                    b64_part = cleaned_config[6:]
                elif cleaned_config.startswith('ss://'):
                    parsed_ss = urlparse(cleaned_config)
                    # SS 链接的 username 部分是 base64 编码的 method:password，可能包含频道名
                    b64_part = parsed_ss.username if parsed_ss.username else ''

                if b64_part:
                    # 确保 Base64 字符串长度是 4 的倍数
                    b64_part += '=' * (-len(b64_part) % 4)
                    decoded_payload = base64.b64decode(b64_part).decode("utf-8", errors='replace')

                    # 尝试从 VMess 'ps' 和 'add' 字段中提取频道名
                    if cleaned_config.startswith('vmess://') and decoded_payload:
                        try:
                            vmess_data = json.loads(decoded_payload)
                            for field in ['ps', 'add']: # 检查 'ps' 和 'add'
                                if field in vmess_data and isinstance(vmess_data[field], str):
                                    matches = pattern_telegram_user.findall(vmess_data[field])
                                    for match in matches:
                                        cleaned_name = match.lower().strip('_')
                                        if len(cleaned_name) >= 5:
                                            extracted_tg_names.add(cleaned_name)
                                            logging.debug(f"从 VMess '{field}' 提取频道名: {cleaned_name}")
                        except json.JSONDecodeError:
                            logging.debug(f"VMess Base64 解码内容不是有效 JSON: {decoded_payload[:50]}...")
                        except Exception as ex:
                            logging.debug(f"处理 VMess 解码内容错误: {ex}")

                    # 尝试从所有 Base64 解码内容中提取频道名
                    matches = pattern_telegram_user.findall(decoded_payload)
                    for match in matches:
                        cleaned_name = match.lower().strip('_')
                        if len(cleaned_name) >= 5:
                            extracted_tg_names.add(cleaned_name)
                            logging.debug(f"从 Base64 解码内容提取频道名: {cleaned_name}")
            except Exception as e:
                logging.debug(f"从 Base64 提取频道名失败: {e}")

        # 尝试从原始链接字符串中提取频道名
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
            # 根据 IGNORE_USERINFO 环境变量和 userinfo 类型决定使用哪个 key 进行去重
            # 这里的简化逻辑已经移动到 parse_and_canonicalize 内部，所以直接使用 simplified_canonical_id
            canonical_id_for_dedup = result['simplified_canonical_id']
            
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
            'name': config['node_name'], # 使用新生成的短名称
            'scheme': config['scheme'],
            'host': config['host'], # 这里是规范化后的 host
            'port': config['port'],
            'userinfo': config['userinfo'] if config['userinfo'] else None,
            'path': config['path'] or None,
            # 将 query 字典转换为更友好的格式，跳过空值
            'query': {k: v[0] if len(v) == 1 else v for k, v in sorted(config['query'].items()) if v} if config['query'] else None,
            'original_link': config['link'],
            'remark': config['remark'] or None, # 原始备注
            'normalized_remark': config['normalized_remark'] or None, # 规范化后的备注
            'dedup_key': config['simplified_canonical_id']
        }
        if config['vmess_params']:
            # 同样，vmess_params 应该只包含非空值
            proxy['vmess_params'] = {k: v for k, v in config['vmess_params'].items() if v}
        if config['ssr_params']:
            # 同样，ssr_params 应该只包含非空值
            proxy['ssr_params'] = {k: v for k, v in config['ssr_params'].items() if v}
        yaml_proxies.append(proxy)

    yaml_data = {'proxies': yaml_proxies}
    yaml_dump(yaml_data, CONFIG_TG_YAML_FILE)

    end_time_total = datetime.now()
    logging.info(f'\n脚本运行完毕！总耗时 - {str(end_time_total - start_time).split('.')[0]}')
