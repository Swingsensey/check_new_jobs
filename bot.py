import os
import asyncio
import logging
import requests
import sqlite3
import pandas as pd
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from datetime import datetime
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
# ID можно взять у @userinfobot. Если не укажете, бот просто не будет слать авто-уведомления
MY_ID = os.getenv('MY_ID') 

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('seen_jobs.db')
    conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY)')
    conn.commit()
    conn.close()

def is_new(job_id):
    conn = sqlite3.connect('seen_jobs.db')
    res = conn.execute('SELECT 1 FROM jobs WHERE id = ?', (job_id,)).fetchone()
    if not res:
        conn.execute('INSERT INTO jobs VALUES (?)', (job_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# --- ПАРСЕР HH ---
async def check_hh():
    keywords = ['режиссер', 'креативный продюсер', 'режиссер youtube']
    new_jobs = []
    for kw in keywords:
        url = f"https://api.hh.ru/vacancies?text={kw}&area=1&order_by=publication_time"
        try:
            r = requests.get(url, timeout=10).json()
            for v in r.get('items', [])[:5]:
                if is_new(f"hh_{v['id']}"):
                    new_jobs.append(f"🆕 **{v['name']}**\n{v['alternate_url']}")
        except: pass
    return new_jobs

# --- ФОНОВАЯ ЗАДАЧА ---
async def monitor():
    while True:
        if MY_ID:
            jobs = await check_hh()
            for j in jobs:
                await bot.send_message(MY_ID, j)
        await asyncio.sleep(1800) # Проверка каждые 30 минут

# --- ВЕБ-СЕРВЕР (ДЛЯ АНТИ-СНА) ---
async def handle(request):
    return web.Response(text="I am awake")

async def start_background_tasks(app):
    asyncio.create_task(monitor())

# --- ЗАПУСК ---
if __name__ == '__main__':
    init_db()
    
    app = web.Application()
    app.router.add_get('/', handle)
    app.on_startup.append(start_background_tasks)
    
    # Render использует порт из переменной окружения PORT
    port = int(os.environ.get("PORT", 8080))
    
    # Запуск и бота, и веб-сервера
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling())
    web.run_app(app, port=port)
