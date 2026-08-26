# Пошаговая установка на твоём ПК (Windows)

Сейчас ты можешь читать это с iPhone. **Выполняй шаги, когда сядешь за ПК** (нужны LM Studio, папка на диске, Python, токен Telegram).

Я уже сделал в репозитории каркас бота, БД и логику подтверждений. Тебе нужно поднять окружение вокруг него.

---

## Что делает кто

| Кто | Что |
|-----|-----|
| **Я (уже в репо)** | код бота, схема БД, карточки «Сохранить/Отмена», `/pause` `/resume`, RRULE, люди/ДР/атрибуты, custom entities |
| **Ты на ПК** | LM Studio + модель, папка данных, Python, токен бота, VPN, первый запуск |

---

## Шаг 0. Что скачать заранее (с телефона можно закладки)

1. **LM Studio:** https://lmstudio.ai  
2. **Python 3.11+:** https://www.python.org/downloads/  
   При установке обязательно галочка **Add python.exe to PATH**  
3. **Git** (если ещё нет): https://git-scm.com/download/win  
4. Этот репозиторий GitHub: `https://github.com/LiDarcy-dot/WR`

---

## Шаг 1. Папка данных ассистента

На ПК создай папку, например:

```text
D:\WR_Assistant_Data
```

или на рабочем столе:

```text
C:\Users\<ТЫ>\Desktop\WR_Assistant_Data
```

Пока можно пустую. Скрипт сам создаст `db/`, `inbox/`, `backups/` и остальное.

---

## Шаг 2. LM Studio + модель (Qwen, без Яндекса)

1. Установи и открой **LM Studio**.
2. В поиске моделей найди и скачай одну из (GGUF, квант **не хуже Q4**, лучше **Q5_K_M** / **Q4_K_M**):

| Приоритет | Что искать в LM Studio |
|-----------|-------------------------|
| 1 | `Qwen2.5-7B-Instruct` GGUF Q5_K_M или Q4_K_M |
| 2 | `Qwen3-8B-Instruct` GGUF Q4_K_M / Q5_K_M (если влезает с контекстом) |

3. Загрузи модель в чат LM Studio.
4. Включи **Local Server** (Developer → Start Server).  
   Обычно адрес: `http://127.0.0.1:1234`
5. Запомни **точное имя модели** в сервере (как в выпадающем списке) — оно понадобится в `.env` как `LM_STUDIO_MODEL`.
6. Контекст поставь примерно **8192** (8k). Не гони 32k на 8 ГБ VRAM.

Проверка: в LM Studio должен отвечать чат локально.

---

## Шаг 3. Telegram-бот

1. В Telegram открой **@BotFather** → `/newbot` → имя и username.
2. Скопируй **токен** (вид `123456:ABC...`).
3. Узнай свой user id: напиши **@userinfobot** → скопируй число (например `123456789`).
4. Напиши своему новому боту `/start` (чтобы чат существовал).

**VPN:** на ПК, где крутится бот, VPN для Telegram держи включённым. Если VPN перезагружаешь — бот сам переподключится при следующем цикле polling (в логах могут быть краткие ошибки — это нормально).

---

## Шаг 4. Скачать код на ПК

В PowerShell:

```powershell
cd $env:USERPROFILE\Desktop
git clone https://github.com/LiDarcy-dot/WR.git
cd WR
git checkout cursor/local-assistant-scaffold-d6ce
```

Если ветка уже вольётся в `main` — достаточно `git clone` без checkout.

---

## Шаг 5. Python-окружение

```powershell
cd $env:USERPROFILE\Desktop\WR\assistant
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Если `Activate.ps1` ругается на политику:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## Шаг 6. Файл настроек `.env`

```powershell
copy .env.example .env
notepad .env
```

Заполни:

```env
TELEGRAM_BOT_TOKEN=вставь_токен_от_BotFather
TELEGRAM_OWNER_ID=твой_числовой_id
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=имя_модели_как_в_LM_Studio
ASSISTANT_DATA_DIR=D:\WR_Assistant_Data
TIMEZONE=Europe/Moscow
```

Путь в `ASSISTANT_DATA_DIR` — тот, что создал на шаге 1.

---

## Шаг 7. Инициализация папки и БД

```powershell
cd $env:USERPROFILE\Desktop\WR\assistant
.\.venv\Scripts\Activate.ps1
python scripts\init_data.py --data-dir "D:\WR_Assistant_Data"
```

Должно напечатать `OK: структура и БД готовы...`

---

## Шаг 8. Запуск бота

1. LM Studio: модель загружена, **Server запущен**.
2. VPN на ПК включён (если без него Telegram не ходит).
3. В PowerShell:

```powershell
cd $env:USERPROFILE\Desktop\WR\assistant
.\.venv\Scripts\Activate.ps1
python main.py
```

4. С **iPhone** в Telegram напиши боту `/start`, потом `/status`.
5. Проверь паузу: `/pause` → любое сообщение → должен отказаться думать → `/resume`.

---

## Шаг 9. Первые проверки данными

Пиши боту с телефона, например:

1. `день рождения друга Вани 01.01.1998, вишлист https://example.com/wish`  
   → должна прийти **карточка** с кнопками **Сохранить / Отмена**.
2. После **Сохранить** — факт в БД (`D:\WR_Assistant_Data\db\assistant.sqlite3`).
3. `напомни завтра в 19:00 проверить почту` → карточка разового напоминания.
4. Сложная регулярка (можно позже, когда базовая связь стабильна).

Если модель отвечает обычным текстом без карточки — это нормально на старте: иногда Qwen не отдаёт JSON. Напиши ещё раз явнее: «сохрани в базу: …». В следующих итерациях я ужесточу парсер/промпт.

---

## Шаг 10. Игры / пауза

- **Вручную:** `/pause` перед игрой, `/resume` после.  
- **Steam:** каркас детекта процессов уже в коде; авто-пауза по списку `.exe` подключим в следующем шаге, когда подтвердишь что базовый чат живой.  
- Вне Steam — только ручная пауза.

Перед тяжёлой игрой можно ещё **Unload** модели в LM Studio — освободит VRAM. Бот в паузе модель не дёргает.

---

## Если что-то не работает

| Симптом | Что проверить |
|---------|----------------|
| Бот молчит | VPN на ПК; `python main.py` запущен; токен верный |
| `/status` → LM Studio недоступна | Local Server в LM Studio; URL `1234`; модель загружена |
| «Доступ запрещён» | `TELEGRAM_OWNER_ID` = твой id, не id бота |
| Ошибка пути данных | `ASSISTANT_DATA_DIR` существует, без кавычек-кривизны в `.env` |
| Out of memory / тормоза | Q4_K_M, контекст 4k–8k, закрыть браузер/игры |

---

## Что уже сделано в коде (не надо делать руками)

- Таблицы: люди, ДР, атрибуты (вишлист и т.п.), ЖКХ, custom entities, разовые и RRULE-напоминания, jobs, pending_actions  
- Telegram: `/start` `/status` `/pause` `/resume`, чат → LM Studio, кнопки подтверждения  
- Скрипт раскладки папок + init БД  
- Заготовка Steam presence  

## Что сделаем следующим этапом (после твоего первого запуска)

1. Авто-пауза по Steam + список процессов  
2. Планировщик напоминаний (отправка в Telegram по `next_fire_at`)  
3. Ежедневный бэкап БД в `backups/`  
4. Жёстче JSON/карточки + команда «изменить»  
5. Inbox файлов с iPhone  

---

Когда выполнишь шаги 1–8 — напиши сюда (с телефона ок):  
`бот живой` / что сломалось на каком шаге. Дальше продолжу допиливать уже по факту.
