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

# 禁用不安全请求警告
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

# 清屏（仅在终端运行时有效）
os.system('cls' if os.name == 'nt' else 'clear')

# --- 文件路径定义 ---
CONFIG_TG_FILE = 'configtg.txt'
TG_CHANNELS_FILE = 'telegramchannels.json'
INV_TG_CHANNELS_FILE = 'invalidtelegramchannels.json'

# --- 文件处理辅助函数 ---

def json_load(path):
    """加载 JSON 文件，处理文件不存在或解码错误"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding="utf-8") as file:
            # 尝试读取，如果文件为空或内容无效，返回空列表
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
    """保存数据到 JSON 文件"""
    try:
        with open(path, 'w', encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False) # ensure_ascii=False 保存中文
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")

def write_lines(data, path):
    """保存列表数据到文本文件，每行一个元素"""
    try:
        with open(path, "w", encoding="utf-8") as file:
            for item in data:
                file.write(str(item) + "\n")
    except Exception as e:
        logging.error(f"保存文件 {path} 时发生错误: {e}")


# --- 链接处理和规范化 ---

def clean_and_urldecode(raw_string):
    """应用基本清理和多层 URL 解码"""
    if not isinstance(raw_string, str):
        return None

    cleaned = raw_string.strip()
    cleaned = re.sub(r'amp;', '', cleaned) # 移除 HTML 实体残留
    cleaned = re.sub(r'', '', cleaned) # 移除无效字符
    # 移除常见的换行编码
    cleaned = re.sub(r'%0A', '', cleaned)
    cleaned = re.sub(r'%250A', '', cleaned)
    cleaned = re.sub(r'%0D', '', cleaned)
    cleaned = re.sub(r'\\n', '', cleaned) # 移除转义换行符

    # 多次 URL 解码直到不再变化
    decoded = cleaned
    while True:
        try:
            new_decoded = requests.utils.unquote(decoded)
            if new_decoded == decoded:
                break
            decoded = new_decoded
        except:
            break # 解码失败则停止

    return decoded

def parse_and_canonicalize(link_string):
    """
    解析代理链接，生成一个用于去重的规范化 ID，并返回清理后的原始链接。
    返回 (canonical_id, cleaned_link) 或 None (如果无效/无法解析)。
    """
    if not link_string or not isinstance(link_string, str):
        return None

    cleaned_decoded_link = clean_and_urldecode(link_string)
    if not cleaned_decoded_link:
        return None

    # 移除链接片段（节点名称） before parsing
    if '#' in cleaned_decoded_link:
        link_without_fragment = cleaned_decoded_link.split('#', 1)[0]
    else:
        link_without_fragment = cleaned_decoded_link

    # 尝试 Base64 解码协议特定部分 (vmess, ssr)
    scheme_specific_part = link_without_fragment
    scheme = ''

    if link_without_fragment.startswith('vmess://'):
        scheme = 'vmess'
        try:
            # Vmess payload 是 Base64 编码的 JSON
            b64_payload = link_without_fragment[8:]
            b64_payload += '=' * (-len(b64_payload) % 4) # 添加 Base64 填充
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8")
            scheme_specific_part = 'vmess://' + decoded_payload # 将解码后的 JSON 放回，以便后续解析
        except Exception as e:
            logging.debug(f"VMess Base64 解码失败: {link_without_fragment[:50]}... Error: {e}")
            return None # Base64 解码失败视为无效链接

    elif link_without_fragment.startswith('ssr://'):
         scheme = 'ssr'
         try:
            # SSR payload 也是 Base64 编码的，格式特殊
            b64_payload = link_without_fragment[6:]
            b64_payload += '=' * (-len(b64_payload) % 4)
            decoded_payload = base64.b64decode(b64_payload).decode("utf-8")
            scheme_specific_part = 'ssr://' + decoded_payload # 将解码后的 payload 放回
         except Exception as e:
             logging.debug(f"SSR Base64 解码失败: {link_without_fragment[:50]}... Error: {e}")
             return None # Base64 解码失败视为无效链接

    elif '://' in link_without_fragment:
        # 对于非 Base64 payload 的协议，直接获取 scheme
        try:
            scheme = link_without_fragment.split('://', 1)[0].lower()
        except:
            return None # 格式错误


    # 解析链接主体
    try:
        parsed = urlparse(scheme_specific_part)
        host = parsed.hostname.lower() if parsed.hostname else ''
        port = parsed.port
        userinfo = parsed.username # 注意：对于某些协议（如 VLESS, Trojan），用户名部分可能是 UUID 或密码

        if not scheme or not host or not port:
             # 必须有协议、主机、端口
             logging.debug(f"链接缺少必需组件 (协议/主机/端口): {link_without_fragment[:50]}...")
             return None

        canonical_netloc = f"{host}:{port}"
        canonical_id = None # 用于去重的核心 ID

        # 根据协议构建规范化 ID
        if scheme in ['vmess']:
             # Vmess ID 在 JSON payload 里
             try:
                 payload = json.loads(parsed.path if parsed.path else '{}') # payload 是 urlparse 的 path 部分对于 vmess://jsonstring
                 vmess_id = payload.get('id')
                 if vmess_id:
                      canonical_id = f"{scheme}://{vmess_id}@{canonical_netloc}"
             except json.JSONDecodeError:
                 logging.debug(f"VMess 解码后内容不是有效的 JSON: {scheme_specific_part}")
                 return None # 解码后不是有效 JSON
             except Exception as e:
                 logging.debug(f"解析 VMess JSON 错误: {e}")
                 return None

        elif scheme in ['vless', 'trojan', 'juicity']:
             # 这些协议的 ID 通常在 userinfo 部分
             if userinfo:
                  canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
             # else: logging.debug(f"{scheme.upper()} 链接缺少用户信息 (ID/密码): {link_without_fragment[:50]}...") # 允许无密码的 trojan/vless?
             # 对于 VLESS/Trojan 理论上可以没有 userinfo，但有的话是去重的关键
             elif scheme == 'trojan': # Trojan 有时只有 host:port
                  canonical_id = f"{scheme}://{canonical_netloc}"
             elif scheme == 'vless' and parsed.path and parsed.path.strip('/') != '': # VLESS UUID 有时在 path
                  vless_id_from_path = parsed.path.strip('/')
                  canonical_id = f"{scheme}://{vless_id_from_path}@{canonical_netloc}"
             else:
                  logging.debug(f"{scheme.upper()} 链接缺少用户信息或 ID: {link_without_fragment[:50]}...")
                  return None # VLESS/Juicity 通常必须有 ID

        elif scheme in ['ss']:
            # SS 链接的 userinfo 是 base64 编码的 method:password
            if userinfo:
                try:
                    userinfo_decoded = base64.b64decode(userinfo + '=' * (-len(userinfo) % 4)).decode("utf-8")
                    if ':' in userinfo_decoded:
                         method, password = userinfo_decoded.split(':', 1)
                         canonical_id = f"{scheme}://{method}:{password}@{canonical_netloc}"
                    else:
                         logging.debug(f"SS userinfo 解码后不是 method:password 格式: {userinfo_decoded}")
                         return None
                except Exception as e:
                    logging.debug(f"SS userinfo Base64 解码失败: {userinfo[:50]}... Error: {e}")
                    return None # Base64 解码失败视为无效链接
            elif parsed.path and parsed.path.strip() != '': # 有时 SS 链接是 ss://base64_full
                 # 这种情况应该在 clean_decode_and_base64 已经处理了
                 # 如果到这里还有 path，可能是格式错误
                 logging.debug(f"SS 链接格式异常 (有 Path 无 userinfo?): {link_without_fragment[:50]}...")
                 return None
            else:
                 logging.debug(f"SS 链接缺少用户信息: {link_without_fragment[:50]}...")
                 return None


        elif scheme in ['hysteria', 'hysteria2', 'hy2', 'socks', 'socks4', 'socks5', 'naive+']:
             # 这些通常以 scheme://[user:pass@]host:port 作为核心标识
             canonical_id = f"{scheme}://{canonical_netloc}"
             if userinfo: # 包含用户/密码如果存在
                  canonical_id = f"{scheme}://{userinfo}@{canonical_netloc}"
             # For naive+, the scheme might be naive+https, need to keep that
             if scheme == 'naive+':
                  # Check if the original link had naive+http or naive+https
                  if cleaned_decoded_link.startswith('naive+http://'):
                       canonical_id = f"naive+http://{canonical_netloc}"
                       if userinfo: canonical_id = f"naive+http://{userinfo}@{canonical_netloc}"
                  elif cleaned_decoded_link.startswith('naive+https://'):
                       canonical_id = f"naive+https://{canonical_netloc}"
                       if userinfo: canonical_id = f"naive+https://{userinfo}@{canonical_netloc}"
                  else:
                       logging.debug(f"Naive+ 链接格式异常 (非 http/https): {link_without_fragment[:50]}...")
                       return None # Invalid naive+


        else:
            # 未知或不受支持的协议
            logging.debug(f"不支持或未知协议: {scheme} - {link_without_fragment[:50]}...")
            return None

        if canonical_id:
            return (canonical_id.lower(), cleaned_decoded_link) # 返回小写规范化 ID 和清理后的原始链接
        else:
             logging.debug(f"未能为协议 {scheme} 生成规范化 ID: {link_without_fragment[:50]}...")
             return None # 生成 ID 失败


    except Exception as e:
        # 捕获解析过程中可能出现的其他异常
        logging.debug(f"解析或规范化链接时发生错误 '{link_string[:50]}...': {e}")
        return None


# --- 线程处理函数 ---

# 使用锁来保护对共享列表的访问
all_potential_links_data = []
data_lock = threading.Lock()

def process(i_url):
    """抓取单个频道页面并提取潜在链接"""
    sem_pars.acquire() # 获取信号量，限制并发线程数
    html_pages = []
    cur_url = i_url
    found_links_in_channel = False # 标记本频道是否找到了有效链接

    try:
        # 根据 pars_dp 抓取多页
        for itter in range(1, pars_dp + 1):
            page_url = f'https://t.me/s/{cur_url}' if itter == 1 else f'https://t.me/s/{cur_url}?before={last_datbef[0]}'
            last_datbef = None # 重置 page 的 data-before

            # 重试机制获取页面
            for _ in range(3): # 最多重试 3 次
                try:
                    response = requests.get(page_url, verify=False, timeout=15) # 增加超时
                    response.raise_for_status() # 检查 HTTP 状态码
                    html_pages.append(response.text)
                    # 查找下一页的 data-before 标记
                    match = re.search(r'data-before="(\d+)"', response.text)
                    if match:
                         last_datbef = [match.group(1)] # 存储为列表以兼容原脚本后续逻辑（尽管后续会改）
                    break # 成功获取则跳出重试循环
                except requests.exceptions.RequestException as e:
                    logging.warning(f"获取 {page_url} 失败 (重试): {e}")
                    time.sleep(random.uniform(5, 15)) # 失败后等待随机时间

            if not html_pages or (itter > 1 and not last_datbef):
                # 第一页获取失败，或后续页获取失败且没有找到下一页标记
                if itter == 1 and not html_pages:
                     logging.warning(f"未能获取频道 {i_url} 的第一页。")
                break # 停止爬取该频道

        # 从所有获取的页面中提取潜在链接
        for page in html_pages:
            soup = BeautifulSoup(page, 'html.parser')
            # 查找包含消息内容的标签
            code_tags = soup.find_all(class_='tgme_widget_message_text')

            for code_tag in code_tags:
                # 提取文本内容，按换行分割，处理可能的多行链接
                potential_links = code_tag.get_text(separator='\n').split('\n')

                for raw_link in potential_links:
                    # 检查是否包含常见的代理协议前缀
                    if any(p in raw_link for p in ["vmess://", "vless://", "ss://", "trojan://",
                                                  "tuic://", "hysteria://", "hysteria2://",
                                                  "hy2://", "juicity://", "nekoray://",
                                                  "socks4://", "socks5://", "socks://", "naive+"]):
                         # 将原始潜在链接和对应的频道名存入共享列表
                         with data_lock:
                             all_potential_links_data.append((raw_link, i_url))
                         found_links_in_channel = True # 标记频道找到链接

        # 标记该频道是否找到了链接 (用于后续区分有效/无效频道)
        if found_links_in_channel:
             with data_lock:
                  # 使用 set 避免重复添加，但锁内操作需要注意性能，这里先append，后续统一处理更高效
                  pass # 链接已经添加到 all_potential_links_data，后续统一处理频道列表

    except Exception as e:
        logging.error(f"处理频道 {i_url} 时发生未预料的错误: {e}")

    finally:
        # 确保信号量在线程结束时释放
        sem_pars.release()


# --- 主流程 ---

# 加载现有频道列表和无效频道列表
tg_name_json = json_load(TG_CHANNELS_FILE)
inv_tg_name_json = json_load(INV_TG_CHANNELS_FILE)

# 清理并更新无效频道列表 (与原脚本逻辑保持一致)
inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5]
tg_name_json = [x for x in tg_name_json if isinstance(x, str) and len(x) >= 5]
# 从无效列表中移除已存在于有效列表的
inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))


thrd_pars = int(os.getenv('THRD_PARS', '128')) # 并发线程数
pars_dp = int(os.getenv('PARS_DP', '1'))     # 每个频道抓取的页面深度

print(f'\n当前配置:')
print(f'  并发抓取线程数 (THRD_PARS) = {thrd_pars}')
print(f'  每个频道抓取页面深度 (PARS_DP) = {pars_dp}')


print(f'\n现有频道统计:')
print(f'  {TG_CHANNELS_FILE} 中的频道总数 - {len(tg_name_json)}')
print(f'  {INV_TG_CHANNELS_FILE} 中的频道总数 - {len(inv_tg_name_json)}')

# 根据配置决定是否使用无效频道列表作为抓取源 (与原脚本逻辑保持一致)
use_inv_tc = os.getenv('USE_INV_TC', 'n')
use_inv_tc = True if use_inv_tc.lower() == 'y' else False

# --- 从 configtg.txt 中提取新的频道名 ---
print(f'\n尝试从现有 {CONFIG_TG_FILE} 中的代理配置中获取新的 TG 频道名...')
config_all = []
if os.path.exists(CONFIG_TG_FILE):
    try:
        with open(CONFIG_TG_FILE, "r", encoding="utf-8") as config_all_file:
            config_all = config_all_file.readlines()
    except Exception as e:
        logging.error(f"读取 {CONFIG_TG_FILE} 失败: {e}")


pattern_telegram_user = re.compile(r'(?:@|%40|t\.me\/)(\w{5,})', re.IGNORECASE) # 优化正则，只捕获用户名
extracted_tg_names = set()

for config in config_all:
    cleaned_config = clean_and_urldecode(config) # 先进行清理和解码
    if not cleaned_config:
        continue

    # 对于 Base64 编码的 Vmess/SSR，尝试解码后再查找频道名
    if cleaned_config.startswith('vmess://') or cleaned_config.startswith('ssr://'):
        try:
            b64_part = cleaned_config.split('://', 1)[1]
            b64_part += '=' * (-len(b64_part) % 4)
            decoded_payload = base64.b64decode(b64_part).decode("utf-8")
            # 在解码后的 payload 中查找频道名
            matches = pattern_telegram_user.findall(decoded_payload)
            for match in matches:
                extracted_tg_names.add(match.lower().encode('ascii', 'ignore').decode())
        except Exception as e:
            logging.debug(f"从 Base64 解码配置中提取频道名失败: {e}")

    # 在原始（已清理解码）链接中查找频道名
    matches = pattern_telegram_user.findall(cleaned_config)
    for match in matches:
         extracted_tg_names.add(match.lower().encode('ascii', 'ignore').decode())


# 将提取到的新频道名合并到现有列表中
extracted_tg_names = {name for name in extracted_tg_names if len(name) >= 5} # 过滤短名称
tg_name_json = list(set(tg_name_json).union(extracted_tg_names)) # 合并并去重
tg_name_json = sorted(tg_name_json) # 排序


print(f'  从 {CONFIG_TG_FILE} 中提取并合并后的频道总数 - {len(tg_name_json)}')

# 保存更新后的频道列表
json_dump(tg_name_json, TG_CHANNELS_FILE)

print(f'从配置中搜索新频道名结束.')

# --- 执行爬取 ---

start_time = datetime.now()
print(f'\n开始爬取 TG 频道并解析配置...')

# 选择要爬取的频道列表
channels_to_process = tg_name_json
if use_inv_tc:
    # 如果配置了使用无效频道列表，则将两者合并作为处理源
    channels_to_process = sorted(list(set(tg_name_json).union(inv_tg_name_json)))
    print(f'  根据 USE_INV_TC=y 配置，将处理 {len(channels_to_process)} 个频道 (合并了有效和无效列表)。')


threads = []
sem_pars = threading.Semaphore(thrd_pars) # 控制并发线程数
all_potential_links_data = [] # 存储原始潜在链接和对应的频道名
data_lock = threading.Lock() # 用于保护 all_potential_links_data

# 创建并启动线程
for url in channels_to_process:
    thread = threading.Thread(target=process, args=(url,))
    threads.append(thread)
    thread.start()

# 等待所有线程完成
for thread in threads:
    thread.join()

end_time_parsing = datetime.now()
print(f'\n爬取和原始链接提取完成 - 耗时 {str(end_time_parsing - start_time).split(".")[0]}')
print(f'共提取到 {len(all_potential_links_data)} 条原始潜在链接。')

# --- 链接去重和规范化处理 ---
print(f'\n开始对提取到的链接进行去重和规范化...')

unique_configs = {} # 存储最终的唯一配置 {canonical_id: cleaned_original_link}
channels_that_worked = set() # 存储成功找到有效链接的频道名

for raw_link, channel_name in all_potential_links_data:
    # 解析并生成规范化 ID
    result = parse_and_canonicalize(raw_link)

    if result:
        canonical_id, cleaned_original_link = result
        # 如果这个规范化 ID 还没有出现过
        if canonical_id not in unique_configs:
            unique_configs[canonical_id] = cleaned_original_link
            channels_that_worked.add(channel_name) # 记录这个频道是有效的


end_time_dedup = datetime.now()
processed_codes_list = list(unique_configs.values()) # 最终去重后的链接列表
print(f'链接去重和规范化完成 - 耗时 {str(end_time_dedup - end_time_parsing).split(".")[0]}')
print(f'最终去重后得到 {len(processed_codes_list)} 条有效配置。')

# --- 更新频道列表 ---
print(f'\n更新频道列表文件...')

# 新的有效频道列表是所有找到了有效链接的频道
new_tg_name_json = sorted(list(channels_that_worked))
# 更新无效频道列表：从原始有效列表中移除这次找到有效链接的频道
inv_tg_name_json = sorted(list(set(tg_name_json) - channels_that_worked).union(inv_tg_name_json)) # 无效列表 = (旧有效列表 - 本次有效列表) U 旧无效列表
inv_tg_name_json = [x for x in inv_tg_name_json if isinstance(x, str) and len(x) >= 5] # 再次清理无效列表

json_dump(new_tg_name_json, TG_CHANNELS_FILE)
json_dump(inv_tg_name_json, INV_TG_CHANNELS_FILE)

print(f'  更新后的 {TG_CHANNELS_FILE} 频道数: {len(new_tg_name_json)}')
print(f'  更新后的 {INV_TG_CHANNELS_FILE} 频道数: {len(inv_tg_name_json)}')


# --- 保存最终结果 ---
print(f'\n保存最终有效配置到 {CONFIG_TG_FILE}...')
write_lines(processed_codes_list, CONFIG_TG_FILE)

end_time_total = datetime.now()
print(f'\n脚本运行完毕！总耗时 - {str(end_time_total - start_time).split(".")[0]}')
