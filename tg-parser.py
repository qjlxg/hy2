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

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
os.system('cls' if os.name == 'nt' else 'clear')

if not os.path.exists('configtg.txt'):
    with open('configtg.txt', 'w', encoding="utf-8") as f:
        pass

def json_load(path):
    with open(path, 'r', encoding="utf-8") as file:
        list_content = json.load(file)
    return list_content

def substring_del(string_list):
    string_list.sort(key=lambda s: len(s), reverse=True)
    out = []
    for s in string_list:
        if not any([s in o for o in out]):
            out.append(s)
    return out

def normalize_config(config):
    config = config.strip()
    for protocol in ["vmess://", "vless://", "ss://", "trojan://", "tuic://", 
                     "hysteria://", "hysteria2://", "hy2://", "juicity://", 
                     "nekoray://", "socks4://", "socks5://", "socks://", "naive+"]:
        if config.startswith(protocol):
            core = config[len(protocol):]
            if "?" in core:
                core = core.split("?")[0]
            core = core.rstrip("…").rstrip("»").rstrip("%").rstrip("`")
            return f"{protocol}{core}"
    return config

tg_name_json = json_load('telegramchannels.json')
inv_tg_name_json = json_load('invalidtelegramchannels.json')

inv_tg_name_json = [x for x in inv_tg_name_json if len(x) >= 5]
inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))

thrd_pars = int(os.getenv('THRD_PARS', '128'))
pars_dp = int(os.getenv('PARS_DP', '1'))

print(f'\nTotal channel names in telegramchannels.json         - {len(tg_name_json)}')
print(f'Total channel names in invalidtelegramchannels.json - {len(inv_tg_name_json)}')

use_inv_tc = os.getenv('USE_INV_TC', 'n')
use_inv_tc = True if use_inv_tc.lower() == 'y' else False

start_time = datetime.now()

sem_pars = threading.Semaphore(thrd_pars)

config_all = []
tg_name = []
new_tg_name_json = []
codes = set()

print(f'Try get new tg channels name from proxy configs in configtg.txt...')
with open("configtg.txt", "r", encoding="utf-8") as config_all_file:
    config_all = config_all_file.readlines()

pattern_telegram_user = r'(?:@)(\w{5,})|(?:%40)(\w{5,})|(?:t\.me\/)(\w{5,})'
for config in config_all:
    if config.startswith('vmess://'):
        try:
            config = base64.b64decode(config[8:]).decode("utf-8")
        except:
            pass
    if config.startswith('ssr://'):
        try:
            config = base64.b64decode(config[6:]).decode("utf-8")
        except:
            pass
    matches_usersname = re.findall(pattern_telegram_user, config, re.IGNORECASE)
    try:
        matches_usersname.extend(re.findall(pattern_telegram_user, base64.b64decode(config).decode("utf-8"), re.IGNORECASE))
    except:
        pass
    for match in matches_usersname:
        for element in match:
            if element:
                tg_name.append(element.lower().encode('ascii', 'ignore').decode())

tg_name = [x for x in tg_name if len(x) >= 5]
tg_name_json = [x for x in tg_name_json if len(x) >= 5]
tg_name = list(set(tg_name))
print(f'\nFound tg channel names - {len(tg_name)}')
print(f'Total old names        - {len(tg_name_json)}')
tg_name_json.extend(tg_name)
tg_name_json = list(set(tg_name_json))
tg_name_json = sorted(tg_name_json)
print(f'In the end, new names  - {len(tg_name_json)}')

with open('telegramchannels.json', 'w', encoding="utf-8") as telegram_channels_file:
    json.dump(tg_name_json, telegram_channels_file, indent=4)

print(f'\nSearch for new names is over - {str(datetime.now() - start_time).split(".")[0]}')

pattern_datbef = re.compile(r'(?:data-before=")(\d*)')
htmltag_pattern = re.compile(r'<.*?>')

def process(i_url):
    sem_pars.acquire()
    html_pages = []
    cur_url = i_url
    god_tg_name = False
    for itter in range(1, pars_dp + 1):
        while True:
            try:
                response = requests.get(f'https://t.me/s/{cur_url}', verify=False)
            except:
                time.sleep(random.randint(5, 25))
                continue
            else:
                if itter == pars_dp:
                    print(f'{tg_name_json.index(i_url) + 1} of {len(tg_name_json)} - {i_url}')
                html_pages.append(response.text)
                last_datbef = re.findall(pattern_datbef, response.text)
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
                if any(p in code_content for p in ["vless://", "ss://", "vmess://", "trojan://", 
                                                   "tuic://", "hysteria://", "hysteria2://", 
                                                   "hy2://", "juicity://", "nekoray://", 
                                                   "socks4://", "socks5://", "socks://", "naive+"]):
                    normalized_code = normalize_config(re.sub(htmltag_pattern, '', code_content))
                    codes.add(normalized_code)
                    new_tg_name_json.append(i_url)
                    god_tg_name = True
    if not god_tg_name:
        inv_tg_name_json.append(i_url)
    sem_pars.release()

print(f'\nStart Parsing...\n')
for url in tg_name_json:
    threading.Thread(target=process, args=(url,)).start()

while threading.active_count() > 1:
    time.sleep(1)

print(f'\nParsing completed - {str(datetime.now() - start_time).split(".")[0]}')

print(f'\nStart check and remove duplicate from parsed configs...')
processed_codes = set()
for part in codes:
    part = re.sub('%0A', '', part)
    part = re.sub('%250A', '', part)
    part = re.sub('%0D', '', part)
    part = requests.utils.unquote(requests.utils.unquote(part)).strip()
    part = re.sub('amp;', '', part)
    part = re.sub('�', '', part)
    part = re.sub(r'fp=(firefox|safari|edge|360|qq|ios|android|randomized|random)', 'fp=chrome', part)
    
    normalized_part = normalize_config(part)
    if any(p in normalized_part for p in ["vmess://", "vless://", "ss://", "trojan://", 
                                          "tuic://", "hysteria://", "hysteria2://", 
                                          "hy2://", "juicity://", "nekoray://", 
                                          "socks4://", "socks5://", "socks://", "naive+"]):
        processed_codes.add(normalized_part)

print(f'\nTrying to delete corrupted configurations...')
processed_codes = list(processed_codes)
processed_codes = [x for x in processed_codes if len(x) > 13 and ("…" in x and "#" in x) or "…" not in x]

new_processed_codes = []
for x in processed_codes:
    if x.endswith('…»'):
        x = x[:-2]
    elif x.endswith('…') or x.endswith('»') or x.endswith('%') or x.endswith('`'):
        x = x[:-1]
    elif x[-2:] == '%':
        x = x[:-2]
    new_processed_codes.append(x.strip())

processed_codes = sorted(list(set(new_processed_codes)))

print(f'\nRemaining tg channels after deletion - {len(set(new_tg_name_json))}')

new_tg_name_json = sorted(list(set(new_tg_name_json)))
inv_tg_name_json = sorted(list(set(inv_tg_name_json)))

print(f'\nSave new telegramchannels.json, invalidtelegramchannels.json and configtg.txt...')

with open('telegramchannels.json', 'w', encoding="utf-8") as telegram_channels_file:
    json.dump(new_tg_name_json, telegram_channels_file, indent=4)

with open('invalidtelegramchannels.json', 'w', encoding="utf-8") as inv_telegram_channels_file:
    json.dump(inv_tg_name_json, inv_telegram_channels_file, indent=4)

with open("configtg.txt", "w", encoding="utf-8") as file:
    for code in processed_codes:
        file.write(code + "\n")

print(f'\nTime spent - {str(datetime.now() - start_time).split(".")[0]}')
