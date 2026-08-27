# Пошаговая установка на твоём ПК (Windows)

Код ассистента лежит в GitHub. С этого облака я **не могу** сам клонировать файлы на твой диск — зато есть скрипт, который сделает всё одной командой.

---

## 0) LM Studio: нужен Local Server, не только LM Link

Вкладка **Developer**:

1. Включи **Developer mode** (у тебя уже On).
2. Найди и включи **локальный сервер / Local Server** (Serve on local network / Start Server).
   - Нужен адрес вида `http://127.0.0.1:1234`
   - Дашборд `lmstudio.ai/dashboard/lm-link` — это другое (удалённый линк), для нашего бота **не обязателен**.
3. Загрузи модель **`qwen/qwen3.5-9b`** (Q4_K_M, context 8192 — ок).
4. В настройках сервера имя модели должно совпадать с тем, что в `.env`: `qwen/qwen3.5-9b`.

Проверка в браузере на ПК: открой `http://127.0.0.1:1234/v1/models` — должен быть JSON со списком моделей.

---

## 1) Одной командой: clone + venv + .env + БД

Открой **PowerShell** и вставь (подставь свой токен бота):

```powershell
cd $env:USERPROFILE\Desktop
git clone https://github.com/LiDarcy-dot/WR.git
cd WR
git checkout cursor/local-assistant-scaffold-d6ce
git pull origin cursor/local-assistant-scaffold-d6ce
cd assistant

# если скрипт ругается на политику:
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

.\scripts\bootstrap_windows.ps1 `
  -BotToken "ВСТАВЬ_ТОКЕН_БОТА" `
  -OwnerId 489485288 `
  -DataDir "$env:USERPROFILE\Desktop\Assistant" `
  -Model "qwen/qwen3.5-9b"
```

Скрипт:
- поставит зависимости в `.venv`
- создаст `.env` (только на диске, не в git)
- подготовит папку `Desktop\Assistant` (`db/`, `inbox/`, …)

---

## 2) Запуск

1. LM Studio: модель загружена, **Local Server** на 1234  
2. VPN для Telegram на ПК — по возможности включи (у тебя 2ip уже «не твой» IP — часто этого хватает)  
3. Запуск:

```powershell
cd $env:USERPROFILE\Desktop\WR\assistant
.\.venv\Scripts\python.exe main.py
```

Или: `.\scripts\run_bot.ps1`

4. В Telegram боту: `/start` → должны появиться кнопки **Меню / Статус / Пауза / Продолжить**  
5. `/status` — LM Studio должна быть «доступна»

---

## 2.1) Файлы и мануалы

Бот **не** кладёт вложения в хранилище сам — только после твоей просьбы.

1. Напиши: `сейчас скину мануалы по КТ, сохрани`  
2. Пришли файлы (PDF/DOCX/TXT/фото). Между ними можно писать комментарии — привяжутся к следующему файлу.  
3. `готово` — закрыть приём.  
4. `какие файлы` — список.  
5. Вопрос: `как выполнить Aging? посмотри в мануалах` — ответ с ссылками на файл и страницу.  
6. Запароленный PDF: `пароль к файлу 12: secret` (id смотри в списке).

Файлы лежат в `Desktop\Assistant\documents\…`, индекс — в SQLite.

---

## 3) Интерфейс (фаза A — Telegram)

- Нижнее меню всегда на экране  
- Inline-меню разделов  
- Карточки сохранения: **Сохранить / Изменить / Отмена**  
- HTML-оформление статусов и карточек  

Веб-панель на ПК — позже (вариант C).

---

## Если LM Studio «недоступна»

- Не LM Link, а именно **локальный** server на `127.0.0.1:1234`  
- В `.env`: `LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1`  
- Имя модели Exact: `qwen/qwen3.5-9b`  
- Бот и LM Studio на **одном** ПК  

## Python 3.14

Ок пробуем. Если `pip install` упадёт — поставь рядом Python **3.12** и в bootstrap используй `py -3.12`.
