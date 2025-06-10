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
from urllib.parse import urlparse, parse_qs, urlencode
import logging

# Disable insecure request warnings
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# Clear console
os.system('cls' if os.name == 'nt' else 'clear')

# --- Configuration Files ---
CONFIG_TG_FILE = 'configtg.txt'
TG_CHANNELS_FILE = 'telegramchannels.json'
INV_TG_CHANNELS_FILE = 'invalidtelegramchannels.json'

# --- Global Data and Locks ---
all_potential_links_data = []
data_lock = threading.Lock()
sem_pars = None # Semaphore will be initialized later based on THRD_PARS

# --- User Agent List for Rotation (Expanded) ---
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
    # Note: HarmonyOS UAs often resemble Android UAs, but might include 'HarmonyOS' or specific device identifiers.
    # These are examples based on observed patterns, actual UAs can be more specific.
    'Mozilla/5.0 (Linux; Android 10; HMA-AL00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36', # Example resembling Android on Huawei
    'Mozilla/5.0 (Linux; HarmonyOS 2.0; SEA-AL10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Mobile Safari/537.36', # Example with HarmonyOS identifier

    # Other potential User Agents (less common but can be included)
    # Add more as needed based on your target platforms/browsers
]


# --- Helper Functions ---

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

    # Remove fragment identifier
    link_without_fragment = cleaned_decoded_link.split('#', 1)[0]

    scheme_specific_part = link_without_fragment
    scheme = ''
    decoded_payload = '' # Initialize for vmess/ssr specifically

    # Handle Base64 encoded schemes first
    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4) # Add padding
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            scheme_specific_part = 'vmess://' + decoded_payload # Reconstruct with decoded payload for urlparse
            logging.debug(f"VMess Base64 解码成功: {decoded_payload[:50]}...")
        except Exception as e:
            logging.debug(f"VMess Base64 解码失败: {link_without_fragment[:50]}... Error: {e}")
            return None

    elif link_without_fragment.startswith('ssr://'):
        scheme = 'ssr'
        try:
            b64_payload = link_without_fragment[6:]
            b64_payload += '=' * (-len(b64_payload) % 4) # Add padding
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            scheme_specific_part = 'ssr://' + decoded_payload # Reconstruct with decoded payload for urlparse
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

        # --- Basic Validation after parsing ---
        if not is_valid_link(parsed):
             logging.debug(f"链接基本验证失败: {link_without_fragment[:50]}...")
             return None
        # --- End Basic Validation ---


        host = parsed.hostname.lower() if parsed.hostname else ''
        port = parsed.port
        userinfo = parsed.username

        # Redundant check after is_valid_link, but kept for clarity based on original
        if not scheme or not host or not port:
             logging.debug(f"链接缺少必需组件 (协议/主机/端口): {link_without_fragment[:50]}...")
             return None

        canonical_netloc = f"{host}:{port}"
        canonical_id = None

        # --- Canonicalization based on scheme ---
        if scheme in ['vmess']:
            try:
                # For vmess, parsed.path contains the JSON payload after decoding
                # urlparse might put it in path or netloc depending on format, re-parse the decoded string
                # We should use the 'decoded_payload' from the base64 step directly for JSON parsing
                if decoded_payload: # Ensure decoded_payload is not empty
                    payload = json.loads(decoded_payload)
                    vmess_id = payload.get('id')
                    if vmess_id:
                        canonical_id = f"{scheme}://{vmess_id}@{canonical_netloc}"
                        logging.debug(f"VMess 规范化成功: {canonical_id}")
                    else:
                        logging.debug(f"VMess JSON 缺少 'id' 字段: {decoded_payload}")
                        return None # VMess without ID is not useful for canonicalization
                else:
                    logging.debug(f"VMess 解码后内容为空，无法解析。")
                    return None
            except json.JSONDecodeError:
                logging.debug(f"VMess 解码后内容不是有效的 JSON: {decoded_payload}")
                return None
            except Exception as e:
                logging.debug(f"解析 VMess JSON 错误: {e}")
                return None

        elif scheme in ['vless', 'trojan', 'juicity']:
             # For these, userinfo is typically the ID/password
             if userinfo:
                 canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
                 logging.debug(f"{scheme.upper()} 规范化成功: {canonical_id}")
             elif scheme == 'trojan':
                 # Some trojan links might not have userinfo but rely on path/params
                 # Canonicalizing without userinfo might be less reliable for uniqueness
                 # Keeping original logic, but be aware
                 canonical_id = f"{scheme}://{canonical_netloc}"
                 logging.debug(f"Trojan 规范化成功 (无用户信息): {canonical_id}")
             elif scheme == 'vless' and parsed.path and parsed.path.strip('/') != '':
                 # Some VLESS might put ID in path
                 vless_id_from_path = parsed.path.strip('/')
                 canonical_id = f"{scheme}://{vless_id_from_path}@{canonical_netloc}"
                 logging.debug(f"VLESS 规范化成功 (从 Path 获取 ID): {canonical_id}")
             else:
                 logging.debug(f"{scheme.upper()} 链接缺少用户信息或 ID: {link_without_fragment[:50]}...")
                 return None

        elif scheme in ['ss']:
             # SS userinfo is base64(method:password)
             if userinfo:
                 try:
                     userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8", errors='replace')
                     if ':' in userinfo_decoded:
                         method, password = userinfo_decoded.split(':', 1)
                         # Canonical ID uses method and password as identifier
                         canonical_id = f"{scheme}://{method}:{password}@{canonical_netloc}"
                         logging.debug(f"SS 规范化成功: {canonical_id}")
                     else:
                         logging.debug(f"SS userinfo 解码后不是 method:password 格式: {userinfo_decoded}")
                         return None
                 except Exception as e:
                     logging.debug(f"SS userinfo Base64 解码失败: {userinfo[:50]}... Error: {e}")
                     return None
             elif parsed.path and parsed.path.strip() != '':
                 logging.debug(f"SS 链接格式异常 (有 Path 无 userinfo?): {link_without_fragment[:50]}...")
                 return None
             else:
                 logging.debug(f"SS 链接缺少用户信息: {link_without_fragment[:50]}...")
                 return None

        elif scheme in ['hysteria', 'hysteria2', 'hy2', 'socks', 'socks4', 'socks5', 'naive+']:
             # For these, netloc (host:port) is often sufficient for canonical ID, userinfo is optional auth
             canonical_id = f"{scheme}://{canonical_netloc}"
             if userinfo:
                 # Include userinfo if present for better uniqueness, though not always required by proto
                 canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
             logging.debug(f"{scheme.upper()} 规范化成功: {canonical_id}")

             if scheme == 'naive+':
                 # Naive+ scheme includes http/https
                 if cleaned_decoded_link.startswith('naive+http://'):
                      canonical_id = f"naive+http://{canonical_netloc}"
                      if userinfo: canonical_id = f"naive+http://{userinfo}@{canonical_netloc}"
                      logging.debug(f"Naive+ HTTP 规范化成功: {canonical_id}")
                 elif cleaned_decoded_link.startswith('naive+https://'):
                      canonical_id = f"naive+https://{canonical_netloc}"
                      if userinfo: canonical_id = f"naive+https://{userinfo}@{canonical_netloc}"
                      logging.debug(f"Naive+ HTTPS 规范化成功: {canonical_id}")
                 else:
                      logging.debug(f"Naive+ 链接格式异常 (非 http/https): {link_without_fragment[:50]}...")
                      return None
        elif scheme in ['tuic', 'nekoray']:
             # Add basic handling for other schemes if needed, assuming netloc is key
             canonical_id = f"{scheme}://{canonical_netloc}"
             if userinfo:
                 canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
             logging.debug(f"{scheme.upper()} 规范化成功: {canonical_id}")

        else:
            logging.debug(f"不支持或未知协议: {scheme} - {link_without_fragment[:50]}...")
            return None

        # --- End Canonicalization ---

        if canonical_id:
            # Return canonical ID (lowercase) and the cleaned original link
            return (canonical_id.lower(), cleaned_decoded_link)
        else:
            # This case should ideally be covered by specific protocol handling or validation
            logging.debug(f"未能为协议 {scheme} 生成规范化 ID: {link_without_fragment[:50]}...")
            return None

    except Exception as e:
        logging.debug(f"解析或规范化链接时发生未预料的错误 '{link_string[:50]}...': {e}")
        return None

# --- Main Processing Function ---

def process(i_url):
    """Processes a single Telegram channel to extract potential proxy links."""
    sem_pars.acquire()
    logging.info(f"开始处理频道: {i_url}")
    html_pages = []
    cur_url = i_url
    found_links_in_channel = False
    selected_user_agent = random.choice(USER_AGENTS) # Select a User-Agent for this thread
    headers = {'User-Agent': selected_user_agent}

    try:
        last_datbef = None
        for itter in range(1, pars_dp + 1):
            # *** BEGIN FIX: Check last_datbef before using it for subsequent pages ***
            if itter > 1 and last_datbef is None:
                logging.debug("上一页未找到下一页数据点，停止分页。")
                break # Exit the loop if no more pages are indicated
            # *** END FIX ***

            page_url = f'https://t.me/s/{cur_url}' if itter == 1 else f'https://t.me/s/{cur_url}?before={last_datbef[0]}'
            logging.debug(f"尝试获取页面: {page_url} (使用 User-Agent: {selected_user_agent})")

            page_fetched = False
            for attempt in range(3): # Retry up to 3 times
                try:
                    response = requests.get(page_url, verify=False, timeout=15, headers=headers)
                    response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    html_pages.append(response.text)
                    match = re.search(r'data-before="(\d+)"', response.text)
                    if match:
                        last_datbef = [match.group(1)]
                        logging.debug(f"找到下一页数据点: {last_datbef[0]}")
                    else:
                        last_datbef = None # No more pages
                        logging.debug("未找到下一页数据点，停止分页。")
                    page_fetched = True
                    logging.debug(f"成功获取页面: {page_url}")
                    break # Exit retry loop on success
                except requests.exceptions.HTTPError as e:
                    logging.warning(f"获取 {page_url} 失败 (HTTP 错误: {e.response.status_code})，重试 {attempt + 1}/3。")
                    time.sleep(random.uniform(5, 15))
                except requests.exceptions.RequestException as e:
                    logging.warning(f"获取 {page_url} 失败 (请求错误: {e})，重试 {attempt + 1}/3。")
                    time.sleep(random.uniform(5, 15))
                except Exception as e:
                    logging.warning(f"获取 {page_url} 失败 (未知错误: {e})，重试 {attempt + 1}/3。")
                    time.sleep(random.uniform(5, 15))


            if not page_fetched:
                logging.error(f"未能获取 {page_url} 页面，跳过该页。")
                # If first page failed or subsequent pages failed after retries, break from page iteration
                # This condition is now implicitly handled by the 'if itter > 1 and last_datbef is None' check above
                # but leaving this as a general catch for immediate page fetch failure
                if itter == 1: # If the first page cannot be fetched, no need to continue for this channel
                     break


        if not html_pages:
            logging.warning(f"频道 {i_url} 未获取到任何页面内容。")
            # No pages fetched, no links to process for this channel
            return


        logging.debug(f"开始解析频道 {i_url} 的 {len(html_pages)} 个页面。")
        for page in html_pages:
            soup = BeautifulSoup(page, 'html.parser')
            # Using find_all with a list of possible class names for message text
            code_tags = soup.find_all(class_=['tgme_widget_message_text', 'tgme_widget_message_service'])

            if not code_tags:
                logging.debug(f"在频道 {i_url} 的页面中未找到消息文本元素。")
                continue # Go to next page if no message tags found

            for code_tag in code_tags:
                # Extract text including line breaks from the tag and its descendants
                potential_links = code_tag.get_text(separator='\n').split('\n')

                for raw_link in potential_links:
                    # Use a compiled regex for efficiency and handle case-insensitively
                    # This regex is just a preliminary filter before full parsing
                    if re.search(r"(vmess|vless|ss|trojan|tuic|hysteria|hysteria2|hy2|juicity|nekoray|socks4|socks5|socks|naive\+):\/", raw_link, re.IGNORECASE):
                        with data_lock:
                            # Store raw link and source channel for later processing
                            all_potential_links_data.append((raw_link, i_url))
                        found_links_in_channel = True
                        logging.debug(f"在频道 {i_url} 中找到潜在链接: {raw_link[:100]}...")

        if found_links_in_channel:
            logging.info(f"在频道 {i_url} 中找到至少一个潜在链接。")
        else:
            logging.info(f"在频道 {i_url} 中未找到潜在链接。")


    except Exception as e:
        logging.error(f"处理频道 {i_url} 时发生未预料的错误: {e}")

    finally:
        sem_pars.release()
        logging.info(f"完成处理频道: {i_url}")


# --- Main Execution ---

if __name__ == "__main__":
    # Configure logging based on environment variable
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("脚本开始运行。")

    tg_name_json = json_load(TG_CHANNELS_FILE)
    inv_tg_name_json = json_load(INV_TG_CHANNELS_FILE)

    # Filter out invalid channel names (less than 5 chars or not string)
    inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]
    tg_name_json = [x for x in tg_name_json if isinstance(x, str) and len(x) >= 5]
    # Remove valid channels from invalid list
    inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))

    thrd_pars = int(os.getenv('THRD_PARS', '128'))
    pars_dp = int(os.getenv('PARS_DP', '1'))
    use_inv_tc = os.getenv('USE_INV_TC', 'n').lower() == 'y'

    # Initialize semaphore after getting THRD_PARS
    sem_pars = threading.Semaphore(thrd_pars)

    logging.info(f'\n当前配置:')
    logging.info(f'  并发抓取线程数 (THRD_PARS) = {thrd_pars}')
    logging.info(f'  每个频道抓取页面深度 (PARS_DP) = {pars_dp}')
    logging.info(f'  使用无效频道列表 (USE_INV_TC) = {use_inv_tc}')
    log_level_name = logging.getLevelName(log_level) # Get level name string
    logging.info(f'  日志级别 (LOG_LEVEL) = {log_level_name}')


    logging.info(f'\n现有频道统计:')
    logging.info(f'  {TG_CHANNELS_FILE} 中的频道总数 - {len(tg_name_json)}')
    logging.info(f'  {INV_TG_CHANNELS_FILE} 中的频道总数 - {len(inv_tg_name_json)}')

    logging.info(f'\n尝试从现有 {CONFIG_TG_FILE} 中的代理配置中获取新的 TG 频道名...')
    config_all = []
    if os.path.exists(CONFIG_TG_FILE):
        try:
            with open(CONFIG_TG_FILE, "r", encoding="utf-8") as config_all_file:
                config_all = config_all_file.readlines()
            logging.info(f"成功读取 {CONFIG_TG_FILE}。")
        except Exception as e:
            logging.error(f"读取 {CONFIG_TG_FILE} 失败: {e}")
            config_all = [] # Ensure config_all is a list even on error

    # Regex to find potential Telegram channel/user names
    pattern_telegram_user = re.compile(r'(?:https?:\/\/t\.me\/|@|%40|\bt\.me\/)([a-zA-Z0-9_]{5,})', re.IGNORECASE)

    extracted_tg_names = set()

    for config in config_all:
        cleaned_config = clean_and_urldecode(config)
        if not cleaned_config:
            continue

        # Handle Base64 encoded parts from vmess/ssr/ss more robustly
        if cleaned_config.startswith('vmess://') or cleaned_config.startswith('ssr://') or cleaned_config.startswith('ss://'):
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
                    b64_part += '=' * (-len(b64_part) % 4) # Add padding
                    decoded_payload = base64.b64decode(b64_part).decode("utf-8", errors='replace')

                    # Search for channel names within the decoded payload
                    matches = pattern_telegram_user.findall(decoded_payload)
                    for match in matches:
                        cleaned_name = match.lower().strip('_')
                        if len(cleaned_name) >= 5:
                            extracted_tg_names.add(cleaned_name)
                            logging.debug(f"从 Base64 解码内容中提取到潜在频道名: {cleaned_name}")

            except Exception as e:
                logging.debug(f"从 Base64 解码配置中提取频道名失败或非预期格式: {e}")


        # Also search for channel names directly in the cleaned config string
        matches = pattern_telegram_user.findall(cleaned_config)
        for match in matches:
            cleaned_name = match.lower().strip('_')
            if len(cleaned_name) >= 5:
                extracted_tg_names.add(cleaned_name)
                logging.debug(f"从原始配置中提取到潜在频道名: {cleaned_name}")


    extracted_tg_names = {name for name in extracted_tg_names if len(name) >= 5}
    initial_tg_count = len(tg_name_json)
    tg_name_json = list(set(tg_name_json).union(extracted_tg_names))
    tg_name_json = sorted(tg_name_json)

    logging.info(f'  从 {CONFIG_TG_FILE} 中提取并合并后，频道总数更新为 - {len(tg_name_json)} (新增 {len(tg_name_json) - initial_tg_count} 个)。')

    json_dump(tg_name_json, TG_CHANNELS_FILE)

    logging.info(f'从配置中搜索新频道名结束.')

    start_time = datetime.now()
    logging.info(f'\n开始爬取 TG 频道并解析配置...')

    channels_to_process = tg_name_json
    if use_inv_tc:
        channels_to_process = sorted(list(set(tg_name_json).union(inv_tg_name_json)))
        logging.info(f'  根据 USE_INV_TC=y 配置，将处理 {len(channels_to_process)} 个频道 (合并了有效和无效列表)。')
    else:
        logging.info(f'  将处理 {len(channels_to_process)} 个有效频道。')


    threads = []
    for url in channels_to_process:
        thread = threading.Thread(target=process, args=(url,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    end_time_parsing = datetime.now()
    logging.info(f'\n爬取和原始链接提取完成 - 耗时 {str(end_time_parsing - start_time).split(".")[0]}')
    logging.info(f'共提取到 {len(all_potential_links_data)} 条原始潜在链接。')

    logging.info(f'\n开始对提取到的链接进行去重和规范化...')

    unique_configs = {}
    channels_that_worked = set()
    invalid_links_count = 0

    for raw_link, channel_name in all_potential_links_data:
        result = parse_and_canonicalize(raw_link)

        if result:
            canonical_id, cleaned_original_link = result
            if canonical_id not in unique_configs:
                unique_configs[canonical_id] = cleaned_original_link
                channels_that_worked.add(channel_name)
                logging.debug(f"添加有效且唯一的配置: {canonical_id}")
            else:
                logging.debug(f"跳过重复配置: {canonical_id}")
        else:
            invalid_links_count += 1
            logging.debug(f"跳过无效或无法解析的链接: {raw_link[:100]}...")


    end_time_dedup = datetime.now()
    processed_codes_list = list(unique_configs.values())
    logging.info(f'链接去重和规范化完成 - 耗时 {str(end_time_dedup - end_time_parsing).split(".")[0]}')
    logging.info(f'最终去重后得到 {len(processed_codes_list)} 条有效配置。')
    logging.info(f'跳过 {invalid_links_count} 条无效或无法解析的链接。')


    logging.info(f'\n更新频道列表文件...')

    new_tg_name_json = sorted(list(channels_that_worked))
    # Update invalid list: original valid channels that didn't yield links + original invalid channels
    inv_tg_name_json = sorted(list((set(tg_name_json) - channels_that_worked).union(set(inv_tg_name_json))))
    # Filter again to be safe
    inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]


    json_dump(new_tg_name_json, TG_CHANNELS_FILE)
    json_dump(inv_tg_name_json, INV_TG_CHANNELS_FILE)

    logging.info(f'  更新后的 {TG_CHANNELS_FILE} 频道数: {len(new_tg_name_json)}')
    logging.info(f'  更新后的 {INV_TG_CHANNELS_FILE} 频道数: {len(inv_tg_name_json)}')

    logging.info(f'\n保存最终有效配置到 {CONFIG_TG_FILE}...')
    write_lines(processed_codes_list, CONFIG_TG_FILE)

    end_time_total = datetime.now()
    logging.info(f'\n脚本运行完毕！总耗时 - {str(end_time_total - start_time).split(".")[0]}')
