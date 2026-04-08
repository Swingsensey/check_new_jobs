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

def search_superjob(query, limit=50):
    if not SUPERJOB_KEY:
        return []
        
    # Москва ID = 4
    url = f"https://api.superjob.ru/2.0/vacancies/?keyword={query}&town=4&count={limit}"
    headers = {'X-Api-App-Id': SUPERJOB_KEY}
    results = []
    
    try:
        r = requests.get(url, headers=headers, timeout=10).json()
        for v in r.get('objects', []):
            pay = "Договорная"
            if v.get('payment_from') or v.get('payment_to'):
                pay = f"от {v.get('payment_from', 0)} до {v.get('payment_to', 0)}"
            
            results.append({
                'id': f"sj_{v['id']}",
                'text': f"🔵 SuperJob: {v['profession']}\n{v['link']}", # Твой стиль!
                'Дата': datetime.fromtimestamp(v['date_published']).strftime('%Y-%m-%d'),
                'Источник': 'SuperJob',
                'Вакансия': v['profession'],
                'Компания': v['client'].get('title', 'Не указана'),
                'Оплата': pay,
                'Ссылка': v['link']
            })
    except Exception as e:
        logging.error(f"SuperJob error: {e}")
    return results

def search_habr(query, limit=20):
    # Москва на Хабр Карьере имеет ID 678
    url = f"https://career.habr.com/vacancies?q={query}&city_id=678&type=all"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Находим карточки вакансий
        items = soup.find_all('div', class_='vacancy-card')
        
        for i in items[:limit]:
            title_tag = i.find('a', class_='vacancy-card__title-link')
            company_tag = i.find('div', class_='vacancy-card__company-title')
            salary_tag = i.find('div', class_='basic-salary')
            
            if title_tag:
                title = title_tag.text.strip()
                link = "https://career.habr.com" + title_tag['href']
                company = company_tag.text.strip() if company_tag else "Не указана"
                pay = salary_tag.text.strip() if salary_tag else "Договорная"
                
                results.append({
                    'id': f"hb_{link[-6:]}", # Берем ID из конца ссылки
                    'text': f"🟢 Habr: {title}\n{link}",
                    'Дата': datetime.now().strftime('%Y-%m-%d'),
                    'Источник': 'Habr',
                    'Вакансия': title,
                    'Компания': company,
                    'Оплата': pay,
                    'Ссылка': link
                })
    except Exception as e:
        logging.error(f"Habr error: {e}")
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

def generate_pro_excel(query):
    # ДВИЖОК СБОРА ДАННЫХ ДЛЯ EXCEL (100 ШТУК)
    raw_data = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Сбор с HH (100 шт)
    try:
        url_hh = f"https://api.hh.ru/vacancies?text={query}&area=1&per_page=100&order_by=publication_time"
        res = requests.get(url_hh, headers=headers, timeout=5).json()
        for v in res.get('items', []):
            s = v.get('salary')
            pay = f"от {s['from']}" if s and s['from'] else "Договорная"
            raw_data.append({
                'Дата': v['published_at'][:10], 'Источник': 'HH',
                'Вакансия': v['name'], 'Компания': v['employer']['name'],
                'Оплата': pay, 'Ссылка': v['alternate_url']
            })
    except: pass

    # Сбор с ТрудВсем
    try:
        url_tr = f"https://opendata.trudvsem.ru/api/v1/vacancies/region/77?text={query}"
        res = requests.get(url_tr, timeout=5).json()
        if res.get('results'):
            for v in res['results']['vacancies'][:30]:
                vac = v['vacancy']
                raw_data.append({
                    'Дата': vac['modification-date'], 'Источник': 'ТрудВсем',
                    'Вакансия': vac['job-name'], 'Компания': vac['company']['name'],
                    'Оплата': vac.get('salary', 'Договорная'), 'Ссылка': vac['vac_url']
                })
    except: pass

    if not raw_data: return None

    # ОФОРМЛЕНИЕ EXCEL (СИНИЙ СТИЛЬ)
    df = pd.DataFrame(raw_data)
    df = df.sort_values(by='Дата', ascending=False)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Вакансии')
        ws = writer.sheets['Вакансии']
        
        # Синяя шапка, белый текст
        fill = PatternFill(start_color="002060", end_color="002060", fill_type="solid")
        font = Font(color="FFFFFF", bold=True)
        
        for col_num, value in enumerate(df.columns.values):
            cell = ws.cell(row=1, column=col_num + 1)
            cell.fill = fill
            cell.font = font
            cell.alignment = Alignment(horizontal='center')
            ws.column_dimensions[chr(65 + col_num)].width = 35 # Ширина колонок
            
        ws.freeze_panes = 'A2' # Закрепить шапку
    output.seek(0)
    return output

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
    wait = await message.answer(f"🔎 Ищу вакансии по запросу: *{query}*...", parse_mode="Markdown")
    
    # СБОР ДАННЫХ ИЗ 4-х ИСТОЧНИКОВ
    hh_res = search_hh(query, 100)
    sj_res = search_superjob(query, 50) 
    hb_res = search_habr(query, 20) # Новый Хабр
    jf_res = search_jobfilter(query, 10)
    
    # Объединяем всё в один список
    found = hh_res + sj_res + hb_res + jf_res
    
    if not found:
        await wait.edit_text("Ничего не найдено.")
        return

    # ВЫДАЧА В ТГ (Твой эталонный лаконичный стиль)
    # Выводим Топ-10 для чата (сначала HH, потом SJ, потом Habr)
    for j in found[:10]:
        await message.answer(j['text'], disable_web_page_preview=True)
        await asyncio.sleep(0.1)

    # ВЫДАЧА EXCEL (Синий отчет, куда попадут все 180 вакансий)
    excel_file = generate_excel(found)
    if excel_file:
        await message.answer_document(
            types.InputFile(excel_file, filename=f"{query.replace(' ', '_')}.xlsx"),
            caption=f"📊 Полный отчет: {len(found)} вакансий (HH + SJ + Habr + JF)"
        )

    # Кнопка подписки
    kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(f"🔔 Подписаться на '{query}'", callback_data=f"sub|{query}"))
    await message.answer("Включить авто-мониторинг этого запроса?", reply_markup=kb)
    await wait.delete()

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
