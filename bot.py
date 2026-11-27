import os
import asyncio
import logging
import requests
import sqlite3
import html
import re
import pandas as pd
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from bs4 import BeautifulSoup
from aiohttp import web
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openpyxl.styles import Font, PatternFill, Alignment
from telethon.errors import FloodWaitError
from aiogram.utils.exceptions import MessageNotModified
from contextlib import suppress
from curl_cffi import requests as crequests
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
API_ID = 23009673
API_HASH = '249328ef42a91e5c80102c3d73c76a9c'
SESSION_STR = os.getenv('TELEGRAM_SESSION')
SJ_KEY = os.getenv('SUPERJOB_KEY') # Твой новый ключ
HH_TOKEN = os.getenv('HH_TOKEN')
SCRAPER_KEY = os.getenv('SCRAPER_API_KEY')
# Список каналов БЕЗ собаки @
CHANNELS = [
    'vdhl_good', 'mediajobs_ru', 'work_in_media', 'distantsiya',
    'theblueprintcareer', 'huggabletalents', 'careerspace', 'morejobs', 'heyanie', 
    'marketing_jobs', 'mirkreatorovjob', 'budujobs', 'normrabota', 'jobpower', 
    'it_vakansii_jobs', 'workasap', 'forproducer', 'vacanciesrus', 
    'honeyiwantmoney', 'evacuatejobs', 'workinart', 'young_relocate', 'iRecommendWork_IT',
    'Inwork', 'cliquejobs', 'fashionfaculty', 'forallmedia', 'vitrinajobs',
    'dnative_job', 'Young_and_Yandex', 'digital_rabota', 'jobforpr', 'megafonjobs',
    'cozy_hr', 'rassvet_pro', 'young_june', 'mtsfintechjobs', 'digital_hr',
    'zdemcv', 'foranalysts', 'hcareers_jobs', 'product_jobs', 'edujobs',
    'talentswanted', 'forchiefs', 'rabota_marketing_juniors', 'tj_collega', 'remotegeekjob',
    'forallmarketing', 'hsecareer', 'dddwork', 'ya_jobs_pm', 'forproducts',
    'practicum_experts', 'zloy_kollega', 'jobforjunior', 'vacantcist', 'avito_career',
    'workasap', 'mirkreatorovjob', 'careerspace', 'huggabletalents', 'theblueprintcareer',
    'heyanie', 'marketing_jobs', 'it_vakansii_jobs'
]
EDU_CHANNELS = [
    # Школы
    'kurslivorg', 'yandex_academy', 'netology_ru', 'skillbox_ru', 
    'skillfactory_ru', 'hexclet_ru', 'loftblog', 
    'stepik_courses', 'free_edu_ru', 'it_shpora',
    # Нейросети и ИИ
    'neuralshit', 'ai_machinelearning_big_data', 'neuro_sh', 
    'promtolog', 'deepfaker', 'textmachine', 'gpt_ru', 'vokrug_ai',
    'igorkrestov', 'ai_for_work', 'neuro_art',
    # Медиа, Дизайн и Видео
    'designers_ru', 'aftereffects_ru', 'premierepro_ru', 
    'fotoforge', 'video_shkola', 'motiongraphics_ru',
    # IT и Разработка
    'proglib', 'habr_com', 'tproger', 'python2day', 'javaproglib'
]

# Создаем клиента для чтения каналов
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)


bot = Bot(token=TOKEN)
# Включаем оперативную память для бота
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Создаем состояния (режимы)
class SearchMode(StatesGroup):
    course = State() # Включен режим курсов
    youtube = State() # Включен режим поиска YouTube-каналов

# Создаем постоянное меню с кнопками
def get_main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(KeyboardButton("💼 Искать работу"), KeyboardButton("🎓 Искать курсы"))
    kb.add(KeyboardButton("🎬 YouTube-каналы"), KeyboardButton("🔔 Мои подписки"))
    return kb
logging.basicConfig(level=logging.INFO)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1'
}

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('manager.db')
    conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE IF NOT EXISTS subs (user_id INTEGER, keyword TEXT, UNIQUE(user_id, keyword))')
    conn.execute('CREATE TABLE IF NOT EXISTS yt_channels (channel_id TEXT PRIMARY KEY)')
    conn.commit()
    conn.close()

def is_new_yt_channel(channel_id):
    conn = sqlite3.connect('manager.db', timeout=20)
    conn.execute('CREATE TABLE IF NOT EXISTS yt_channels (channel_id TEXT PRIMARY KEY)')
    res = conn.execute('SELECT 1 FROM yt_channels WHERE channel_id = ?', (channel_id,)).fetchone()
    if not res:
        conn.execute('INSERT INTO yt_channels VALUES (?)', (channel_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def add_subscription(user_id, keyword):
    conn = sqlite3.connect('manager.db')
    conn.execute('INSERT OR IGNORE INTO subs (user_id, keyword) VALUES (?, ?)', (user_id, keyword.lower()))
    conn.commit()
    conn.close()

def get_all_subs():
    conn = sqlite3.connect('manager.db')
    data = conn.execute('SELECT user_id, keyword FROM subs').fetchall()
    conn.close()
    return data

def is_new_job(job_id):
    conn = sqlite3.connect('manager.db')
    res = conn.execute('SELECT 1 FROM jobs WHERE id = ?', (job_id,)).fetchone()
    if not res:
        conn.execute('INSERT INTO jobs VALUES (?)', (job_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# --- ПАРСЕРЫ ---
async def search_telegram_history(query, limit_per_channel=2, target_channels=None):
    if not client.is_connected(): 
        await client.start()
        
    results = []
    seen_texts = set()
    date_limit = datetime.now() - timedelta(days=14)
    query_low = query.lower().replace('ё', 'е')

    # Если мы не передали спец. каналы, берем дефолтные 30 из главного списка
    channels_to_search = target_channels if target_channels else CHANNELS[:30]

    for channel in channels_to_search:
        try:
            async for msg in client.iter_messages(channel, search=query, limit=limit_per_channel):
                if not msg.text or len(msg.text) < 100: continue
                if msg.date.replace(tzinfo=None) < date_limit: continue

                text_id = msg.text[:100].lower().replace('ё', 'е').strip()
                if text_id in seen_texts: continue
                seen_texts.add(text_id)

                pay = "См. в посте"
                salary_found = re.search(r'(\d[\d\s\.]*)\s?(руб|р\.|₽|\$|€|usd|eur|к|k)', msg.text.lower())
                if salary_found:
                    pay = salary_found.group(0).strip()

                desc = msg.text[:200].replace('\n', ' ').replace('*', '').replace('_', '').strip()
                display_text = msg.text[:400].replace('*', '').replace('_', '').strip()
                
                results.append({
                    'id': f"tg_{channel}_{msg.id}",
                    'text': f"📱 TG [{channel}]: {display_text}...\n\n💰 Зарплата: {pay}\nhttps://t.me/{channel}/{msg.id}",
                    'Дата': msg.date.strftime('%Y-%m-%d'),
                    'Источник': f'TG: {channel}',
                    'Вакансия': query.capitalize(),
                    'Компания': channel,
                    'Оплата': pay,
                    'Ссылка': f"https://t.me/{channel}/{msg.id}",
                    'Описание': desc
                })
            
            await asyncio.sleep(0.3) 
        except Exception as e:
            logging.error(f"Ошибка канала {channel}: {e}")
            continue
    return results

def search_trudvsem(query, limit=50):
    # Официальный API "Работа России" (Москва)
    url = f"https://opendata.trudvsem.ru/api/v1/vacancies/region/77?text={query}&limit={limit}"
    results = []
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200: return []
        
        data = r.json()
        # Трудвсем отдает вложенный список
        vacancies = data.get('results', {}).get('vacancies', [])
        
        for item in vacancies:
            v = item.get('vacancy', {})
            
            # Чистим требования от HTML мусора
            raw_req = v.get('requirement', 'Описание доступно по ссылке')
            clean_req = re.sub(r'<[^>]*>', '', str(raw_req)).replace('&quot;', '"').strip()

            results.append({
                'id': f"trud_{v.get('id')}",
                'Дата': v.get('creation-date', '')[:10],
                'Источник': 'Trud', 
                'Вакансия': v.get('job-name', '—'), 
                'Компания': v.get('company', {}).get('name', '—'), 
                'Оплата': v.get('salary', 'Договорная'), 
                'Ссылка': v.get('vac_url', '#'),
                'Описание': clean_req[:250]
            })
            
        logging.info(f"TrudVsem: Найдено {len(results)} вакансий")
    except Exception as e:
        logging.error(f"TrudVsem error: {e}")
    
    return results

def search_hh(query, limit=50):
    # Пытаемся взять из системы, если нет - подставляем твой ключ напрямую
    scraper_key = os.getenv('SCRAPER_API_KEY', '2589882df539e22324ece67efd265e7a')
    
    target_url = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page={limit}"
    proxy_url = f"http://api.scraperapi.com?api_key={scraper_key}&url={target_url}"
    
    results = []
    try:
        # ТАЙМАУТ 30 СЕКУНД - это критично для прокси!
        r = requests.get(proxy_url, timeout=30)
        
        if r.status_code == 401:
            logging.error("ScraperAPI: Ошибка ключа (401). Проверь подписку или лимиты.")
            return []

        if r.status_code != 200:
            logging.error(f"ScraperAPI HH Fail: {r.status_code}")
            return []

        data = r.json()
        for v in data.get('items', []):
            sal = v.get('salary')
            pay = f"от {sal['from']}" if sal and sal.get('from') else "Договорная"
            results.append({
                'id': f"hh_{v['id']}",
                'Дата': v.get('published_at', '')[:10],
                'Источник': 'HH', 'Вакансия': v['name'], 
                'Компания': v.get('employer', {}).get('name', '—'), 
                'Оплата': pay, 'Ссылка': v['alternate_url']
            })
    except Exception as e:
        logging.error(f"HH error: {e}")
    return results
    
def search_superjob(query, limit=50):
    if not SJ_KEY: return []
    url = f"https://api.superjob.ru/2.0/vacancies/?keyword={query}&town=4&count={limit}"
    headers = {'X-Api-App-Id': SJ_KEY}
    results = []
    try:
        r = requests.get(url, headers=headers, timeout=10).json()
        for v in r.get('objects', []):
            # ВНИМАНИЕ: Обязательно вычисляем pay перед использованием!
            p_from = v.get('payment_from')
            p_to = v.get('payment_to')
            if p_from and p_to: pay = f"{p_from}-{p_to}"
            elif p_from: pay = f"от {p_from}"
            else: pay = "Договорная"
                # --- ВСТАВИТЬ ЭТО ---
            # Извлекаем краткое описание (суть) из поля candidat
            desc = (v.get('candidat', '') or "").replace('\n', ' ').strip()
            # --------------------

            results.append({
                'id': f"sj_{v['id']}",
                'text': f"🔵 SJ: {v['profession']}\n💰 {pay} | 📅 {datetime.fromtimestamp(v['date_published']).strftime('%d.%m')}\n{v['link']}",
                'Дата': datetime.fromtimestamp(v['date_published']).strftime('%Y-%m-%d'),
                'Источник': 'SuperJob', 'Вакансия': v['profession'], 'Компания': v['client'].get('title', '—'), 'Оплата': pay, 'Ссылка': v['link'],
                'Описание': desc[:200]
            })
    except Exception as e:
        logging.error(f"SJ error: {e}")
    return results
    
def search_habr(query, limit=20):
    # Москва = 678, тип вакансий = все
    url = f"https://career.habr.com/vacancies?q={query}&city_id=678&type=all"
    results = []
    try:
        # Устанавливаем таймаут чуть больше, Хабр иногда думает
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            logging.error(f"Habr returned status {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        # Основной контейнер вакансий на Хабре
        items = soup.find_all('div', class_='vacancy-card')

        for i in items[:limit]:
            # Ищем заголовок и ссылку
            title_link = i.find('a', class_='vacancy-card__title-link')
            company_link = i.find('a', class_='vacancy-card__company-title') # Ссылка на компанию
            salary_div = i.find('div', class_='basic-salary') # Зарплата

            if title_link:
                title = title_link.text.strip()
                link = "https://career.habr.com" + title_link['href']
                company = company_link.text.strip() if company_link else "Компания не указана"
                pay = salary_div.text.strip() if salary_div else "Договорная"
                # --- ВСТАВИТЬ ЭТО ---
                # Ищем навыки (стек технологий) как суть вакансии
                skills_div = i.find('div', class_='vacancy-card__skills')
                desc = skills_div.text.strip() if skills_div else "Стек технологий доступен по ссылке."
                # --------------------

                # Сохраняем в нашем эталонном формате
                results.append({
                    'id': f"hb_{link.split('/')[-1]}", # Берем ID вакансии из URL
                    'text': f"🟢 Habr: {title}\n💰 {pay} | 📅 Сегодня\n{link}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'), # Хабр пишет "вчера/сегодня", для Excel ставим текущую
                    'Источник': 'Habr',
                    'Вакансия': title,
                    'Компания': company,
                    'Оплата': pay,
                    'Ссылка': link,
                    'Описание': desc
                })

        logging.info(f"Habr: Найдено {len(results)} вакансий")

    except Exception as e:
        logging.error(f"Критическая ошибка Хабр Карьеры: {e}")

    return results

def search_geekjob(query, limit=10):
    # Поиск по разделу Digital/IT
    url = f"https://geekjob.ru/vacancies?q={query.replace(' ', '+')}"
    results = []
    try:
        r = crequests.get(url, headers=HEADERS, impersonate="chrome120", timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Ищем карточки вакансий
        items = soup.find_all('li', class_='vacancy-card')
        
        for i in items[:limit]:
            a = i.find('a', class_='vacancy-name')
            if a:
                title = a.text.strip()
                link = "https://geekjob.ru" + a['href']
                
                # Ищем компанию
                comp_div = i.find('div', class_='company-name')
                company = comp_div.text.strip() if comp_div else "—"
                
                # Ищем зарплату
                pay_span = i.find('span', class_='salary')
                pay = pay_span.text.strip() if pay_span else "Договорная"
                
                # --- НОВОЕ: ИЩЕМ СУТЬ (ОПИСАНИЕ) ---
                # На GeekJob суть обычно в блоке vacancy-description или в тегах
                desc_div = i.find('div', class_='vacancy-description') or i.find('p')
                desc = desc_div.text.strip() if desc_div else "IT-вакансия: подробности стека и задач доступны по ссылке."

                results.append({
                    'id': f"gj_{link.split('/')[-1]}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'GeekJob', 
                    'Вакансия': title, 
                    'Компания': company, 
                    'Оплата': pay, 
                    'Ссылка': link,
                    'Описание': desc[:200] # Наша "суть" для ручного поиска
                })
    except Exception as e:
        logging.error(f"GeekJob error: {e}")
        
    return results

def search_jobfilter(query, limit=5):
    scraper_key = os.getenv('SCRAPER_API_KEY', '2589882df539e22324ece67efd265e7a')
    target_url = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}&city=москва"
    proxy_url = f"http://api.scraperapi.com?api_key={scraper_key}&url={target_url}"
    
    results = []
    try:
        r = requests.get(proxy_url, timeout=30) # Увеличили время ожидания
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', class_='vacancy_item')
        for i in items[:limit]:
            a = i.find('a')
            if a:
                link = "https://jobfilter.ru" + a['href']
                results.append({
                    'id': f"jf_{a['href'][-10:]}",
                    'text': f"🌐 JF: {a.text.strip()}\n{link}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'JobFilter', 'Вакансия': a.text.strip(), 
                    'Компания': '—', 'Оплата': '—', 'Ссылка': link
                })
    except: pass
    return results

def search_stepik(query, limit=5):
    # Убрали is_popular=true, чтобы он не подсовывал рандомный мусор
    search_url = f"https://stepik.org/api/search-results?query={query}&type=course"
    results = []
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10).json()
        search_results = r.get('search-results', [])
        
        if not search_results:
            return []

        course_ids = [str(item['course']) for item in search_results[:limit]]
        courses_url = f"https://stepik.org/api/courses?{'&'.join(['pk=' + c for c in course_ids])}"
        courses_data = requests.get(courses_url, headers=HEADERS, timeout=10).json().get('courses', [])
        
        # Разбиваем запрос юзера на слова для строгой проверки
        query_words = query.lower().split()

        for c in courses_data:
            if not c.get('is_paid'): 
                title = c.get('title', 'Без названия')
                summary = c.get('summary', '').replace('\n', ' ')
                
                # ЖЕСТКИЙ ФИЛЬТР: Проверяем, есть ли суть запроса в названии или описании
                text_to_check = (title + " " + summary).lower()
                
                # Ищем совпадения (хотя бы одно длинное слово из запроса должно быть в курсе)
                is_relevant = False
                for word in query_words:
                    if len(word) > 2 and word in text_to_check:
                        is_relevant = True
                        break
                
                # Если слова из запроса вообще не встречаются в курсе - выкидываем его (мусор)
                if not is_relevant and len(query_words) > 0:
                    continue

                url = f"https://stepik.org/course/{c['id']}"
                results.append({
                    'title': title,
                    'desc': summary[:100],
                    'url': url
                })
    except Exception as e:
        logging.error(f"Stepik error: {e}")
    return results

def translate_to_english(text: str) -> str:
    """Перевод на английский через MyMemory (бесплатно)."""
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": text, "langpair": "ru|en"}
        r = requests.get(url, params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and translated.lower() != text.lower():
                return translated.strip()
    except Exception as e:
        logging.warning(f"Translation error: {e}")
    return text


def search_free_courses(query: str, limit_per_source: int = 8):
    """
    Единый поиск бесплатных курсов:
    - Microsoft Learn
    - Coursera (audit)
    - MIT OpenCourseWare + YouTube
    """
    results = []
    original_query = query.strip()
    query_en = translate_to_english(original_query)
    
    logging.info(f"Free courses search: '{original_query}' → '{query_en}'")

   

    # 2. Coursera (audit)
    try:
        url = "https://api.coursera.org/api/courses.v1"
        params = {
            "q": "search",
            "query": query_en,
            "limit": limit_per_source,
            "fields": "name,slug,description,partnerIds",
            "includes": "partnerIds"
        }
        
        r = requests.get(url, params=params, timeout=20)
        
        if r.status_code == 200:
            data = r.json()
            elements = data.get("elements", [])
            
            partners = {
                p["id"]: p.get("name", "")
                for p in data.get("linked", {}).get("partners.v1", [])
            }
            
            for course in elements:
                name = course.get("name", "Без названия")
                slug = course.get("slug")
                if not slug:
                    continue
                    
                link = f"https://www.coursera.org/learn/{slug}"
                desc = (course.get("description") or "")[:220] or "Описание доступно на странице курса"
                
                partner_ids = course.get("partnerIds", [])
                partner_name = partners.get(str(partner_ids[0]), "Coursera") if partner_ids else "Coursera"
                
                results.append({
                    "id": f"coursera_{course.get('id', slug)}",
                    "Дата": datetime.now().strftime("%Y-%m-%d"),
                    "Источник": "Coursera (audit)",
                    "Вакансия": name,
                    "Компания": partner_name,
                    "Оплата": "Audit (материалы бесплатно)",
                    "Ссылка": link,
                    "Описание": desc,
                    "text": (
                        f"🎓 **Coursera (audit)**\n"
                        f"**{name}**\n"
                        f"🏢 {partner_name}\n\n"
                        f"{desc[:160]}...\n\n"
                        f"🔗 {link}"
                    )
                })
    except Exception as e:
        logging.error(f"Coursera error: {e}")

    # 3. MIT OpenCourseWare + YouTube
    try:
        query_encoded = query_en.replace(" ", "+")
        
        # MIT OCW
        ocw_url = f"https://ocw.mit.edu/search/?q={query_encoded}"
        results.append({
            "id": f"ocw_{hash(query_en)}",
            "Дата": datetime.now().strftime("%Y-%m-%d"),
            "Источник": "MIT OCW",
            "Вакансия": f"MIT OpenCourseWare: {original_query}",
            "Компания": "Massachusetts Institute of Technology",
            "Оплата": "Полностью бесплатно",
            "Ссылка": ocw_url,
            "Описание": "Официальные материалы MIT (лекции, задания, видео).",
            "text": (
                f"🏛️ **MIT OpenCourseWare**\n"
                f"Поиск: «{original_query}»\n\n"
                f"🔗 {ocw_url}"
            )
        })
        
        # YouTube
        yt_variants = [
            (f"{query_en} full course", "Полный курс"),
            (f"{query_en} free course official", "Официальные курсы"),
            (f"{query_en} MIT OpenCourseWare", "MIT на YouTube"),
        ]
        
        for i, (yt_query, label) in enumerate(yt_variants):
            yt_url = f"https://www.youtube.com/results?search_query={yt_query.replace(' ', '+')}"
            results.append({
                "id": f"yt_{hash(query_en)}_{i}",
                "Дата": datetime.now().strftime("%Y-%m-%d"),
                "Источник": "YouTube",
                "Вакансия": f"YouTube: {label}",
                "Компания": "YouTube",
                "Оплата": "Бесплатно",
                "Ссылка": yt_url,
                "Описание": f"Поиск: {label}",
                "text": (
                    f"▶️ **YouTube** — {label}\n"
                    f"Запрос: «{original_query}»\n\n"
                    f"🔗 {yt_url}"
                )
            })
    except Exception as e:
        logging.error(f"OCW/YouTube error: {e}")

    return results

@client.on(events.NewMessage(chats=CHANNELS))
async def telethon_handler(event):
    try:
        # 1. Получаем текст и приводим к нижнему регистру + убираем ё
        text = event.message.message
        if not text: return
        text_for_search = text.lower().replace('ё', 'е')

        # 2. Получаем данные о канале
        chat = await event.get_chat()
        title = getattr(chat, 'title', 'Media Channel')
        username = getattr(chat, 'username', 'channel')

        # 3. Проверяем подписки
        subs = get_all_subs()
        matched_users = []

        for user_id, kw in subs:
            # Сравниваем ключевое слово (тоже без ё) с текстом поста
            if kw.lower().replace('ё', 'е') in text_for_search:
                matched_users.append(user_id)

        if matched_users:
            # 4. Проверка на дубликаты (чтобы не слать одно и то же)
            if is_new_job(f"tg_{event.chat_id}_{event.id}"):
                # Формируем прямую ссылку на пост
                post_url = f"https://t.me/{username}/{event.id}" if username else "Ссылка скрыта"

                for uid in set(matched_users):
                    try:
                        # 5. Отправляем сообщение с заголовком и ссылкой в конце
                        await bot.send_message(
                            uid, 
                            f"⚡️ **НОВОЕ В КАНАЛЕ: {title}**\n\n"
                            f"{text[:3500]}\n\n"
                            f"🔗 **Оригинал поста:** {post_url}",
                            disable_web_page_preview=False # Оставляем превью для удобства
                        )
                        await asyncio.sleep(0.3) # Защита от Flood Limit
                    except: pass
    except Exception as e:
        logging.error(f"Ошибка в telethon_handler: {e}")

async def monitor_sites():
    while True:
        try:
            logging.info("Запуск циклической проверки сайтов...")
            subs = get_all_subs() # Получаем список [(user_id, keyword), ...]

            if not subs:
                logging.info("Подписок пока нет. Спим.")
                await asyncio.sleep(600)
                continue

            for user_id, kw in subs:
                # 1. Собираем свежак с 3-х главных сайтов (по 15 штук)
                # Habr и JobFilter тоже можно добавить, если нужно
                hh = search_hh(kw, 15)
                sj = search_superjob(kw, 15)
                hb = search_habr(kw, 10) 

                all_current_jobs = hh + sj + hb

                # Нормализуем ключевое слово для проверки (е/ё)
                kw_clean = kw.lower().replace('ё', 'е')

                for job in all_current_jobs:
                    # 2. Проверяем, подходит ли вакансия под ключевое слово (на всякий случай)
                    # и не присылали ли мы её уже раньше (is_new_job)
                    job_text_clean = job['text'].lower().replace('ё', 'е')

                    if kw_clean in job_text_clean:
                        if is_new_job(job['id']):
                            try:
                                # 3. Отправляем пользователю
                                await bot.send_message(
                                    user_id, 
                                    f"🔔 **НОВАЯ ВАКАНСИЯ ПО ПОДПИСКЕ**\n"
                                    f"🔍 Запрос: `{kw.upper()}`\n\n"
                                    f"{job['text']}"
                                )
                                # Небольшая пауза, чтобы не поймать Flood Limit от Telegram
                                await asyncio.sleep(0.7)
                            except Exception as send_error:
                                logging.error(f"Ошибка отправки сообщения юзеру {user_id}: {send_error}")

            logging.info("Проверка завершена. Следующий запуск через 30 минут.")

        except Exception as e:
            logging.error(f"Критическая ошибка в monitor_sites: {e}")

        # Ждем 30 минут (1800 секунд) перед следующей проверкой
        await asyncio.sleep(1800)

def generate_excel(data):
    try:
        if not data:
            return None
            
        raw_data = []
        for item in data:
            # 1. Добавляем 'Описание' в список собираемых полей
            raw_data.append({
                'Дата': str(item.get('Дата', '—')),
                'Источник': str(item.get('Источник', '—')),
                'Вакансия': str(item.get('Вакансия', '—')),
                'Компания': str(item.get('Компания', '—')),
                'Оплата': str(item.get('Оплата', '—')),
                'Описание': str(item.get('Описание', '—')), # НОВОЕ ПОЛЕ
                'Ссылка': str(item.get('Ссылка', '—'))
            })

        df = pd.DataFrame(raw_data)
        
        # 2. Умная сортировка по дате
        if not df.empty:
            df['TempDate'] = pd.to_datetime(df['Дата'], errors='coerce')
            df = df.sort_values(by='TempDate', ascending=False)
            df = df.drop(columns=['TempDate']) 

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Вакансии')
            ws = writer.sheets['Вакансии']
            
            # 3. Настройка оформления
            header_fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            link_font = Font(color="0000FF", underline="single")
            
            # Находим индексы нужных колонок
            link_col_idx = df.columns.get_loc("Ссылка") + 1 if "Ссылка" in df.columns else None
            desc_col_idx = df.columns.get_loc("Описание") + 1 if "Описание" in df.columns else None

            for col_num, column in enumerate(df.columns):
                cell = ws.cell(row=1, column=col_num + 1)
                cell.fill = header_fill
                cell.font = header_font
                
                col_letter = chr(65 + col_num)
                # Настройка ширины колонок
                if column == 'Ссылка':
                    ws.column_dimensions[col_letter].width = 45
                elif column == 'Вакансия':
                    ws.column_dimensions[col_letter].width = 40
                elif column == 'Описание':
                    ws.column_dimensions[col_letter].width = 60 # Широкая колонка для сути
                else:
                    ws.column_dimensions[col_letter].width = 20

            # 4. Делаем ссылки кликабельными и настраиваем перенос текста для Описания
            for row in range(2, len(df) + 2):
                # Для ссылок
                if link_col_idx:
                    cell_link = ws.cell(row=row, column=link_col_idx)
                    if cell_link.value and str(cell_link.value).startswith('http'):
                        cell_link.hyperlink = cell_link.value
                        cell_link.font = link_font
                
                # Для описания (включаем перенос текста, чтобы было удобно читать)
                if desc_col_idx:
                    cell_desc = ws.cell(row=row, column=desc_col_idx)
                    cell_desc.alignment = Alignment(wrap_text=True, vertical='top')

            ws.freeze_panes = 'A2'
            
        output.seek(0)
        return output
    except Exception as e:
        logging.error(f"Критическая ошибка Excel: {e}")
        return None

# --- ОБРАБОТЧИКИ ---
# --- YOUTUBE ПАРСЕР ДЛЯ РЕЖИССЁРА ---
def parse_yt_duration(duration_str):
    match = re.match(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str or '')
    if not match:
        return 0
    d = int(match.group(1) or 0)
    h = int(match.group(2) or 0)
    m = int(match.group(3) or 0)
    s = int(match.group(4) or 0)
    return d * 86400 + h * 3600 + m * 60 + s

def extract_yt_contacts(texts):
    full_text = "\n".join([t for t in texts if t])
    
    # 1. Ищем Email
    raw_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', full_text)
    bad_ext = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')
    emails = []
    for e in raw_emails:
        e_low = e.lower()
        if not e_low.endswith(bad_ext) and 'example.com' not in e_low:
            if e_low not in emails:
                emails.append(e_low)

    # 2. Ищем Telegram (ссылки t.me/... и @ники рядом со словами про рекламу/менеджера)
    tgs = []
    for m in re.findall(r'(?:https?://)?(?:t\.me|telegram\.me)/(?!joinchat|\+)([a-zA-Z0-9_]{4,32})', full_text, flags=re.IGNORECASE):
        handle = f"@{m}"
        if handle.lower() not in [x.lower() for x in tgs]:
            tgs.append(handle)

    tg_keywords = ('тг', 'tg', 'телеграм', 'telegram', 'менеджер', 'manager', 'реклам', 'сотруднич', 'pr', 'пиар', 'связ', 'contact', 'business', 'коммерц', 'агент', 'продюсер')
    for line in full_text.splitlines():
        line_low = line.lower()
        if any(kw in line_low for kw in tg_keywords):
            for m in re.findall(r'(?<![a-zA-Z0-9._%+-])@([a-zA-Z0-9_]{5,32})', line):
                handle = f"@{m}"
                if handle.lower() not in [x.lower() for x in tgs]:
                    tgs.append(handle)

    # 3. Прочие внешние ссылки (сайты, Taplink, Linktree, соцсети)
    raw_urls = re.findall(r'https?://[^\s\)\]\>\"\'<]+', full_text)
    other_links = []
    skip_domains = ('youtube.com', 'youtu.be', 't.me', 'telegram.me', 'bit.ly', 'clck.ru')
    for u in raw_urls:
        u_clean = u.rstrip('.,;:!?')
        u_low = u_clean.lower()
        if not any(d in u_low for d in skip_domains):
            if u_clean not in other_links:
                other_links.append(u_clean)

    return ", ".join(emails[:3]), ", ".join(tgs[:3]), ", ".join(other_links[:3])

def check_yt_language(texts, target_lang):
    combined = " ".join(texts)
    cyrillic = len(re.findall(r'[а-яА-ЯёЁ]', combined))
    latin = len(re.findall(r'[a-zA-Z]', combined))
    total_letters = cyrillic + latin
    if total_letters == 0:
        return False
    if target_lang == 'ru':
        return cyrillic >= 10 and (cyrillic / total_letters) >= 0.25
    else:
        return cyrillic <= 2 and (latin / total_letters) >= 0.75

def search_youtube_channels(query, pages=2, genre_label=None, exclude_cids=None, video_duration=None):
    api_key = (os.getenv('YOUTUBE_API_KEY') or '').strip()
    if not api_key:
        return {"error": "NO_KEY"}

    # Новые фильтры: от 300к подписчиков, упор на крупные продакшн-каналы
    MIN_SUBS = 300000
    MAX_SUBS = 30000000
    MIN_AVG_VIEWS = 20000
    MIN_AVG_DURATION_MIN = 6.0
    MAX_DAYS_SINCE_LAST = 75

    exclude_set = exclude_cids or set()
    genre_name = genre_label or query
    is_russian = bool(re.search(r'[а-яА-ЯёЁ]', query))
    target_lang = 'ru' if is_russian else 'en'

    try:
        # 1. Двойной поиск (до 100 видео на нишу: самые просматриваемые + свежие)
        if video_duration:
            search_passes = [
                ('viewCount', video_duration, 180)
            ]
        else:
            search_passes = [
                ('viewCount', 'long', 180),
                ('relevance', 'medium', 90)
            ][:pages]

        channel_ids = []
        for s_order, s_dur, s_days in search_passes:
            pub_after = (datetime.utcnow() - timedelta(days=s_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
            params = {
                'part': 'snippet',
                'q': query,
                'type': 'video',
                'maxResults': 50,
                'order': s_order,
                'relevanceLanguage': target_lang,
                'publishedAfter': pub_after,
                'key': api_key
            }
            if s_dur:
                params['videoDuration'] = s_dur

            r = requests.get('https://www.googleapis.com/youtube/v3/search', params=params, timeout=15)
            if r.status_code in (400, 403):
                err_msg = r.json().get('error', {}).get('message', r.text)
                logging.error(f"YT API error {r.status_code}: {err_msg}")
                return {"error": f"YT: {err_msg}"}
            if r.status_code != 200:
                logging.error(f"YT search status {r.status_code}: {r.text}")
                continue

            for item in r.json().get('items', []):
                cid = item.get('snippet', {}).get('channelId')
                if cid and cid not in channel_ids and cid not in exclude_set:
                    channel_ids.append(cid)

        if not channel_ids:
            return {"items": [], "lang": target_lang}

        # 2. Получаем данные о каналах пачками по 50
        channels_info = {}
        for i in range(0, len(channel_ids), 50):
            chunk = channel_ids[i:i+50]
            r = requests.get(
                'https://www.googleapis.com/youtube/v3/channels',
                params={'part': 'snippet,statistics,contentDetails', 'id': ','.join(chunk), 'key': api_key},
                timeout=15
            )
            if r.status_code != 200:
                continue
            for item in r.json().get('items', []):
                stats = item.get('statistics', {})
                if stats.get('hiddenSubscriberCount'):
                    continue
                subs = int(stats.get('subscriberCount', 0))
                if MIN_SUBS <= subs <= MAX_SUBS:
                    uploads_id = item.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')
                    if uploads_id:
                        channels_info[item['id']] = {
                            'id': item['id'],
                            'title': item.get('snippet', {}).get('title', 'Без названия'),
                            'desc': item.get('snippet', {}).get('description', ''),
                            'subs': subs,
                            'uploads_id': uploads_id
                        }

        if not channels_info:
            return {"items": [], "lang": target_lang}

        # 3. Проверяем до 100 каналов (в 8 потоков)
        from concurrent.futures import ThreadPoolExecutor
        candidate_list = list(channels_info.values())[:100]
        channel_video_ids = {}
        all_video_ids = []

        def fetch_pl(ch):
            try:
                r = requests.get(
                    'https://www.googleapis.com/youtube/v3/playlistItems',
                    params={'part': 'contentDetails', 'playlistId': ch['uploads_id'], 'maxResults': 10, 'key': api_key},
                    timeout=10
                )
                if r.status_code == 200:
                    vids = [it['contentDetails']['videoId'] for it in r.json().get('items', []) if it.get('contentDetails', {}).get('videoId')]
                    return ch['id'], vids
            except Exception:
                pass
            return ch['id'], []

        with ThreadPoolExecutor(max_workers=8) as pool:
            for ch_id, vids in pool.map(fetch_pl, candidate_list):
                if vids:
                    channel_video_ids[ch_id] = vids
                    all_video_ids.extend(vids)

        if not all_video_ids:
            return {"items": [], "lang": target_lang}

        # 4. Выгружаем статистику, категории и длительность видео
        videos_data = {}
        unique_vids = list(dict.fromkeys(all_video_ids))
        for i in range(0, len(unique_vids), 50):
            chunk = unique_vids[i:i+50]
            r = requests.get(
                'https://www.googleapis.com/youtube/v3/videos',
                params={'part': 'snippet,contentDetails,statistics', 'id': ','.join(chunk), 'key': api_key},
                timeout=15
            )
            if r.status_code != 200:
                continue
            for v in r.json().get('items', []):
                videos_data[v['id']] = v

        # Стоп-слова по темам, которые мы исключили
        bad_channel_words = (
            'авто', 'тест-драйв', 'тест драйв', 'автоподбор', 'дрифт', 'гараж',
            'роблокс', 'roblox', 'майнкрафт', 'minecraft', 'гейминг', 'gaming', 'play', 'стрим', 'twitch', 'твич',
            'электроник', 'гаджет', 'техно', 'айфон', 'wylsa', 'droider',
            'бьюти', 'beauty', 'визаж', 'макияж', 'makeup', 'косметик',
            'влог', 'vlog', 'вязание', 'повязать', 'рукоделие', 'вышивк', 'лайфстайл', 'lifestyle',
            'фитнес', 'fitness', 'мма', 'mma', 'ufc', 'бокс', 'спорт',
            'пранк', 'prank', 'нарезк', 'кинокомпот', 'блокбастер', 'мелодрам', 'русский телик',
            'лучшие фильмы', 'новые фильмы', 'kingsize films', 'best film', 'времякино', 'для сна',
            'live', 'новости', 'news', 'шейтельман', 'ходорковский', 'дождь', 'спивак', 'франклин'
        )
        bad_video_words = (
            'роблокс', 'roblox', 'майнкрафт', 'minecraft', 'brawl stars', 'cs2', 'dota', 'gta ', 'летсплей', 'стрим',
            'тест-драйв', 'тест драйв', 'автоподбор', 'автообзор', 'обзор авто', 'разгон до 100',
            'обзор смартфона', 'обзор iphone', 'сборка пк', 'видеокарт', 'распаковка техники',
            'макияж', 'косметичка', 'визажист', 'уход за кожей', 'крашусь', 'вязание', 'крючком', 'спицами',
            'тренировка', 'похудеть', 'бой ufc', 'пранк', 'prank', 'розыгрыш',
            'прямой эфир', 'утренний стрим', 'вечерний стрим', 'сводка новостей', 'новости дня', 'главные новости'
        )
        # Категории YouTube: 2 = Авто, 17 = Спорт, 20 = Видеоигры
        banned_categories = {'2', '17', '20'}

        final_results = []
        now_utc = datetime.utcnow()

        for ch in candidate_list:
            ch_title_low = ch['title'].lower()
            if any(bw in ch_title_low for bw in bad_channel_words):
                continue

            vids = channel_video_ids.get(ch['id'], [])
            long_videos = []
            titles_for_lang = [ch['title']]
            cat_ids = []
            bad_vid_hits = 0

            for vid in vids:
                v_obj = videos_data.get(vid)
                if not v_obj:
                    continue
                v_snip = v_obj.get('snippet', {})
                v_title = v_snip.get('title', '')
                titles_for_lang.append(v_title)
                dur_sec = parse_yt_duration(v_obj.get('contentDetails', {}).get('duration', ''))

                if dur_sec > 180:
                    cat_ids.append(str(v_snip.get('categoryId', '')))
                    v_title_low = v_title.lower()
                    if any(bw in v_title_low for bw in bad_video_words):
                        bad_vid_hits += 1

                    views = int(v_obj.get('statistics', {}).get('viewCount', 0))
                    pub_str = v_snip.get('publishedAt', '')[:10]
                    long_videos.append({
                        'id': vid,
                        'dur_sec': dur_sec,
                        'views': views,
                        'pub_str': pub_str,
                        'desc': v_snip.get('description', '')
                    })

            if not check_yt_language(titles_for_lang, target_lang):
                continue

            if len(long_videos) < 3:
                continue

            # Если большинство видео из категорий Авто/Спорт/Игры — выкидываем
            banned_cat_count = sum(1 for c in cat_ids if c in banned_categories)
            if banned_cat_count >= len(long_videos) / 2:
                continue

            # Если 30%+ последних видео со стоп-словами (стримы, тачки, пранки, косметика) — выкидываем
            if bad_vid_hits >= max(2, len(long_videos) * 0.3):
                continue

            avg_dur_min = sum(v['dur_sec'] for v in long_videos) / len(long_videos) / 60.0
            avg_views = int(sum(v['views'] for v in long_videos) / len(long_videos))

            if avg_dur_min < MIN_AVG_DURATION_MIN or avg_views < MIN_AVG_VIEWS:
                continue

            if avg_dur_min > 120 and any(w in ch_title_low for w in ('кино', 'фильм', 'сериал')):
                continue

            long_videos.sort(key=lambda x: x['pub_str'], reverse=True)
            latest_vid = long_videos[0]
            try:
                latest_dt = datetime.strptime(latest_vid['pub_str'], '%Y-%m-%d')
                if (now_utc - latest_dt).days > MAX_DAYS_SINCE_LAST:
                    continue
            except Exception:
                continue

            texts_for_contacts = [ch['desc']] + [v['desc'] for v in long_videos[:3]]
            email, tg, links = extract_yt_contacts(texts_for_contacts)

            is_new = is_new_yt_channel(ch['id'])
            has_contact = 1 if (email or tg) else 0

            subs = ch['subs']
            if subs >= 1000000:
                segment = '🔥 Миллионник'
            elif avg_views >= subs * 0.45:
                segment = '🚀 Быстрорастущий'
            else:
                segment = '💼 Крупный'

            final_results.append({
                'channel_id': ch['id'],
                'is_new_flag': 1 if is_new else 0,
                'has_contact': has_contact,
                'Статус': '🆕 Новый' if is_new else '♻️ Уже был',
                'Жанр': genre_name,
                'Сегмент': segment,
                'Канал': ch['title'],
                'Подписчики': subs,
                'Ср. просмотры': avg_views,
                'Ср. длина (мин)': round(avg_dur_min, 1),
                'Последнее видео': latest_vid['pub_str'],
                'Email': email if email else '—',
                'Telegram': tg if tg else '—',
                'Другие ссылки': links if links else '—',
                'Вкладка О канале': f"https://www.youtube.com/channel/{ch['id']}/about",
                'Последний ролик': f"https://www.youtube.com/watch?v={latest_vid['id']}",
                'Ссылка на канал': f"https://www.youtube.com/channel/{ch['id']}",
                'Имя': '',
                'Отправлять': 'да' if email else '',
                'Статус_отправки': ''
            })

        final_results.sort(key=lambda x: (x['is_new_flag'], x['has_contact'], x['Ср. просмотры']), reverse=True)
        return {"items": final_results, "lang": target_lang}

    except Exception as e:
        logging.error(f"YouTube search error: {e}")
        return {"error": str(e)}

def fetch_channels_by_handles(handles):
    api_key = (os.getenv('YOUTUBE_API_KEY') or '').strip()
    if not api_key:
        return {"error": "NO_KEY"}

    results = []
    try:
        for h in handles[:50]:
            clean_h = h.lstrip('@').strip()
            r = requests.get(
                'https://www.googleapis.com/youtube/v3/channels',
                params={'part': 'snippet,statistics,contentDetails', 'forHandle': clean_h, 'key': api_key},
                timeout=15
            )
            if r.status_code != 200 or not r.json().get('items'):
                continue
            item = r.json()['items'][0]
            cid = item['id']
            title = item.get('snippet', {}).get('title', clean_h)
            desc = item.get('snippet', {}).get('description', '')
            subs = int(item.get('statistics', {}).get('subscriberCount', 0))
            uploads_id = item.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')

            long_videos = []
            if uploads_id:
                pr = requests.get(
                    'https://www.googleapis.com/youtube/v3/playlistItems',
                    params={'part': 'contentDetails', 'playlistId': uploads_id, 'maxResults': 10, 'key': api_key},
                    timeout=10
                )
                vids = [it['contentDetails']['videoId'] for it in pr.json().get('items', []) if it.get('contentDetails', {}).get('videoId')]
                if vids:
                    vr = requests.get(
                        'https://www.googleapis.com/youtube/v3/videos',
                        params={'part': 'snippet,contentDetails,statistics', 'id': ','.join(vids), 'key': api_key},
                        timeout=15
                    )
                    for v in vr.json().get('items', []):
                        dur_sec = parse_yt_duration(v.get('contentDetails', {}).get('duration', ''))
                        if dur_sec > 180:
                            long_videos.append({
                                'id': v['id'],
                                'dur_sec': dur_sec,
                                'views': int(v.get('statistics', {}).get('viewCount', 0)),
                                'pub_str': v.get('snippet', {}).get('publishedAt', '')[:10],
                                'desc': v.get('snippet', {}).get('description', '')
                            })

            long_videos.sort(key=lambda x: x['pub_str'], reverse=True)
            avg_dur = round(sum(v['dur_sec'] for v in long_videos) / len(long_videos) / 60.0, 1) if long_videos else 0
            avg_views = int(sum(v['views'] for v in long_videos) / len(long_videos)) if long_videos else 0
            latest_vid_id = long_videos[0]['id'] if long_videos else ''
            latest_date = long_videos[0]['pub_str'] if long_videos else '—'

            texts_for_contacts = [desc] + [v['desc'] for v in long_videos[:3]]
            email, tg, links = extract_yt_contacts(texts_for_contacts)
            is_new = is_new_yt_channel(cid)

            if subs <= 300000 and avg_views >= subs * 0.45:
                segment = '🚀 Растущий'
            elif subs >= 500000:
                segment = '🔥 Флагман'
            else:
                segment = '💼 Активный'

            results.append({
                'channel_id': cid,
                'is_new_flag': 1 if is_new else 0,
                'has_contact': 1 if (email or tg) else 0,
                'Статус': '🆕 Новый' if is_new else '♻️ Уже был',
                'Жанр': 'Свой список',
                'Сегмент': segment,
                'Канал': title,
                'Подписчики': subs,
                'Ср. просмотры': avg_views,
                'Ср. длина (мин)': avg_dur,
                'Последнее видео': latest_date,
                'Email': email if email else '—',
                'Telegram': tg if tg else '—',
                'Другие ссылки': links if links else '—',
                'Вкладка О канале': f"https://www.youtube.com/channel/{cid}/about",
                'Последний ролик': f"https://www.youtube.com/watch?v={latest_vid_id}" if latest_vid_id else '—',
                'Ссылка на канал': f"https://www.youtube.com/channel/{cid}",
                'Имя': '',
                'Отправлять': 'да' if email else '',
                'Статус_отправки': ''
            })
        return {"items": results, "lang": "ru"}
    except Exception as e:
        logging.error(f"Handles error: {e}")
        return {"error": str(e)}

def generate_yt_excel(data):
    try:
        if not data:
            return None

        clean_rows = []
        for item in data:
            clean_rows.append({
                'Статус': item['Статус'],
                'Жанр': item.get('Жанр', '—'),
                'Сегмент': item.get('Сегмент', '—'),
                'Канал': item['Канал'],
                'Подписчики': item['Подписчики'],
                'Ср. просмотры': item['Ср. просмотры'],
                'Ср. длина (мин)': item['Ср. длина (мин)'],
                'Последнее видео': item['Последнее видео'],
                'Email': item['Email'],
                'Telegram': item['Telegram'],
                'Другие ссылки': item['Другие ссылки'],
                'Вкладка О канале': item['Вкладка О канале'],
                'Последний ролик': item['Последний ролик'],
                'Ссылка на канал': item['Ссылка на канал'],
                'Имя': item.get('Имя', ''),
                'Отправлять': item.get('Отправлять', ''),
                'Статус_отправки': item.get('Статус_отправки', ''),
            })

        df = pd.DataFrame(clean_rows)
        output = BytesIO()

        def format_ws(ws, target_df):
            header_fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            link_font = Font(color="0000FF", underline="single")

            widths = {
                'Статус': 13, 'Жанр': 25, 'Сегмент': 15, 'Канал': 28, 'Подписчики': 14,
                'Ср. просмотры': 15, 'Ср. длина (мин)': 15, 'Последнее видео': 15,
                'Email': 28, 'Telegram': 22, 'Другие ссылки': 35, 'Вкладка О канале': 35,
                'Последний ролик': 35, 'Ссылка на канал': 35, 'Имя': 20,
                'Отправлять': 14, 'Статус_отправки': 22
            }

            for col_num, col_name in enumerate(target_df.columns):
                cell = ws.cell(row=1, column=col_num + 1)
                cell.fill = header_fill
                cell.font = header_font
                ws.column_dimensions[chr(65 + col_num)].width = widths.get(col_name, 20)

            link_cols = ['Вкладка О канале', 'Последний ролик', 'Ссылка на канал']
            link_indices = [target_df.columns.get_loc(c) + 1 for c in link_cols if c in target_df.columns]

            for row in range(2, len(target_df) + 2):
                for idx in link_indices:
                    cell_link = ws.cell(row=row, column=idx)
                    if cell_link.value and str(cell_link.value).startswith('http'):
                        cell_link.hyperlink = cell_link.value
                        cell_link.font = link_font

            ws.auto_filter.ref = ws.dimensions
            ws.freeze_panes = 'A2'

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Все_каналы')
            format_ws(writer.sheets['Все_каналы'], df)

            df_growing = df[df['Сегмент'].str.contains('Растущий|Быстрорастущий', na=False)]
            if not df_growing.empty:
                df_growing.to_excel(writer, index=False, sheet_name='Растущие')
                format_ws(writer.sheets['Растущие'], df_growing)

        output.seek(0)
        return output
    except Exception as e:
        logging.error(f"YouTube Excel error: {e}")
        return None

def send_to_google_sheet(items):
    gs_url = (os.getenv('GSHEET_URL') or '').strip()
    if not gs_url or not items:
        return None
    keys = [
        'Статус', 'Жанр', 'Сегмент', 'Канал', 'Подписчики', 'Ср. просмотры', 'Ср. длина (мин)',
        'Последнее видео', 'Email', 'Telegram', 'Другие ссылки',
        'Вкладка О канале', 'Последний ролик', 'Ссылка на канал',
        'Имя', 'Отправлять', 'Статус_отправки'
    ]
    rows_payload = [{k: item.get(k, '') for k in keys} for item in items]
    try:
        r = requests.post(gs_url, json={'rows': rows_payload}, timeout=30)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logging.error(f"Google Sheet sync error: {e}")
    return None

@dp.message_handler(commands=['start'], state="*")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.finish() # Сбрасываем режим на "Работу" по умолчанию
    name = message.from_user.first_name
    await message.answer(
        f"Привет, {name}! 🎬 Я — твой персональный агент по поиску работы в кино, медиа и IT.\n\n"
        f"**Что я умею:**\n"
        f"🔍 **Мгновенный поиск:** Напиши название профессии, и я тут же перерою HH.ru, SuperJob, Habr и JobFilter.\n"
        f"📂 **Excel-отчеты:** На каждый запрос я присылаю файл со всеми найденными вакансиями.\n"
        f"⚡️ **Live-мониторинг:** Я читаю 54 Telegram-канала в реальном времени.\n"
        f"🎓 **Поиск курсов:** Нажми кнопку **«🎓 Искать курсы»** и напиши тему, а я найду лучшие **бесплатные** уроки на Stepik и YouTube.\n\n"
        f"**Как запустить авто-поиск работы:**\n"
        f"1️⃣ Нажми **«💼 Искать работу»** и напиши ключевое слово, например: `режиссер` или `продюсер`.\n"
        f"2️⃣ Под результатом поиска нажми кнопку **«🔔 Подписаться»**.\n"
        f"3️⃣ Всё! Как только появится новая вакансия с этим словом — я мгновенно пришлю её в личку.\n\n"
        f"💡 **Совет:** Подписывайся на короткие слова (`режиссер`, а не `режиссером`), чтобы я ловил все склонения.\n\n"
        f"Выбери нужный режим с помощью кнопок внизу 👇",
        parse_mode="Markdown",
        reply_markup=get_main_kb()
    )

@dp.message_handler(text="💼 Искать работу", state="*")
async def btn_job(message: types.Message, state: FSMContext):
    await state.finish() # Выключаем режим курсов
    await message.answer("💼 **РЕЖИМ: ПОИСК РАБОТЫ**\n\nПросто напиши профессию (например: `режиссер` или `монтажер`), и я соберу вакансии со всех сайтов и 54 каналов.", parse_mode="Markdown")

@dp.message_handler(text="🎓 Искать курсы", state="*")
async def btn_course(message: types.Message, state: FSMContext):
    await SearchMode.course.set() # Включаем режим курсов
    await message.answer("🎓 **РЕЖИМ: ПОИСК КУРСОВ**\n\nНапиши тему, которую хочешь изучить (например: `python`, `дизайн`, `ии генерация видео`).", parse_mode="Markdown")

@dp.message_handler(text="🎬 YouTube-каналы", state="*")
async def btn_youtube(message: types.Message, state: FSMContext):
    await SearchMode.youtube.set()
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🔥 Авто-сбор: Топ-ниши 300к+ (RU)", callback_data="yt_batch|ru"),
        types.InlineKeyboardButton("🌍 Авто-сбор: Топ-ниши 300к+ (EN)", callback_data="yt_batch|en")
    )
    await message.answer(
        "🎬 <b>РЕЖИМ: ПОИСК КРУПНЫХ YOUTUBE-КАНАЛОВ (300к+)</b>\n\n"
        "Ищу кулинарные и тревел-шоу, документалки (как Редакция), доки о моде и брендах, развлекательные и детские шоу — "
        "без тачек, игр, бьюти, влогов и говорящих голов.\n\n"
        "✍️ <b>Или напиши сюда:</b>\n"
        "• свою тему\n"
        "• либо список каналов через @ или ссылки (<code>@redactsiya @GEOSHOW</code>) — вытащу контакты прямо в Google Таблицу.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message_handler(text="🔔 Мои подписки", state="*")
@dp.message_handler(commands=['mysubs'], state="*")
async def list_subs(message: types.Message, state: FSMContext):
    conn = None
    try:
        conn = sqlite3.connect('manager.db', timeout=20)
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS subs (user_id INTEGER, keyword TEXT, UNIQUE(user_id, keyword))')
        data = cursor.execute('SELECT keyword FROM subs WHERE user_id = ?', (message.from_user.id,)).fetchall()
        if not data:
            await message.answer("У тебя пока нет активных подписок. 🤷‍♂️")
        else:
            subs_list = "\n".join([f"✅ <code>{html.escape(row[0])}</code>" for row in data])
            await message.answer(f"🔔 <b>Твои подписки:</b>\n\n{subs_list}\n\n🗑 <code>/del слово</code>", parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка в mysubs: {e}")
        await message.answer("⚠ Ошибка базы данных. Попробуй еще раз через 5 секунд.")
    finally:
        if conn:
            conn.close()

@dp.message_handler(commands=['del'], state="*")
async def del_sub(message: types.Message):
    keyword = message.get_args().lower().strip()
    if not keyword:
        await message.answer("⚠ Нужно указать слово для удаления.\n\nПример: `/del режиссер`", parse_mode="Markdown")
        return
    conn = sqlite3.connect('manager.db')
    res = conn.execute('SELECT 1 FROM subs WHERE user_id = ? AND keyword = ?', (message.from_user.id, keyword)).fetchone()
    if res:
        conn.execute('DELETE FROM subs WHERE user_id = ? AND keyword = ?', (message.from_user.id, keyword))
        conn.commit()
        await message.answer(f"❌ Подписка на слово '{keyword}' удалена. Я больше не буду присылать по нему уведомления.")
    else:
        await message.answer(f"🤔 У тебя нет активной подписки на слово '{keyword}'. Проверь список командой /mysubs")
    conn.close()

@dp.message_handler(commands=['stop_all'], state="*")
async def clear_subs(message: types.Message):
    conn = sqlite3.connect('manager.db')
    conn.execute('DELETE FROM subs WHERE user_id = ?', (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("📴 Мониторинг остановлен. Все твои подписки были успешно удалены.")

# --- НИЖЕ СТОЯТ ОБРАБОТЧИКИ ТЕКСТА В РЕЖИМАХ ---

@dp.message_handler(state=SearchMode.course)
async def process_course_search(message: types.Message, state: FSMContext):
    if message.text.startswith('/'):
        return

    query = message.text.strip()
    wait = await message.answer(f"📚 Ищу бесплатные курсы по теме: `{query}`...", parse_mode="Markdown")

    try:
        stepik_courses = search_stepik(query)
        free_courses = search_free_courses(query, limit_per_source=5)

        text = f"🎓 БЕСПЛАТНЫЕ МАТЕРИАЛЫ: «{query.upper()}»\n\n"
        if stepik_courses:
            text += "🟢 Stepik:\n"
            for c in stepik_courses[:3]:
                title = c['title'].replace('[', '').replace(']', '').replace('*', '').replace('_', '')
                text += f"• {title}\n  {c['url']}\n  {c['desc']}...\n\n"
        else:
            text += "🟢 Stepik: ничего не найдено\n\n"

        if free_courses:
            text += "📘 Другие источники:\n\n"
            for item in free_courses[:8]:
                clean = item.get('text', '')
                clean = clean.replace('**', '').replace('*', '').replace('_', '').replace('`', '')
                text += f"{clean}\n\n"
        else:
            text += "📘 Дополнительные источники пока пусты\n\n"

        await wait.edit_text("📡 Проверяю Telegram-каналы школ...")
        try:
            tg_edu = await search_telegram_history(query, limit_per_channel=2, target_channels=EDU_CHANNELS)
            if tg_edu:
                text += "📱 Свежее в Telegram-школах:\n"
                for j in tg_edu[:2]:
                    text += f"• {j['Компания']}: {j['Ссылка']}\n"
            else:
                text += "📱 Telegram-школы: ничего нового\n"
        except Exception as e:
            logging.error(f"TG Edu error: {e}")
            text += "📱 Telegram-школы: временно недоступны\n"

        await wait.edit_text(text, parse_mode=None, disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"Ошибка поиска курсов: {e}")
        await wait.edit_text(f"❌ Произошла ошибка при поиске курсов.\nПопробуй ещё раз чуть позже.\n\nОшибка: `{str(e)[:100]}`", parse_mode="Markdown")

@dp.message_handler(state=SearchMode.youtube)
async def process_youtube_search(message: types.Message, state: FSMContext):
    if message.text.startswith('/'):
        return

    query = message.text.strip()
    handles = re.findall(r'@([a-zA-Z0-9_.-]{2,35})', query)

    wait = await message.answer(
        f"🎬 Собираю данные по {'твоему списку каналов' if handles else f'теме <b>{html.escape(query)}</b>'}...\n"
        f"<i>Проверяю до 100 каналов, просмотры и контакты (15–30 секунд).</i>",
        parse_mode="HTML"
    )

    loop = asyncio.get_running_loop()
    if handles:
        res = await loop.run_in_executor(None, fetch_channels_by_handles, handles)
    else:
        res = await loop.run_in_executor(None, search_youtube_channels, query, 2, query, None, None)

    if "error" in res:
        err = res["error"]
        if err == "NO_KEY":
            await wait.edit_text("❌ Не найден ключ <code>YOUTUBE_API_KEY</code>.", parse_mode="HTML")
        else:
            await wait.edit_text(f"❌ Ошибка при поиске:\n<code>{html.escape(err[:250])}</code>", parse_mode="HTML")
        return

    items = res.get("items", [])
    if not items:
        await wait.edit_text(
            f"🤷‍♂️ По запросу <b>«{html.escape(query)}»</b> ничего не нашлось по текущим фильтрам.",
            parse_mode="HTML"
        )
        return

    preview_text = f"✅ Найдено каналов: <b>{len(items)}</b>\n<b>Топ-5 из выборки:</b>\n\n"
    for ch in items[:5]:
        contacts = []
        if ch['Email'] != '—': contacts.append(f"📧 {ch['Email']}")
        if ch['Telegram'] != '—': contacts.append(f"✈️ {ch['Telegram']}")
        c_str = " | ".join(contacts) if contacts else "🔒 Почта под капчей (см. ссылку в Excel)"
        preview_text += (
            f"{ch['Статус']} | {ch['Сегмент']} <b>{html.escape(ch['Канал'])}</b>\n"
            f"👥 {ch['Подписчики']:,} | 👁 ~{ch['Ср. просмотры']:,} | ⏱ {ch['Ср. длина (мин)']} мин\n"
            f"{c_str}\n"
            f"{ch['Ссылка на канал']}\n\n"
        )

    await wait.delete()
    await message.answer(preview_text, parse_mode="HTML", disable_web_page_preview=True)

    gs_res = await loop.run_in_executor(None, send_to_google_sheet, items)
    gs_kb = None
    gs_caption = ""
    if gs_res and gs_res.get('ok'):
        gs_caption = f"\n📥 В Google Таблицу добавлено новых строк: <b>{gs_res.get('added', 0)}</b>"
        if gs_res.get('url'):
            gs_kb = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("📊 Открыть Google Таблицу", url=gs_res['url'])
            )

    excel_file = generate_yt_excel(items)
    if excel_file:
        safe_name = re.sub(r'[^\w\s-]', '', query).strip().replace(' ', '_')[:25] or 'channels'
        await message.answer_document(
            types.InputFile(excel_file, filename=f"YT_{safe_name}.xlsx"),
            caption=f"📊 Готовая база: <b>{len(items)}</b> каналов.{gs_caption}",
            reply_markup=gs_kb,
            parse_mode="HTML"
        )

YT_DEFAULT_GENRES = {
    'ru': [
        # 7 запросов по кулинарии и еде
        ('Большие кулинарные шоу', 'кулинарное шоу|гастро шоу|фуд шоу', 'long'),
        ('Большие кулинарные шоу', 'кулинарное шоу|готовка шоу|рецепты шоу', 'medium'),
        ('Большие кулинарные шоу', 'битва шефов|адская кухня|молодые ножи|кондитер', 'long'),
        ('Большие кулинарные шоу', 'шеф повар|рецепт от шефа|кулинария', 'medium'),
        ('Большие кулинарные шоу', 'обзор ресторанов|дегустация|ресторанный', 'long'),
        ('Большие кулинарные шоу', 'уличная еда|стрит фуд|казан мангал|готовка на природе', 'medium'),
        ('Большие кулинарные шоу', 'ивлев|обломов|емельяненко|высоцкая|грильков', 'medium'),

        # 8 запросов по большим тревел-каналам и экспедициям
        ('Большие тревел-шоу', 'тревел шоу|орел и решка|мир наизнанку', 'long'),
        ('Большие тревел-шоу', 'большое путешествие|кругосветное путешествие|кругосветка', 'long'),
        ('Большие тревел-шоу', 'птушкин|комаров|бедняков|своим ходом|лядов', 'long'),
        ('Большие тревел-шоу', 'экспедиция фильм|путешествие фильм|документальный фильм путешествие', 'long'),
        ('Большие тревел-шоу', 'африка путешествие|азия путешествие|латинская америка|дикие племена', 'long'),
        ('Большие тревел-шоу', 'путешествие на край света|арктика|антарктида|экстремальное путешествие', 'long'),
        ('Большие тревел-шоу', 'на поезде через|через всю страну|по миру своим ходом|неизвестная страна', 'long'),
        ('Большие тревел-шоу', 'тревел шоу|обзор стран|путешествия по миру|гид по городу', 'medium'),

        # Документалки и журналистика (без стримов)
        ('Документалки и журналистика', 'документальный фильм|документальное кино', 'long'),
        ('Документалки и журналистика', 'большой репортаж|спецрепортаж|журналистское расследование', 'long'),
        ('Документалки и журналистика', 'редакция|the люди|погребижская|фильм о людях', 'long'),
        ('Документалки и журналистика', 'как живут в|закрытая страна|большой выпуск', 'long'),

        # Мода и бренды
        ('Документалки о моде и брендах', 'история моды|документальный фильм о моде|модный дом', 'long'),
        ('Документалки о моде и брендах', 'история бренда|как создавался бренд|индустрия моды', 'medium'),

        # Развлекательные не-юмор шоу
        ('Развлекательные шоу (не юмор)', 'развлекательное шоу|реалити шоу|большое шоу', 'long'),
        ('Развлекательные шоу (не юмор)', 'выживание шоу|прятки|челлендж 24 часа|кто последний', 'long'),
        ('Развлекательные шоу (не юмор)', 'викторина шоу|интеллектуальное шоу|угадай|детектив шоу', 'long'),

        # Дети
        ('Шоу с участием детей', 'детское шоу|шоу с детьми|лучше всех|дети на тв', 'long'),
        ('Шоу с участием детей', 'детский проект|шоу талантов дети|умнее всех|дети челлендж', 'medium'),

        # Интервью, юмор, научпоп, музыка
        ('Большие интервью и подкасты', 'большое интервью|видеоподкаст|подкаст шоу', 'long'),
        ('Крупные юмористические шоу', 'импровизация шоу|плюшки|чбд|настя ивлеева шоу', 'long'),
        ('Научпоп, космос и история', 'научпоп|космос документальный|топлес|utopia show', 'long'),
        ('Научпоп, космос и история', 'загадки истории|архив аномалий|мистика расследование', 'long'),
        ('Музыкальные шоу и фильмы', 'музыкальное шоу|музыкальный фильм|история музыки', 'long'),
        ('Музыкальные шоу и фильмы', 'бэкстейдж съемок|как снимали клип|шоу голос', 'medium'),
    ],
    'en': [
        ('Big Cooking & Food Shows', 'cooking competition show|chef show|gastronomy documentary|food show', 'long'),
        ('Big Cooking & Food Shows', 'cooking show|street food tour|michelin chef|restaurant review', 'medium'),
        ('Big Travel Shows', 'travel show|travel documentary|expedition documentary', 'long'),
        ('Big Travel Shows', 'around the world|solo travel documentary|epic journey', 'long'),
        ('Big Travel Shows', 'most dangerous places|remote tribes|extreme travel', 'long'),
        ('Big Travel Shows', 'travel guide|luxury travel|street travel show', 'medium'),
        ('Documentary & Journalism', 'documentary film|investigative journalism|mini documentary|special report', 'long'),
        ('Fashion Docs & Brands', 'fashion documentary|history of fashion|fashion house documentary|brand documentary', 'long'),
        ('Entertainment & Reality Shows', 'reality show|survival challenge show|game show|big challenge', 'long'),
        ('Kids & Family Shows', 'kids talent show|family game show|children show', 'long'),
        ('Interviews & Video Podcasts', 'video podcast|long interview|talk show', 'long'),
        ('Science, Space & History', 'science documentary|space documentary|history documentary', 'long'),
        ('Music Shows & Docs', 'music documentary|music show|behind the scenes music film', 'medium'),
    ]
}

@dp.callback_query_handler(lambda c: c.data.startswith('yt_batch|'), state="*")
async def yt_batch_handler(cb: types.CallbackQuery):
    lang = cb.data.split('|')[1]
    genres = YT_DEFAULT_GENRES.get(lang, YT_DEFAULT_GENRES['ru'])
    await cb.answer("Запускаю авто-сбор!")

    lang_title = "RU 🇷🇺" if lang == 'ru' else "EN 🇬🇧"
    wait = await cb.message.answer(
        f"🚀 <b>Запускаю авто-сбор ({lang_title}) по {len(genres)} нишам...</b>\n"
        f"<i>Собираю и флагманов, и молодые растущие каналы (~2 минуты).</i>",
        parse_mode="HTML"
    )

    loop = asyncio.get_running_loop()
    all_items = []
    seen_cids = set()
    stop_error = None

    for idx, (genre_name, kw, v_dur) in enumerate(genres, 1):
        with suppress(Exception):
            await wait.edit_text(
                f"🎬 <b>Авто-сбор ({lang_title}): шаг {idx} из {len(genres)}</b>\n"
                f"🔍 Ищу нишу: <code>{html.escape(genre_name)}</code>\n"
                f"📊 Уже собрано каналов: <b>{len(all_items)}</b>",
                parse_mode="HTML"
            )

        res = await loop.run_in_executor(None, search_youtube_channels, kw, 1, genre_name, set(seen_cids), v_dur)

        if "error" in res:
            stop_error = res["error"]
            break

        for ch in res.get("items", []):
            cid = ch.get('channel_id')
            if cid and cid not in seen_cids:
                seen_cids.add(cid)
                all_items.append(ch)

        await asyncio.sleep(0.3)

    if stop_error and not all_items:
        await wait.edit_text(f"❌ Ошибка при сборе:\n<code>{html.escape(stop_error[:250])}</code>", parse_mode="HTML")
        return

    if not all_items:
        await wait.edit_text("🤷‍♂️ Ничего не нашлось по текущим фильтрам.")
        return

    all_items.sort(key=lambda x: (x['is_new_flag'], x['has_contact'], x['Ср. просмотры']), reverse=True)
    all_items.sort(key=lambda x: x['Жанр'])

    with suppress(Exception):
        await wait.delete()

    gs_res = await loop.run_in_executor(None, send_to_google_sheet, all_items)
    gs_kb = None
    gs_caption = ""
    if gs_res and gs_res.get('ok'):
        gs_caption = f"\n📥 В Google Таблицу добавлено новых строк: <b>{gs_res.get('added', 0)}</b>"
        if gs_res.get('url'):
            gs_kb = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("📊 Открыть Google Таблицу", url=gs_res['url'])
            )

    warn_text = f"\n⚠️ <i>Сбор остановлен досрочно ({html.escape(stop_error[:100])}), отдаю всё, что успел найти.</i>" if stop_error else ""

    excel_file = generate_yt_excel(all_items)
    if excel_file:
        date_str = datetime.now().strftime('%Y-%m-%d')
        await cb.message.answer_document(
            types.InputFile(excel_file, filename=f"YT_ALL_{lang.upper()}_{date_str}.xlsx"),
            caption=(
                f"✅ <b>Авто-сбор ({lang_title}) завершён!</b>\n"
                f"📊 Собрано уникальных каналов: <b>{len(all_items)}</b>{gs_caption}{warn_text}"
            ),
            reply_markup=gs_kb,
            parse_mode="HTML"
        )

@dp.message_handler(state=None)
async def manual_search(message: types.Message):
    if message.text.startswith('/'): return

    query = message.text.strip()
    # Ограничиваем запрос для кнопки (Telegram limit 64 bytes)
    short_query = query[:30] 
    
    status_msg = await message.answer(f"🔎 <b>Ищу вакансии:</b> <code>{query}</code>...", parse_mode="HTML")

    all_found = []
    seen_ids = set()

    # 1. Сбор с сайтов
    with suppress(MessageNotModified):
        await status_msg.edit_text("🌐 <b>Опрашиваю сайты...</b>", parse_mode="HTML")

    loop = asyncio.get_running_loop()
    # Добавляем JobFilter обратно, он давал массу результатов
    tasks = [
        loop.run_in_executor(None, search_hh, query, 50),
        loop.run_in_executor(None, search_superjob, query, 30),
        loop.run_in_executor(None, search_habr, query, 20),
        loop.run_in_executor(None, search_trudvsem, query, 40), # Прямой метод
        loop.run_in_executor(None, search_jobfilter, query, 15) 
    ]
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                for job in res:
                    if job.get('id') and job['id'] not in seen_ids:
                        all_found.append(job)
                        seen_ids.add(job['id'])
    except Exception as e:
        logging.error(f"Ошибка сайтов: {e}")

    # 2. Сбор из Telegram
    with suppress(MessageNotModified):
        # Показываем, сколько уже нашли на сайтах
        await status_msg.edit_text(f"📡 <b>Проверяю 54 канала...</b> (Сайты: {len(all_found)})", parse_mode="HTML")

    try:
        # Увеличим лимит до 5, чтобы не пропускать свежее
        tg_hist = await search_telegram_history(query, limit_per_channel=5)
        if tg_hist:
            for job in tg_hist:
                if job['id'] not in seen_ids:
                    all_found.append(job)
                    seen_ids.add(job['id'])
    except Exception as e:
        logging.error(f"Ошибка TG: {e}")

    if not all_found:
        await status_msg.edit_text(f"❌ По запросу '<b>{query}</b>' ничего не найдено.", parse_mode="HTML")
        return

    # 3. УМНАЯ СОРТИРОВКА
    def sort_key(x):
        d = str(x.get('Дата', '')).lower()
        # Если дата YYYY-MM-DD (как у Trud и HH), она сортируется идеально сама
        # Если дата DD.MM, превращаем ее для сравнения
        if '.' in d and len(d) <= 5:
            day, month = d.split('.')
            return f"2026-{month}-{day}"
        return d if d else "0000-00-00"

    all_found.sort(key=sort_key, reverse=True)

    # 4. Вывод топ-15
    for j in all_found[:15]:
        try:
            v_name = html.escape(str(j.get('Вакансия', '—')))
            v_pay = html.escape(str(j.get('Оплата', 'Договорная')))
            v_comp = html.escape(str(j.get('Компания', '—')))
            v_date = html.escape(str(j.get('Дата', '—')))
            v_src = str(j.get('Источник', ''))
            v_link = j.get('Ссылка', '#')
            # Берем наше новое поле Описание
            v_desc = html.escape(str(j.get('Описание', 'Описание доступно по ссылке.')))

            # Подбираем иконку и текстовую метку
            if "HH" in v_src: 
                icon, label = "🔴", "HH"
            elif "SJ" in v_src or "SuperJob" in v_src: 
                icon, label = "🔵", "SJ"
            elif "Habr" in v_src: 
                icon, label = "🟢", "Habr"
            elif "Trud" in v_src: 
                icon, label = "🏢", "Trud" # Исправлено: теперь две переменные
            elif "Geek" in v_src: 
                icon, label = "👨‍💻", "GeekJob"
            else: 
                icon, label = "📱", "TG"

            # ФОРМИРУЕМ КРАСИВЫЙ ТЕКСТ (Как в подписке)
            pretty_text = (
                f"{icon} {label}: <b>{v_name}</b>\n"
                f"💰 <b>{v_pay}</b> | 📅 {v_date}\n"
                f"🏢 {v_comp}\n\n"
                f"📝 <b>Суть:</b> <i>{v_desc}...</i>\n\n"
                f"{v_link}"
            )

            await message.answer(pretty_text, disable_web_page_preview=True, parse_mode="HTML")
            await asyncio.sleep(0.3)
        except Exception as e:
            logging.error(f"Ошибка вывода: {e}")

    # 5. Генерация Excel и кнопка
    try:
        excel_file = generate_excel(all_found)
        if excel_file:
            # Важно: используем short_query, чтобы кнопка не сломалась
            kb = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(f"🔔 Подписаться на '{short_query}'", callback_data=f"sub|{short_query}")
            )
            await message.answer_document(
                types.InputFile(excel_file, filename=f"Jobs_{short_query}.xlsx"),
                caption=f"✅ Найдено вакансий: <b>{len(all_found)}</b>\n(Сортировка: Самые новые вверху)",
                reply_markup=kb,
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Excel error: {e}")
        await message.answer(f"📊 Поиск завершен. Найдено вакансий: {len(all_found)}")

    await status_msg.delete()

# --- ОБРАБОТЧИК КНОПКИ ПОДПИСКИ ---
@dp.callback_query_handler(lambda c: c.data.startswith('sub|'))
async def sub_handler(cb: types.CallbackQuery):
    # 1. Извлекаем ключевое слово из даты кнопки
    kw = cb.data.split('|')[1]
    user_id = cb.from_user.id

    try:
        # 2. Записываем в базу данных
        add_subscription(user_id, kw)

        # 3. Отправляем всплывающее уведомление (alert)
        await bot.answer_callback_query(
            cb.id, 
            text=f"✅ Подписка на '{kw}' оформлена!", 
            show_alert=True
        )

        # 4. Отправляем подтверждающее сообщение в чат
        await bot.send_message(
            user_id, 
            f"🔔 **Готово!**\n\nЯ запомнил запрос: `{kw}`.\n"
            f"Как только в каналах или на сайтах появится новая вакансия с этим словом, я мгновенно пришлю её тебе сюда."
        )

    except Exception as e:
        logging.error(f"Subscription error: {e}")
        await bot.answer_callback_query(cb.id, text="❌ Произошла ошибка при подписке.")

async def handle(request):
    return web.Response(text="Bot is running!")

async def main():
    init_db()

    # 1. Запуск Веб-сервера
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()

    # 2. Запуск Telethon (каналы)
    try:
        if not client.is_connected():
            await client.start() # Используй start(), он сам проверит авторизацию
        
        # Сброс Timestamp для стабильности
        await client.get_dialogs(limit=1)
        logging.info("Telethon готов!")
    except Exception as e:
        logging.error(f"Telethon error: {e}")

    # 3. Запуск Aiogram (бот)
    # Удаляем вебхуки и старые соединения
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем фоновый мониторинг сайтов
    asyncio.create_task(monitor_sites()) 

    logging.info("Бот запущен и очищен от старых обновлений!")
    
    # --- ИСПРАВЛЕННЫЙ КУСОК ---
    # Сначала принудительно пропускаем старые сообщения
    await dp.skip_updates()
    # Потом запускаем опрос без аргументов внутри
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
