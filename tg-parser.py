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
import urllib3
import logging

# 禁用 requests 的 SSL 验证警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 是否在本地运行
LOCAL_RUN = True  # 如果在本地运行，设置为 True，否则设置为 False

os.system('cls' if os.name == 'nt' else 'clear')

if not os.path.exists('config-tg.txt'):
    with open('config-tg.txt', 'w'):
        pass


def json_load(path):
    try:
        with open(path, 'r', encoding="utf-8") as file:
            list_content = json.load(file)
            return list_content
    except FileNotFoundError:
        logging.error(f"文件未找到: {path}")
        return []
    except json.JSONDecodeError:
        logging.error(f"JSON 解析错误: {path}")
        return []


def substring_del(string_list):
    list1 = list(string_list)
    list2 = list(string_list)
    list1.sort(key=lambda s: len(s), reverse=False)
    list2.sort(key=lambda s: len(s), reverse=True)
    out = list()
    for s1 in list1:
        for s2 in list2:
            if s1 in s2 and len(s1) < len(s2):
                out.append(s1)
                break
            if len(s1) >= len(s2):
                break
    out = list(set(string_list) - set(out))
    return out


# 从 JSON 文件加载 Telegram 频道名称
tg_name_json = json_load('telegram channels.json')
inv_tg_name_json = json_load('invalid telegram channels.json')

inv_tg_name_json[:] = [x for x in inv_tg_name_json if len(x) >= 5]
inv_tg_name_json = list(set(inv_tg_name_json) - set(tg_name_json))

# 设置抓取线程数和深度
if LOCAL_RUN:
    thrd_pars = 2  # 在本地运行时，减少线程数
    pars_dp = 1  # 在本地运行时，减少抓取深度
else:
    thrd_pars = int(input('\nThreads for parsing: '))
    pars_dp = int(input('\nParsing depth (1dp = 20 last tg posts): '))

print(f'\nTotal channel names in telegram channels.json         - {len(tg_name_json)}')
print(f'Total channel names in invalid telegram channels.json - {len(inv_tg_name_json)}')

while (use_inv_tc := input(
        '\nTry looking for proxy configs from "invalid telegram channels.json" too? (Enter y/n): ').lower()) not in {"y",
                                                                                                                     "n"}:
    pass
print()

start_time = datetime.now()

if use_inv_tc == 'y':
    tg_name_json.extend(inv_tg_name_json)
    inv_tg_name_json.clear()
    tg_name_json = list(set(tg_name_json))
    tg_name_json = sorted(tg_name_json)

sem_pars = threading.Semaphore(thrd_pars)

config_all = list()
tg_name = list()
new_tg_name_json = list()

print(f'Try get new tg channels name from proxy configs in config-tg.txt...')

try:
    with open("config-tg.txt", "r", encoding="utf-8") as config_all_file:
        config_all = config_all_file.readlines()
except FileNotFoundError:
    logging.error("config-tg.txt 文件未找到")
    config_all = []

pattern_telegram_user = r'(?:@)(\w{5,})|(?:%40)(\w{5,})|(?:t\.me\/)(\w{5,})|(?:t\.me%2F)(\w{5,})|(?:t\.me-)(\w{5,})'
pattern_datbef = re.compile(r'(?:data-before=")(\d*)')

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
        matches_usersname = re.findall(pattern_telegram_user, base64.b64decode(config).decode("utf-8"),
                                        re.IGNORECASE)
    except:
        pass

    for index, element in enumerate(matches_usersname):
        if element[0] != '':
            tg_name.append(element[0].lower().encode('ascii', 'ignore').decode())
        if element[1] != '':
            tg_name.append(element[1].lower().encode('ascii', 'ignore').decode())
        if element[2] != '':
            tg_name.append(element[2].lower().encode('ascii', 'ignore').decode())
        if element[3] != '':
            tg_name.append(element[3].lower().encode('ascii', 'ignore').decode())
        if element[4] != '':
            tg_name.append(element[4].lower().encode('ascii', 'ignore').decode())

tg_name[:] = [x for x in tg_name if len(x) >= 5]
tg_name_json[:] = [x for x in tg_name_json if len(x) >= 5]
tg_name = list(set(tg_name))
print(f'\nFound tg channel names - {len(tg_name)}')
print(f'Total old names        - {len(tg_name_json)}')
tg_name_json.extend(tg_name)
tg_name_json = list(set(tg_name_json))
tg_name_json = sorted(tg_name_json)
print(f'In the end, new names  - {len(tg_name_json)}')

with open('telegram channels.json', 'w', encoding="utf-8") as telegram_channels_file:
    json.dump(tg_name_json, telegram_channels_file, indent=4)

print(f'\nSearch for new names is over - {str(datetime.now() - start_time).split(".")[0]}')

print(f'\nStart Parsing...\n')

def extract_urls(html_content):
    """从 HTML 内容中提取 URL。"""
    urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
                       html_content)
    return urls


def process(i_url):
    sem_pars.acquire()
    html_pages = list()
    cur_url = i_url
    god_tg_name = False
    extracted_urls = []  # 用于存储提取到的 URL
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for itter in range(1, pars_dp + 1):
        while True:
            try:
                response = requests.get(f'https://t.me/s/{cur_url}', headers=headers, verify=False, timeout=10)
                response.raise_for_status()  # 检查请求是否成功
            except requests.exceptions.RequestException as e:
                logging.warning(f"请求 {cur_url} 失败: {e}")
                time.sleep(random.randint(5, 25))
                continue # 循环重试
            else:
                if itter == pars_dp:
                    print(f'{tg_name_json.index(i_url) + 1} of {walen} - {i_url}')
                html_pages.append(response.text)
                last_datbef = re.findall(pattern_datbef, response.text)
                break

        if not last_datbef:
            break
        cur_url = f'{i_url}?before={last_datbef[0]}'

    for page in html_pages:
        soup = BeautifulSoup(page, 'html.parser')
        text_elements = soup.find_all(class_='tgme_widget_message_text')  # 选择包含文本的元素
        for element in text_elements:
            text_content = element.get_text()  # 获取文本内容
            urls = extract_urls(text_content)  # 提取文本中的 URL
            extracted_urls.extend(urls)  # 添加到 URL 列表中
            if urls:
                god_tg_name = True # 只要提取到一个 URL, 就认为是有效的频道.

    if not god_tg_name:
        inv_tg_name_json.append(i_url)
    sem_pars.release()
    return extracted_urls  # 返回提取到的 URL


htmltag_pattern = re.compile(r'<.*?>')

codes = list()

all_urls = []  # 存储所有提取到的 URL

walen = len(tg_name_json)

threads = []
for url in tg_name_json:
    thread = threading.Thread(target=lambda u: all_urls.extend(process(u)), args=(url,))
    threads.append(thread)
    thread.start()

for thread in threads:
    thread.join()  # 等待所有线程完成

while threading.active_count() > 1:
    time.sleep(1)

print(f'\nParsing completed - {str(datetime.now() - start_time).split(".")[0]}')

print(f'\nStart check and remove duplicate from parsed configs...')

# 后处理 proxies 的代码,  为了简化，先注释掉，专注于提取 URL
#codes = list(set(codes))
# ...  (省略，如需要，可取消注释)

print(f'\nDelete tg channels that not contains proxy configs...')
new_tg_name_json = list(set(new_tg_name_json))
new_tg_name_json = sorted(new_tg_name_json)
print(f'\nRemaining tg channels after deletion - {len(new_tg_name_json)}')

inv_tg_name_json = list(set(inv_tg_name_json))
inv_tg_name_json = sorted(inv_tg_name_json)

print(f'\nSave new telegram channels.json, invalid telegram channels.json and config-tg.txt...')
with open('telegram channels.json', 'w', encoding="utf-8") as telegram_channels_file:
    json.dump(new_tg_name_json, telegram_channels_file, indent=4)

with open('invalid telegram channels.json', 'w', encoding="utf-8") as inv_telegram_channels_file:
    json.dump(inv_tg_name_json, inv_telegram_channels_file, indent=4)

#with open("config-tg.txt", "w", encoding="utf-8") as file:
#    for code in processed_codes:
#        file.write(code.encode("utf-8").decode("utf-8") + "\n")

# 去重 URL
all_urls = list(set(all_urls))

# 保存所有提取到的 URL 到文件
output_file = "all_urls.txt"
with open(output_file, "w", encoding="utf-8") as f:
    for url in all_urls:
        f.write(url + "\n")

print(f"\n所有提取到的 URL 已保存到 {output_file}")
print(f'\nTime spent - {str(datetime.now() - start_time).split(".")[0]}')
input('\nPress Enter to finish ...')
