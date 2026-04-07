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

# --- УЛУЧШЕННЫЕ ПАРСЕРЫ ---

def fetch_data(query, limit=50):
    all_jobs = []
    
    # 1. HH.RU - Ищем ТОЛЬКО в названии вакансии (search_field=name)
    try:
        url_hh = f"https://api.hh.ru/vacancies?text={query}&search_field=name&area=1&per_page={limit}&order_by=publication_time"
        r = requests.get(url_hh, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            sal = v.get('salary')
            pay = f"от {sal['from']}" if sal and sal['from'] else "Договорная"
            all_jobs.append({
                'id': f"hh_{v['id']}",
                'Дата': v['published_at'][:10],
                'Источник': 'HH.ru',
                'Вакансия': v['name'],
                'Компания': v['employer']['name'],
                'Оплата': pay,
                'Ссылка': v['alternate_url']
            })
    except Exception as e:
        logging.error(f"HH error: {e}")

    # 2. JobFilter - Парсинг
    try:
        url_jf = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}&city=москва"
        r = requests.get(url_jf, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', {'class': ['vacancy_item', 'vacancy-card', 'vacancy-item']})
        for i in items[:20]:
            a = i.find('a')
            if a:
                all_jobs.append({
                    'id': f"jf_{a['href']}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'JobFilter',
                    'Вакансия': a.text.strip(),
                    'Компания': '—',
                    'Оплата': 'См. на сайте',
                    'Ссылка': "https://jobfilter.ru" + a['href'] if not a['href'].startswith('http') else a['href']
                })
    except Exception as e:
        logging.error(f"JF error: {e}")
    
    # Удаляем дубли и сортируем
    unique_jobs = []
    seen = set()
    for j in all_jobs:
        if j['Ссылка'] not in seen:
            unique_jobs.append(j)
            seen.add(j['Ссылка'])
    
    unique_jobs.sort(key=lambda x: x['Дата'], reverse=True)
    return unique_jobs[:limit]

# --- КРАСИВЫЙ EXCEL ---
def generate_excel(data):
    df = pd.DataFrame(data).drop(columns=['id'])
    output = BytesIO()
    # Настройка стилей через ExcelWriter
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Вакансии')
        workbook = writer.book
        worksheet = writer.sheets['Вакансии']
        # Делаем заголовок жирным и настраиваем ширину колонок
        for col_num, value in enumerate(df.columns.values):
            column_len = max(df[value].astype(str).map(len).max(), len(value)) + 2
            worksheet.column_dimensions[chr(65 + col_num)].width = min(column_len, 50)
    output.seek(0)
    return output

# --- ФОНОВЫЙ МОНИТОРИНГ ---
async def monitor():
    while True:
        try:
            subs = get_all_subs()
            for user_id, kw in subs:
                found = fetch_data(kw, limit=5)
                for job in found:
                    if is_new_job(job['id']):
                        msg = (f"🔔 **Новая вакансия по подписке [{kw.upper()}]:**\n\n"
                               f"💼 {job['Вакансия']}\n💰 {job['Оплата']}\n📍 {job['Источник']}\n🔗 [Открыть]({job['Ссылка']})")
                        await bot.send_message(user_id, msg, parse_mode="Markdown")
                        await asyncio.sleep(0.5)
        except: pass
        await asyncio.sleep(1800)

# --- ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    name = message.from_user.first_name
    await message.answer(
        f"Привет, {name}! 👋\n\n"
        f"Я ищу вакансии **только по названиям**, чтобы выдавать самый релевантный результат.\n\n"
        f"**Механика:**\n"
        f"1. Пишешь запрос (напр. `режиссер рекламы`).\n"
        f"2. Получаешь 7 свежих ссылок сообщением.\n"
        f"3. Получаешь красивый Excel-отчет (50 вакансий).\n"
        f"4. Можешь подписаться на авто-мониторинг кнопкой.\n\n"
        f"Что ищем?", parse_mode="Markdown"
    )

@dp.message_handler()
async def search_handler(message: types.Message):
    query = message.text
    wait = await message.answer(f"🔎 Ищу вакансии по запросу: *{query}*...", parse_mode="Markdown")
    
    data = fetch_data(query, limit=50)
    if not data:
        await wait.edit_text("Ничего не найдено. Попробуй сократить запрос.")
        return

    # 1. Сообщения (Топ-7)
    await message.answer(f"🔝 **Самые свежие для чата:**", parse_mode="Markdown")
    for j in data[:7]:
        msg = f"📍 {j['Источник']} | {j['Дата']}\n💼 **{j['Вакансия']}**\n💰 {j['Оплата']}\n🔗 [Открыть]({j['Ссылка']})"
        await message.answer(msg, parse_mode="Markdown", disable_web_page_preview=True)
        await asyncio.sleep(0.2)

    # 2. Файл Excel
    file_data = generate_excel(data)
    await message.answer_document(
        types.InputFile(file_data, filename=f"{query}.xlsx"),
        caption=f"📊 Полный отчет по запросу '{query}'"
    )

    # 3. Кнопка подписки
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}"))
    await message.answer("Хотите получать новые вакансии по этому запросу автоматически?", reply_markup=kb)
    await wait.delete()

@dp.callback_query_handler(lambda c: c.data.startswith('sub|'))
async def sub_callback(cb: types.CallbackQuery):
    kw = cb.data.split('|')[1]
    add_subscription(cb.from_user.id, kw)
    await bot.answer_callback_query(cb.id, f"Подписка на {kw} оформлена!", show_alert=True)

# --- ВЕБ-СЕРВЕР (RENDER) ---
async def handle(request):
    return web.Response(text="Bot is alive")

async def main():
    init_db()
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()

    asyncio.create_task(monitor())
    await dp.start_polling(skip_updates=True)

if __name__ == '__main__':
    asyncio.run(main())
