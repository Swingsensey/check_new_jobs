import os
import asyncio
import logging
import requests
import pandas as pd
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from bs4 import BeautifulSoup
from aiohttp import web
from datetime import datetime

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN')
# Проверяем токен в логах
if not TOKEN:
    logging.error("BOT_TOKEN НЕ НАЙДЕН В ПЕРЕМЕННЫХ ОКРУЖЕНИЯ!")

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
}

# --- ФУНКЦИИ ПОИСКА ---
def get_all_jobs(query, limit=50):
    combined_data = []
    # HH.ru
    try:
        url_hh = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page={limit}&order_by=publication_time"
        r = requests.get(url_hh, headers=HEADERS, timeout=10).json()
        for v in r.get('items', []):
            sal = v.get('salary')
            pay = f"от {sal['from']}" if sal and sal['from'] else "Договорная"
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

    # JobFilter (упрощенный поиск)
    try:
        url_jf = f"https://jobfilter.ru/vacancies?q={query.replace(' ', '+')}&city=москва"
        r = requests.get(url_jf, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        items = soup.find_all('div', {'class': ['vacancy_item', 'vacancy-card']})
        for i in items[:15]:
            a = i.find('a')
            if a:
                combined_data.append({
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'JobFilter',
                    'Название': a.text.strip(),
                    'Компания': '—',
                    'Оплата': 'См. на сайте',
                    'Ссылка': "https://jobfilter.ru" + a['href'] if not a['href'].startswith('http') else a['href']
                })
    except Exception as e:
        logging.error(f"JF Error: {e}")

    combined_data.sort(key=lambda x: x['Дата'], reverse=True)
    return combined_data[:limit]

# --- ОБРАБОТЧИКИ ---

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    logging.info(f"Команда /start от {message.from_user.id}")
    await message.answer(f"Привет, {message.from_user.first_name}! 🎬\nНапиши мне профессию (например: `Продюсер`), и я пришлю 7 ссылок текстом + Excel-файл со всеми остальными.")

@dp.message_handler()
async def search_handler(message: types.Message):
    query = message.text
    logging.info(f"Запрос поиска: {query}")
    
    wait_msg = await message.answer(f"🔎 Ищу вакансии по запросу *{query}*...", parse_mode="Markdown")
    
    jobs = get_all_jobs(query)
    
    if not jobs:
        await wait_msg.edit_text("Ничего не найдено. Попробуй другой запрос.")
        return

    # 1. Ссылки текстом (Топ-7)
    await message.answer(f"🔝 **Самые свежие вакансии по запросу '{query}':**", parse_mode="Markdown")
    for j in jobs[:7]:
        await message.answer(f"📍 {j['Источник']} | {j['Дата']}\n💼 **{j['Название']}**\n💰 {j['Оплата']}\n🔗 [Открыть]({j['Ссылка']})", parse_mode="Markdown", disable_web_page_preview=True)

    # 2. Excel
    df = pd.DataFrame(jobs)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Vacancies')
    output.seek(0)
    
    await message.answer_document(types.InputFile(output, filename=f"{query}.xlsx"), caption="📂 Весь список в Excel.")
    await wait_msg.delete()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Бот активен и слушает сообщения!")

async def main():
    # Настройка веб-сервера
    app = web.Application()
    app.router.add_get('/', handle)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Веб-сервер запущен на порту {port}")

    # Запуск бота (Polling)
    try:
        logging.info("Бот начинает опрос (polling)...")
        await dp.start_polling()
    finally:
        await bot.close()

if __name__ == '__main__':
    asyncio.run(main())
