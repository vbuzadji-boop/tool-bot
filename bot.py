import os
import asyncio
import json
import logging

from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import gspread
from oauth2client.service_account import ServiceAccountCredentials

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
TOOLS_SHEET_NAME = "tools"
MOVES_SHEET_NAME = "moves"


logging.basicConfig(level=logging.INFO)

user_states = {}


def get_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    if not GOOGLE_CREDENTIALS:
        raise Exception("GOOGLE_CREDENTIALS не задана")

    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

    return gspread.authorize(creds)

def get_tools_sheet():
    client = get_client()
    return client.open_by_key(SPREADSHEET_ID).worksheet(TOOLS_SHEET_NAME)


def get_moves_sheet():
    client = get_client()
    return client.open_by_key(SPREADSHEET_ID).worksheet(MOVES_SHEET_NAME)


def get_all_tools():
    return get_tools_sheet().get_all_records()


def get_tools_list():
    return get_tools_sheet().get_all_records()


def find_tool(tool_id):
    data = get_all_tools()
    for row in data:
        if str(row.get("id", "")).strip().upper() == tool_id.strip().upper():
            return row
    return None


def get_row_index_by_tool_id(tool_id):
    sheet = get_tools_sheet()
    values = sheet.get_all_values()

    for i, row in enumerate(values[1:], start=2):
        if len(row) > 0 and str(row[0]).strip().upper() == tool_id.strip().upper():
            return i
    return None


def normalize_tool_id(text: str) -> str:
    text = text.strip()

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            text = parts[1].strip()
        else:
            return ""

    if text.lower().startswith("tool_"):
        text = text[5:]

    return text.strip().upper()


def format_tool_text(tool):
    return (
        f"🔧 {tool.get('название')}\n\n"
        f"ID: {tool.get('id')}\n"
        f"Статус: {tool.get('статус') or '-'}\n"
        f"У кого: {tool.get('у кого') or '-'}\n"
        f"Объект: {tool.get('объект') or '-'}\n"
        f"Последнее действие: {tool.get('последнее действие') or '-'}"
    )


def build_tool_keyboard(tool_id):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Забрал", callback_data=f"take:{tool_id}")
    kb.button(text="🔄 Вернул", callback_data=f"return:{tool_id}")
    kb.button(text="📍 На объект", callback_data=f"object:{tool_id}")
    kb.adjust(1)
    return kb.as_markup()


def update_tool(tool_id, status=None, user=None, obj=None, last_action=None):
    sheet = get_tools_sheet()
    row_idx = get_row_index_by_tool_id(tool_id)

    if not row_idx:
        return False

    headers = sheet.row_values(1)
    header_map = {name: i + 1 for i, name in enumerate(headers)}

    if status is not None and "статус" in header_map:
        sheet.update_cell(row_idx, header_map["статус"], status)

    if user is not None and "у кого" in header_map:
        sheet.update_cell(row_idx, header_map["у кого"], user)

    if obj is not None and "объект" in header_map:
        sheet.update_cell(row_idx, header_map["объект"], obj)

    if last_action is not None and "последнее действие" in header_map:
        sheet.update_cell(row_idx, header_map["последнее действие"], last_action)

    return True


def add_move(tool_id, action, employee="", obj="", clicked_by="", comment=""):
    tool = find_tool(tool_id)
    tool_name = tool.get("название") if tool else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sheet = get_moves_sheet()
    sheet.append_row([
        now,
        tool_id,
        tool_name,
        action,
        employee,
        obj,
        clicked_by,
        comment
    ])


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def send_tool_card(message: Message, raw_text: str):
    tool_id = normalize_tool_id(raw_text)

    if not tool_id:
        await message.answer("Отправьте ID инструмента, например: T001")
        return

    tool = find_tool(tool_id)

    if not tool:
        await message.answer(f"Инструмент {tool_id} не найден")
        return

    photo = tool.get("фото_url")
    text = format_tool_text(tool)
    markup = build_tool_keyboard(tool_id)

    if photo:
        await message.answer_photo(photo=photo, caption=text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@dp.message(CommandStart())
async def start_handler(message: Message):
    text = message.text or ""

    if text.strip() == "/start":
        await message.answer(
            "Напишите ID инструмента, например: T001\n"
            "Или используйте команду /list для списка инструментов."
        )
        return

    await send_tool_card(message, text)


@dp.message(F.text == "/list")
async def list_tools_handler(message: Message):
    tools = get_tools_list()

    if not tools:
        await message.answer("Список инструментов пуст.")
        return

    lines = ["📋 Список инструментов:\n"]

    for tool in tools:
        tool_id = str(tool.get("id", "")).strip()
        name = str(tool.get("название", "")).strip()
        lines.append(f"{tool_id} — {name}")

    text = "\n".join(lines)

    if len(text) > 3500:
        parts = []
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > 3500:
                parts.append(current)
                current = line
            else:
                current += ("\n" if current else "") + line

        if current:
            parts.append(current)

        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)

    await message.answer("👉 Введите ID инструмента, например: T001")


@dp.message(F.text)
async def text_handler(message: Message):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    # 👇 ВСТАВИЛИ СЮДА
    if chat_id in user_states and user_states[chat_id]["mode"] == "repair_confirm":
        tool_id = user_states[chat_id]["tool_id"]

        if text.lower() in ["да", "yes"]:
            update_tool(
                tool_id=tool_id,
                status="на ремонте"
            )

            add_move(
                tool_id=tool_id,
                action="ремонт",
                employee="",
                obj="",
                clicked_by=str(chat_id),
                comment="отправлен в ремонт"
            )

            await message.answer("🔧 Инструмент отправлен на ремонт")
        else:
            await message.answer("✅ Оставлен на складе")

        del user_states[chat_id]
        return

    if chat_id in user_states and user_states[chat_id]["mode"] == "object_wait_name":
        tool_id = user_states[chat_id]["tool_id"]
        obj = text
        last_action = f"на объекте: {obj} ({datetime.now().strftime('%d.%m %H:%M')})"

        current_tool = find_tool(tool_id)
        current_user = current_tool.get("у кого") if current_tool else ""

        update_tool(
            tool_id=tool_id,
            status="на объекте",
            user=current_user or "",
            obj=obj,
            last_action=last_action
        )

        add_move(
            tool_id=tool_id,
            action="на объект",
            employee=current_user or "",
            obj=obj,
            clicked_by=str(chat_id),
            comment=""
        )

        del user_states[chat_id]
        await message.answer("Готово: инструмент отмечен как находящийся на объекте.")
        await send_tool_card(message, tool_id)
        return

    await send_tool_card(message, text)


@dp.callback_query(F.data.startswith("take:"))
async def take_handler(callback: CallbackQuery):
    tool_id = callback.data.split(":", 1)[1]
    user_states[callback.message.chat.id] = {
        "mode": "take_wait_user",
        "tool_id": tool_id
    }
    await callback.message.answer("Введите имя сотрудника, который забрал инструмент:")
    await callback.answer()


@dp.callback_query(F.data.startswith("return:"))
async def return_handler(callback: CallbackQuery):
    tool_id = callback.data.split(":", 1)[1]
    last_action = f"возврат ({datetime.now().strftime('%d.%m %H:%M')})"

    update_tool(
        tool_id=tool_id,
        status="на складе",
        user="",
        obj="",
        last_action=last_action
    )

    add_move(
        tool_id=tool_id,
        action="возврат",
        employee="",
        obj="",
        clicked_by=str(callback.message.chat.id),
        comment=""
    )

    # 👇 НОВОЕ — спрашиваем про ремонт
    user_states[callback.message.chat.id] = {
        "mode": "repair_confirm",
        "tool_id": tool_id
    }

    await callback.message.answer("Нужно отправить инструмент на ремонт? (да/нет)")
    await callback.answer()

@dp.callback_query(F.data.startswith("object:"))
async def object_handler(callback: CallbackQuery):
    tool_id = callback.data.split(":", 1)[1]
    user_states[callback.message.chat.id] = {
        "mode": "object_wait_name",
        "tool_id": tool_id
    }
    await callback.message.answer("Введите название объекта:")
    await callback.answer()


async def handle(request):
    return web.Response(text="Bot is running")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    await start_web_server()   # ВАЖНО!
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
