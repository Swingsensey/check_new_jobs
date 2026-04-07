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

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
API_ID = 23009673
API_HASH = '249328ef42a91e5c80102c3d73c76a9c'
SESSION_STR = os.getenv('TELEGRAM_SESSION')
# Список каналов БЕЗ собаки @
CHANNELS = [
    # Твой основной список
    'vdhl_good', 'mediajobs_ru', 'kinorabochie', 'gigs_for_creatives', 
    'ru_tvjobs', 'work_in_media', 'promofox', 'creative_jobs',
    
    # Твой дополнительный список
    'moviestart_ru', 'se_cinema', 'grushamedia', 'teletet', 
    'cinemapeople', 'my_casting',
    
    # ТОП-3 дополнения для коммерческого режима и продакшна (рекомендую!)
    'distantsiya',           # Дистанция (огромный канал с креативом)
    'rabota_v_production',   # Работа в продакшне (самое мясо по съемкам)
    'v_kadre_za_kadrom'      # В кадре и за кадром (вакансии съемочных групп)
]

# Создаем клиента для чтения каналов
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

# Список каналов для мониторинга (добавь свои)
CHANNELS = ['@vdhl_good', '@mediajobs_ru', '@kinorabochie', '@gigs_for_creatives']

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
def search_hh(query, limit=5):
    url = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page={limit}&order_by=publication_time"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            results.append({
                'id': f"hh_{v['id']}",
                'text': f"🔴 **HH: {v['name']}**\n{v['alternate_url']}"
            })
    except: pass
    return results

def search_trudvsem(query, limit=5):
    results = []
    try:
        url = f"https://opendata.trudvsem.ru/api/v1/vacancies/region/77?text={query}"
        r = requests.get(url, timeout=10).json()
        if r.get('results'):
            for v in r['results']['vacancies'][:limit]:
                vac = v['vacancy']
                results.append({
                    'id': f"tr_{vac['id']}",
                    'text': f"🔵 **ТрудВсем: {vac['job-name']}**\n{vac['vac_url']}"
                })
    except: pass
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

@client.on(events.NewMessage(chats=CHANNELS))
async def telethon_handler(event):
    text = event.message.message
    if not text:
        return

    # Получаем все подписки из базы
    subs = get_all_subs()
    
    # Проверяем, есть ли ключевое слово в тексте сообщения
    matched_users = []
    text_lower = text.lower()
    for user_id, keyword in subs:
        if keyword in text_lower:
            matched_users.append(user_id)
            
    if matched_users:
        # Генерируем уникальный ID для сообщения, чтобы не дублировать
        job_id = f"tg_{event.chat_id}_{event.id}"
        if is_new_job(job_id):
            # Получаем название канала
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', 'Telegram Канал')
            
            for uid in set(matched_users):
                try:
                    msg = f"⚡️ **ГОРЯЧАЯ ВАКАНСИЯ ИЗ КАНАЛА: {chat_title}**\n\n{text[:3500]}"
                    await bot.send_message(uid, msg, parse_mode="Markdown")
                except:
                    pass

# --- МОНИТОРИНГ САЙТОВ ---
async def monitor_sites():
    while True:
        try:
            subs = get_all_subs()
            for user_id, kw in subs:
                all_found = search_hh(kw, 3) + search_trudvsem(kw, 3) + search_jobfilter(kw, 3)
                for job in all_found:
                    if is_new_job(job['id']):
                        await bot.send_message(user_id, f"🔔 Новинка по вашей подписке [{kw.upper()}]:\n\n{job['text']}", parse_mode="Markdown")
                        await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Error in monitor: {e}")
        await asyncio.sleep(1800)

# --- ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    name = message.from_user.first_name
    await message.answer(
        f"Привет, {name}! 🎬 Я — твой персональный агент по поиску работы в кино и медиа.\n\n"
        f"**Что я умею:**\n"
        f"🔍 **Мгновенный поиск:** Напиши название профессии, и я тут же перерою HH.ru, ТрудВсем и JobFilter.\n"
        f"📂 **Excel-отчеты:** На каждый запрос я присылаю файл с 50 свежими вакансиями.\n"
        f"⚡ **Live-мониторинг:** Я читаю 17+ элитных Telegram-каналов (*VDHL, Кинорабочие, Gigs for Creatives* и др.) в реальном времени.\n\n"
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
    await message.answer(f"🔎 Ищу вакансии по запросу: *{query}*...", parse_mode="Markdown")
    
    found = search_hh(query) + search_trudvsem(query) + search_jobfilter(query)
    
    if not found:
        await message.answer("Ничего не найдено.")
        return

    for j in found:
        await message.answer(j['text'], parse_mode="Markdown")
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}"))
    await message.answer("Включить авто-мониторинг этого запроса?", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('sub|'))
async def sub_handler(callback_query: types.CallbackQuery):
    query = callback_query.data.split('|')[1]
    add_subscription(callback_query.from_user.id, query)
    await bot.answer_callback_query(callback_query.id, f"Подписка оформлена!", show_alert=True)
    await bot.send_message(callback_query.from_user.id, f"✅ Готово! Мониторю '{query}' везде.")

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Bot is Alive")

async def main():
    init_db()
    
    # Запуск Веб-сервера (чтобы Render не убивал бота)
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()

    # Запуск фонового мониторинга сайтов
    asyncio.create_task(monitor_sites())
    
    # Запуск бота
    await dp.start_polling()
    # Запускаем чтение каналов
    await client.start()
    logging.info("Мониторинг Telegram-каналов запущен!")

if __name__ == '__main__':
    asyncio.run(main())
