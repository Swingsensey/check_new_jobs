import os
import asyncio
import logging
import requests
import sqlite3
import pandas as pd
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from bs4 import BeautifulSoup
from aiohttp import web
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
API_ID = 23009673
API_HASH = '249328ef42a91e5c80102c3d73c76a9c'
SESSION_STR = os.getenv('TELEGRAM_SESSION')

# Каналы для мониторинга
CHANNELS = ['vdhl_good', 'mediajobs_ru', 'kinorabochie', 'gigs_for_creatives', 'ru_tvjobs']

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

# Юзербот для чтения каналов
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('manager.db')
    conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE IF NOT EXISTS subs (user_id INTEGER, keyword TEXT, UNIQUE(user_id, keyword))')
    conn.commit()
    conn.close()

def get_subs_for_text(text):
    """Проверяет, есть ли в тексте ключевые слова из подписок"""
    conn = sqlite3.connect('manager.db')
    subs = conn.execute('SELECT user_id, keyword FROM subs').fetchall()
    conn.close()
    
    matching_users = []
    text_lower = text.lower()
    for user_id, kw in subs:
        if kw in text_lower:
            matching_users.append(user_id)
    return list(set(matching_users))

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

# --- МОНИТОРИНГ КАНАЛОВ (Telethon) ---
@client.on(events.NewMessage(chats=CHANNELS))
async def handler(event):
    text = event.message.message
    users_to_notify = get_subs_for_text(text)
    
    if users_to_notify:
        # Убираем дубли по ID сообщения
        if is_new_job(f"tg_{event.chat_id}_{event.id}"):
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', 'Канал')
            
            for user_id in users_to_notify:
                try:
                    await bot.send_message(
                        user_id, 
                        f"⚡️ **ГОРЯЧАЯ ВАКАНСИЯ ИЗ КАНАЛА: {chat_title}**\n\n{text[:3500]}...", 
                        parse_mode="Markdown"
                    )
                except: pass

# --- ПАРСЕРЫ САЙТОВ ---
def fetch_sites_data(query, limit=50):
    all_jobs = []
    # HH.ru
    try:
        url = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page={limit}&order_by=publication_time"
        r = requests.get(url, timeout=10).json()
        for v in r.get('items', []):
            all_jobs.append({
                'id': f"hh_{v['id']}", 'Дата': v['published_at'][:10],
                'Источник': 'HH.ru', 'Вакансия': v['name'], 'Ссылка': v['alternate_url']
            })
    except: pass
    
    # ТрудВсем
    try:
        url = f"https://opendata.trudvsem.ru/api/v1/vacancies/region/77?text={query}"
        r = requests.get(url, timeout=10).json()
        if r.get('results'):
            for v in r['results']['vacancies'][:20]:
                vac = v['vacancy']
                all_jobs.append({
                    'id': f"tr_{vac['id']}", 'Дата': vac['modification-date'],
                    'Источник': 'ТрудВсем', 'Вакансия': vac['job-name'], 'Ссылка': vac['vac_url']
                })
    except: pass
    
    all_jobs.sort(key=lambda x: x['Дата'], reverse=True)
    return all_jobs[:limit]

# --- ОБРАБОТЧИКИ БОТА ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(f"Привет, {message.from_user.first_name}! 👋\nЯ ищу вакансии везде: на сайтах и в ТОП-каналах киноиндустрии.\n\nПросто напиши профессию.")

@dp.message_handler()
async def search(message: types.Message):
    query = message.text
    wait = await message.answer(f"🔎 Ищу вакансии: *{query}*...", parse_mode="Markdown")
    
    data = fetch_sites_data(query)
    for j in data[:7]:
        await message.answer(f"🔴 {j['Источник']}: {j['Вакансия']}\n{j['Ссылка']}", disable_web_page_preview=True)
    
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔔 Подписаться", callback_data=f"sub|{query}"))
    await message.answer(f"Найдено {len(data)} вакансий. Включить авто-мониторинг сайтов и каналов?", reply_markup=kb)
    await wait.delete()

@dp.callback_query_handler(lambda c: c.data.startswith('sub|'))
async def sub(cb: types.CallbackQuery):
    kw = cb.data.split('|')[1]
    conn = sqlite3.connect('manager.db')
    conn.execute('INSERT OR IGNORE INTO subs (user_id, keyword) VALUES (?, ?)', (cb.from_user.id, kw.lower()))
    conn.commit()
    conn.close()
    await bot.answer_callback_query(cb.id, f"Подписка на {kw} активна!", show_alert=True)

# --- ВЕБ-СЕРВЕР И ЗАПУСК ---
async def handle(request): return web.Response(text="Alive")

async def main():
    init_db()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

    # Запускаем Юзербота и Бот одновременно
    await client.start()
    logging.info("Userbot started!")
    
    # Фоновая задача мониторинга сайтов
    async def monitor_sites():
        while True:
            await asyncio.sleep(1800)
            # Логика поиска по подпискам (аналогично предыдущим версиям)
            
    asyncio.create_task(monitor_sites())
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())
