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

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

os.system('cls' if os.name == 'nt' else 'clear')

CONFIG_TG_FILE = 'configtg.txt'
TG_CHANNELS_FILE = 'telegramchannels.json'
INV_TG_CHANNELS_FILE = 'invalidtelegramchannels.json'

def json_load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding="utf-8") as file:
            content = file.read()
            if not content:
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        logging.warning(f"文件 {path} 内容无效，返回空列表。")
        return []
    except Exception as e:
        logging.error(f"加载文件 {path} 时发生错误: {e}")
        return []

def json_dump(data, path):
    try:
        with open(path, 'w', encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def write_lines(data, path):
    try:
        with open(path, "w", encoding="utf-8") as file:
            for item in data:
                file.write(str(item) + "\n")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def clean_and_urldecode(raw_string):
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
            break

    return decoded

def parse_and_canonicalize(link_string):
    if not link_string or not isinstance(link_string, str):
        return None

    cleaned_decoded_link = clean_and_urldecode(link_string)
    if not cleaned_decoded_link:
        return None

    if '#' in cleaned_decoded_link:
        link_without_fragment = cleaned_decoded_link.split('#', 1)[0]
    else:
        link_without_fragment = cleaned_decoded_link

    scheme_specific_part = link_without_fragment
    scheme = ''

    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            scheme_specific_part = 'vmess://' + decoded_payload
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
        except Exception as e:
            logging.debug(f"SSR Base64 解码失败: {link_without_fragment[:50]}... Error: {e}")
            return None

    elif '://' in link_without_fragment:
        try:
            scheme = link_without_fragment.split('://', 1)[0].lower()
        except:
            return None

    try:
        parsed = urlparse(scheme_specific_part)
        host = parsed.hostname.lower() if parsed.hostname else ''
        port = parsed.port
        userinfo = parsed.username

        if not scheme or not host or not port:
            logging.debug(f"链接缺少必需组件 (协议/主机/端口): {link_without_fragment[:50]}...")
            return None

        canonical_netloc = f"{host}:{port}"
        canonical_id = None

        if scheme in ['vmess']:
            try:
                payload = json.loads(parsed.path if parsed.path else '{}')
                vmess_id = payload.get('id')
                if vmess_id:
                    canonical_id = f"{scheme}://{vmess_id}@{canonical_netloc}"
            except json.JSONDecodeError:
                logging.debug(f"VMess 解码后内容不是有效的 JSON: {scheme_specific_part}")
                return None
            except Exception as e:
                logging.debug(f"解析 VMess JSON 错误: {e}")
                return None

        elif scheme in ['vless', 'trojan', 'juicity']:
            if userinfo:
                canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
            elif scheme == 'trojan':
                canonical_id = f"{scheme}://{canonical_netloc}"
            elif scheme == 'vless' and parsed.path and parsed.path.strip('/') != '':
                vless_id_from_path = parsed.path.strip('/')
                canonical_id = f"{scheme}://{vless_id_from_path}@{canonical_netloc}"
            else:
                logging.debug(f"{scheme.upper()} 链接缺少用户信息或 ID: {link_without_fragment[:50]}...")
                return None

        elif scheme in ['ss']:
            if userinfo:
                try:
                    userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8", errors='replace')
                    if ':' in userinfo_decoded:
                        method, password = userinfo_decoded.split(':', 1)
                        canonical_id = f"{scheme}://{method}:{password}@{canonical_netloc}"
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
            canonical_id = f"{scheme}://{canonical_netloc}"
            if userinfo:
                canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
            if scheme == 'naive+':
                if cleaned_decoded_link.startswith('naive+http://'):
                        canonical_id = f"naive+http://{canonical_netloc}"
                        if userinfo: canonical_id = f"naive+http://{userinfo}@{canonical_netloc}"
                elif cleaned_decoded_link.startswith('naive+https://'):
                        canonical_id = f"naive+https://{canonical_netloc}"
                        if userinfo: canonical_id = f"naive+https://{userinfo}@{canonical_netloc}"
                else:
                        logging.debug(f"Naive+ 链接格式异常 (非 http/https): {link_without_fragment[:50]}...")
                        return None

        else:
            logging.debug(f"不支持或未知协议: {scheme} - {link_without_fragment[:50]}...")
            return None

        if canonical_id:
            return (canonical_id.lower(), cleaned_decoded_link)
        else:
            logging.debug(f"未能为协议 {scheme} 生成规范化 ID: {link_without_fragment[:50]}...")
            return None

    except Exception as e:
        logging.debug(f"解析或规范化链接时发生错误 '{link_string[:50]}...': {e}")
        return None

all_potential_links_data = []
data_lock = threading.Lock()

def process(i_url):
    sem_pars.acquire()
    html_pages = []
    cur_url = i_url
    found_links_in_channel = False

    try:
        last_datbef = None # Initialize last_datbef before the loop
        for itter in range(1, pars_dp + 1):
            page_url = f'https://t.me/s/{cur_url}' if itter == 1 else f'https://t.me/s/{cur_url}?before={last_datbef[0]}'
            # last_datbef is updated inside the inner loop

            for _ in range(3):
                try:
                    response = requests.get(page_url, verify=False, timeout=15)
                    response.raise_for_status()
                    html_pages.append(response.text)
                    match = re.search(r'data-before="(\d+)"', response.text)
                    if match:
                        last_datbef = [match.group(1)]
                    else:
                        last_datbef = None # If no match, stop trying to paginate
                    break
                except requests.exceptions.RequestException as e:
                    logging.warning(f"获取 {page_url} 失败 (重试): {e}")
                    time.sleep(random.uniform(5, 15))
            
            if not html_pages or (itter > 1 and not last_datbef):
                # If first page failed or subsequent pages have no 'data-before', break
                if itter == 1 and not html_pages:
                    logging.warning(f"未能获取频道 {i_url} 的第一页。")
                break


        for page in html_pages:
            soup = BeautifulSoup(page, 'html.parser')
            # Using find_all with a list of possible class names for message text
            code_tags = soup.find_all(class_=['tgme_widget_message_text', 'tgme_widget_message_service'])


            for code_tag in code_tags:
                # Extract text including line breaks from the tag and its descendants
                potential_links = code_tag.get_text(separator='\n').split('\n')


                for raw_link in potential_links:
                    # Use a compiled regex for efficiency and handle case-insensitively
                    if re.search(r"(vmess|vless|ss|trojan|tuic|hysteria|hysteria2|hy2|juicity|nekoray|socks4|socks5|socks|naive\+):\/", raw_link, re.IGNORECASE):
                        with data_lock:
                            all_potential_links_data.append((raw_link, i_url))
                        found_links_in_channel = True

        if found_links_in_channel:
            # This block doesn't do anything, maybe it was intended for logging or tracking?
            # Keeping it as is based on your original code.
            with data_lock:
                pass


    except Exception as e:
        logging.error(f"处理频道 {i_url} 时发生未预料的错误: {e}")

    finally:
        sem_pars.release()

# Configure logging (added missing logging basicConfig)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Set logging level for debug messages to DEBUG if you need more verbosity
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


tg_name_json = json_load(TG_CHANNELS_FILE)
inv_tg_name_json = json_load(INV_TG_CHANNELS_FILE)

inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]
tg_name_json = [x for x in tg_name_json if isinstance(x, str) and len(x) >= 5]
inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))

thrd_pars = int(os.getenv('THRD_PARS', '128'))
pars_dp = int(os.getenv('PARS_DP', '1'))

print(f'\n当前配置:')
print(f'  并发抓取线程数 (THRD_PARS) = {thrd_pars}')
print(f'  每个频道抓取页面深度 (PARS_DP) = {pars_dp}')

print(f'\n现有频道统计:')
print(f'  {TG_CHANNELS_FILE} 中的频道总数 - {len(tg_name_json)}')
# Corrected the variable name here:
print(f'  {INV_TG_CHANNELS_FILE} 中的频道总数 - {len(inv_tg_name_json)}')

use_inv_tc = os.getenv('USE_INV_TC', 'n')
use_inv_tc = True if use_inv_tc.lower() == 'y' else False

print(f'\n尝试从现有 {CONFIG_TG_FILE} 中的代理配置中获取新的 TG 频道名...')
config_all = []
if os.path.exists(CONFIG_TG_FILE):
    try:
        with open(CONFIG_TG_FILE, "r", encoding="utf-8") as config_all_file:
            config_all = config_all_file.readlines()
    except Exception as e:
        logging.error(f"读取 {CONFIG_TG_FILE} 失败: {e}")

# Relaxed the regex slightly to capture potential channel names more broadly
# Original: re.compile(r'(?:@|%40|t\.me\/)(\w{5,})', re.IGNORECASE)
# New: Allows for names starting with letters/numbers and followed by letters/numbers/underscores (common in usernames/channel names)
pattern_telegram_user = re.compile(r'(?:https?:\/\/t\.me\/|@|%40|\bt\.me\/)([a-zA-Z0-9_]{5,})', re.IGNORECASE)

extracted_tg_names = set()

for config in config_all:
    cleaned_config = clean_and_urldecode(config)
    if not cleaned_config:
        continue

    # Handle Base64 encoded parts from vmess/ssr/ss more robustly
    if cleaned_config.startswith('vmess://') or cleaned_config.startswith('ssr://') or cleaned_config.startswith('ss://'):
        try:
            # Extract the Base64 part based on the scheme
            if cleaned_config.startswith('vmess://'):
                b64_part = cleaned_config[8:]
            elif cleaned_config.startswith('ssr://'):
                b64_part = cleaned_config[6:]
            elif cleaned_config.startswith('ss://'):
                # For SS, the userinfo part is Base64 encoded
                parsed_ss = urlparse(cleaned_config)
                b64_part = parsed_ss.username if parsed_ss.username else ''
                # Continue to the next iteration if there's no userinfo in SS
                if not b64_part:
                    continue

            # Add padding and decode
            b64_part += '=' * (-len(b64_part) % 4)
            decoded_payload = base64.b64decode(b64_part).decode("utf-8", errors='replace')

            # Search for channel names within the decoded payload
            matches = pattern_telegram_user.findall(decoded_payload)
            for match in matches:
                # Basic cleanup for extracted names
                cleaned_name = match.lower().strip('_')
                if len(cleaned_name) >= 5:
                    extracted_tg_names.add(cleaned_name)

        except Exception as e:
            # Changed logging level to debug as this is a common occurrence for non-channel configs
            logging.debug(f"从 Base64 解码配置中提取频道名失败或非预期格式: {e}")


    # Also search for channel names directly in the cleaned config string
    matches = pattern_telegram_user.findall(cleaned_config)
    for match in matches:
        # Basic cleanup for extracted names
        cleaned_name = match.lower().strip('_')
        if len(cleaned_name) >= 5:
            extracted_tg_names.add(cleaned_name)


extracted_tg_names = {name for name in extracted_tg_names if len(name) >= 5}
tg_name_json = list(set(tg_name_json).union(extracted_tg_names))
tg_name_json = sorted(tg_name_json)


print(f'  从 {CONFIG_TG_FILE} 中提取并合并后的频道总数 - {len(tg_name_json)}')

json_dump(tg_name_json, TG_CHANNELS_FILE)

print(f'从配置中搜索新频道名结束.')

start_time = datetime.now()
print(f'\n开始爬取 TG 频道并解析配置...')

channels_to_process = tg_name_json
if use_inv_tc:
    channels_to_process = sorted(list(set(tg_name_json).union(inv_tg_name_json)))
    print(f'  根据 USE_INV_TC=y 配置，将处理 {len(channels_to_process)} 个频道 (合并了有效和无效列表)。')


threads = []
sem_pars = threading.Semaphore(thrd_pars)
all_potential_links_data = []
data_lock = threading.Lock()

for url in channels_to_process:
    thread = threading.Thread(target=process, args=(url,))
    threads.append(thread)
    thread.start()

for thread in threads:
    thread.join()

end_time_parsing = datetime.now()
print(f'\n爬取和原始链接提取完成 - 耗时 {str(end_time_parsing - start_time).split(".")[0]}')
print(f'共提取到 {len(all_potential_links_data)} 条原始潜在链接。')

print(f'\n开始对提取到的链接进行去重和规范化...')

unique_configs = {}
channels_that_worked = set()

for raw_link, channel_name in all_potential_links_data:
    result = parse_and_canonicalize(raw_link)

    if result:
        canonical_id, cleaned_original_link = result
        if canonical_id not in unique_configs:
            unique_configs[canonical_id] = cleaned_original_link
            channels_that_worked.add(channel_name)


end_time_dedup = datetime.now()
processed_codes_list = list(unique_configs.values())
print(f'链接去重和规范化完成 - 耗时 {str(end_time_dedup - end_time_parsing).split(".")[0]}')
print(f'最终去重后得到 {len(processed_codes_list)} 条有效配置。')

print(f'\n更新频道列表文件...')

new_tg_name_json = sorted(list(channels_that_worked))
# 修正了这一行：将 inv_tg_name_json 也转换为集合，然后再执行 union 操作
inv_tg_name_json = sorted(list((set(tg_name_json) - channels_that_worked).union(set(inv_tg_name_json))))
inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]

json_dump(new_tg_name_json, TG_CHANNELS_FILE)
json_dump(inv_tg_name_json, INV_TG_CHANNELS_FILE)

print(f'  更新后的 {TG_CHANNELS_FILE} 频道数: {len(new_tg_name_json)}')
print(f'  更新后的 {INV_TG_CHANNELS_FILE} 频道数: {len(inv_tg_name_json)}')

print(f'\n保存最终有效配置到 {CONFIG_TG_FILE}...')
write_lines(processed_codes_list, CONFIG_TG_FILE)

end_time_total = datetime.now()
print(f'\n脚本运行完毕！总耗时 - {str(end_time_total - start_time).split(".")[0]}')
