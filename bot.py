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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
}

# --- ЛОГИКА СБОРА ДАННЫХ ---
def get_all_jobs(query, limit=50):
    combined_data = []
    
    # 1. HH.ru
    try:
        url_hh = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page={limit}&order_by=publication_time"
        r = requests.get(url_hh, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            salary = v.get('salary')
            pay = f"от {salary['from']}" if salary and salary['from'] else "Договорная"
            combined_data.append({
                'Дата': v['published_at'][:10],
                'Источник': 'HH.ru',
                'Название': v['name'],
                'Компания': v['employer']['name'],
                'Оплата': pay,
                'Ссылка': v['alternate_url']
            })
    except Exception as e:
        logging.error(f"HH Error: {e}")

    # 2. JobFilter.ru
    try:
        url_jf = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}&city=москва"
        r = requests.get(url_jf, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', {'class': ['vacancy_item', 'vacancy-card', 'vacancy-item']})
        for i in items[:20]: # JobFilter берем чуть меньше для баланса
            a = i.find('a')
            if a:
                combined_data.append({
                    'Дата': datetime.now().strftime('%Y-%m-%d'), # JF не всегда дает дату, ставим сегодня
                    'Источник': 'JobFilter',
                    'Название': a.text.strip(),
                    'Компания': '—',
                    'Оплата': 'См. на сайте',
                    'Ссылка': "https://jobfilter.ru" + a['href'] if not a['href'].startswith('http') else a['href']
                })
    except Exception as e:
        logging.error(f"JF Error: {e}")

    # Сортировка: Сначала свежие
    combined_data.sort(key=lambda x: x['Дата'], reverse=True)
    return combined_data[:limit]

# --- ОБРАБОТЧИК ПОИСКА ---
@dp.message_handler()
async def search_and_send(message: types.Message):
    query = message.text
    if query.startswith('/'): return

    wait_msg = await message.answer(f"🚀 Ищу вакансии по запросу *{query}*...", parse_mode="Markdown")
    
    jobs = get_all_jobs(query)
    
    if not jobs:
        await wait_msg.edit_text("Ничего не найдено. Попробуй другой запрос.")
        return

    # 1. Отправляем первые 7 вакансий текстом
    await message.answer(f"🔝 **Топ-7 самых свежих вакансий:**", parse_mode="Markdown")
    for j in jobs[:7]:
        short_msg = (
            f"📍 {j['Источник']} | {j['Дата']}\n"
            f"💼 **{j['Название']}**\n"
            f"💰 {j['Оплата']}\n"
            f"🔗 [Откликнуться]({j['Ссылка']})"
        )
        await message.answer(short_msg, parse_mode="Markdown", disable_web_page_preview=True)
        await asyncio.sleep(0.2)

    # 2. Формируем и отправляем Excel со всеми остальными (50 шт)
    df = pd.DataFrame(jobs)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Вакансии')
    output.seek(0)
    
    filename = f"{query}_{datetime.now().strftime('%d-%m')}.xlsx"
    await message.answer_document(
        types.InputFile(output, filename=filename),
        caption=f"📂 Полный отчет: {len(jobs)} вакансий по запросу '{query}'."
    )
    await wait_msg.delete()

# --- ВЕБ-СЕРВЕР (ДЛЯ RENDER) ---
async def handle(request):
    return web.Response(text="Bot is running")

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(f"Привет, {message.from_user.first_name}! 🎬\nНапиши профессию, и я пришлю ссылки + Excel-файл.")

if __name__ == '__main__':
    app = web.Application()
    app.router.add_get('/', handle)
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling())
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, port=port)
