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
os.system('cls' if os.name == 'nt' else 'clear')

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
                resp = requests.get(f'https://t.me/s/{cur_url}', verify=False)
                html = resp.text
                html_pages.append(html)
                last_datbef = re.findall(r'data-before="(\d*)"', html)
                if not last_datbef:
                    break
                cur_url = f'{channel}?before={last_datbef[0]}'
            except Exception:
                time.sleep(random.uniform(5, 25))
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

def main():
    # 加载数据
    tg_channels = set(load_json('telegramchannels.json'))
    invalid_channels = set(load_json('invalidtelegramchannels.json'))
    config_lines = []
    if os.path.exists('configtg.txt'):
        with open('configtg.txt', 'r', encoding='utf-8') as f:
            config_lines = f.readlines()

    # 用户输入
    thrd_pars = int(input('\nThreads for parsing: '))
    pars_dp = int(input('\nParsing depth (1dp = 20 last tg posts): '))
    print(f'\nTotal channel names in telegramchannels.json         - {len(tg_channels)}')
    print(f'Total channel names in invalidtelegramchannels.json - {len(invalid_channels)}')
    use_inv = input('\nTry looking for proxy configs from "invalidtelegramchannels.json" too? (Enter y/n): ').lower() == 'y'

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
    cleaned_codes = {clean_code(code) for code in codes if len(code) > 13}
    cleaned_codes = {c for c in cleaned_codes if ("…" in c and "#" in c) or ("…" not in c)}
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
    input('\nPress Enter to finish ...')

if __name__ == "__main__":
    main()
