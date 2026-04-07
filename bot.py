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

# Твой расширенный список каналов
CHANNELS = [
    'vdhl_good', 'mediajobs_ru', 'kinorabochie', 'gigs_for_creatives', 
    'ru_tvjobs', 'work_in_media', 'promofox', 'creative_jobs',
    'moviestart_ru', 'se_cinema', 'grushamedia', 'teletet', 
    'cinemapeople', 'my_casting', 'distantsiya', 'rabota_v_production', 'v_kadre_za_kadrom'
]

client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}

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
    url = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page={limit}&order_by=publication_time"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            sal = v.get('salary')
            pay = f"от {sal['from']}" if sal and sal['from'] else "Договорная"
            results.append({
                'id': f"hh_{v['id']}",
                'text': f"🔴 HH: {v['name']}\n{v['alternate_url']}",
                'Дата': v['published_at'][:10],
                'Источник': 'HH',
                'Вакансия': v['name'],
                'Компания': v['employer']['name'],
                'Оплата': pay,
                'Ссылка': v['alternate_url']
            })
    except: pass
    return results

def search_trudvsem(query, limit=20):
    results = []
    try:
        url = f"https://opendata.trudvsem.ru/api/v1/vacancies/region/77?text={query}"
        r = requests.get(url, timeout=10).json()
        if r.get('results'):
            for v in r['results']['vacancies'][:limit]:
                vac = v['vacancy']
                results.append({
                    'id': f"tr_{vac['id']}",
                    'text': f"🔵 ТрудВсем: {vac['job-name']}\n{vac['vac_url']}",
                    'Дата': vac['modification-date'],
                    'Источник': 'ТрудВсем',
                    'Вакансия': vac['job-name'],
                    'Компания': vac['company']['name'],
                    'Оплата': vac.get('salary', 'Договорная'),
                    'Ссылка': vac['vac_url']
                })
    except: pass
    return results

def search_jobfilter(query, limit=20):
    url = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}&city=москва"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', class_='vacancy_item') or soup.find_all('div', class_='vacancy-item')
        for i in items[:limit]:
            a = i.find('a')
            if a:
                results.append({
                    'id': f"jf_{a['href'][-10:]}",
                    'text': f"🌐 JF: {a.text.strip()}\nhttps://jobfilter.ru{a['href']}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'JobFilter',
                    'Вакансия': a.text.strip(),
                    'Компания': '—',
                    'Оплата': 'См. на сайте',
                    'Ссылка': "https://jobfilter.ru" + a['href'] if not a['href'].startswith('http') else a['href']
                })
    except: pass
    return results

# --- КРАСИВЫЙ EXCEL ---
def generate_excel(data):
    df = pd.DataFrame(data).drop(columns=['id', 'text'])
    df['Дата'] = pd.to_datetime(df['Дата'], errors='coerce').dt.date
    df = df.sort_values(by='Дата', ascending=False)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Вакансии')
        ws = writer.sheets['Вакансии']
        header_fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True, size=12)
        for col_num, value in enumerate(df.columns.values):
            cell = ws.cell(row=1, column=col_num + 1)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')
            ws.column_dimensions[chr(65 + col_num)].width = 40
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
    output.seek(0)
    return output

# --- МОНИТОРИНГ ---
@client.on(events.NewMessage(chats=CHANNELS))
async def telethon_handler(event):
    text = event.message.message
    if not text: return
    subs = get_all_subs()
    matched_users = [user_id for user_id, kw in subs if kw in text.lower()]
    if matched_users:
        if is_new_job(f"tg_{event.chat_id}_{event.id}"):
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', 'Канал')
            for uid in set(matched_users):
                try:
                    await bot.send_message(uid, f"⚡️ **ГОРЯЧАЯ ВАКАНСИЯ: {chat_title}**\n\n{text[:3500]}")
                except: pass

async def monitor_sites():
    while True:
        try:
            subs = get_all_subs()
            for user_id, kw in subs:
                all_found = search_hh(kw, 3) + search_trudvsem(kw, 3) + search_jobfilter(kw, 3)
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
        f"Привет, {name}! 👋\n\nЯ ищу вакансии для кино и медиа.\n"
        f"Напиши профессию (например: `режиссер`), и я пришлю ссылки + Excel.\n\n"
        f"Как только по твоим подпискам выйдет пост в Telegram-каналах — я пришлю его мгновенно!",
        parse_mode="Markdown")

@dp.message_handler()
async def manual_search(message: types.Message):
    query = message.text
    wait = await message.answer(f"🔎 Ищу вакансии по запросу: {query}...")
    
    found = search_hh(query, 100) + search_trudvsem(query, 20) + search_jobfilter(query, 10)
    
    if not found:
        await wait.edit_text("Ничего не найдено.")
        return

    # ВЫДАЧА В ТГ (Твой эталонный стиль)
    for j in found[:10]:
        await message.answer(j['text'], disable_web_page_preview=True)
        await asyncio.sleep(0.1)

    # ВЫДАЧА EXCEL
    excel_file = generate_excel(found)
    await message.answer_document(types.InputFile(excel_file, filename=f"{query}.xlsx"), caption=f"📊 Полный отчет по '{query}'")

    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}"))
    await message.answer("Включить авто-мониторинг этого запроса?", reply_markup=kb)
    await wait.delete()

@dp.callback_query_handler(lambda c: c.data.startswith('sub|'))
async def sub_handler(cb: types.CallbackQuery):
    kw = cb.data.split('|')[1]
    add_subscription(cb.from_user.id, kw)
    await bot.answer_callback_query(cb.id, "Подписка оформлена!", show_alert=True)

# --- ЗАПУСК ДЛЯ RENDER ---
async def handle(request): return web.Response(text="Alive")

async def main():
    init_db()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()
    asyncio.create_task(monitor_sites())
    await client.start()
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
