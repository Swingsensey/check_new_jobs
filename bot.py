import os
import asyncio
import logging
import requests
import sqlite3
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
    'it_vakansii_jobs', 'workasap', 'forproducer', 'vacanciesrus'
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
async def search_telegram_history(query, limit_per_channel=5):
    results = []
    query_low = query.lower()
    for channel in CHANNELS:
        try:
            # Метод iter_messages просматривает последние сообщения в канале
            async for msg in client.iter_messages(channel, limit=limit_per_channel):
                if msg.text and query_low in msg.text.lower():
                    results.append({
                        'id': f"tg_hist_{channel}_{msg.id}",
                        'text': f"📱 TG [{channel}]: {msg.text[:400]}...\nhttps://t.me/{channel}/{msg.id}",
                        'Дата': msg.date.strftime('%Y-%m-%d') if msg.date else "Неизвестно",
                        'Источник': f'TG: {channel}',
                        'Вакансия': 'Архив канала',
                        'Компания': channel,
                        'Оплата': 'В посте',
                        'Ссылка': f"https://t.me/{channel}/{msg.id}"
                    })
        except Exception as e:
            logging.error(f"Ошибка поиска в архиве {channel}: {e}")
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

def search_jobfilter(query, limit=5):
    url = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}&city=москва"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', class_='vacancy_item') or soup.find_all('div', class_='vacancy-item')
        for i in items[:limit]:
            a = i.find('a')
            if a:
                link = "https://jobfilter.ru" + a['href'] if not a['href'].startswith('http') else a['href']
                results.append({
                    'id': f"jf_{a['href'][-10:]}",
                    'text': f"🌐 JF: {a.text.strip()}\n{link}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'), # Добавили поле
                    'Источник': 'JobFilter', # Добавили поле
                    'Вакансия': a.text.strip(), # Добавили поле
                    'Компания': '—', # Добавили поле
                    'Оплата': 'См. на сайте', # Добавили поле
                    'Ссылка': link
                })
    except: pass
    return results

@client.on(events.NewMessage(chats=CHANNELS))
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
        raw_data = []
        for item in data:
            # Используем .get(), чтобы бот не падал, если поля нет
            raw_data.append({
                'Дата': item.get('Дата', '—'),
                'Источник': item.get('Источник', '—'),
                'Вакансия': item.get('Вакансия', '—'),
                'Компания': item.get('Компания', '—'),
                'Оплата': item.get('Оплата', '—'),
                'Ссылка': item.get('Ссылка', '—')
            })

        df = pd.DataFrame(raw_data)
        if not df.empty and 'Дата' in df.columns:
            df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce').dt.date
            df = df.sort_values(by='Дата', ascending=False)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Вакансии')
            ws = writer.sheets['Вакансии']
            fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
            font = Font(color="FFFFFF", bold=True)
            for col_num in range(len(df.columns)):
                cell = ws.cell(row=1, column=col_num + 1)
                cell.fill = fill; cell.font = font
                ws.column_dimensions[chr(65 + col_num)].width = 35
            ws.freeze_panes = 'A2'
        output.seek(0)
        return output
    except Exception as e:
        logging.error(f"Excel error: {e}")
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

@dp.message_handler()
async def manual_search(message: types.Message):
    query = message.text
    wait = await message.answer(f"🔎 Ищу вакансии по запросу: {query}...")
    
    # 1. Сбор данных
    tg_hist = []
    try: tg_hist = await search_telegram_history(query, limit_per_channel=5)
    except: pass

    hh, sj, hb, jf = [], [], [], []
    try: hh = search_hh(query, 80)
    except: pass
    try: sj = search_superjob(query, 40)
    except: pass
    try: hb = search_habr(query, 30)
    except: pass
    try: jf = search_jobfilter(query, 20)
    except: pass
    
    # ФИЛЬТР ДУБЛИКАТОВ (чтобы одна и та же вакансия не вышла дважды)
    all_raw = tg_hist + hh + sj + hb + jf
    seen_ids = set()
    all_found = []
    for job in all_raw:
        if job['id'] not in seen_ids:
            all_found.append(job)
            seen_ids.add(job['id'])
    
    if not all_found:
        await wait.edit_text(f"По запросу '{query}' ничего не найдено.")
        return

    # 2. РАСПРЕДЕЛЕНИЕ (по 4 из каждого источника, но только уникальные)
    top_mix = []
    for source in [tg_hist, hh, sj, hb, jf]:
        added = 0
        for item in source:
            if added < 4 and item in all_found:
                top_mix.append(item)
                added += 1

    for j in top_mix[:20]:
        try:
            await message.answer(j['text'], disable_web_page_preview=True)
            await asyncio.sleep(0.2) 
        except: pass

    # 3. Excel-отчет
    excel_file = generate_excel(all_found)
    if excel_file:
        await message.answer_document(
            types.InputFile(excel_file, filename=f"{query}.xlsx"), 
            caption=f"📊 Найдено уникальных вакансий: {len(all_found)}\n(Собрано из сайтов и каналов)"
        )

    # 4. Кнопка подписки
    kb = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}")
    )
    await message.answer(f"Включить авто-мониторинг для '{query}'?", reply_markup=kb)
    await wait.delete()

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
    
async def handle(request): # Добавь это, чтобы веб-сервер работал
    return web.Response(text="OK")

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
