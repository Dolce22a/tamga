import os
import logging
import requests
from datetime import date
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials

# ═══════════════════════════════════════════════
#  КОНФИГ
# ═══════════════════════════════════════════════
BOT_TOKEN      = '8161288549:AAGlkeWLUdqAzRI2I1T4cYpILUsZLVbWEt4'
SPREADSHEET_ID = '1oCMcofMMof0uTL28qvxO1SJRNWuKL3cYtl4rk6dC_PQ'
ALLOWED_USERS  = {778913939}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app         = Flask(__name__)
user_states = {}  # user_id -> {'action': str, 'step': int | 'confirm', 'data': dict}

API = f'https://api.telegram.org/bot{BOT_TOKEN}'


# ═══════════════════════════════════════════════
#  GOOGLE SHEETS
# ═══════════════════════════════════════════════
SCOPES = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]

def get_sheet(name: str):
    creds  = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(name)

def next_id(sheet, prefix: str) -> str:
    """Считает строки с данными (без заголовка) и генерирует новый ID."""
    all_vals = sheet.get_all_values()
    count    = max(len(all_vals) - 1, 0)
    return f'{prefix}_{str(count + 1).zfill(3)}'

def normalize(val: str) -> str:
    """Нормализует 'нет'/'no'/'-' в пустую строку."""
    if val.strip().lower() in ('нет', 'no', '-', 'пропустить', 'skip', ''):
        return ''
    return val.strip()


# ─── Сохранение в листы ──────────────────────────────────────────────────────

def save_person(d: dict):
    sheet = get_sheet('Persons')
    pid   = next_id(sheet, 'person')
    row = [
        pid,                         # A  id
        d.get('name_kz',   ''),      # B  name_kz
        d.get('name_ru',   ''),      # C  name_ru
        d.get('name_en',   ''),      # D  name_en
        d.get('role',      ''),      # E  role
        d.get('years',     ''),      # F  years
        d.get('bio_ru',    ''),      # G  bio_ru
        '',                          # H  (пусто)
        '',                          # I  (пусто)
        d.get('films',     ''),      # J  films
        d.get('photo_url', ''),      # K  photo_url
        d.get('tags',      ''),      # L  tags
        '',                          # M  (пусто)
        'опубликован',               # N  status
        str(date.today()),           # O  date_added
        'telegram_bot',              # P  added_by
    ]
    log.info(f'save_person pid={pid}')
    sheet.append_row(row, value_input_option='RAW')

def save_film(d: dict):
    sheet = get_sheet('Films')
    fid   = next_id(sheet, 'film')
    row = [
        fid,                              # A  id
        d.get('title_kz',    ''),         # B  title_kz
        d.get('title_ru',    ''),         # C  title_ru
        d.get('title_en',    ''),         # D  title_en
        d.get('year',        ''),         # E  year
        d.get('direction',   ''),         # F  direction
        d.get('genre',       ''),         # G  genre
        d.get('director_id', ''),         # H  director_id
        d.get('operator_id', ''),         # I  operator_id
        d.get('duration',    ''),         # J  duration
        d.get('studio',      ''),         # K  studio
        d.get('synopsis_ru', ''),         # L  synopsis_ru
        d.get('synopsis_kz', ''),         # M  synopsis_kz
        d.get('synopsis_en', ''),         # N  synopsis_en
        d.get('poster_url',  ''),         # O  poster_url
        d.get('stills_urls', ''),         # P  stills_urls
        d.get('access_status', 'по запросу'),  # Q  access_status
        d.get('tags',        ''),         # R  tags
        'опубликован',                    # S  status
        str(date.today()),                # T  date_added
        'telegram_bot',                   # U  added_by
    ]
    log.info(f'save_film fid={fid}')
    sheet.append_row(row, value_input_option='RAW')

def save_media(d: dict):
    sheet = get_sheet('Media')
    mid   = next_id(sheet, 'media')
    row = [
        mid,
        d.get('type',           ''),
        d.get('film_id',        ''),
        d.get('person_id',      ''),
        d.get('year',           ''),
        d.get('description_ru', ''),
        d.get('url',            ''),
        d.get('copyright',      ''),
        str(date.today()),
        'telegram_bot',
    ]
    log.info(f'save_media mid={mid}')
    sheet.append_row(row, value_input_option='RAW')


# ═══════════════════════════════════════════════
#  TELEGRAM HELPERS
# ═══════════════════════════════════════════════

def send(chat_id: int, text: str, parse_mode: str = 'Markdown'):
    try:
        r = requests.post(
            f'{API}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode},
            timeout=10
        )
        if not r.ok:
            log.warning(f'Markdown failed ({r.status_code}), retry plain')
            requests.post(
                f'{API}/sendMessage',
                json={'chat_id': chat_id, 'text': text},
                timeout=10
            )
    except Exception as e:
        log.error(f'send error: {e}')

def get_file_url(file_id: str) -> str:
    try:
        r    = requests.get(f'{API}/getFile?file_id={file_id}', timeout=10)
        path = r.json()['result']['file_path']
        return f'https://api.telegram.org/file/bot{BOT_TOKEN}/{path}'
    except Exception as e:
        log.error(f'get_file_url error: {e}')
        return ''

def extract_photo_url(message: dict, text: str) -> str:
    """Достаёт URL фото из вложения, либо из текстового URL."""
    if 'photo' in message:
        return get_file_url(message['photo'][-1]['file_id'])
    t = text.strip()
    if t.startswith('http'):
        return t
    return ''  # пропустить / нет / - → пусто


# ═══════════════════════════════════════════════
#  ШАГИ ДИАЛОГА
#
#  Каждый элемент списка описывает ОДИН шаг:
#    question — текст вопроса, который бот задаёт
#    save_to  — ключ в dict data, куда сохранить ОТВЕТ пользователя
#    is_photo — если True, ответ обрабатывается как фото/URL
#
#  Логика работы:
#    При старте (/add_film и т.д.) бот отправляет question шага 0
#    и сохраняет step=0.
#    Когда приходит ответ: сохраняем в save_to шага 0,
#    переходим на шаг 1, отправляем question шага 1, и т.д.
#    Когда шаги закончились — переходим на confirm.
# ═══════════════════════════════════════════════

PERSON_STEPS = [
    {'question': '➤ Шаг 1 из 9\n\nВведите имя на *казахском языке*:',              'save_to': 'name_kz'},
    {'question': '➤ Шаг 2 из 9\n\nВведите имя на *русском языке*:',                'save_to': 'name_ru'},
    {'question': '➤ Шаг 3 из 9\n\nВведите имя на *английском языке* _(или "нет")_:', 'save_to': 'name_en'},
    {'question': (
        '➤ Шаг 4 из 9\n\nУкажите *роль* (одно из):\n'
        '• Режиссёр\n• Оператор\n• Сценарист\n• Актёр\n'
        '• Монтажёр\n• Художник\n• Композитор\n• Другое'
     ), 'save_to': 'role'},
    {'question': '➤ Шаг 5 из 9\n\nГоды жизни _(формат: 1923–1987 или 1950–н.в.)_:', 'save_to': 'years'},
    {'question': '➤ Шаг 6 из 9\n\nБиография на *русском* _(до 500 символов)_:',    'save_to': 'bio_ru'},
    {'question': '➤ Шаг 7 из 9\n\nФильмография через запятую _(или "нет")_:',       'save_to': 'films'},
    {'question': '➤ Шаг 8 из 9\n\nТеги через запятую\n_(пример: режиссёр, советское кино)_:', 'save_to': 'tags'},
    {'question': '➤ Шаг 9 из 9\n\n🖼 Прикрепите *фото* или отправьте URL\n_(или напишите "нет")_:',
     'save_to': 'photo_url', 'is_photo': True},
]

# FILM_STEPS — строго соответствует колонкам:
# title_kz, title_ru, title_en, year, direction, genre,
# director_id, operator_id, duration, studio,
# synopsis_ru, synopsis_kz, synopsis_en,
# poster_url, stills_urls, access_status, tags
FILM_STEPS = [
    {'question': '➤ Шаг 1 из 17\n\nНазвание фильма на *казахском* _(или "нет")_:',  'save_to': 'title_kz'},
    {'question': '➤ Шаг 2 из 17\n\nНазвание фильма на *русском*:',                   'save_to': 'title_ru'},
    {'question': '➤ Шаг 3 из 17\n\nНазвание фильма на *английском* _(или "нет")_:',  'save_to': 'title_en'},
    {'question': '➤ Шаг 4 из 17\n\nГод выпуска _(пример: 1975)_:',                   'save_to': 'year'},
    {'question': (
        '➤ Шаг 5 из 17\n\nНаправление (одно из):\n'
        '• Художественное\n• Документальное\n• Анимационное\n• Научно-популярное'
     ), 'save_to': 'direction'},
    {'question': '➤ Шаг 6 из 17\n\nЖанр(ы) через запятую\n_(пример: драма, исторический)_:', 'save_to': 'genre'},
    {'question': '➤ Шаг 7 из 17\n\nИмя режиссёра :',        'save_to': 'director_id'},
    {'question': '➤ Шаг 8 из 17\n\nИмя продюссера :',         'save_to': 'operator_id'},
    {'question': '➤ Шаг 9 из 17\n\nДлительность в минутах _(или "нет")_:',                    'save_to': 'duration'},
    {'question': '➤ Шаг 10 из 17\n\nСтудия _(пример: Казахфильм)_:',                          'save_to': 'studio'},
    {'question': '➤ Шаг 11 из 17\n\nСинопсис на *русском* _(или "нет")_:',                    'save_to': 'synopsis_ru'},
    {'question': '➤ Шаг 12 из 17\n\nСинопсис на *казахском* _(или "нет")_:',                  'save_to': 'synopsis_kz'},
    {'question': '➤ Шаг 13 из 17\n\nСинопсис на *английском* _(или "нет")_:',                 'save_to': 'synopsis_en'},
    {'question': '➤ Шаг 14 из 17\n\n🖼 Прикрепите *постер* или отправьте URL\n_(или "нет")_:',
     'save_to': 'poster_url', 'is_photo': True},
    {'question': '➤ Шаг 15 из 17\n\nURL кадров через запятую _(или "нет")_:',                  'save_to': 'stills_urls'},
    {'question': (
        '➤ Шаг 16 из 17\n\nСтатус доступа (одно из):\n'
        '• по запросу\n• свободный доступ\n• архивный\n• ограниченный'
     ), 'save_to': 'access_status'},
    {'question': '➤ Шаг 17 из 17\n\nТеги через запятую\n_(пример: советское кино, 1970-е)_:', 'save_to': 'tags'},
]

MEDIA_STEPS = [
    {'question': (
        '➤ Шаг 1 из 7\n\nТип медиа (одно из):\n'
        '• фото\n• видео\n• постер\n• кадр\n• документ'
     ), 'save_to': 'type'},
    {'question': '➤ Шаг 2 из 7\n\nfilm\\_id _(пример: film\\_001 или "нет")_:',       'save_to': 'film_id'},
    {'question': '➤ Шаг 3 из 7\n\nperson\\_id _(пример: person\\_001 или "нет")_:',    'save_to': 'person_id'},
    {'question': '➤ Шаг 4 из 7\n\nГод создания _(или "нет")_:',                        'save_to': 'year'},
    {'question': '➤ Шаг 5 из 7\n\nОписание на *русском* _(или "нет")_:',               'save_to': 'description_ru'},
    {'question': '➤ Шаг 6 из 7\n\nURL файла _(или "нет")_:',                           'save_to': 'url'},
    {'question': '➤ Шаг 7 из 7\n\nАвторское право _(или "нет")_:',                     'save_to': 'copyright'},
]


# ═══════════════════════════════════════════════
#  ОБРАБОТКА ШАГОВ
# ═══════════════════════════════════════════════

def process_step(steps: list, action: str,
                 chat_id: int, user_id: int,
                 text: str, message: dict, state: dict):
    """
    Принимает ОТВЕТ пользователя на текущий шаг,
    сохраняет его, переходит к следующему шагу.
    """
    step_idx = state['step']
    d        = state['data']
    current  = steps[step_idx]

    # 1. Сохраняем ответ пользователя в нужное поле
    if current.get('is_photo'):
        value = extract_photo_url(message, text)
    else:
        value = normalize(text)
    d[current['save_to']] = value
    log.info(f'[{action}] step={step_idx} saved "{current["save_to"]}" = {value!r}')

    # 2. Переходим к следующему шагу
    next_idx = step_idx + 1

    if next_idx >= len(steps):
        # Все шаги пройдены → показываем превью
        user_states[user_id] = {'action': action, 'step': 'confirm', 'data': d}
        send_preview(action, chat_id, d)
    else:
        # Задаём следующий вопрос
        next_q = steps[next_idx]['question']
        user_states[user_id] = {'action': action, 'step': next_idx, 'data': d}
        send(chat_id, next_q)


# ═══════════════════════════════════════════════
#  ПРЕВЬЮ ПЕРЕД СОХРАНЕНИЕМ
# ═══════════════════════════════════════════════

def send_preview(action: str, chat_id: int, d: dict):
    S = '─' * 28
    def v(key): return d.get(key) or '—'
    def trunc(key, n=200):
        s = d.get(key, '')
        return (s[:n] + '...') if len(s) > n else (s or '—')

    if action == 'add_person':
        text = (
            f"📋 *ПРОВЕРЬТЕ ДАННЫЕ — ПЕРСОНА*\n{S}\n"
            f"🇰🇿 *Имя КЗ:* {v('name_kz')}\n"
            f"🇷🇺 *Имя РУ:* {v('name_ru')}\n"
            f"🌐 *Имя EN:* {v('name_en')}\n"
            f"{S}\n"
            f"🎭 *Роль:* {v('role')}\n"
            f"📅 *Годы:* {v('years')}\n"
            f"{S}\n"
            f"📝 *Биография:*\n{trunc('bio_ru')}\n"
            f"{S}\n"
            f"🎬 *Фильмография:* {v('films')}\n"
            f"🏷 *Теги:* {v('tags')}\n"
            f"🖼 *Фото:* {'✅ есть' if d.get('photo_url') else '❌ нет'}\n"
            f"{S}\n✅ *да* — сохранить  |  ❌ *нет* — отменить"
        )

    elif action == 'add_film':
        text = (
            f"📋 *ПРОВЕРЬТЕ ДАННЫЕ — ФИЛЬМ*\n{S}\n"
            f"🇰🇿 *Название КЗ:* {v('title_kz')}\n"
            f"🇷🇺 *Название РУ:* {v('title_ru')}\n"
            f"🌐 *Название EN:* {v('title_en')}\n"
            f"{S}\n"
            f"📅 *Год:* {v('year')}\n"
            f"🎞 *Направление:* {v('direction')}\n"
            f"🎭 *Жанр:* {v('genre')}\n"
            f"👤 *director\\_id:* {v('director_id')}\n"
            f"📷 *operator\\_id:* {v('operator_id')}\n"
            f"⏱ *Длит.:* {v('duration')} мин\n"
            f"🏛 *Студия:* {v('studio')}\n"
            f"{S}\n"
            f"📝 *Синопсис РУ:*\n{trunc('synopsis_ru')}\n"
            f"📝 *Синопсис КЗ:*\n{trunc('synopsis_kz')}\n"
            f"📝 *Синопсис EN:*\n{trunc('synopsis_en')}\n"
            f"{S}\n"
            f"🖼 *Постер:* {'✅ есть' if d.get('poster_url') else '❌ нет'}\n"
            f"🎞 *Кадры:* {v('stills_urls')}\n"
            f"🔓 *Доступ:* {v('access_status')}\n"
            f"🏷 *Теги:* {v('tags')}\n"
            f"{S}\n✅ *да* — сохранить  |  ❌ *нет* — отменить"
        )

    elif action == 'add_media':
        text = (
            f"📋 *ПРОВЕРЬТЕ ДАННЫЕ — МЕДИА*\n{S}\n"
            f"🖼 *Тип:* {v('type')}\n"
            f"🎬 *film\\_id:* {v('film_id')}\n"
            f"👤 *person\\_id:* {v('person_id')}\n"
            f"📅 *Год:* {v('year')}\n"
            f"{S}\n"
            f"📝 *Описание:* {trunc('description_ru')}\n"
            f"🔗 *URL:* {v('url')}\n"
            f"©️ *Копирайт:* {v('copyright')}\n"
            f"{S}\n✅ *да* — сохранить  |  ❌ *нет* — отменить"
        )
    else:
        text = '❌ Неизвестное действие.'

    send(chat_id, text)


# ═══════════════════════════════════════════════
#  ПОДТВЕРЖДЕНИЕ
# ═══════════════════════════════════════════════

def handle_confirm(chat_id: int, user_id: int, text: str, state: dict):
    action = state['action']
    d      = state['data']
    log.info(f'[confirm] action={action} data={d}')

    if text.strip().lower() in ('да', 'yes', 'д', 'y'):
        try:
            if action == 'add_person':
                save_person(d)
                name = d.get('name_ru') or d.get('name_kz') or '—'
                send(chat_id, f"✅ Персона *{name}* сохранена!\n\n/add\\_person — ещё\n/start — меню")
            elif action == 'add_film':
                save_film(d)
                title = d.get('title_ru') or d.get('title_kz') or '—'
                send(chat_id, f"✅ Фильм *{title}* сохранён!\n\n/add\\_film — ещё\n/start — меню")
            elif action == 'add_media':
                save_media(d)
                send(chat_id, f"✅ Медиа *{d.get('type') or '—'}* сохранено!\n\n/add\\_media — ещё\n/start — меню")
        except Exception as e:
            log.error(f'save error: {e}', exc_info=True)
            send(chat_id, f"❌ Ошибка сохранения:\n`{e}`\n\nПроверь подключение к Google Sheets.")
    else:
        send(chat_id, '❌ Отменено. Данные не сохранены.\n\nНапиши /start чтобы начать заново.')

    user_states.pop(user_id, None)


# ═══════════════════════════════════════════════
#  WEBHOOK
# ═══════════════════════════════════════════════

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data    = request.json
        message = data.get('message')
        if not message:
            return 'OK'

        chat_id = message['chat']['id']
        user_id = message['from']['id']
        text    = (message.get('text') or '').strip()

        if user_id not in ALLOWED_USERS:
            send(chat_id, '⛔ Нет доступа.')
            return 'OK'

        log.info(f'>>> user={user_id} text={text!r} state={user_states.get(user_id)}')

        state = user_states.get(user_id)

        # ── Команды (всегда приоритетнее состояния) ──────────────────
        if text == '/start':
            user_states.pop(user_id, None)
            send(chat_id,
                 '👋 *TAMGA Admin Bot*\n'
                 '━━━━━━━━━━━━━━━━━━━━━━━━\n'
                 '/add\\_person — добавить персону\n'
                 '/add\\_film   — добавить фильм\n'
                 '/add\\_media  — добавить медиафайл\n'
                 '/status      — статистика базы\n'
                 '/cancel      — отменить действие\n'
                 '━━━━━━━━━━━━━━━━━━━━━━━━')

        elif text == '/cancel':
            if user_states.pop(user_id, None):
                send(chat_id, '❌ Действие отменено.\n\nНапиши /start для начала.')
            else:
                send(chat_id, 'Нет активных действий. Напиши /start.')

        elif text == '/add_person':
            user_states[user_id] = {'action': 'add_person', 'step': 0, 'data': {}}
            send(chat_id,
                 '👤 *Добавление персоны*\n'
                 '━━━━━━━━━━━━━━━━━━━━━━━━\n'
                 '/cancel — отменить в любой момент\n\n'
                 + PERSON_STEPS[0]['question'])

        elif text == '/add_film':
            user_states[user_id] = {'action': 'add_film', 'step': 0, 'data': {}}
            send(chat_id,
                 '🎬 *Добавление фильма*\n'
                 '━━━━━━━━━━━━━━━━━━━━━━━━\n'
                 '/cancel — отменить в любой момент\n\n'
                 + FILM_STEPS[0]['question'])

        elif text == '/add_media':
            user_states[user_id] = {'action': 'add_media', 'step': 0, 'data': {}}
            send(chat_id,
                 '🖼 *Добавление медиа*\n'
                 '━━━━━━━━━━━━━━━━━━━━━━━━\n'
                 '/cancel — отменить в любой момент\n\n'
                 + MEDIA_STEPS[0]['question'])

        elif text == '/status':
            try:
                p = max(len(get_sheet('Persons').get_all_values()) - 1, 0)
                f = max(len(get_sheet('Films').get_all_values())   - 1, 0)
                m = max(len(get_sheet('Media').get_all_values())   - 1, 0)
                send(chat_id,
                     f'📊 *Статистика TAMGA*\n'
                     f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
                     f'👤 Персоналии: *{p}*\n'
                     f'🎬 Фильмы: *{f}*\n'
                     f'🖼 Медиа: *{m}*\n'
                     f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
                     f'🗓 {date.today()}')
            except Exception as e:
                send(chat_id, f'❌ Ошибка:\n`{e}`')

        elif state:
            action = state['action']

            if state['step'] == 'confirm':
                handle_confirm(chat_id, user_id, text, state)

            elif action == 'add_person':
                process_step(PERSON_STEPS, action, chat_id, user_id, text, message, state)

            elif action == 'add_film':
                process_step(FILM_STEPS, action, chat_id, user_id, text, message, state)

            elif action == 'add_media':
                process_step(MEDIA_STEPS, action, chat_id, user_id, text, message, state)

            else:
                send(chat_id, '❌ Неизвестное действие. Напиши /cancel.')

        else:
            send(chat_id, 'Не понимаю команду. Напиши /start.')

    except Exception as e:
        log.error(f'webhook error: {e}', exc_info=True)

    return 'OK'


@app.route('/')
def index():
    return '✅ TAMGA Bot is running'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)