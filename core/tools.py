from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import structlog
from google.genai import types

from core import database as db
from utils.validators import parse_day_of_week

log = structlog.get_logger(__name__)


class ToolRegistry:
    """Registry for Gemini 2.0 Pro Function Calling Tools."""

    def __init__(self) -> None:
        pass

    @property
    def gemini_tools(self) -> List[types.Tool]:
        """Returns the list of tools formatted for Gemini genai SDK."""
        # Using FunctionDeclaration matching genai v1.0.0+ syntax
        return [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_schedule_for_day",
                        description="Получает расписание занятий на конкретный день недели. 0 - Понедельник, 6 - Воскресенье.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "day_of_week": types.Schema(
                                    type=types.Type.INTEGER,
                                    description="День недели цифрой (0=Пн, 1=Вт, 2=Ср, 3=Чт, 4=Пт, 5=Сб, 6=Вс)",
                                )
                            },
                            required=["day_of_week"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="get_upcoming_deadlines",
                        description="Получает список ближайших дедлайнов (задания, домашка).",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "days_ahead": types.Schema(
                                    type=types.Type.INTEGER,
                                    description="На сколько дней вперед искать (обычно 30)",
                                )
                            },
                            required=["days_ahead"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="get_upcoming_exams",
                        description="Получает список ближайших экзаменов (терминов).",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "days_ahead": types.Schema(
                                    type=types.Type.INTEGER,
                                    description="На сколько дней вперед искать (обычно 30)",
                                )
                            },
                            required=["days_ahead"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="get_subject_info",
                        description="Поиск информации по предмету, преподавателю или предметным ссылкам.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "query": types.Schema(
                                    type=types.Type.STRING,
                                    description="Название предмета или имя преподавателя",
                                )
                            },
                            required=["query"],
                        ),
                    ),
                    types.FunctionDeclaration(
                        name="get_current_datetime_info",
                        description="Получает ТЕКУЩУЮ дату, день недели и время. Вызывать всегда, когда нужны относительные даты (завтра, сегодня).",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={},
                        ),
                    ),
                ]
            )
        ]

    async def execute_tool(self, call: types.FunctionCall) -> types.Part:
        """Executes a function call requested by the LLM and returns the result."""
        name = call.name
        args = call.args if call.args else {}
        
        log.info("executing llm tool", tool_name=name, args=args)
        
        try:
            if name == "get_schedule_for_day":
                day = int(args.get("day_of_week", 0))
                # Protect against out-of-bounds days
                if not 0 <= day <= 6:
                     result = {"error": "Invalid day_of_week. Must be 0-6."}
                else:
                    schedule = await db.get_schedule_for_day(day)
                    if not schedule:
                        result = {"result": "Расписание пустое или пар нет."}
                    else:
                        result = {"result": schedule}
                
            elif name == "get_upcoming_deadlines":
                days = int(args.get("days_ahead", 30))
                deadlines = await db.get_upcoming_deadlines(days)
                result = {"result": deadlines if deadlines else "Дедлайнов нет."}
                
            elif name == "get_upcoming_exams":
                days = int(args.get("days_ahead", 30))
                exams = await db.get_upcoming_exams(days)
                result = {"result": exams if exams else "Экзаменов нет."}
                
            elif name == "get_subject_info":
                query = str(args.get("query", ""))
                subject = await db.get_subject_by_name(query)
                result = {"result": subject if subject else f"Предмет {query} не найден."}
                
            elif name == "get_current_datetime_info":
                now = datetime.now()
                result = {
                    "current_date": now.strftime("%Y-%m-%d"),
                    "current_time": now.strftime("%H:%M:%S"),
                    "current_day_of_week": now.weekday() # 0 = Monday
                }
            
            else:
                log.warning("unknown tool called by llm", tool_name=name)
                result = {"error": f"Unknown function: {name}"}
                
        except Exception as e:
            log.error("tool execution failed", tool_name=name, error=str(e))
            result = {"error": str(e)}

        # Wrap result in a Part for Google GenAI SDK v1.0
        return types.Part.from_function_response(
            name=name,
            response=result
        )
