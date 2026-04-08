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
    'vdhl_good', 'mediajobs_ru', 'work_in_media',
    'moviestart_ru', 'distantsiya'
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
def search_hh(query, limit=100):
    # Добавлен параметр search_field=name для чистоты поиска
    url = f"https://api.hh.ru/vacancies?text={query}&search_field=name&area=1&per_page={limit}&order_by=publication_time"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            results.append({
                'id': f"hh_{v['id']}",
                'text': f"🔴 HH: {v['name']}\n💰 {pay} | 📅 {v['published_at'][:10]}\n{v['alternate_url']}",
                'Дата': v['published_at'][:10],
                'Источник': 'HH', 'Вакансия': v['name'], 'Компания': v['employer']['name'], 'Оплата': 'Договорная', 'Ссылка': v['alternate_url']
            })
    except: pass
    return results

def search_superjob(query, limit=50):
    if not SJ_KEY: return [] # Исправлено имя переменной!
    url = f"https://api.superjob.ru/2.0/vacancies/?keyword={query}&town=4&count={limit}"
    headers = {'X-Api-App-Id': SJ_KEY}
    results = []
    try:
        r = requests.get(url, headers=headers, timeout=10).json()
        for v in r.get('objects', []):
            results.append({
                'id': f"sj_{v['id']}",
                'text': f"🔵 SJ: {v['profession']}\n💰 {pay} | 📅 {datetime.fromtimestamp(v['date_published']).strftime('%d.%m')}\n{v['link']}",
                'Дата': datetime.fromtimestamp(v['date_published']).strftime('%Y-%m-%d'),
                'Источник': 'SuperJob', 'Вакансия': v['profession'], 'Компания': v['client'].get('title', '—'), 'Оплата': 'Договорная', 'Ссылка': v['link']
            })
    except: pass
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
            results.append({
                'id': f"jf_{a['href']}",
                'text': f"🌐 **JF: {a.text.strip()}**\nhttps://jobfilter.ru{a['href']}"
            })
    except: pass
    return results

@client.on(events.NewMessage()) # ОСТАВЬ СКОБКИ ПУСТЫМИ!
async def telethon_handler(event):
    try:
        chat = await event.get_chat()
        username = getattr(chat, 'username', None)
        
        # Фильтруем только нужные каналы здесь, чтобы не было ошибок
        if not username or username not in CHANNELS:
            return

        text = event.message.message
        if not text: return

        subs = get_all_subs()
        matched_users = [user_id for user_id, kw in subs if kw in text.lower()]
        
        if matched_users:
            if is_new_job(f"tg_{event.chat_id}_{event.id}"):
                for uid in set(matched_users):
                    try:
                        await bot.send_message(uid, f"⚡️ **КАНАЛ: {getattr(chat, 'title', 'Media')}**\n\n{text[:3500]}")
                    except: pass
    except: pass

def generate_excel(data):
    # Метод теперь просто оформляет таблицу из уже найденных вакансий
    try:
        raw_data = []
        for item in data:
            raw_data.append({
                'Дата': item['Дата'], 'Источник': item['Источник'],
                'Вакансия': item['Вакансия'], 'Компания': item['Компания'],
                'Оплата': item['Оплата'], 'Ссылка': item['Ссылка']
            })

        df = pd.DataFrame(raw_data)
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

async def monitor_sites():
    while True:
        try:
            subs = get_all_subs()
            for user_id, kw in subs:
                # Проверяем по 3 штуки из каждого ТОП источника
                all_found = search_hh(kw, 3) + search_superjob(kw, 3) + search_habr(kw, 3)
                for job in all_found:
                    if is_new_job(job['id']):
                        await bot.send_message(user_id, f"🔔 Новинка по подписке [{kw.upper()}]:\n\n{job['text']}")
                        await asyncio.sleep(0.5)
        except: pass
        await asyncio.sleep(1800)

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
    
    # Сбор данных с защитой от сбоев
    hh = []
    try: hh = search_hh(query, 100)
    except: pass
    
    sj = []
    try: sj = search_superjob(query, 50)
    except: pass
    
    hb = []
    try: hb = search_habr(query, 20)
    except: pass
    
    jf = []
    try: jf = search_jobfilter(query, 10)
    except: pass
    
    all_found = hh + sj + hb + jf
    
    if not all_found:
        await wait.edit_text("Ничего не найдено. Попробуй другое слово.")
        return

    # 1. Твой эталонный стиль в чат (Топ-10)
    top_mix = hh[:5] + sj[:3] + hb[:2]
    for j in top_mix:
        icon = "🔴" if "HH" in j['Источник'] else "🔵" if "SJ" in j['Источник'] else "🟢"
        msg = f"{icon} {j['Источник']}: {j['Вакансия']}\n{j['Ссылка']}"
        await message.answer(msg, disable_web_page_preview=True)
        await asyncio.sleep(0.1)

    # 2. Идеальный синий Excel (теперь он не виснет)
    try:
        excel_file = generate_excel(all_found)
        if excel_file:
            await message.answer_document(
                types.InputFile(excel_file, filename=f"{query}.xlsx"), 
                caption=f"📊 Полный отчет по запросу '{query}'"
            )
    except:
        await message.answer("⚠️ Файл создается, подождите...")

    # 3. Кнопка подписки
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔔 Подписаться", callback_data=f"sub|{query}"))
    await message.answer(f"Включить авто-мониторинг для '{query}'?", reply_markup=kb)
    await wait.delete()

async def main():
    init_db()
    
    # 1. Запуск Веб-сервера (для Render)
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()

    # 2. Запускаем чтение каналов (ДОЛЖНО БЫТЬ ПЕРЕД БОТОМ)
    await client.start()
    logging.info("Мониторинг Telegram-каналов запущен!")

    # 3. Запуск фонового мониторинга сайтов
    asyncio.create_task(monitor_sites())
    
    # 4. Запуск бота (ЭТА СТРОКА ВСЕГДА ПОСЛЕДНЯЯ)
    logging.info("Бот запущен и слушает сообщения...")
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
