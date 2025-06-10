import requests
import threading
import json
import os
import time
import random
import re
import base64
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, quote
import logging

# Disable insecure request warnings
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# Clear console (kept for context, but not part of the core logic to be optimized)
os.system('cls' if os.name == 'nt' else 'clear')

# --- Configuration Files (kept for context) ---
CONFIG_TG_FILE = 'configtg.txt'
TG_CHANNELS_FILE = 'telegramchannels.json'
INV_TG_CHANNELS_FILE = 'invalidtelegramchannels.json'

# --- Global Data and Locks (kept for context) ---
all_potential_links_data = []
data_lock = threading.Lock()
sem_pars = None # Semaphore will be initialized later based on THRD_PARS

# --- User Agent List for Rotation (kept for context) ---
USER_AGENTS = [
    # Desktop Browsers
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', # Chrome on Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0', # Firefox on Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15', # Safari on macOS
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', # Chrome on macOS
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0', # Firefox on Ubuntu
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36', # Chrome on Linux
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59 Safari/537.36', # Edge on Windows

    # Mobile Browsers (Android)
    'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36', # Chrome on Android (Galaxy S10)
    'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36', # Chrome on Android (Pixel 5)
    'Mozilla/5.0 (Android 10; Mobile; rv:89.0) Gecko/89.0 Firefox/89.0', # Firefox on Android
    'Mozilla/5.0 (Linux; Android 10; SM-A205U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36', # Chrome on Android (Galaxy A20)

    # Mobile Browsers (iOS)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1', # Safari on iOS (iPhone)
    'Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1', # Safari on iOS (iPad)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/91.0.4472.80 Mobile/15E148 Safari/604.1', # Chrome on iOS

    # Mobile Browsers (HarmonyOS - Common patterns, may vary)
    'Mozilla/5.0 (Linux; Android 10; HMA-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36', # Example resembling Android on Huawei
    'Mozilla/5.0 (Linux; HarmonyOS 2.0; SEA-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Mobile Safari/537.36', # Example with HarmonyOS identifier

    # Other potential User Agents (less common but can be included)
]


# --- Helper Functions (kept existing and added necessary imports for urlencode, quote) ---

def json_load(path):
    """Loads JSON data from a file."""
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
    """Saves JSON data to a file."""
    try:
        with open(path, 'w', encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        logging.info(f"成功保存文件 {path}。")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def write_lines(data, path):
    """Writes a list of strings to a file, each on a new line."""
    try:
        with open(path, "w", encoding="utf-8") as file:
            for item in data:
                file.write(str(item) + "\n")
        logging.info(f"成功保存文件 {path}。")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def clean_and_urldecode(raw_string):
    """Cleans and URL-decodes a string."""
    if not isinstance(raw_string, str):
        return None

    cleaned = raw_string.strip()
    cleaned = re.sub(r'amp;', '', cleaned)
    cleaned = re.sub(r'', '', cleaned) # This line still seems redundant/typo, but kept as per original.
    cleaned = re.sub(r'%0A', '', cleaned)
    cleaned = re.sub(r'%250A', '', cleaned)
    cleaned = re.sub(r'%0D', '', cleaned)
    cleaned = re.sub(r'\\n', '', cleaned)

    decoded = cleaned
    while True:
        try:
            new_decoded = requests.utils.unquote(decoded)
            if new_decoded == decoded:
                break
            decoded = new_decoded
        except:
            # Handle potential decoding errors that unquote might raise on malformed strings
            logging.debug(f"URL 解码失败: {decoded[:50]}...")
            break

    return decoded

def is_valid_link(parsed_url):
    """Performs basic validation on a parsed URL."""
    # Check for valid scheme (already handled in parse_and_canonicalize, but good to double check)
    if parsed_url.scheme not in ['vmess', 'vless', 'ss', 'trojan', 'tuic', 'hysteria', 'hysteria2', 'hy2', 'juicity', 'nekoray', 'socks4', 'socks5', 'socks', 'naive+']:
        logging.debug(f"链接协议不受支持或无效: {parsed_url.scheme}")
        return False

    # Check for valid host
    if not parsed_url.hostname or '.' not in parsed_url.hostname:
        logging.debug(f"链接主机名无效: {parsed_url.hostname}")
        return False

    # Check for valid port range (ports are typically 1-65535)
    if parsed_url.port is None or not (1 <= parsed_url.port <= 65535):
        logging.debug(f"链接端口无效: {parsed_url.port}")
        return False

    # Add other basic checks as needed (e.g., specific protocol requirements)

    return True


def parse_and_canonicalize(link_string):
    """Parses, cleans, decodes, and canonicalizes a proxy link."""
    if not link_string or not isinstance(link_string, str):
        logging.debug("输入链接字符串为空或非字符串类型。")
        return None

    cleaned_decoded_link = clean_and_urldecode(link_string)
    if not cleaned_decoded_link:
        logging.debug(f"清洗或 URL 解码失败: {link_string[:50]}...")
        return None

    # Remove fragment identifier (name/remark) for canonicalization
    link_without_fragment = cleaned_decoded_link.split('#', 1)[0]

    scheme = ''
    parsed_payload_for_urlparse = link_without_fragment # Default for non-base64 schemes
    vmess_json_payload = None # For vmess specific parsing
    ssr_decoded_parts = None # For SSR specific parsing

    # Handle Base64 encoded schemes first (VMess and SSR)
    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4) # Add padding
            decoded_payload_str = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            vmess_json_payload = json.loads(decoded_payload_str)
            # For VMess, we will use the 'add' and 'port' from the JSON for urlparse to ensure consistency
            # and later build the canonical_id from the JSON payload itself.
            add = vmess_json_payload.get('add', '')
            port = vmess_json_payload.get('port', '')
            if add and port:
                parsed_payload_for_urlparse = f"vmess://{add}:{port}"
            else:
                logging.debug("VMess JSON 缺少 'add' 或 'port' 字段。")
                return None
            logging.debug(f"VMess Base64 解码并解析 JSON 成功。")
        except (json.JSONDecodeError, Exception) as e:
            logging.debug(f"VMess Base64 解码或 JSON 解析失败: {link_without_fragment[:50]}... 错误: {e}")
            return None

    elif link_without_fragment.startswith('ssr://'):
        scheme = 'ssr'
        try:
            b64_payload = link_without_fragment[6:]
            b64_payload += '=' * (-len(b64_payload) % 4) # Add padding
            decoded_payload_str = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            ssr_decoded_parts = decoded_payload_str.split(':')
            if len(ssr_decoded_parts) >= 6: # host:port:protocol:method:obfs:password_b64
                # Construct a URL-like string for urlparse to handle path/query, if any, although SSR query is custom
                ssr_host = ssr_decoded_parts[0]
                ssr_port = ssr_decoded_parts[1]
                # The rest of the string after host:port might contain custom params
                remaining_path_query = decoded_payload_str.split(':', 2)[-1] # Gets "protocol:method:obfs:password_b64/?"
                parsed_payload_for_urlparse = f"ssr://{ssr_host}:{ssr_port}/{remaining_path_query}"
                logging.debug(f"SSR Base64 解码并提取主要部分成功。")
            else:
                logging.debug(f"SSR Base64 解码内容格式不符预期: {decoded_payload_str[:50]}...")
                return None
        except Exception as e:
            logging.debug(f"SSR Base64 解码失败或解析错误: {link_without_fragment[:50]}... 错误: {e}")
            return None

    elif '://' in link_without_fragment:
        try:
            scheme = link_without_fragment.split('://', 1)[0].lower()
        except Exception as e:
            logging.debug(f"提取协议失败: {link_without_fragment[:50]}... 错误: {e}")
            return None
    else:
        logging.debug(f"链接不包含协议: {link_without_fragment[:50]}...")
        return None

    try:
        parsed = urlparse(parsed_payload_for_urlparse)

        if not is_valid_link(parsed):
            logging.debug(f"链接基本验证失败: {link_without_fragment[:50]}...")
            return None

        host = parsed.hostname.lower() if parsed.hostname else ''
        port = parsed.port
        userinfo = parsed.username

        if not scheme or not host or not port:
            logging.debug(f"链接缺少必需组件 (协议/主机/端口): {link_without_fragment[:50]}...")
            return None

        canonical_id_components = [scheme]

        # For specific schemes, include userinfo directly or after decoding
        if scheme == 'ss':
            if userinfo:
                try:
                    userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8", errors='replace')
                    if ':' in userinfo_decoded:
                        method, password = userinfo_decoded.split(':', 1)
                        canonical_id_components.append(f"{method}:{password}")
                    else:
                        logging.debug(f"SS userinfo 解码后不是 method:password 格式: {userinfo_decoded}")
                        return None
                except Exception as e:
                    logging.debug(f"SS userinfo Base64 解码失败: {userinfo[:50]}... 错误: {e}")
                    return None
            else:
                logging.debug(f"SS 链接缺少用户信息: {link_without_fragment[:50]}...")
                return None
        elif userinfo: # For vless, trojan, juicity, etc. where userinfo is ID/password
            canonical_id_components.append(userinfo)

        canonical_id_components.append(f"{host}:{port}")

        # Canonicalize Path - strip leading/trailing slashes if not root and relevant
        canonical_path = parsed.path.strip('/')
        if canonical_path:
            # Paths might be crucial for VLESS/Trojan
            canonical_id_components.append(f"path={canonical_path}")

        # Canonicalize Query Parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        canonical_query_list = []
        for key in sorted(query_params.keys()): # Sort keys for consistent order
            values = query_params[key]
            for value in sorted(values): # Sort values for consistent order if multiple exist
                canonical_query_list.append(f"{key}={value}")

        if canonical_query_list:
            canonical_query = "&".join(canonical_query_list)
            canonical_id_components.append(f"query={canonical_query}")

        # Specific handling for VMess JSON fields for higher uniqueness
        if scheme == 'vmess' and vmess_json_payload:
            vmess_fields_to_include = ['id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'fp', 'v'] # Added 'v' (version) for completeness
            vmess_canonical_parts = []
            for field in sorted(vmess_fields_to_include):
                value = vmess_json_payload.get(field)
                if value is not None and value != '':
                    vmess_canonical_parts.append(f"{field}={value}")
            if vmess_canonical_parts:
                canonical_id_components.append(f"vmess_params={';'.join(vmess_canonical_parts)}")

        # Specific handling for SSR fields from its decoded parts
        if scheme == 'ssr' and ssr_decoded_parts:
            # Format: host:port:protocol:method:obfs:password_b64/?obfsparam=...
            try:
                ssr_host = ssr_decoded_parts[0]
                ssr_port = ssr_decoded_parts[1]
                ssr_protocol = ssr_decoded_parts[2]
                ssr_method = ssr_decoded_parts[3]
                ssr_obfs = ssr_decoded_parts[4]
                
                # password_b64 is ssr_decoded_parts[5], and the rest is query part
                password_part_with_query = ssr_decoded_parts[5]
                actual_password_b64 = password_part_with_query.split('/?')[0] # Remove query if present

                # Decode password for canonical ID
                password_canonical = base64.b64decode(actual_password_b64 + '=' * (-len(actual_password_b64) % 4)).decode("utf-8", errors='replace')
                
                ssr_specific_parts = [
                    f"protocol={ssr_protocol}",
                    f"method={ssr_method}",
                    f"obfs={ssr_obfs}",
                    f"password={password_canonical}" # Include decoded password
                ]
                
                # Handle SSR custom query parameters from the original decoded string
                ssr_custom_query_str = ''
                if '/?' in decoded_payload_str:
                    ssr_custom_query_str = decoded_payload_str.split('/?', 1)[1]
                
                ssr_custom_params = parse_qs(ssr_custom_query_str, keep_blank_values=True)
                ssr_canonical_custom_list = []
                for key in sorted(ssr_custom_params.keys()):
                    for value in sorted(ssr_custom_params[key]):
                        ssr_canonical_custom_list.append(f"{key}={value}")

                if ssr_canonical_custom_list:
                    ssr_custom_query = "&".join(ssr_canonical_custom_list)
                    ssr_specific_parts.append(f"custom_query={ssr_custom_query}")

                canonical_id_components.append(f"ssr_params={';'.join(ssr_specific_parts)}")

            except Exception as e:
                logging.debug(f"SSR 深入解析并构建 canonical ID 失败: {e}")
                return None


        # Join all components to form the final canonical ID
        canonical_id = "_".join(canonical_id_components).lower() # Use underscore for clearer separation

        if canonical_id:
            return (canonical_id, cleaned_decoded_link)
        else:
            logging.debug(f"未能为协议 {scheme} 生成完整的规范化 ID: {link_without_fragment[:50]}...")
            return None

    except Exception as e:
        logging.error(f"解析或规范化链接时发生未预料的错误 '{link_string[:50]}...': {e}")
        return None

# The rest of your script's main execution logic would remain the same,
# as it calls `parse_and_canonicalize` and uses its output for deduplication.

# Example of how it would be used in the main part of your script:
# (This part is for illustration, not to be added directly to the output unless user asks for full script)
if __name__ == "__main__":
    # ... (existing logging and config setup) ...

    # The existing loop for deduplication will now use the more precise canonical_id:
    # unique_configs = {}
    # for raw_link, channel_name in all_potential_links_data:
    #     result = parse_and_canonicalize(raw_link)
    #     if result:
    #         canonical_id, cleaned_original_link = result
    #         if canonical_id not in unique_configs:
    #             unique_configs[canonical_id] = cleaned_original_link
    #             # ... (rest of your logic) ...
