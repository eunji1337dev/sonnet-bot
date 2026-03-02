"""
Асинхронная работа с SQLite.
Инициализация схемы, CRUD-операции для всех таблиц.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import sqlite3
import aiosqlite
import structlog

from config import settings

log = structlog.get_logger(__name__)

_db: Optional[aiosqlite.Connection] = None


# ═══════════════════════════════════════════════════════
# LIFECYCLE
# ═══════════════════════════════════════════════════════


async def init_db() -> None:
    """Открыть соединение и создать таблицы."""
    global _db
    os.makedirs(os.path.dirname(settings.database_path) or ".", exist_ok=True)
    _db = await aiosqlite.connect(settings.database_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _create_tables()
    await _seed_faq()
    await _seed_subjects()
    await _seed_schedule()
    await _seed_links()
    log.info("database initialized", path=settings.database_path)


async def close_db() -> None:
    """Закрыть соединение."""
    global _db
    if _db:
        await _db.close()
        _db = None
        log.info("database closed")


def get_db() -> aiosqlite.Connection:
    """Получить текущее соединение."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


async def get_setting(key: str, default: str = "") -> str:
    """Получить настройку из БД."""
    db = get_db()
    try:
        cursor = await db.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else default
    except Exception as e:
        log.error("failed to get setting", key=key, error=str(e))
        return default


async def set_setting(key: str, value: str) -> None:
    """Сохранить настройку в БД."""
    db = get_db()
    try:
        await db.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
    except Exception as e:
        log.error("failed to set setting", key=key, value=value, error=str(e))


# ═══════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════


async def _create_tables() -> None:
    db = get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_of_week INTEGER NOT NULL,
            time_start TEXT NOT NULL,
            time_end TEXT NOT NULL,
            subject TEXT NOT NULL,
            subject_sk TEXT,
            room TEXT,
            teacher TEXT,
            group_type TEXT DEFAULT 'all',
            is_active BOOLEAN DEFAULT 1,
            semester TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS schedule_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            change_date TEXT NOT NULL,
            change_type TEXT NOT NULL,
            new_room TEXT,
            new_time TEXT,
            reason TEXT,
            announced_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES schedule(id)
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_ru TEXT NOT NULL,
            name_sk TEXT,
            name_en TEXT,
            teacher TEXT,
            teacher_email TEXT,
            teacher_office TEXT,
            exam_type TEXT,
            exam_description TEXT,
            grade_formula TEXT,
            teams_link TEXT,
            materials_link TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            subject_id INTEGER,
            deadline_date TEXT NOT NULL,
            deadline_time TEXT,
            reminder_sent BOOLEAN DEFAULT 0,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subject_id) REFERENCES subjects(id)
        );

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER,
            exam_date TEXT NOT NULL,
            exam_time TEXT,
            room TEXT,
            exam_type TEXT,
            registration_deadline TEXT,
            notes TEXT,
            FOREIGN KEY (subject_id) REFERENCES subjects(id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            description TEXT,
            added_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            role TEXT DEFAULT 'student',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ai_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question TEXT,
            answer TEXT,
            tokens_used INTEGER,
            response_time_ms INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            votes TEXT DEFAULT '{}',
            created_by INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            text TEXT NOT NULL,
            remind_at TIMESTAMP NOT NULL,
            is_sent BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            chat_id INTEGER,
            text TEXT NOT NULL,
            reply_to_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_created
            ON chat_messages(chat_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    await db.commit()


# ═══════════════════════════════════════════════════════
# FAQ SEED DATA
# ═══════════════════════════════════════════════════════

_FAQ_SEED = [
    (
        "faq",
        "Как работает система оценивания?",
        "Оценки A-E (сдано), Fx (не сдано). A — отлично, B — очень хорошо, C — хорошо, D — удовлетворительно, E — достаточно. Для пересдачи регистрируешься на opravny termin через AIS.",
        "оценки,система,grading",
    ),
    (
        "faq",
        "Что такое termin / opravny termin?",
        "Termin — дата экзамена. Opravny termin — пересдача. Druhy opravny termin — вторая пересдача. Регистрация на термины через AIS.",
        "термин,пересдача,экзамен,termin",
    ),
    (
        "faq",
        "Как зарегистрироваться на экзамен?",
        "Через систему AIS (Akademicky informacny system). Зайти в AIS, выбрать предмет, выбрать доступный термин и зарегистрироваться.",
        "регистрация,экзамен,ais",
    ),
    (
        "faq",
        "Что будет если получить Fx?",
        "Предмет не засчитан. Нужно регистрироваться на пересдачу (opravny termin). Если и пересдача Fx — можно попробовать druhy opravny termin. Если и он не сдан — предмет переносится на следующий год.",
        "fx,не сдал,пересдача",
    ),
    (
        "faq",
        "Где искать расписание?",
        "В системе университета или через команду /schedule этого бота. Бот показывает расписание с учетом отмен и переносов.",
        "расписание,где,schedule",
    ),
    (
        "faq",
        "Как связаться с преподавателем?",
        "Через Microsoft Teams или по электронной почте. Email преподавателя можно посмотреть через /subject <название предмета>.",
        "преподаватель,связаться,email,teams",
    ),
]


async def get_classes_starting_at(
    day_of_week: int, time_start: str, semester: Optional[str] = None
) -> List[sqlite3.Row]:
    """Найти занятия, начинающиеся в указанное время."""
    db = get_db()
    sem = semester or settings.current_semester
    cursor = await db.execute(
        "SELECT * FROM schedule WHERE day_of_week = ? AND time_start = ? AND semester = ? AND is_active = 1",
        (day_of_week, time_start, sem),
    )
    return list(await cursor.fetchall())


async def _seed_faq() -> None:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM notes WHERE category = 'faq'")
    row = await cursor.fetchone()
    if row is not None and row[0] > 0:
        return
    for category, title, content, tags in _FAQ_SEED:
        await db.execute(
            "INSERT INTO notes (category, title, content, tags) VALUES (?, ?, ?, ?)",
            (category, title, content, tags),
        )
    await db.commit()
    log.info("seeded FAQ", count=len(_FAQ_SEED))


# ═══════════════════════════════════════════════════════
# SCHEDULE CRUD
# ═══════════════════════════════════════════════════════


async def get_schedule_for_day(
    day_of_week: int, semester: Optional[str] = None
) -> List[Dict[str, Any]]:
    db = get_db()
    sem = semester or settings.current_semester
    cursor = await db.execute(
        "SELECT * FROM schedule WHERE day_of_week = ? AND semester = ? AND is_active = 1 ORDER BY time_start",
        (day_of_week, sem),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_full_schedule(semester: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_db()
    sem = semester or settings.current_semester
    cursor = await db.execute(
        "SELECT * FROM schedule WHERE semester = ? AND is_active = 1 ORDER BY day_of_week, time_start",
        (sem,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_schedule_entry(
    day_of_week: int,
    time_start: str,
    time_end: str,
    subject: str,
    room: str = "",
    teacher: str = "",
    subject_sk: str = "",
    group_type: str = "all",
    semester: Optional[str] = None,
) -> int:
    db = get_db()
    sem = semester or settings.current_semester
    cursor = await db.execute(
        """INSERT INTO schedule
           (day_of_week, time_start, time_end, subject, subject_sk, room, teacher, group_type, semester)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            day_of_week,
            time_start,
            time_end,
            subject,
            subject_sk,
            room,
            teacher,
            group_type,
            sem,
        ),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def remove_schedule_entry(entry_id: int) -> bool:
    db = get_db()
    cursor = await db.execute("DELETE FROM schedule WHERE id = ?", (entry_id,))
    await db.commit()
    return cursor.rowcount > 0


async def update_schedule_entry(entry_id: int, field: str, value: str) -> bool:
    allowed = {
        "subject",
        "subject_sk",
        "room",
        "teacher",
        "time_start",
        "time_end",
        "group_type",
        "day_of_week",
    }
    if field not in allowed:
        return False
    db = get_db()
    cursor = await db.execute(
        f"UPDATE schedule SET {field} = ? WHERE id = ?",  # nosec B608
        (value, entry_id),
    )
    await db.commit()
    return cursor.rowcount > 0


# ═══════════════════════════════════════════════════════
# SCHEDULE CHANGES
# ═══════════════════════════════════════════════════════


async def add_schedule_change(
    schedule_id: int,
    change_date: str,
    change_type: str,
    new_room: str = "",
    new_time: str = "",
    reason: str = "",
    announced_by: str = "",
) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO schedule_changes
           (schedule_id, change_date, change_type, new_room, new_time, reason, announced_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            schedule_id,
            change_date,
            change_type,
            new_room,
            new_time,
            reason,
            announced_by,
        ),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_changes_for_date(date_str: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute(
        "SELECT sc.*, s.subject FROM schedule_changes sc JOIN schedule s ON sc.schedule_id = s.id WHERE sc.change_date = ?",
        (date_str,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════
# SUBJECTS CRUD
# ═══════════════════════════════════════════════════════


async def get_all_subjects() -> List[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute("SELECT * FROM subjects ORDER BY name_ru")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_subject_by_name(query: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    q = f"%{query}%"
    cursor = await db.execute(
        "SELECT * FROM subjects WHERE name_ru LIKE ? OR name_sk LIKE ? OR name_en LIKE ? LIMIT 1",
        (q, q, q),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def add_subject(
    name_ru: str,
    name_sk: str = "",
    name_en: str = "",
    teacher: str = "",
    teacher_email: str = "",
    teacher_office: str = "",
    exam_type: str = "",
    exam_description: str = "",
    grade_formula: str = "",
    teams_link: str = "",
    materials_link: str = "",
    notes: str = "",
) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO subjects
           (name_ru, name_sk, name_en, teacher, teacher_email, teacher_office,
            exam_type, exam_description, grade_formula, teams_link, materials_link, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name_ru,
            name_sk,
            name_en,
            teacher,
            teacher_email,
            teacher_office,
            exam_type,
            exam_description,
            grade_formula,
            teams_link,
            materials_link,
            notes,
        ),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════
# DEADLINES CRUD
# ═══════════════════════════════════════════════════════


async def get_active_deadlines() -> List[Dict[str, Any]]:
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = await db.execute(
        """SELECT d.*, s.name_ru as subject_name FROM deadlines d
           LEFT JOIN subjects s ON d.subject_id = s.id
           WHERE d.deadline_date >= ? ORDER BY d.deadline_date""",
        (today,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_deadline(
    title: str,
    deadline_date: str,
    description: str = "",
    subject_id: Optional[int] = None,
    deadline_time: str = "",
    created_by: str = "",
) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO deadlines (title, description, subject_id, deadline_date, deadline_time, created_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title, description, subject_id, deadline_date, deadline_time, created_by),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def remove_deadline(deadline_id: int) -> bool:
    db = get_db()
    cursor = await db.execute("DELETE FROM deadlines WHERE id = ?", (deadline_id,))
    await db.commit()
    return cursor.rowcount > 0


async def get_upcoming_deadlines(days_ahead: int) -> List[Dict[str, Any]]:
    """Дедлайны в ближайшие N дней (для напоминаний)."""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = await db.execute(
        """SELECT d.*, s.name_ru as subject_name FROM deadlines d
           LEFT JOIN subjects s ON d.subject_id = s.id
           WHERE d.deadline_date >= ? AND d.deadline_date <= date(?, '+' || ? || ' days')
           ORDER BY d.deadline_date""",
        (today, today, days_ahead),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════
# EXAMS CRUD
# ═══════════════════════════════════════════════════════


async def get_all_exams() -> List[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute(
        """SELECT e.*, s.name_ru as subject_name FROM exams e
           LEFT JOIN subjects s ON e.subject_id = s.id
           ORDER BY e.exam_date""",
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_upcoming_exams(days_ahead: int = 30) -> List[Dict[str, Any]]:
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = await db.execute(
        """SELECT e.*, s.name_ru as subject_name FROM exams e
           LEFT JOIN subjects s ON e.subject_id = s.id
           WHERE e.exam_date >= ? AND e.exam_date <= date(?, '+' || ? || ' days')
           ORDER BY e.exam_date""",
        (today, today, days_ahead),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_exam(
    subject_id: int,
    exam_date: str,
    exam_time: str = "",
    room: str = "",
    exam_type: str = "riadny",
    registration_deadline: str = "",
    notes: str = "",
) -> int:
    db = get_db()
    cursor = await db.execute(
        """INSERT INTO exams (subject_id, exam_date, exam_time, room, exam_type, registration_deadline, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            subject_id,
            exam_date,
            exam_time,
            room,
            exam_type,
            registration_deadline,
            notes,
        ),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════
# NOTES / FAQ / LINKS
# ═══════════════════════════════════════════════════════


async def get_notes_by_category(category: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM notes WHERE category = ? ORDER BY created_at DESC",
        (category,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def search_notes(query: str) -> List[Dict[str, Any]]:
    db = get_db()
    q = f"%{query}%"
    cursor = await db.execute(
        "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY created_at DESC",
        (q, q, q),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_note(
    category: str, title: str, content: str, tags: str = "", created_by: str = ""
) -> int:
    db = get_db()
    cursor = await db.execute(
        "INSERT INTO notes (category, title, content, tags, created_by) VALUES (?, ?, ?, ?, ?)",
        (category, title, content, tags, created_by),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_all_links(category: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_db()
    if category:
        cursor = await db.execute(
            "SELECT * FROM links WHERE category = ? ORDER BY created_at DESC",
            (category,),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM links ORDER BY category, created_at DESC"
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_link(
    title: str, url: str, category: str = "", description: str = "", added_by: str = ""
) -> int:
    db = get_db()
    cursor = await db.execute(
        "INSERT INTO links (title, url, category, description, added_by) VALUES (?, ?, ?, ?, ?)",
        (title, url, category, description, added_by),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════


async def upsert_user(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    role: Optional[str] = None,
) -> None:
    db = get_db()
    existing = await db.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    row = await existing.fetchone()
    now = datetime.now().isoformat()
    if row:
        if role:
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_name=?, role=?, last_active=? WHERE id=?",
                (username, first_name, last_name, role, now, user_id),
            )
        else:
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_name=?, last_active=? WHERE id=?",
                (username, first_name, last_name, now, user_id),
            )
    else:
        await db.execute(
            "INSERT INTO users (id, username, first_name, last_name, role, last_active) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, last_name, role or "student", now),
        )
    await db.commit()


async def get_user_role(user_id: int) -> str:
    db = get_db()
    cursor = await db.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    return row["role"] if row else "student"


async def set_user_role(user_id: int, role: str) -> bool:
    db = get_db()
    cursor = await db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    await db.commit()
    return cursor.rowcount > 0


# ═══════════════════════════════════════════════════════
# AI LOGS
# ═══════════════════════════════════════════════════════


async def log_ai_request(
    user_id: int,
    question: str,
    answer: str,
    tokens_used: int = 0,
    response_time_ms: int = 0,
) -> None:
    db = get_db()
    await db.execute(
        "INSERT INTO ai_logs (user_id, question, answer, tokens_used, response_time_ms) VALUES (?, ?, ?, ?, ?)",
        (user_id, question, answer, tokens_used, response_time_ms),
    )
    await db.commit()


async def get_ai_stats(days: int = 7) -> Dict[str, Any]:
    db = get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) as total_queries, SUM(tokens_used) as total_tokens,
                  AVG(response_time_ms) as avg_response_ms
           FROM ai_logs WHERE created_at >= datetime('now', '-' || ? || ' days')""",
        (days,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else {}


# ═══════════════════════════════════════════════════════
# POLLS
# ═══════════════════════════════════════════════════════


async def create_poll(question: str, options: List[str], created_by: int) -> int:
    db = get_db()
    cursor = await db.execute(
        "INSERT INTO polls (question, options, created_by) VALUES (?, ?, ?)",
        (question, json.dumps(options, ensure_ascii=False), created_by),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_poll(poll_id: int) -> Optional[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    d = dict(row)
    d["options"] = json.loads(d["options"])
    d["votes"] = json.loads(d["votes"])
    return d


async def vote_poll(poll_id: int, user_id: int, option_index: int) -> bool:
    db = get_db()
    poll = await get_poll(poll_id)
    if not poll or not poll["is_active"]:
        return False
    if option_index < 0 or option_index >= len(poll["options"]):
        return False
    votes = poll["votes"]
    # Убрать предыдущий голос
    for key in list(votes.keys()):
        if str(user_id) in votes[key]:
            votes[key].remove(str(user_id))
    # Добавить новый
    key = str(option_index)
    if key not in votes:
        votes[key] = []
    votes[key].append(str(user_id))
    await db.execute(
        "UPDATE polls SET votes = ? WHERE id = ?",
        (json.dumps(votes, ensure_ascii=False), poll_id),
    )
    await db.commit()
    return True


async def close_poll(poll_id: int) -> bool:
    db = get_db()
    cursor = await db.execute("UPDATE polls SET is_active = 0 WHERE id = ?", (poll_id,))
    await db.commit()
    return cursor.rowcount > 0


# ═══════════════════════════════════════════════════════
# REMINDERS
# ═══════════════════════════════════════════════════════


async def add_reminder(user_id: int, chat_id: int, text: str, remind_at: str) -> int:
    db = get_db()
    cursor = await db.execute(
        "INSERT INTO reminders (user_id, chat_id, text, remind_at) VALUES (?, ?, ?, ?)",
        (user_id, chat_id, text, remind_at),
    )
    await db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def get_pending_reminders() -> List[Dict[str, Any]]:
    db = get_db()
    now = datetime.now().isoformat()
    cursor = await db.execute(
        "SELECT * FROM reminders WHERE is_sent = 0 AND remind_at <= ? ORDER BY remind_at",
        (now,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def mark_reminder_sent(reminder_id: int) -> None:
    db = get_db()
    await db.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,))
    await db.commit()


# ═══════════════════════════════════════════════════════
# CHAT MESSAGES (память группы)
# ═══════════════════════════════════════════════════════


async def save_chat_message(
    user_id: int,
    username: str,
    first_name: str,
    chat_id: int,
    text: str,
    reply_to_message_id: Optional[int] = None,
) -> None:
    """Сохранить сообщение из группового чата."""
    db = get_db()
    await db.execute(
        """INSERT INTO chat_messages (user_id, username, first_name, chat_id, text, reply_to_message_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, username, first_name, chat_id, text, reply_to_message_id),
    )
    await db.commit()


async def get_recent_messages(chat_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Получить последние N сообщений из чата."""
    db = get_db()
    cursor = await db.execute(
        """SELECT first_name, text, created_at FROM chat_messages
           WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?""",
        (chat_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in reversed(list(rows))]  # Chronological order


async def search_messages(
    chat_id: int, keywords: List[str], limit: int = 20
) -> List[Dict[str, Any]]:
    """Поиск по всей истории сообщений по ключевым словам."""
    if not keywords:
        return []
    db = get_db()
    # Строим LIKE-запрос для каждого ключевого слова
    conditions = " OR ".join(["text LIKE ?" for _ in keywords])
    params = [f"%{kw}%" for kw in keywords]
    params_tuple = tuple([chat_id] + params + [limit])

    cursor = await db.execute(
        f"""SELECT first_name, text, created_at FROM chat_messages
            WHERE chat_id = ? AND ({conditions})
            ORDER BY created_at DESC LIMIT ?""",  # nosec B608
        params_tuple,
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in reversed(list(rows))]


async def get_message_count(chat_id: int) -> int:
    """Количество сохранённых сообщений в чате."""
    db = get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (chat_id,)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


# ═══════════════════════════════════════════════════════
# USAGE STATS
# ═══════════════════════════════════════════════════════


async def get_usage_stats(days: int = 7) -> Dict[str, Any]:
    db = get_db()

    ai = await get_ai_stats(days)

    cursor = await db.execute("SELECT COUNT(*) as total FROM users")
    users_row = await cursor.fetchone()

    cursor = await db.execute(
        """SELECT COUNT(*) as active_users
           FROM users WHERE last_active >= datetime('now', '-' || ? || ' days')""",
        (days,),
    )
    active_row = await cursor.fetchone()

    return {
        "ai_queries": ai.get("total_queries", 0),
        "total_tokens": ai.get("total_tokens", 0),
        "avg_response_ms": ai.get("avg_response_ms", 0),
        "total_users": users_row["total"] if users_row else 0,
        "active_users": active_row["active_users"] if active_row else 0,
    }


# ═══════════════════════════════════════════════════════
# SEED: SUBJECTS (Летний семестр 2025/2026)
# ═══════════════════════════════════════════════════════

_SUBJECTS_SEED = [
    {
        "name_ru": "География религий",
        "name_sk": "Geografia náboženstiev",
        "teacher": "doc. PhDr. ThDr. Daniel Porubec",
        "teacher_email": "daniel.porubec@unipo.sk",
        "exam_type": "",
        "exam_description": "",
    },
    {
        "name_ru": "История Европы II",
        "name_sk": "Dejiny Európy II.",
        "teacher": "doc. PhDr. Jaroslav Coranič",
        "teacher_email": "jaroslav.coranic@unipo.sk",
        "exam_type": "",
        "exam_description": "",
    },
    {
        "name_ru": "История философии — средневековье",
        "name_sk": "Dejiny filozofie – stredovek",
        "teacher": "doc. PhDr. ThDr. Daniel Porubec",
        "teacher_email": "daniel.porubec@unipo.sk",
        "exam_type": "",
        "exam_description": "",
    },
    {
        "name_ru": "Английский язык II",
        "name_sk": "Anglický jazyk II.",
        "teacher": "Mgr. Drahomira Longauerová",
        "teacher_email": "drahomira.longauerova@unipo.sk",
        "exam_type": "",
        "exam_description": "1. skupina: среда 13:15–14:55. 2. skupina: вторник 09:45–11:25",
    },
    {
        "name_ru": "Основы демографии",
        "name_sk": "Základy demografie",
        "teacher": "prof. Mgr. Kamil Kardis",
        "teacher_email": "kamil.kardis@unipo.sk",
        "exam_type": "индивидуальный проект",
        "exam_description": "Структура: Введение → Демография → Факторы → Прогноз → Заключение. ⚠️ Кардис игнорирует письма — спрашивать лично!",
    },
    {
        "name_ru": "Словацкий язык",
        "name_sk": "Slovenský jazyk",
        "teacher": "PaedDr. Zdenka Uherová",
        "teacher_email": "zdenka.uherova@unipo.sk",
        "exam_type": "",
        "exam_description": "Ректорат, ауд. E225. Книга: Križom Krážom A2. Сайт: https://www.e-slovak.sk/",
    },
    {
        "name_ru": "История Словакии I",
        "name_sk": "Dejiny Slovenska I.",
        "teacher": "Mgr. Jana Lukáčová",
        "teacher_email": "jana.lukacova.1@unipo.sk",
        "exam_type": "проект + тест + тест",
        "exam_description": "Проект: 3–4 чел, 6 мин/чел; тема до Марии Терезии; 5 печатных источников. ⚠️ Нет 02.04 и 13–17.04",
    },
    {
        "name_ru": "Философия познания",
        "name_sk": "Filozofia poznania",
        "teacher": "doc. ThDr. Radovan Šoltés",
        "teacher_email": "radovan.soltes@unipo.sk",
        "exam_type": "2 písomky",
        "exam_description": "2 письменные работы",
    },
    {
        "name_ru": "Феноменология религии",
        "name_sk": "Fenomenológia náboženstva",
        "teacher": "doc. ThDr. Radovan Šoltés",
        "teacher_email": "radovan.soltes@unipo.sk",
        "exam_type": "2 písomky",
        "exam_description": "2 письменные работы",
    },
    {
        "name_ru": "Теория и методология религиоведения",
        "name_sk": "Teória a metodológia religionistiky",
        "teacher": "doc. ThDr. Radovan Šoltés",
        "teacher_email": "radovan.soltes@unipo.sk",
        "exam_type": "презентация",
        "exam_description": "Группа 2–3 чел. Тема: суеверие/магия. Структура: 1. Содержание / 2. История / 3. Психология",
    },
    {
        "name_ru": "Экологическое воспитание",
        "name_sk": "Ekologická výchova",
        "teacher": "prof. ThDr. Marek Petro",
        "teacher_email": "marek.petro@unipo.sk",
        "exam_type": "презентация + семестровая работа",
        "exam_description": "Группа 5 чел; 5 подглав; 15 страниц. ⏰ Дедлайн: 09.04",
    },
    {
        "name_ru": "Христианская археология",
        "name_sk": "Kresťanská archeológia",
        "teacher": "Mgr. Jana Lukáčová",
        "teacher_email": "jana.lukacova.1@unipo.sk",
        "exam_type": "презентация (зачёт)",
        "exam_description": "Группа 3 чел, 5 мин/чел. Источник: публикации Peter Tsaban, период I–II века",
    },
]


async def _seed_subjects() -> None:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM subjects")
    row = await cursor.fetchone()
    if row is not None and row[0] > 0:
        return
    for s in _SUBJECTS_SEED:
        await db.execute(
            """INSERT INTO subjects (name_ru, name_sk, teacher, teacher_email, exam_type, exam_description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                s["name_ru"],
                s.get("name_sk", ""),
                s.get("teacher", ""),
                s.get("teacher_email", ""),
                s.get("exam_type", ""),
                s.get("exam_description", ""),
            ),
        )
    await db.commit()
    log.info("seeded subjects", count=len(_SUBJECTS_SEED))


# ═══════════════════════════════════════════════════════
# SEED: SCHEDULE (Летний семестр 2025/2026)
# ═══════════════════════════════════════════════════════

# (day_of_week, time_start, time_end, subject, room, teacher, group_type)
_SCHEDULE_SEED = [
    # Понедельник (Po)
    (0, "08:00", "09:40", "Geografia náboženstiev", "A2", "Porubec", "all"),
    (0, "09:45", "11:25", "Dejiny Európy II.", "A2", "Coranič", "all"),
    # Вторник (Ut)
    (1, "08:00", "09:40", "Dejiny filozofie – stredovek", "A2", "Porubec", "all"),
    (1, "09:45", "11:25", "Anglický jazyk II.", "A2", "Longauerová", "sk2"),
    (1, "11:30", "13:10", "Základy demografie", "A2", "Kardis K.", "all"),
    (1, "15:00", "16:40", "Slovenský jazyk", "Rektorát E225", "Uherová", "all"),
    # Среда (St)
    (2, "08:00", "09:40", "Dejiny Slovenska I.", "A3", "Lukáčová", "all"),
    (2, "09:45", "11:25", "Filozofia poznania", "A2", "Šoltés", "all"),
    (2, "11:30", "13:10", "Fenomenológia náboženstva", "A2", "Šoltés", "all"),
    (2, "13:15", "14:55", "Anglický jazyk II.", "A2", "Longauerová", "sk1"),
    # Четверг (Št)
    (3, "08:00", "09:40", "Kresťanská archeológia", "A2", "Lukáčová", "all"),
    (3, "09:45", "11:25", "Ekologická výchova", "A2", "Petro", "all"),
    (3, "11:30", "13:10", "Teória a metodológia religionistiky", "A2", "Šoltés", "all"),
    (3, "15:00", "16:40", "Slovenský jazyk", "Rektorát E225", "Uherová", "all"),
    # Пятница — ВЫХОДНОЙ
]


async def _seed_schedule() -> None:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM schedule")
    row = await cursor.fetchone()
    if row is not None and row[0] > 0:
        return
    sem = settings.current_semester
    for day, t_start, t_end, subject, room, teacher, group_type in _SCHEDULE_SEED:
        await db.execute(
            """INSERT INTO schedule (day_of_week, time_start, time_end, subject, room, teacher, group_type, semester)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (day, t_start, t_end, subject, room, teacher, group_type, sem),
        )
    await db.commit()
    log.info("seeded schedule", count=len(_SCHEDULE_SEED))


# ═══════════════════════════════════════════════════════
# SEED: LINKS
# ═══════════════════════════════════════════════════════

_LINKS_SEED = [
    (
        "Расписание GTF",
        "https://www.unipo.sk/greckokatolicka-teologicka-fakulta/informacie-pre-studentov/dennaforma/rozvrh",
        "university",
        "Официальное расписание",
    ),
    (
        "e-Slovak",
        "https://www.e-slovak.sk/",
        "study",
        "Учебник словацкого + сертификат",
    ),
    (
        "Google Maps GTF",
        "https://maps.app.goo.gl/ZNjDkxJDvq1HaWUR9",
        "navigation",
        "Карта факультета",
    ),
    ("Telegram — основной", "https://t.me/eusb1gtf", "chat", "Основной чат группы"),
    ("Telegram — флуд", "https://t.me/+anXo4zu6f10xN2Ni", "chat", "Флуд-чат"),
    (
        "Peter Tsaban (книги)",
        "https://ekniznice.cvtisr.sk/view/uuid:fab148b2-20a7-4b48-b7e5-a1d10fc3ff1d",
        "study",
        "Для презентации по Kresťanská archeológia",
    ),
    (
        "Križom Krážom A1 (PDF)",
        "https://www.scribd.com/document/552274126/",
        "study",
        "Учебник словацкого A1",
    ),
]


async def _seed_links() -> None:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM links")
    row = await cursor.fetchone()
    if row is not None and row[0] > 0:
        return
    for title, url, category, description in _LINKS_SEED:
        await db.execute(
            "INSERT INTO links (title, url, category, description) VALUES (?, ?, ?, ?)",
            (title, url, category, description),
        )
    await db.commit()
    log.info("seeded links", count=len(_LINKS_SEED))
