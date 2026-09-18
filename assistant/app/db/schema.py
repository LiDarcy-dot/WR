SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assistant_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS persona_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    system_prompt TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    aliases TEXT,
    relation TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS birthdays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL UNIQUE REFERENCES people(id) ON DELETE CASCADE,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    year INTEGER,
    notify_offsets_days TEXT NOT NULL DEFAULT '[7,1,0]',
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS person_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'text',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(person_id, key)
);

CREATE TABLE IF NOT EXISTS zhkh_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    provider TEXT,
    account_number TEXT,
    login_ref TEXT,
    url TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS zhkh_meters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES zhkh_accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    unit TEXT,
    submit_rule TEXT,
    last_value REAL,
    last_submitted_at TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS zhkh_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id INTEGER NOT NULL REFERENCES zhkh_meters(id) ON DELETE CASCADE,
    period TEXT NOT NULL,
    value REAL,
    status TEXT NOT NULL DEFAULT 'drafted',
    confirmed_at TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(meter_id, period)
);

CREATE TABLE IF NOT EXISTS entity_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entity_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type_id INTEGER NOT NULL REFERENCES entity_types(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'text',
    required INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    UNIQUE(entity_type_id, key)
);

CREATE TABLE IF NOT EXISTS entity_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type_id INTEGER NOT NULL REFERENCES entity_types(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entity_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES entity_records(id) ON DELETE CASCADE,
    field_id INTEGER NOT NULL REFERENCES entity_fields(id) ON DELETE CASCADE,
    value_text TEXT,
    value_num REAL,
    value_date TEXT,
    value_bool INTEGER,
    UNIQUE(record_id, field_id)
);

CREATE TABLE IF NOT EXISTS reminders_one_shot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT,
    fire_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    snooze_until TEXT,
    source_type TEXT,
    source_id INTEGER,
    channel TEXT NOT NULL DEFAULT 'telegram',
    created_from TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminders_recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT,
    rrule TEXT NOT NULL,
    dtstart TEXT NOT NULL,
    time_of_day TEXT NOT NULL DEFAULT '10:00',
    timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
    next_fire_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source_type TEXT,
    source_id INTEGER,
    adapt_window INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminder_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_kind TEXT NOT NULL,
    reminder_id INTEGER NOT NULL,
    planned_at TEXT NOT NULL,
    sent_at TEXT,
    user_action TEXT,
    action_at TEXT,
    snooze_minutes INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT,
    category TEXT,
    remindable INTEGER NOT NULL DEFAULT 0,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relative_path TEXT NOT NULL,
    original_name TEXT,
    mime TEXT,
    sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'inbox',
    source_type TEXT,
    source_id INTEGER,
    ocr_text TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    priority INTEGER NOT NULL DEFAULT 100,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    locked_until TEXT
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL UNIQUE,
    login TEXT,
    secret_encrypted TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DEFAULT_PERSONA_PROMPT = """Ты локальный личный ассистент на ПК пользователя.
Отвечай по-русски, кратко и по делу.
У тебя ЕСТЬ локальная база SQLite: люди, дни рождения, напоминания, ЖКХ.
Факты из блока «ФАКТЫ ИЗ ЛОКАЛЬНОЙ БД» — достоверны: опирайся на них.
Не говори, что у тебя нет памяти или базы — она есть.
Пользователь пишет свободно, с ошибками — понимай смысл.
Чтобы СОХРАНИТЬ новые данные — верни JSON propose_action (не обычный текст «подтверди»).
Подтверждение пользователь даст кнопкой, «Да», «+» или голосом — это делает программа.
Не выдумывай факты, которых нет в БД и которые пользователь не сообщал.
"""

DEFAULT_JOBS = (
    ("due_reminders", 10, 30),
    ("inbox_scan", 40, 120),
    ("mail_poll", 50, 180),
    ("gosuslugi_check", 80, 3600),
    ("zhkh_check", 80, 3600),
    ("backup_db", 90, 86400),
)
