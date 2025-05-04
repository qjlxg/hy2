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

# 全局设置
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
# os.system('cls' if os.name == 'nt' else 'clear')  # 注释掉，避免无终端环境报错

def load_json(path):
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([], f)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def extract_tg_names_from_config(config_lines):
    pattern = r'(?:@|%40|t\.me/)(\w{5,})'
    tg_names = set()
    for line in config_lines:
        for content in [line, try_base64_decode(line)]:
            if content:
                tg_names.update([m.lower() for m in re.findall(pattern, content, re.IGNORECASE)])
    return tg_names

def try_base64_decode(s):
    try:
        if s.startswith('vmess://'):
            return base64.b64decode(s[8:]).decode('utf-8')
        if s.startswith('ssr://'):
            return base64.b64decode(s[6:]).decode('utf-8')
        return base64.b64decode(s).decode('utf-8')
    except Exception:
        return ""

def parse_channel(channel, depth, codes, valid_channels, invalid_channels, sem, htmltag_pattern):
    with sem:
        cur_url = channel
        html_pages = []
        for _ in range(depth):
            try:
                resp = requests.get(f'https://t.me/s/{cur_url}', verify=False, timeout=10)
                html = resp.text
                html_pages.append(html)
                last_datbef = re.findall(r'data-before="(\d*)"', html)
                if not last_datbef:
                    break
                cur_url = f'{channel}?before={last_datbef[0]}'
            except Exception:
                time.sleep(random.uniform(1, 3))
                continue

        found_code = False
        for page in html_pages:
            soup = BeautifulSoup(page, 'html.parser')
            for tag in soup.find_all(class_='tgme_widget_message_text'):
                for line in str(tag).split('<br/>'):
                    if any(proto in line for proto in [
                        "vless://", "ss://", "vmess://", "trojan://", "tuic://",
                        "hysteria://", "hy2://", "hysteria2://", "juicity://",
                        "nekoray://", "socks4://", "socks5://", "socks://", "naive+"
                    ]):
                        code = re.sub(htmltag_pattern, '', line)
                        codes.append(code)
                        valid_channels.add(channel)
                        found_code = True
        if not found_code:
            invalid_channels.add(channel)

def clean_code(code):
    code = requests.utils.unquote(requests.utils.unquote(code))
    code = re.sub(r'amp;|�|%0A|%250A|%0D', '', code)
    code = re.sub(r'fp=(firefox|safari|edge|360|qq|ios|android|randomized|random)', 'fp=chrome', code)
    code = code.strip()
    # 截取协议头
    for proto in ["vmess://", "vless://", "ss://", "trojan://", "tuic://", "hysteria://", "hysteria2://", "hy2://", "juicity://", "nekoray://", "socks4://", "socks5://", "socks://", "naive+"]:
        if proto in code:
            code = proto + code.split(proto, 1)[1]
            break
    # 去除结尾异常字符
    code = code.rstrip('…»%`')
    return code

def remove_duplicate_nodes(node_list):
    """删除重复节点，保留唯一节点"""
    seen = set()
    unique_nodes = []
    for node in node_list:
        if node not in seen:
            unique_nodes.append(node)
            seen.add(node)
    return unique_nodes

def fetch_and_test_subscribe_links(channels, max_pages=3, sleep_sec=1.0, out_file="data/t.txt"):
    pattern = r"https?://[^\s'\"<>]*api/v1/client/subscribe\?token=[\w\-]+"
    urls = set()
    for channel in channels:
        base_url = f"https://t.me/s/{channel}"
        last_id = None
        for _ in range(max_pages):
            url = base_url if last_id is None else f"{base_url}?before={last_id}"
            try:
                resp = requests.get(url, timeout=10)
            except Exception:
                time.sleep(sleep_sec)
                continue
            resp.encoding = resp.apparent_encoding
            html = resp.text
            found = re.findall(pattern, html)
            urls.update(found)
            ids = re.findall(r'data-post="[^/]+/(\d+)"', html)
            if not ids:
                break
            min_id = min(map(int, ids))
            if last_id == min_id:
                break
            last_id = min_id
            time.sleep(sleep_sec)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for url in sorted(urls):
            f.write(url + "\n")
    print(f"\n共找到{len(urls)}个订阅链接，已保存到{out_file}")
    return sorted(urls)

def test_urls(urls, timeout=10):
    ok, fail = [], []
    for url in urls:
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                ok.append(url)
            else:
                fail.append(url)
        except Exception:
            fail.append(url)
    print(f"可用: {len(ok)}，不可用: {len(fail)}")
    if fail:
        print("不可用URL：")
        for u in fail:
            print(u)
    return ok, fail

def main():
    # 加载数据
    tg_channels = set(load_json('telegramchannels.json'))
    invalid_channels = set(load_json('invalidtelegramchannels.json'))
    config_lines = []
    if os.path.exists('configtg.txt'):
        with open('configtg.txt', 'r', encoding='utf-8') as f:
            config_lines = f.readlines()

    # 使用环境变量或默认值，避免 input() 导致 EOFError
    thrd_pars = int(os.getenv('THRD_PARS', '10'))
    pars_dp = int(os.getenv('PARS_DP', '1'))
    print(f'\nTotal channel names in telegramchannels.json         - {len(tg_channels)}')
    print(f'Total channel names in invalidtelegramchannels.json - {len(invalid_channels)}')
    use_inv = os.getenv('USE_INV_TC', 'n').lower() == 'y'

    start_time = datetime.now()

    # 合并无效频道
    if use_inv:
        tg_channels |= invalid_channels
        invalid_channels.clear()

    # 从configtg.txt中提取tg频道名
    print(f'Try get new tg channels name from proxy configs in configtg.txt...')
    tg_names_from_config = extract_tg_names_from_config(config_lines)
    tg_channels |= tg_names_from_config
    tg_channels = {x for x in tg_channels if len(x) >= 5}
    print(f'Found tg channel names - {len(tg_names_from_config)}')
    print(f'Total old names        - {len(tg_channels)}')

    save_json('telegramchannels.json', sorted(tg_channels))

    print(f'\nSearch for new names is over - {str(datetime.now() - start_time).split(".")[0]}')
    print(f'\nStart Parsing...\n')

    # 多线程爬取频道
    sem = threading.Semaphore(thrd_pars)
    codes = []
    valid_channels = set()
    invalid_channels_new = set()
    htmltag_pattern = re.compile(r'<.*?>')
    threads = []
    for idx, channel in enumerate(sorted(tg_channels)):
        t = threading.Thread(target=parse_channel, args=(channel, pars_dp, codes, valid_channels, invalid_channels_new, sem, htmltag_pattern))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    print(f'\nParsing completed - {str(datetime.now() - start_time).split(".")[0]}')
    print(f'\nStart check and remove duplicate from parsed configs...')

    # 清洗、去重
    cleaned_codes = [clean_code(code) for code in codes if len(code) > 13]
    cleaned_codes = [c for c in cleaned_codes if ("…" in c and "#" in c) or ("…" not in c)]
    # 节点去重
    cleaned_codes = remove_duplicate_nodes(cleaned_codes)
    cleaned_codes = sorted(cleaned_codes)

    print(f'\nDelete tg channels that not contains proxy configs...')
    valid_channels = sorted(valid_channels)
    invalid_channels = sorted(invalid_channels_new | invalid_channels)

    print(f'\nRemaining tg channels after deletion - {len(valid_channels)}')
    print(f'\nSave new telegramchannels.json, invalidtelegramchannels.json and configtg.txt...')

    save_json('telegramchannels.json', valid_channels)
    save_json('invalidtelegramchannels.json', invalid_channels)
    with open("configtg.txt", "w", encoding="utf-8") as f:
        for code in cleaned_codes:
            f.write(code + "\n")

    print(f'\nTime spent - {str(datetime.now() - start_time).split(".")[0]}')

    # 抓取订阅链接并测试
    subscribe_urls = fetch_and_test_subscribe_links(valid_channels, max_pages=3)
    test_urls(subscribe_urls)

    # input('\nPress Enter to finish ...')  # 注释掉，避免无交互环境卡死

if __name__ == "__main__":
    main()
