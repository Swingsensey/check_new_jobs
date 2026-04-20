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
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openpyxl.styles import Font, PatternFill, Alignment
from telethon.errors import FloodWaitError
from aiogram.utils.exceptions import MessageNotModified
from contextlib import suppress
# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
API_ID = 23009673
API_HASH = '249328ef42a91e5c80102c3d73c76a9c'
SESSION_STR = os.getenv('TELEGRAM_SESSION')
SJ_KEY = os.getenv('SUPERJOB_KEY') # Твой новый ключ
# Список каналов БЕЗ собаки @
CHANNELS = [
    'vdhl_good', 'mediajobs_ru', 'work_in_media', 'moviestart_ru', 'distantsiya',
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

# Создаем клиента для чтения каналов
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)


bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
}

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('manager.db')
    conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE IF NOT EXISTS subs (user_id INTEGER, keyword TEXT, UNIQUE(user_id, keyword))')
    conn.commit()
    conn.close()

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
async def search_telegram_history(query, limit_per_channel=10):
    if not client.is_connected(): await client.start()
    results = []
    seen_texts = set()
    
    for channel in CHANNELS[:25]:
        try:
            async for msg in client.iter_messages(channel, search=query, limit=limit_per_channel):
                if not msg.text or len(msg.text) < 40: continue
                
                # Защита от старья: если вакансии больше месяца — пропускаем (опционально)
                # if (datetime.now() - msg.date.replace(tzinfo=None)).days > 30: continue

                text_id = msg.text[:80].lower().strip()
                if text_id in seen_texts: continue
                seen_texts.add(text_id)

                # Ищем зарплату
                pay = "Договорная"
                salary_found = re.search(r'(\d[\d\s\.]*)\s?(руб|р\.|₽|\$|€|usd|eur|к)', msg.text.lower())
                if salary_found: pay = salary_found.group(0).strip()

                results.append({
                    'id': f"tg_{channel}_{msg.id}",
                    'Дата': msg.date.strftime('%Y-%m-%d'),
                    'Источник': f'TG: {channel}',
                    'Вакансия': query.capitalize(),
                    'Компания': channel,
                    'Оплата': pay,
                    'Ссылка': f"https://t.me/{channel}/{msg.id}",
                    'snippet': msg.text[:120].replace('\n', ' ') # Короткое описание для чата
                })
        except: continue
    return results
    
def search_hh(query, limit=100):
    url = f"https://api.hh.ru/vacancies?text={query}&search_field=name&area=1&per_page={limit}&order_by=publication_time"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            # СНАЧАЛА СЧИТАЕМ PAY
            sal = v.get('salary')
            pay = f"от {sal['from']}" if sal and sal['from'] else "Договорная"
            
            # ПОТОМ ИСПОЛЬЗУЕМ
            results.append({
                'id': f"hh_{v['id']}",
                'text': f"🔴 HH: {v['name']}\n💰 {pay} | 📅 {v['published_at'][:10]}\n{v['alternate_url']}",
                'Дата': v['published_at'][:10],
                'Источник': 'HH', 'Вакансия': v['name'], 'Компания': v['employer']['name'], 'Оплата': pay, 'Ссылка': v['alternate_url']
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
            
            results.append({
                'id': f"sj_{v['id']}",
                'text': f"🔵 SJ: {v['profession']}\n💰 {pay} | 📅 {datetime.fromtimestamp(v['date_published']).strftime('%d.%m')}\n{v['link']}",
                'Дата': datetime.fromtimestamp(v['date_published']).strftime('%Y-%m-%d'),
                'Источник': 'SuperJob', 'Вакансия': v['profession'], 'Компания': v['client'].get('title', '—'), 'Оплата': pay, 'Ссылка': v['link']
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
                
                # Сохраняем в нашем эталонном формате
                results.append({
                    'id': f"hb_{link.split('/')[-1]}", # Берем ID вакансии из URL
                    'text': f"🟢 Habr: {title}\n💰 {pay} | 📅 Сегодня\n{link}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'), # Хабр пишет "вчера/сегодня", для Excel ставим текущую
                    'Источник': 'Habr',
                    'Вакансия': title,
                    'Компания': company,
                    'Оплата': pay,
                    'Ссылка': link
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
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        # Ищем карточки вакансий
        items = soup.find_all('li', class_='vacancy-card')
        for i in items[:limit]:
            a = i.find('a', class_='vacancy-name')
            if a:
                title = a.text.strip()
                link = "https://geekjob.ru" + a['href']
                company = i.find('div', class_='company-name').text.strip() if i.find('div', class_='company-name') else "—"
                pay = i.find('span', class_='salary').text.strip() if i.find('span', class_='salary') else "Договорная"
                
                results.append({
                    'id': f"gj_{link.split('/')[-1]}",
                    'text': f"👨‍💻 GeekJob: {title}\n💰 {pay} | {company}\n{link}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'GeekJob', 'Вакансия': title, 'Компания': company, 'Оплата': pay, 'Ссылка': link
                })
    except: pass
    return results

def search_jobfilter(query, limit=10):
    url = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        # Пытаемся найти карточки (у них часто меняются классы)
        items = soup.select('.vacancy_item, .vacancy-item, [class*="vacancy"]')
        
        for i in items[:limit]:
            a = i.find('a')
            if not a: continue
            
            title = a.text.strip()
            link = a['href'] if a['href'].startswith('http') else "https://jobfilter.ru" + a['href']
            
            # Пытаемся найти компанию и оплату в соседних тегах
            salary = i.find(text=re.compile(r'\d')) if i.find(text=re.compile(r'\d')) else "—"

            results.append({
                'id': f"jf_{hash(link)}", # Безопасный ID
                'text': f"🌐 **JobFilter**: {title}\n{link}",
                'Дата': datetime.now().strftime('%Y-%m-%d'),
                'Источник': 'JobFilter',
                'Вакансия': title,
                'Компания': '—',
                'Оплата': 'См. на сайте',
                'Ссылка': link
            })
    except Exception as e:
        logging.error(f"JobFilter error: {e}")
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
            # 1. Очищаем данные и убираем технические поля (id, text)
            raw_data.append({
                'Дата': str(item.get('Дата', '—')),
                'Источник': str(item.get('Источник', '—')),
                'Вакансия': str(item.get('Вакансия', '—')),
                'Компания': str(item.get('Компания', '—')),
                'Оплата': str(item.get('Оплата', '—')),
                'Ссылка': str(item.get('Ссылка', '—'))
            })

        df = pd.DataFrame(raw_data)
        
        # 2. Умная сортировка по дате
        if not df.empty:
            # Создаем временную колонку для правильного сравнения дат
            df['TempDate'] = pd.to_datetime(df['Дата'], errors='coerce')
            df = df.sort_values(by='TempDate', ascending=False)
            df = df.drop(columns=['TempDate']) 

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Вакансии')
            ws = writer.sheets['Вакансии']
            
            # 3. Настройка оформления и ссылок
            header_fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            link_font = Font(color="0000FF", underline="single") # Синий цвет для ссылок
            
            # Находим индекс колонки "Ссылка"
            link_col_idx = df.columns.get_loc("Ссылка") + 1 if "Ссылка" in df.columns else None

            for col_num, column in enumerate(df.columns):
                # Оформляем шапку
                cell = ws.cell(row=1, column=col_num + 1)
                cell.fill = header_fill
                cell.font = header_font
                
                # Устанавливаем ширину колонок
                col_letter = chr(65 + col_num)
                if column == 'Ссылка':
                    ws.column_dimensions[col_letter].width = 45
                elif column == 'Вакансия':
                    ws.column_dimensions[col_letter].width = 40
                else:
                    ws.column_dimensions[col_letter].width = 20

            # 4. Делаем ссылки кликабельными
            if link_col_idx:
                for row in range(2, len(df) + 2):
                    cell = ws.cell(row=row, column=link_col_idx)
                    if cell.value and str(cell.value).startswith('http'):
                        cell.hyperlink = cell.value
                        cell.font = link_font

            # Закрепляем первую строку
            ws.freeze_panes = 'A2'
            
        output.seek(0)
        return output
    except Exception as e:
        logging.error(f"Критическая ошибка Excel: {e}")
        return None

# --- ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    name = message.from_user.first_name
    await message.answer(
        f"Привет, {name}! 🎬 Я — твой персональный агент по поиску работы в кино и медиа.\n\n"
        f"**Что я умею:**\n"
        f"🔍 **Мгновенный поиск:** Напиши название профессии, и я тут же перерою HH.ru, SuperJob, Habr и JobFilter.\n"
        f"📂 **Excel-отчеты:** На каждый запрос я присылаю файл с 50 свежими вакансиями.\n"
        f"⚡️ **Live-мониторинг:** Я читаю Telegram-каналы в реальном времени.\n\n"
        f"**Как запустить авто-поиск:**\n"
        f"1️⃣ Напиши ключевое слово, например: `режиссер` или `продюсер`.\n"
        f"2️⃣ Под результатом поиска нажми кнопку **«🔔 Подписаться»**.\n"
        f"3️⃣ Всё! Как только в каналах или на сайтах появится вакансия с этим словом — я мгновенно пришлю её тебе в личку.\n\n"
        f"💡 **Совет:** Подписывайся на короткие слова (например, `режиссер`), чтобы я ловил все склонения: *«ищем режиссера»*, *«нужны режиссеры»*.\n\n"
        f"Что ищем сегодня?",
        parse_mode="Markdown"
    )

@dp.message_handler(commands=['mysubs'])
async def list_subs(message: types.Message):
    try:
        # Подключаемся к базе
        conn = sqlite3.connect('manager.db')
        # Проверяем наличие таблицы, чтобы не было вылета
        conn.execute('CREATE TABLE IF NOT EXISTS subs (user_id INTEGER, keyword TEXT, UNIQUE(user_id, keyword))')
        
        data = conn.execute('SELECT keyword FROM subs WHERE user_id = ?', (message.from_user.id,)).fetchall()
        conn.close()
        
        if not data:
            await message.answer(
                "У тебя пока нет активных подписок. 🤷‍♂️\n\n"
                "Напиши профессию и нажми кнопку «Подписаться» под результатами поиска.",
                parse_mode="Markdown"
            )
        else:
            # Используем экранирование, чтобы Markdown не ломался от спецсимволов
            subs_list = "\n".join([f"✅ `{str(row[0])}`" for row in data])
            text = (
                "🔔 **Твои активные подписки:**\n\n"
                f"{subs_list}\n\n"
                "---\n"
                "🗑 Чтобы удалить: `/del слово`"
            )
            await message.answer(text, parse_mode="Markdown")
            
    except Exception as e:
        logging.error(f"Ошибка в mysubs: {e}")
        await message.answer("⚠ Ошибка при чтении списка подписок. Попробуй позже.")

@dp.message_handler(commands=['del'])
async def del_sub(message: types.Message):
    # Извлекаем слово, которое идет после команды /del
    keyword = message.get_args().lower().strip()
    
    if not keyword:
        await message.answer(
            "⚠ Нужно указать слово для удаления.\n\nПример: `/del режиссер`", 
            parse_mode="Markdown"
        )
        return
        
    conn = sqlite3.connect('manager.db')
    # Проверяем, была ли такая подписка
    res = conn.execute('SELECT 1 FROM subs WHERE user_id = ? AND keyword = ?', (message.from_user.id, keyword)).fetchone()
    
    if res:
        conn.execute('DELETE FROM subs WHERE user_id = ? AND keyword = ?', (message.from_user.id, keyword))
        conn.commit()
        await message.answer(f"❌ Подписка на слово '{keyword}' удалена. Я больше не буду присылать по нему уведомления.")
    else:
        await message.answer(f"🤔 У тебя нет активной подписки на слово '{keyword}'. Проверь список командой /mysubs")
    conn.close()

@dp.message_handler(commands=['stop_all'])
async def clear_subs(message: types.Message):
    conn = sqlite3.connect('manager.db')
    conn.execute('DELETE FROM subs WHERE user_id = ?', (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("📴 Мониторинг остановлен. Все твои подписки были успешно удалены.")

@dp.message_handler()
async def manual_search(message: types.Message):
    if message.text.startswith('/'): return
    
    query = message.text
    # Используем HTML-разметку (<b>, <i>, <code>)
    status_msg = await message.answer(f"🔎 <b>Ищу вакансии по запросу:</b> <code>{query}</code>...", parse_mode="HTML")
    
    all_found = []
    seen_ids = set()

    # 1. Параллельный сбор с сайтов
    with suppress(MessageNotModified):
        await status_msg.edit_text("🌐 Опрашиваю сайты (HH, SuperJob, Habr, GeekJob)...", parse_mode="HTML")
    
    loop = asyncio.get_running_loop()
    try:
        tasks = [
            loop.run_in_executor(None, search_hh, query, 50),
            loop.run_in_executor(None, search_superjob, query, 30),
            loop.run_in_executor(None, search_habr, query, 20),
            loop.run_in_executor(None, search_jobfilter, query, 20)
        ]
        
        sites_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in sites_results:
            if isinstance(res, list):
                for job in res:
                    if job.get('id') and job['id'] not in seen_ids:
                        all_found.append(job)
                        seen_ids.add(job['id'])
            elif isinstance(res, Exception):
                logging.error(f"Ошибка парсера: {res}")
    except Exception as e:
        logging.error(f"Ошибка параллельного парсинга: {e}")

    # 2. Сбор из Telegram (Архивы)
    with suppress(MessageNotModified):
        await status_msg.edit_text(f"📡 Проверяю архивы каналов... (Найдено: <b>{len(all_found)}</b>)", parse_mode="HTML")
    
    try:
        tg_hist = await search_telegram_history(query)
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

    # 3. Вывод результатов
    # СОРТИРУЕМ ВСЁ НАЙДЕННОЕ ПО ДАТЕ (Сначала новые)
    all_found.sort(key=lambda x: x.get('Дата', ''), reverse=True)
    
    await status_msg.edit_text("📤 <b>Отправляю самые свежие результаты...</b>", parse_mode="HTML")
    
    for j in all_found[:15]:
        try:
            v_src = j.get('Источник', '')
            # Возвращаем нормальные логотипы
            icon = "🔴" if "HH" in v_src else "🔵" if "SJ" in v_src else "🟢" if "Habr" in v_src else "📱"
            
            v_name = html.escape(str(j.get('Вакансия', '—')))
            v_pay = html.escape(str(j.get('Оплата', 'Договорная')))
            v_comp = html.escape(str(j.get('Компания', '—')))
            
            # Берем кусочек описания (если это ТГ, берем из сохраненного текста)
            # Мы добавим это поле в метод поиска ТГ чуть ниже
            v_desc = j.get('snippet', '') 

            pretty_text = (
                f"{icon} <b>{v_name}</b>\n"
                f"💰 <b>{v_pay}</b> | 🏢 {v_comp}\n"
                f"📝 {v_desc}...\n"
                f"🔗 <a href='{j['Ссылка']}'>Открыть вакансию</a>"
            )

            await message.answer(pretty_text, disable_web_page_preview=True, parse_mode="HTML")
            await asyncio.sleep(0.3)
        except: pass

    # 4. Финальный блок (Excel + Кнопка)
    try:
        excel_file = generate_excel(all_found)
        if excel_file:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}"))
            
            await message.answer_document(
                types.InputFile(excel_file, filename=f"Jobs_{query}.xlsx"),
                caption=f"✅ Поиск завершен!\nНайдено: <b>{len(all_found)}</b> вакансий.",
                reply_markup=kb,
                parse_mode="HTML"
            )
    except:
        await message.answer(f"✅ Найдено вакансий: {len(all_found)}")

    # Удаляем сообщение о поиске в конце
    await status_msg.delete()
    
async def handle(request):
    return web.Response(text="Bot is running!")

async def main(): # НИКАКИХ ОТСТУПОВ ПЕРЕД async
    init_db()
    
    # 1. Запуск Веб-сервера
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

    # 2. Запуск мониторинга каналов
    try:
        await client.start()
        logging.info("Telethon запущен!")
    except Exception as e:
        logging.error(f"Telethon error: {e}")

    # 3. Бот
    # Если функции monitor_sites нет, закомментируй строку ниже:
    asyncio.create_task(monitor_sites()) 
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
