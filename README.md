# WR — локальный ассистент

Личный Telegram-ассистент на твоём ПК: **LM Studio (Qwen)** + **SQLite** + бот. Без платных API и без российского хостинга моделей.

## Документы

- **[assistant/SETUP_PC.md](assistant/SETUP_PC.md)** — пошаговая установка на Windows (это твой главный чеклист с iPhone/ПК).
- Код: каталог `assistant/`.

## Стек (v0.1)

- Python 3.11+
- `python-telegram-bot` → Telegram
- LM Studio OpenAI-compatible API → локальная Qwen
- SQLite → люди, ДР, атрибуты, ЖКХ, custom entities, RRULE/разовые напоминания

## Быстрый старт (кратко)

1. Следуй `assistant/SETUP_PC.md`
2. Скачай Qwen2.5-7B-Instruct (GGUF ≥ Q4) в LM Studio
3. Заполни `assistant/.env`
4. `python scripts/init_data.py --data-dir ...`
5. `python main.py`

## Команды бота

| Команда | Смысл |
|---------|--------|
| `/start` | приветствие |
| `/status` | пауза, LM Studio, путь данных |
| `/pause` | не вызывать модель (игры/работа) |
| `/resume` | снять паузу |

Любое сохранение в БД — через карточку и кнопки **Сохранить / Отмена**.
