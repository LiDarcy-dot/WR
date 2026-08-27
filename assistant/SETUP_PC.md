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
   Или пул сразу: `возможные пароли pass1 pass2 pass3` — бот сам переберёт на всех файлах, где нужен пароль.

### Временное чтение (без хранилища)

1. `сейчас скину файл — не сохраняй, прочитай, потом спрошу`  
2. Бот ждёт файл (не ищет в базе сразу).  
3. Пришли файл/фото → разберёт (текст / vision / аудио).  
4. Задавай вопросы. Можно **ответом (reply)** на любое своё сообщение с фото/файлом/голосом.  
5. `забей` / `передумал` / `отмена` — закрыть сессию.

Фото (в т.ч. HEIC): нужен vision в LM Studio. Если основная модель не видит картинки — скачай VL-модель и в `.env`:

```
LM_STUDIO_VISION_MODEL=имя_модели_из_LM_Studio
```

Аудио: пробует `/v1/audio/transcriptions` (Whisper в LM Studio, если доступно) и временно переключает модель; иначе можно `pip install faster-whisper`.

Файлы лежат в `Desktop\Assistant\documents\…`, индекс — в SQLite.

---

## Обновление кода

Ты уже в PowerShell — **не** оборачивай команду в `powershell -Command "..."`.

### Вариант A (одна короткая команда)

```powershell
irm https://raw.githubusercontent.com/LiDarcy-dot/WR/cursor/local-assistant-scaffold-d6ce/assistant/scripts/force_update.ps1 | iex
```

Должно написать `FORCE UPDATE OK`, потом Enter и перезапуск `START_BOT.bat`.

### Вариант B (вставь блок целиком)

```powershell
$ErrorActionPreference = "Stop"
$t = Join-Path $env:USERPROFILE "Desktop\Assistant"
if (-not (Test-Path (Join-Path $t "main.py"))) { throw "No Desktop\Assistant\main.py" }
$tmp = Join-Path $env:TEMP ("WR-" + [guid]::NewGuid().ToString("N"))
Write-Host "Cloning..." -ForegroundColor Cyan
git clone --branch cursor/local-assistant-scaffold-d6ce --depth 1 https://github.com/LiDarcy-dot/WR.git $tmp
$dstApp = Join-Path $t "app"
if (Test-Path $dstApp) { Remove-Item -LiteralPath $dstApp -Recurse -Force }
Copy-Item (Join-Path $tmp "assistant\app") $dstApp -Recurse -Force
Copy-Item (Join-Path $tmp "assistant\main.py") (Join-Path $t "main.py") -Force
Copy-Item (Join-Path $tmp "assistant\requirements.txt") (Join-Path $t "requirements.txt") -Force
Copy-Item (Join-Path $tmp "assistant\scripts") (Join-Path $t "scripts") -Recurse -Force
Copy-Item (Join-Path $tmp "assistant\scripts\UPDATE.cmd") (Join-Path $t "UPDATE.cmd") -Force
Copy-Item (Join-Path $tmp "assistant\START_BOT.bat") (Join-Path $t "START_BOT.bat") -Force
Remove-Item -LiteralPath $tmp -Recurse -Force
Set-Location $t
$py = Join-Path $t ".venv\Scripts\python.exe"
& $py -m pip install -q -r requirements.txt
& $py -c "from app.files.store import ensure_files_schema; print('files OK')"
Write-Host "UPDATE OK - restart START_BOT.bat" -ForegroundColor Green
```

После первого обновления можно запускать `Desktop\Assistant\UPDATE.cmd` (двойной клик по `.cmd`, не по `.ps1`).

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
