import requests
import threading
import json
import os
import time
import random
import re
import base64
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, quote
import logging
from concurrent.futures import ThreadPoolExecutor

# 禁用不安全请求警告
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# 清空控制台
os.system('cls' if os.name == 'nt' else 'clear')

# --- 配置文件 ---
CONFIG_TG_FILE = 'configtg.txt'
TG_CHANNELS_FILE = 'telegramchannels.json'
INV_TG_CHANNELS_FILE = 'invalidtelegramchannels.json'

# --- 全局数据和锁 ---
all_potential_links_data = []
data_lock = threading.Lock()
sem_pars = None  # 稍后根据 THRD_PARS 初始化信号量

# --- 用户代理列表（扩展） ---
USER_AGENTS = [
    # 桌面浏览器
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    # 移动浏览器
    'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1',
]

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

def clean_and_urldecode(raw_string):
    """清理并解码 URL 字符串"""
    if not isinstance(raw_string, str):
        return None

    cleaned = raw_string.strip()
    cleaned = re.sub(r'amp;', '', cleaned)
    cleaned = re.sub(r'%0A|%250A|%0D|\\n', '', cleaned, flags=re.IGNORECASE)

    decoded = cleaned
    max_decode_attempts = 5  # 防止无限循环
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

def parse_and_canonicalize(link_string):
    """解析、清理、解码并规范化代理链接"""
    if not link_string or not isinstance(link_string, str):
        logging.debug("输入链接字符串为空或非字符串类型。")
        return None

    cleaned_decoded_link = clean_and_urldecode(link_string)
    if not cleaned_decoded_link:
        logging.debug(f"清洗或 URL 解码失败: {link_string[:50]}...")
        return None

    link_without_fragment = cleaned_decoded_link.split('#', 1)[0]
    scheme = ''
    parsed_payload_for_urlparse = link_without_fragment
    vmess_json_payload = None
    ssr_decoded_parts = None

    # 处理 Base64 编码的协议（VMess 和 SSR）
    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload_str = base64.b64decode(b64_payload).decode("utf-8", errors='replace')
            vmess_json_payload = json.loads(decoded_payload_str)
            add = vmess_json_payload.get('add', '')
            port = vmess_json_payload.get('port', '')
            if add and port:
                parsed_payload_for_urlparse = f"vmess://{add}:{port}"
            else:
                logging.debug("VMess JSON 缺少 'add' 或 'port' 字段。")
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
            ssr_decoded_parts = decoded_payload_str.split(':')
            if len(ssr_decoded_parts) >= 6:
                ssr_host = ssr_decoded_parts[0]
                ssr_port = ssr_decoded_parts[1]
                remaining_path_query = ":".join(ssr_decoded_parts[2:])
                parsed_payload_for_urlparse = f"ssr://{ssr_host}:{ssr_port}/{remaining_path_query}"
            else:
                logging.debug(f"SSR Base64 解码内容格式不符: {decoded_payload_str[:50]}...")
                return None
        except Exception as e:
            logging.debug(f"SSR Base64 解码失败或解析错误: {link_without_fragment[:50]}... 错误: {e}")
            return None

    elif '://' in link_without_fragment:
        scheme = link_without_fragment.split('://', 1)[0].lower()
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
            logging.debug(f"链接缺少必需组件: {link_without_fragment[:50]}...")
            return None

        canonical_id_components = [scheme]

        if scheme == 'ss':
            if userinfo:
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
                logging.debug(f"SS 链接缺少用户信息: {link_without_fragment[:50]}...")
                return None
        elif userinfo:
            canonical_id_components.append(userinfo)

        canonical_id_components.append(f"{host}:{port}")

        canonical_path = parsed.path.strip('/')
        if canonical_path:
            canonical_id_components.append(f"path={quote(canonical_path, safe='')}")

        query_params = parse_qs(parsed.query, keep_blank_values=True)
        canonical_query_list = []
        for key in sorted(query_params.keys()):
            for value in sorted(query_params[key]):
                canonical_query_list.append(f"{quote(key.lower(), safe='')}={quote(value.lower(), safe='')}")
        if canonical_query_list:
            canonical_id_components.append(f"query={';'.join(canonical_query_list)}")

        # 优化 VMess 规范化
        if scheme == 'vmess' and vmess_json_payload:
            vmess_fields = ['id', 'aid', 'net', 'type', 'host', 'path', 'tls', 'sni', 'fp', 'v', 'add', 'port', 'ps', 'alpn']
            vmess_canonical_parts = []
            for field in sorted(vmess_fields):
                value = vmess_json_payload.get(field)
                if value is not None and value != '':
                    vmess_canonical_parts.append(f"{field}={quote(str(value).lower(), safe='')}")
            if vmess_canonical_parts:
                canonical_id_components.append(f"vmess_params={';'.join(vmess_canonical_parts)}")

        # 优化 SSR 规范化
        if scheme == 'ssr' and ssr_decoded_parts:
            try:
                ssr_protocol = ssr_decoded_parts[2]
                ssr_method = ssr_decoded_parts[3]
                ssr_obfs = ssr_decoded_parts[4]
                password_part_with_query = ssr_decoded_parts[5]
                actual_password_b64 = password_part_with_query.split('/?')[0]
                password_canonical = base64.b64decode(actual_password_b64 + '=' * (-len(actual_password_b64) % 4)).decode("utf-8", errors='replace')
                
                ssr_specific_parts = [
                    f"protocol={quote(ssr_protocol.lower(), safe='')}",
                    f"method={quote(ssr_method.lower(), safe='')}",
                    f"obfs={quote(ssr_obfs.lower(), safe='')}",
                    f"password={quote(password_canonical.lower(), safe='')}"
                ]

                ssr_custom_query_str = ''
                if '/?' in decoded_payload_str:
                    ssr_custom_query_str = decoded_payload_str.split('/?', 1)[1]
                ssr_custom_params = parse_qs(ssr_custom_query_str, keep_blank_values=True)
                ssr_canonical_custom_list = []
                for key in sorted(ssr_custom_params.keys()):
                    for value in sorted(ssr_custom_params[key]):
                        ssr_canonical_custom_list.append(f"{quote(key.lower(), safe='')}={quote(value.lower(), safe='')}")
                if ssr_canonical_custom_list:
                    ssr_specific_parts.append(f"custom_query={';'.join(ssr_canonical_custom_list)}")

                canonical_id_components.append(f"ssr_params={';'.join(ssr_specific_parts)}")
            except Exception as e:
                logging.debug(f"SSR 规范化失败: {e}")
                return None

        canonical_id = "###".join(canonical_id_components).lower()
        if canonical_id:
            return (canonical_id, cleaned_decoded_link)
        else:
            logging.debug(f"未能生成规范化 ID: {link_without_fragment[:50]}...")
            return None

    except Exception as e:
        logging.error(f"解析或规范化链接错误: {link_string[:50]}... 错误: {e}")
        return None

# --- 去重处理（并行化） ---

def process_link(link_data):
    """处理单个链接并返回规范化结果"""
    raw_link, channel_name = link_data
    result = parse_and_canonicalize(raw_link)
    if result:
        return result, channel_name
    return None, channel_name

# --- 主处理函数 ---

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

# --- 主执行逻辑 ---

if __name__ == "__main__":
    # 配置日志
    log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("脚本开始运行。")

    tg_name_json = json_load(TG_CHANNELS_FILE)
    inv_tg_name_json = json_load(INV_TG_CHANNELS_FILE)

    # 过滤无效频道名
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

    logging.info(f'\n现有频道统计:')
    logging.info(f'  {TG_CHANNELS_FILE} 中的频道总数 - {len(tg_name_json)}')
    logging.info(f'  {INV_TG_CHANNELS_FILE} 中的频道总数 - {len(inv_tg_name_json)}')

    logging.info(f'\n从 {CONFIG_TG_FILE} 中提取新的 TG 频道名...')
    config_all = []
    if os.path.exists(CONFIG_TG_FILE):
        try:
            with open(CONFIG_TG_FILE, "r", encoding="utf-8") as config_all_file:
                config_all = config_all_file.readlines()
            logging.info(f"成功读取 {CONFIG_TG_FILE}。")
        except Exception as e:
            logging.error(f"读取 {CONFIG_TG_FILE} 失败: {e}")

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
        logging.info(f'  处理 {len(channels_to_process)} 个频道（包含无效列表）。')
    else:
        logging.info(f'  处理 {len(channels_to_process)} 个有效频道。')

    threads = []
    for url in channels_to_process:
        thread = threading.Thread(target=process, args=(url,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    end_time_parsing = datetime.now()
    logging.info(f'\n爬取完成 - 耗时 {str(end_time_parsing - start_time).split(".")[0]}')
    logging.info(f'共提取到 {len(all_potential_links_data)} 条潜在链接。')

    logging.info(f'\n开始去重和规范化链接...')
    unique_configs = {}
    channels_that_worked = set()
    invalid_links_count = 0

    with ThreadPoolExecutor(max_workers=thrd_pars) as executor:
        results = list(executor.map(process_link, all_potential_links_data))

    for result, channel_name in results:
        if result:
            canonical_id, cleaned_original_link = result
            if canonical_id not in unique_configs:
                unique_configs[canonical_id] = cleaned_original_link
                channels_that_worked.add(channel_name)
                logging.debug(f"添加唯一配置: {canonical_id}")
            else:
                logging.debug(f"跳过重复配置: {canonical_id}")
        else:
            invalid_links_count += 1
            logging.debug(f"跳过无效链接: {channel_name}")

    end_time_dedup = datetime.now()
    processed_codes_list = list(unique_configs.values())
    logging.info(f'去重完成 - 耗时 {str(end_time_dedup - end_time_parsing).split(".")[0]}')
    logging.info(f'最终得到 {len(processed_codes_list)} 条有效配置，跳过 {invalid_links_count} 条无效链接。')

    logging.info(f'\n更新频道列表...')
    new_tg_name_json = sorted(list(channels_that_worked))
    inv_tg_name_json = sorted(list((set(tg_name_json) - channels_that_worked).union(set(inv_tg_name_json))))
    inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]

    json_dump(new_tg_name_json, TG_CHANNELS_FILE)
    json_dump(inv_tg_name_json, INV_TG_CHANNELS_FILE)

    logging.info(f'  更新后 {TG_CHANNELS_FILE} 频道数: {len(new_tg_name_json)}')
    logging.info(f'  更新后 {INV_TG_CHANNELS_FILE} 频道数: {len(inv_tg_name_json)}')

    logging.info(f'\n保存有效配置到 {CONFIG_TG_FILE}...')
    write_lines(processed_codes_list, CONFIG_TG_FILE)

    end_time_total = datetime.now()
    logging.info(f'\n脚本运行完毕！总耗时 - {str(end_time_total - start_time).split(".")[0]}')
