import asyncio
import logging
import sqlite3
import requests
from aiogram import Bot, Dispatcher, types
from bs4 import BeautifulSoup # Нужна установка: pip install beautifulsoup4

# Настройки
API_TOKEN = 'ВАШ_ТОКЕН'
CHAT_ID = 'ВАШ_ЛИЧНЫЙ_ID' # Бот будет слать уведомления именно вам
KEYWORDS = ['режиссер', 'креативный продюсер']

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('jobs.db')
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS sent_jobs (job_id TEXT PRIMARY KEY)')
    conn.commit()
    conn.close()

def is_new_job(job_id):
    conn = sqlite3.connect('jobs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM sent_jobs WHERE job_id = ?', (job_id,))
    exists = cursor.fetchone()
    if not exists:
        cursor.execute('INSERT INTO sent_jobs VALUES (?)', (job_id,))
        conn.commit()
    conn.close()
    return not exists

# --- ПАРСЕРЫ ---

async def check_hh():
    """Проверка HeadHunter"""
    new_items = []
    for query in KEYWORDS:
        url = f"https://api.hh.ru/vacancies?text={query}&area=1&order_by=publication_time"
        res = requests.get(url).json()
        for v in res.get('items', []):
            if is_new_job(f"hh_{v['id']}"):
                new_items.append(f"🔥 **Новое на HH: {v['name']}**\n{v['alternate_url']}")
    return new_items

async def check_jobfilter():
    """Пример парсинга JobFilter (упрощенно)"""
    new_items = []
    # Логика сбора данных через BeautifulSoup...
    # (Сайты без API требуют аккуратного написания селекторов)
    return new_items

# --- ФОНОВАЯ ЗАДАЧА ---
async def monitor_jobs():
    while True:
        logging.info("Проверка новых вакансий...")
        try:
            # Проверяем HH
            hh_jobs = await check_hh()
            for job_msg in hh_jobs:
                await bot.send_message(CHAT_ID, job_msg)
            
            # Сюда можно добавить авито и другие источники
            
        except Exception as e:
            logging.error(f"Ошибка мониторинга: {e}")
        
        await asyncio.sleep(1800) # Проверка каждые 30 минут

if __name__ == '__main__':
    init_db()
    loop = asyncio.get_event_loop()
    loop.create_task(monitor_jobs()) # Запуск фоновой проверки
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
