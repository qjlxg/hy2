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
    for proto in ["vmess://", "vless://", "ss://", "trojan://", "tuic://", "hysteria://", "hysteria2://", "hy2://", "juicity://", "nekoray://", "socks4://", "socks5://", "socks://", "naive+"]:
        if proto in code:
            code = proto + code.split(proto, 1)[1]
            break
    code = code.rstrip('…»%`')
    return code

def remove_duplicate_nodes(node_list):
    seen = set()
    unique_nodes = []
    for node in node_list:
        if node not in seen:
            unique_nodes.append(node)
            seen.add(node)
    return unique_nodes

def fetch_subscribe_links(channels, max_pages=3, sleep_sec=1.0, out_file="data/t.txt"):
    pattern = r"https?://[^\s'\"<>]*api/v1/client/subscribe\?token=[\w\-]+"
    urls = set()
    for channel in channels:
        base_url = f"https://t.me/s/{channel}"
        last_id = None
        for _ in range(max_pages):
            url = base_url if last_id is None else f"{base_url}?before={last_id}"
            resp = requests.get(url)
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
    print(f"共找到{len(urls)}个订阅链接，已保存到{out_file}")
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
    tg_name_json = load_json('telegramchannels.json')
    inv_tg_name_json = load_json('invalidtelegramchannels.json')
    inv_tg_name_json = [x for x in inv_tg_name_json if len(x) >= 5]
    inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))

    thrd_pars = int(os.getenv('THRD_PARS', '128'))
    pars_dp = int(os.getenv('PARS_DP', '1'))
    use_inv_tc = os.getenv('USE_INV_TC', 'n').lower() == 'y'

    print(f'\nTotal channel names in telegramchannels.json         - {len(tg_name_json)}')
    print(f'Total channel names in invalidtelegramchannels.json - {len(inv_tg_name_json)}')

    start_time = datetime.now()
    sem_pars = threading.Semaphore(thrd_pars)

    print(f'Try get new tg channels name from proxy configs in configtg.txt...')
    with open("configtg.txt", "r", encoding="utf-8") as config_all_file:
        config_all = config_all_file.readlines()

    tg_name = list(extract_tg_names_from_config(config_all))
    tg_name = [x for x in tg_name if len(x) >= 5]
    tg_name_json = [x for x in tg_name_json if len(x) >= 5]
    print(f'\nFound tg channel names - {len(tg_name)}')
    print(f'Total old names        - {len(tg_name_json)}')
    tg_name_json = sorted(list(set(tg_name_json + tg_name)))
    print(f'In the end, new names  - {len(tg_name_json)}')

    save_json('telegramchannels.json', tg_name_json)
    print(f'\nSearch for new names is over - {str(datetime.now() - start_time).split(".")[0]}')
    print(f'\nStart Parsing...\n')

    codes = []
    new_tg_name_json = []
    htmltag_pattern = re.compile(r'<.*?>')
    walen = len(tg_name_json)

    def process(i_url):
        sem_pars.acquire()
        html_pages = []
        cur_url = i_url
        god_tg_name = False
        for itter in range(1, pars_dp + 1):
            while True:
                try:
                    response = requests.get(f'https://t.me/s/{cur_url}')
                except:
                    time.sleep(random.randint(5, 25))
                    continue
                else:
                    if itter == pars_dp:
                        print(f'{tg_name_json.index(i_url) + 1} of {walen} - {i_url}')
                    html_pages.append(response.text)
                    last_datbef = re.findall(r'data-before="(\d*)"', response.text)
                    break
            if not last_datbef:
                break
            cur_url = f'{i_url}?before={last_datbef[0]}'
        for page in html_pages:
            soup = BeautifulSoup(page, 'html.parser')
            code_tags = soup.find_all(class_='tgme_widget_message_text')
            for code_tag in code_tags:
                code_content2 = str(code_tag).split('<br/>')
                for code_content in code_content2:
                    if any(proto in code_content for proto in [
                        "vless://", "ss://", "vmess://", "trojan://", "tuic://",
                        "hysteria://", "hy2://", "hysteria2://", "juicity://",
                        "nekoray://", "socks4://", "socks5://", "socks://", "naive+"
                    ]):
                        codes.append(re.sub(htmltag_pattern, '', code_content))
                        new_tg_name_json.append(i_url)
                        god_tg_name = True
        if not god_tg_name:
            inv_tg_name_json.append(i_url)
        sem_pars.release()

    threads = []
    for url in tg_name_json:
        t = threading.Thread(target=process, args=(url,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    print(f'\nParsing completed - {str(datetime.now() - start_time).split(".")[0]}')
    print(f'\nStart check and remove duplicate from parsed configs...')

    codes = list(set(codes))
    processed_codes = []
    for part in codes:
        part = clean_code(part)
        if "vmess://" in part:
            processed_codes.append(part.strip())
        elif "vless://" in part and "@" in part and ":" in part[8:]:
            processed_codes.append(part.strip())
        elif "ss://" in part:
            processed_codes.append(part.strip())
        elif "trojan://" in part and "@" in part and ":" in part[9:]:
            processed_codes.append(part.strip())
        elif "tuic://" in part and ":" in part[7:] and "@" in part:
            processed_codes.append(part.strip())
        elif "hysteria://" in part and ":" in part[11:] and "=" in part:
            processed_codes.append(part.strip())
        elif "hysteria2://" in part and "@" in part and ":" in part[12:]:
            processed_codes.append(part.strip())
        elif "hy2://" in part and "@" in part and ":" in part[6:]:
            processed_codes.append(part.strip())
        elif "juicity://" in part:
            processed_codes.append(part.strip())
        elif "nekoray://" in part:
            processed_codes.append(part.strip())
        elif "socks4://" in part and ":" in part[9:]:
            processed_codes.append(part.strip())
        elif "socks5://" in part and ":" in part[9:]:
            processed_codes.append(part.strip())
        elif "socks://" in part and ":" in part[8:]:
            processed_codes.append(part.strip())
        elif "naive+" in part and ":" in part[13:] and "@" in part:
            processed_codes.append(part.strip())

    print(f'\nTrying to delete corrupted configurations...')
    processed_codes = list(set(processed_codes))
    processed_codes = [x for x in processed_codes if (len(x) > 13) and (("…" in x and "#" in x) or ("…" not in x))]
    new_processed_codes = []
    for x in processed_codes:
        x = x.rstrip('…»%`')
        new_processed_codes.append(x.strip())
    processed_codes = sorted(set(new_processed_codes))

    processed_codes = remove_duplicate_nodes(processed_codes)

    print(f'\nDelete tg channels that not contains proxy configs...')
    new_tg_name_json = sorted(set(new_tg_name_json))
    print(f'\nRemaining tg channels after deletion - {len(new_tg_name_json)}')
    inv_tg_name_json = sorted(set(inv_tg_name_json))

    print(f'\nSave new telegramchannels.json, invalidtelegramchannels.json and configtg.txt...')
    save_json('telegramchannels.json', new_tg_name_json)
    save_json('invalidtelegramchannels.json', inv_tg_name_json)
    with open("configtg.txt", "w", encoding="utf-8") as file:
        for code in processed_codes:
            file.write(code + "\n")

    print(f'\nTime spent - {str(datetime.now() - start_time).split(".")[0]}')

    # ----------- 新增：抓取订阅链接并测试可用性 -----------
    def fetch_and_test_subscribe_links(channels, max_pages=3, sleep_sec=1.0, out_file="data/t.txt"):
        pattern = r"https?://[^\s'\"<>]*api/v1/client/subscribe\?token=[\w\-]+"
        urls = set()
        for channel in channels:
            base_url = f"https://t.me/s/{channel}"
            last_id = None
            for _ in range(max_pages):
                url = base_url if last_id is None else f"{base_url}?before={last_id}"
                resp = requests.get(url)
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

    # 使用新tg频道名列表抓取并测试
    subscribe_urls = fetch_and_test_subscribe_links(new_tg_name_json, max_pages=3)
    test_urls(subscribe_urls)

    input('\nPress Enter to finish ...')

if __name__ == "__main__":
    main()
