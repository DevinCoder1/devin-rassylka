"""Telegram broadcast bot — aiogram 3 front-end over a Telethon user-bot."""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import uuid
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

import keyboards
from broadcaster import Broadcaster
from config import BOT_TOKEN
from spintax import spin
from states import ChatStates, LoginStates, SettingStates, TextStates
from storage import Storage
from userbot import UserbotManager

MEDIA_DIR = os.path.join(os.path.dirname(__file__), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

MEDIA_TYPE_LABELS = {
    "photo": "🖼 фото",
    "video": "🎬 видео",
    "document": "📎 документ",
    "animation": "🌀 GIF",
    "audio": "🎵 аудио",
    "voice": "🎙 голосовое",
    "video_note": "📹 кружок",
    "sticker": "🪄 стикер",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("broadcast-bot")

storage = Storage()
userbots = UserbotManager()
broadcaster = Broadcaster(storage, userbots)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


def _pick_media(message: Message) -> Optional[tuple[str, str, Optional[str]]]:
    """Return (media_type, file_id, suggested_ext) if message contains supported media."""
    if message.photo:
        return "photo", message.photo[-1].file_id, ".jpg"
    if message.video:
        return "video", message.video.file_id, ".mp4"
    if message.animation:
        return "animation", message.animation.file_id, ".mp4"
    if message.document:
        name = message.document.file_name or ""
        ext = os.path.splitext(name)[1] or ""
        return "document", message.document.file_id, ext or None
    if message.audio:
        return "audio", message.audio.file_id, ".mp3"
    if message.voice:
        return "voice", message.voice.file_id, ".ogg"
    if message.video_note:
        return "video_note", message.video_note.file_id, ".mp4"
    if message.sticker:
        return "sticker", message.sticker.file_id, ".webp"
    return None


async def _download_media(file_id: str, ext: Optional[str]) -> str:
    file = await bot.get_file(file_id)
    suffix = ext or os.path.splitext(file.file_path or "")[1] or ""
    dst = os.path.join(MEDIA_DIR, f"{uuid.uuid4().hex}{suffix}")
    await bot.download_file(file.file_path, destination=dst)
    return dst


def _remove_media_file(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


HELP_TEXT = (
    "<b>Как пользоваться</b>\n\n"
    "1. Получи <b>API ID</b> и <b>API HASH</b> на https://my.telegram.org → API development tools.\n"
    "2. Нажми «🔑 Войти в аккаунт», введи API ID, API HASH, номер телефона.\n"
    "3. Telegram пришлёт код в твой аккаунт — введи его в формате <code>1 2 3 4 5</code> "
    "(с пробелами/дефисами), иначе Telegram аннулирует код.\n"
    "4. Добавь чаты (через @username, ссылку t.me/... или числовой ID).\n"
    "5. Задай контент рассылки — пришли боту текстовое сообщение <b>или медиа</b> "
    "(фото, видео, документ, GIF, аудио, голосовое, кружок, стикер) с подписью или без. "
    "Поддерживается <b>spintax</b>: <code>Привет, {друг|коллега|сосед}!</code> — каждый раз случайный вариант.\n"
    "6. В «⚙️ Настройки» выбери интервал, джиттер, паузу между циклами, "
    "перемешивание чатов.\n"
    "7. Жми «▶️ Запустить рассылку». Бот будет слать сообщения с твоего аккаунта "
    "по кругу, пока ты не нажмёшь «⏹ Остановить».\n\n"
    "⚠️ Помни про лимиты Telegram: слишком короткий интервал или большое число чатов "
    "приведут к FloodWait и блокировке аккаунта."
)


async def render_menu(chat_id: int, tg_user_id: int, edit: Optional[Message] = None) -> None:
    user = await storage.get_user(tg_user_id)
    chats = await storage.list_chats(tg_user_id)
    status = "🟢 работает" if user.is_running else "⚪️ остановлена"
    acc = "подключён" if user.session else "не подключён"
    if user.media_path:
        media_label = MEDIA_TYPE_LABELS.get(user.media_type or "", user.media_type or "медиа")
        content = f"{media_label}{' + текст' if user.message_text else ''}"
    elif user.message_text:
        content = "текст"
    else:
        content = "не задан"
    text = (
        f"<b>Рассылочный бот</b>\n\n"
        f"Аккаунт: <b>{acc}</b>\n"
        f"Чатов: <b>{len(chats)}</b>\n"
        f"Контент: <b>{content}</b>\n"
        f"Интервал: <b>{user.interval}с</b> ±{user.jitter}с, пауза между циклами: "
        f"<b>{user.cycle_delay}с</b>\n"
        f"Spintax: <b>{'вкл' if user.spintax_enabled else 'выкл'}</b>, "
        f"перемешивание: <b>{'вкл' if user.shuffle else 'выкл'}</b>\n"
        f"Рассылка: <b>{status}</b>\n"
        f"Отправлено: <b>{user.sent_count}</b>, ошибок: <b>{user.fail_count}</b>"
    )
    kb = keyboards.main_menu(user, len(chats))
    if edit is not None:
        try:
            await edit.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb)


# ---------- Start / help / menu ----------


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await render_menu(message.chat.id, message.from_user.id)


@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await render_menu(message.chat.id, message.from_user.id)


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=keyboards.back_menu(), disable_web_page_preview=True)


@dp.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)
    await call.answer()


@dp.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery) -> None:
    await call.message.edit_text(
        HELP_TEXT, reply_markup=keyboards.back_menu(), disable_web_page_preview=True
    )
    await call.answer()


@dp.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current and current.startswith("LoginStates"):
        await userbots.cancel_login(call.from_user.id)
    await call.answer("Отменено")
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)


# ---------- Login flow ----------


@dp.callback_query(F.data == "login")
async def cb_login(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LoginStates.api_id)
    await call.message.edit_text(
        "Введите <b>API ID</b> (число).\n\nПолучить: https://my.telegram.org",
        reply_markup=keyboards.cancel_menu(),
        disable_web_page_preview=True,
    )
    await call.answer()


@dp.callback_query(F.data == "account")
async def cb_account(call: CallbackQuery) -> None:
    user = await storage.get_user(call.from_user.id)
    msg = (
        f"Аккаунт подключён.\nТелефон: <code>{html.escape(user.phone or '—')}</code>\n"
        "Можно выйти, чтобы подключить другой."
    )
    await call.message.edit_text(msg, reply_markup=keyboards.account_menu(has_session=True))
    await call.answer()


@dp.callback_query(F.data == "logout")
async def cb_logout(call: CallbackQuery) -> None:
    if broadcaster.is_running(call.from_user.id):
        await broadcaster.stop(call.from_user.id)
    await userbots.drop_client(call.from_user.id)
    await storage.update_user(
        call.from_user.id, session=None, api_id=None, api_hash=None, phone=None
    )
    await call.answer("Вышли из аккаунта")
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)


@dp.message(LoginStates.api_id)
async def login_api_id(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("API ID должен быть числом. Попробуй ещё раз.", reply_markup=keyboards.cancel_menu())
        return
    await state.update_data(api_id=int(text))
    await state.set_state(LoginStates.api_hash)
    await message.answer("Теперь введи <b>API HASH</b>.", reply_markup=keyboards.cancel_menu())


@dp.message(LoginStates.api_hash)
async def login_api_hash(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{32}", text):
        await message.answer(
            "API HASH должен быть 32-символьной hex-строкой. Попробуй ещё раз.",
            reply_markup=keyboards.cancel_menu(),
        )
        return
    await state.update_data(api_hash=text)
    await state.set_state(LoginStates.phone)
    await message.answer(
        "Введи номер телефона в международном формате, например <code>+79991234567</code>.",
        reply_markup=keyboards.cancel_menu(),
    )


@dp.message(LoginStates.phone)
async def login_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    if not re.fullmatch(r"\+?\d{7,15}", phone):
        await message.answer("Неверный номер. Попробуй ещё раз.", reply_markup=keyboards.cancel_menu())
        return
    data = await state.get_data()
    try:
        await userbots.start_login(message.from_user.id, data["api_id"], data["api_hash"], phone)
    except Exception as exc:
        log.exception("start_login failed")
        await message.answer(
            f"Ошибка при запросе кода: <code>{html.escape(str(exc))}</code>",
            reply_markup=keyboards.cancel_menu(),
        )
        await state.clear()
        return
    await state.update_data(phone=phone)
    await state.set_state(LoginStates.code)
    await message.answer(
        "Код отправлен в твой Telegram.\n"
        "⚠️ Введи его <b>с пробелами или дефисами</b> между цифрами "
        "(например <code>1 2 3 4 5</code>), иначе Telegram аннулирует код.",
        reply_markup=keyboards.cancel_menu(),
    )


@dp.message(LoginStates.code)
async def login_code(message: Message, state: FSMContext) -> None:
    code = re.sub(r"\D", "", message.text or "")
    if not code:
        await message.answer("Не вижу цифр в коде. Попробуй ещё раз.", reply_markup=keyboards.cancel_menu())
        return
    status, data = await userbots.confirm_code(message.from_user.id, code)
    if status == "ok":
        fsm = await state.get_data()
        await storage.update_user(
            message.from_user.id,
            api_id=fsm["api_id"],
            api_hash=fsm["api_hash"],
            phone=fsm["phone"],
            session=data,
        )
        await state.clear()
        await message.answer("✅ Аккаунт подключён.")
        await render_menu(message.chat.id, message.from_user.id)
    elif status == "2fa":
        await state.set_state(LoginStates.password)
        await message.answer("Включена 2FA. Введи облачный пароль:", reply_markup=keyboards.cancel_menu())
    else:
        await message.answer(
            f"Ошибка: <code>{html.escape(str(data))}</code>\nПопробуй ввести код ещё раз "
            "или нажми «Отмена» и начни заново.",
            reply_markup=keyboards.cancel_menu(),
        )


@dp.message(LoginStates.password)
async def login_password(message: Message, state: FSMContext) -> None:
    password = message.text or ""
    status, data = await userbots.confirm_password(message.from_user.id, password)
    if status == "ok":
        fsm = await state.get_data()
        await storage.update_user(
            message.from_user.id,
            api_id=fsm["api_id"],
            api_hash=fsm["api_hash"],
            phone=fsm["phone"],
            session=data,
        )
        await state.clear()
        await message.answer("✅ Аккаунт подключён.")
        await render_menu(message.chat.id, message.from_user.id)
    else:
        await message.answer(
            f"Ошибка: <code>{html.escape(str(data))}</code>. Попробуй ещё раз.",
            reply_markup=keyboards.cancel_menu(),
        )


# ---------- Chats ----------


@dp.callback_query(F.data == "chats")
async def cb_chats(call: CallbackQuery) -> None:
    chats = await storage.list_chats(call.from_user.id)
    if chats:
        lines = "\n".join(f"• <code>{html.escape(c.identifier)}</code>" for c in chats)
        text = f"<b>Чаты для рассылки ({len(chats)})</b>\n\n{lines}"
    else:
        text = "Список чатов пуст."
    await call.message.edit_text(text, reply_markup=keyboards.chats_menu(chats))
    await call.answer()


@dp.callback_query(F.data == "addchat")
async def cb_addchat(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ChatStates.waiting)
    await call.message.edit_text(
        "Пришли чат одним из способов:\n"
        "• <code>@username</code>\n"
        "• ссылка <code>https://t.me/username</code> или <code>https://t.me/+abc...</code>\n"
        "• числовой ID (например <code>-1001234567890</code>)\n\n"
        "Можно прислать несколько штук через пробел или перевод строки.",
        reply_markup=keyboards.cancel_menu(),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("rmchat:"))
async def cb_rmchat(call: CallbackQuery) -> None:
    chat_id = int(call.data.split(":", 1)[1])
    await storage.remove_chat(call.from_user.id, chat_id)
    chats = await storage.list_chats(call.from_user.id)
    if chats:
        lines = "\n".join(f"• <code>{html.escape(c.identifier)}</code>" for c in chats)
        text = f"<b>Чаты для рассылки ({len(chats)})</b>\n\n{lines}"
    else:
        text = "Список чатов пуст."
    await call.message.edit_text(text, reply_markup=keyboards.chats_menu(chats))
    await call.answer("Удалён")


@dp.message(ChatStates.waiting)
async def chat_input(message: Message, state: FSMContext) -> None:
    tokens = re.split(r"[\s,]+", (message.text or "").strip())
    tokens = [t for t in tokens if t]
    if not tokens:
        await message.answer("Не вижу идентификаторов чатов. Попробуй ещё раз.", reply_markup=keyboards.cancel_menu())
        return
    added, skipped = 0, 0
    for token in tokens:
        ok = await storage.add_chat(message.from_user.id, token, None)
        if ok:
            added += 1
        else:
            skipped += 1
    await state.clear()
    await message.answer(f"Добавлено: {added}, дубликатов пропущено: {skipped}.")
    await render_menu(message.chat.id, message.from_user.id)


# ---------- Text ----------


@dp.callback_query(F.data == "text")
async def cb_text(call: CallbackQuery, state: FSMContext) -> None:
    user = await storage.get_user(call.from_user.id)
    await state.set_state(TextStates.waiting)
    current_parts = []
    if user.media_path:
        media_label = MEDIA_TYPE_LABELS.get(user.media_type or "", user.media_type or "медиа")
        current_parts.append(f"Сейчас установлено медиа: {media_label}")
    if user.message_text:
        current_parts.append(
            f"Текст/подпись:\n<blockquote>{html.escape(user.message_text)}</blockquote>"
        )
    current = "\n".join(current_parts) if current_parts else "Сейчас ничего не задано."
    await call.message.edit_text(
        "Пришли одним сообщением то, что хочешь рассылать:\n"
        "• <b>текст</b>,\n"
        "• <b>фото / видео / документ / GIF / аудио / голосовое / кружок / стикер</b> "
        "(можно с подписью).\n\n"
        "Поддерживается <b>spintax</b>: <code>Привет, {друг|коллега}!</code>\n\n"
        f"{current}",
        reply_markup=keyboards.text_edit_menu(has_media=bool(user.media_path), has_text=bool(user.message_text)),
    )
    await call.answer()


@dp.callback_query(F.data == "clear_media")
async def cb_clear_media(call: CallbackQuery, state: FSMContext) -> None:
    user = await storage.get_user(call.from_user.id)
    _remove_media_file(user.media_path)
    await storage.update_user(call.from_user.id, media_path=None, media_type=None)
    await call.answer("Медиа удалено")
    await state.clear()
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)


@dp.callback_query(F.data == "clear_text")
async def cb_clear_text(call: CallbackQuery, state: FSMContext) -> None:
    await storage.update_user(call.from_user.id, message_text="")
    await call.answer("Текст удалён")
    await state.clear()
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)


@dp.message(TextStates.waiting)
async def text_input(message: Message, state: FSMContext) -> None:
    caption = message.caption or message.text or ""
    media = _pick_media(message)
    if media is None and not caption:
        await message.answer(
            "Нужно текстовое сообщение или медиа (фото/видео/документ/GIF/аудио/голосовое/кружок).",
            reply_markup=keyboards.cancel_menu(),
        )
        return

    user = await storage.get_user(message.from_user.id)
    updates: dict = {"message_text": caption}
    if media is not None:
        media_type, file_id, ext = media
        try:
            path = await _download_media(file_id, ext)
        except Exception as exc:
            log.exception("download media failed")
            await message.answer(
                f"Не удалось скачать медиа: <code>{html.escape(str(exc))}</code>",
                reply_markup=keyboards.cancel_menu(),
            )
            return
        _remove_media_file(user.media_path)
        updates["media_path"] = path
        updates["media_type"] = media_type

    await storage.update_user(message.from_user.id, **updates)
    await state.clear()
    if media is not None:
        label = MEDIA_TYPE_LABELS.get(updates["media_type"], updates["media_type"])
        await message.answer(f"Сохранено: {label}{' + подпись' if caption else ''}.")
    else:
        await message.answer("Текст сохранён.")
    await render_menu(message.chat.id, message.from_user.id)


@dp.callback_query(F.data == "preview")
async def cb_preview(call: CallbackQuery) -> None:
    user = await storage.get_user(call.from_user.id)
    if not user.message_text and not user.media_path:
        await call.answer("Сначала задай текст или медиа", show_alert=True)
        return
    rendered = spin(user.message_text) if user.spintax_enabled else user.message_text
    caption_html = html.escape(rendered) if rendered else ""
    if user.media_path and os.path.exists(user.media_path):
        from aiogram.types import FSInputFile

        file = FSInputFile(user.media_path)
        try:
            await call.message.delete()
        except Exception:
            pass
        header = "<b>Превью:</b>\n"
        send_kwargs = {"caption": header + caption_html, "reply_markup": keyboards.back_menu()}
        mt = user.media_type
        try:
            if mt == "photo":
                await bot.send_photo(call.message.chat.id, file, **send_kwargs)
            elif mt == "video":
                await bot.send_video(call.message.chat.id, file, **send_kwargs)
            elif mt == "animation":
                await bot.send_animation(call.message.chat.id, file, **send_kwargs)
            elif mt == "audio":
                await bot.send_audio(call.message.chat.id, file, **send_kwargs)
            elif mt == "voice":
                await bot.send_voice(call.message.chat.id, file, **send_kwargs)
            elif mt == "video_note":
                await bot.send_video_note(call.message.chat.id, file, reply_markup=keyboards.back_menu())
                if caption_html:
                    await bot.send_message(call.message.chat.id, header + caption_html)
            elif mt == "sticker":
                await bot.send_sticker(call.message.chat.id, file)
                await bot.send_message(
                    call.message.chat.id,
                    header + (caption_html or "<i>(без подписи)</i>"),
                    reply_markup=keyboards.back_menu(),
                )
            else:
                await bot.send_document(call.message.chat.id, file, **send_kwargs)
        except Exception as exc:
            await bot.send_message(
                call.message.chat.id,
                f"Не удалось показать медиа: <code>{html.escape(str(exc))}</code>",
                reply_markup=keyboards.back_menu(),
            )
        await call.answer()
        return

    await call.message.edit_text(
        f"<b>Превью (случайный вариант):</b>\n\n{caption_html}",
        reply_markup=keyboards.back_menu(),
    )
    await call.answer()


# ---------- Settings ----------


@dp.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery) -> None:
    user = await storage.get_user(call.from_user.id)
    await call.message.edit_text(
        "<b>Настройки рассылки</b>\n\n"
        "• Интервал — задержка между сообщениями.\n"
        "• Джиттер — случайное отклонение интервала ±N секунд (делает рассылку «живее»).\n"
        "• Пауза между циклами — сколько ждать после прохода по всем чатам.\n"
        "• Перемешивание — менять порядок чатов каждый цикл.\n"
        "• Spintax — случайный выбор вариантов в <code>{a|b|c}</code>.",
        reply_markup=keyboards.settings_menu(user),
    )
    await call.answer()


@dp.callback_query(F.data == "set_interval")
async def cb_set_interval(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingStates.interval)
    await call.message.edit_text(
        "Введи интервал между сообщениями в секундах (целое число ≥ 1).",
        reply_markup=keyboards.cancel_menu(),
    )
    await call.answer()


@dp.callback_query(F.data == "set_jitter")
async def cb_set_jitter(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingStates.jitter)
    await call.message.edit_text(
        "Введи джиттер в секундах (0 — без джиттера).",
        reply_markup=keyboards.cancel_menu(),
    )
    await call.answer()


@dp.callback_query(F.data == "set_cycle")
async def cb_set_cycle(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingStates.cycle)
    await call.message.edit_text(
        "Введи паузу между полными циклами в секундах (0 — без паузы).",
        reply_markup=keyboards.cancel_menu(),
    )
    await call.answer()


@dp.callback_query(F.data == "toggle_shuffle")
async def cb_toggle_shuffle(call: CallbackQuery) -> None:
    user = await storage.get_user(call.from_user.id)
    await storage.update_user(call.from_user.id, shuffle=0 if user.shuffle else 1)
    user = await storage.get_user(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=keyboards.settings_menu(user))
    await call.answer("Переключено")


@dp.callback_query(F.data == "toggle_spintax")
async def cb_toggle_spintax(call: CallbackQuery) -> None:
    user = await storage.get_user(call.from_user.id)
    await storage.update_user(call.from_user.id, spintax_enabled=0 if user.spintax_enabled else 1)
    user = await storage.get_user(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=keyboards.settings_menu(user))
    await call.answer("Переключено")


@dp.callback_query(F.data == "reset_stats")
async def cb_reset_stats(call: CallbackQuery) -> None:
    await storage.reset_stats(call.from_user.id)
    user = await storage.get_user(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=keyboards.settings_menu(user))
    await call.answer("Статистика сброшена")


@dp.message(SettingStates.interval)
async def set_interval(message: Message, state: FSMContext) -> None:
    if not (message.text or "").strip().isdigit():
        await message.answer("Нужно целое число ≥ 1.", reply_markup=keyboards.cancel_menu())
        return
    value = max(1, int(message.text.strip()))
    await storage.update_user(message.from_user.id, interval=value)
    await state.clear()
    await message.answer(f"Интервал установлен: {value} сек.")
    await render_menu(message.chat.id, message.from_user.id)


@dp.message(SettingStates.jitter)
async def set_jitter(message: Message, state: FSMContext) -> None:
    if not (message.text or "").strip().isdigit():
        await message.answer("Нужно целое число ≥ 0.", reply_markup=keyboards.cancel_menu())
        return
    value = int(message.text.strip())
    await storage.update_user(message.from_user.id, jitter=value)
    await state.clear()
    await message.answer(f"Джиттер установлен: ±{value} сек.")
    await render_menu(message.chat.id, message.from_user.id)


@dp.message(SettingStates.cycle)
async def set_cycle(message: Message, state: FSMContext) -> None:
    if not (message.text or "").strip().isdigit():
        await message.answer("Нужно целое число ≥ 0.", reply_markup=keyboards.cancel_menu())
        return
    value = int(message.text.strip())
    await storage.update_user(message.from_user.id, cycle_delay=value)
    await state.clear()
    await message.answer(f"Пауза между циклами установлена: {value} сек.")
    await render_menu(message.chat.id, message.from_user.id)


# ---------- Stats / start / stop ----------


@dp.callback_query(F.data == "stats")
async def cb_stats(call: CallbackQuery) -> None:
    user = await storage.get_user(call.from_user.id)
    chats = await storage.list_chats(call.from_user.id)
    status = "🟢 работает" if user.is_running else "⚪️ остановлена"
    text = (
        f"<b>Статистика</b>\n\n"
        f"Рассылка: {status}\n"
        f"Чатов: {len(chats)}\n"
        f"Отправлено: <b>{user.sent_count}</b>\n"
        f"Ошибок: <b>{user.fail_count}</b>"
    )
    await call.message.edit_text(text, reply_markup=keyboards.back_menu())
    await call.answer()


@dp.callback_query(F.data == "start")
async def cb_start(call: CallbackQuery) -> None:
    ok, msg = await broadcaster.start(call.from_user.id)
    await call.answer(msg, show_alert=not ok)
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)


@dp.callback_query(F.data == "stop")
async def cb_stop(call: CallbackQuery) -> None:
    ok, msg = await broadcaster.stop(call.from_user.id)
    await call.answer(msg, show_alert=not ok)
    await render_menu(call.message.chat.id, call.from_user.id, edit=call.message)


# ---------- Notifier (broadcaster → bot) ----------


async def notify(tg_user_id: int, text: str) -> None:
    try:
        await bot.send_message(tg_user_id, text)
    except Exception:
        log.exception("notify send failed")


# ---------- Lifecycle ----------


async def resume_running() -> None:
    """Resume broadcasts that were marked running before the last shutdown."""
    try:
        user_ids = await storage.list_running_users()
    except Exception:
        log.exception("list_running_users failed")
        return
    for uid in user_ids:
        ok, msg = await broadcaster.start(uid)
        log.info("resume user %s: ok=%s msg=%s", uid, ok, msg)


async def on_shutdown() -> None:
    for uid in list(broadcaster._tasks.keys()):
        await broadcaster.stop(uid)
    await userbots.close_all()


async def main() -> None:
    await storage.init()
    broadcaster.set_notifier(notify)
    await resume_running()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
