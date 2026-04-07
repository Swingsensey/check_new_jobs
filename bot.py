import os
import asyncio
import logging
import requests
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from bs4 import BeautifulSoup

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
}

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('manager.db')
    # Таблица вакансий
    conn.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY)')
    # Таблица подписок (кто на какое слово подписан)
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
    url = f"https://api.hh.ru/vacancies?text={query}&area=1&order_by=publication_time"
    results = []
    try:
        r = requests.get(url, timeout=10).json()
        for v in r.get('items', [])[:limit]:
            results.append({
                'id': f"hh_{v['id']}",
                'text': f"🔴 **HH: {v['name']}**\n{v['alternate_url']}"
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

# --- ФОНОВЫЙ МОНИТОРИНГ ---
async def monitor():
    while True:
        subs = get_all_subs()
        for user_id, kw in subs:
            # Ищем на обеих площадках
            all_found = search_hh(kw, 3) + search_jobfilter(kw, 3)
            for job in all_found:
                if is_new_job(job['id']):
                    try:
                        await bot.send_message(user_id, f"🔔 Новинка по вашей подписке [{kw.upper()}]:\n\n{job['text']}", parse_mode="Markdown")
                        await asyncio.sleep(0.5)
                    except: pass
        await asyncio.sleep(1800) # 30 минут

# --- ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    name = message.from_user.first_name
    await message.answer(
        f"Привет, {name}! 👋\n\n"
        f"Я — поисковик вакансий для индустрии кино и медиа.\n\n"
        f"**Как со мной работать:**\n"
        f"1. Просто напиши мне профессию (например: `Креативный продюсер`).\n"
        f"2. Я выдам последние вакансии с HH и JobFilter.\n"
        f"3. Под результатом появится кнопка подписки — нажми её, и я буду присылать новые вакансии сам!\n\n"
        f"Что ищем сегодня?",
        parse_mode="Markdown"
    )

@dp.message_handler()
async def manual_search(message: types.Message):
    query = message.text
    await message.answer(f"🔎 Ищу вакансии по запросу: *{query}*...", parse_mode="Markdown")
    
    found = search_hh(query) + search_jobfilter(query)
    
    if not found:
        await message.answer("Ничего не найдено. Попробуй другое слово.")
        return

    for j in found:
        await message.answer(j['text'], parse_mode="Markdown")
    
    # Кнопка подписки
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}"))
    await message.answer("Хотите получать уведомления о новых вакансиях по этому запросу?", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('sub|'))
async def sub_handler(callback_query: types.CallbackQuery):
    query = callback_query.data.split('|')[1]
    add_subscription(callback_query.from_user.id, query)
    await bot.answer_callback_query(callback_query.id, f"Подписка оформлена!", show_alert=True)
    await bot.send_message(callback_query.from_user.id, f"✅ Готово! Теперь я мониторю '{query}' 24/7.")

if __name__ == '__main__':
    init_db()
    loop = asyncio.get_event_loop()
    loop.create_task(monitor())
    executor.start_polling(dp, skip_updates=True)
