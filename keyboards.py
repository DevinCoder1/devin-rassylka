from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from storage import ChatRow, UserRow


def main_menu(user: UserRow, chats_count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if user.session:
        kb.button(text="🔐 Аккаунт: подключён", callback_data="account")
    else:
        kb.button(text="🔑 Войти в аккаунт", callback_data="login")
    kb.button(text=f"💬 Чаты ({chats_count})", callback_data="chats")
    content_label = "✏️ Контент рассылки"
    if user.media_path:
        content_label = "🖼 Контент (медиа задано)"
    elif user.message_text:
        content_label = "✏️ Контент (текст задан)"
    kb.button(text=content_label, callback_data="text")
    kb.button(text="⚙️ Настройки", callback_data="settings")
    if user.is_running:
        kb.button(text="⏹ Остановить рассылку", callback_data="stop")
    else:
        kb.button(text="▶️ Запустить рассылку", callback_data="start")
    kb.button(text="👁 Превью сообщения", callback_data="preview")
    kb.button(text="📊 Статистика", callback_data="stats")
    kb.button(text="ℹ️ Помощь", callback_data="help")
    kb.adjust(1, 1, 1, 1, 1, 2, 1)
    return kb.as_markup()


def back_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="menu")
    return kb.as_markup()


def text_edit_menu(has_media: bool, has_text: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_media:
        kb.button(text="🗑 Удалить медиа", callback_data="clear_media")
    if has_text:
        kb.button(text="🗑 Удалить текст", callback_data="clear_text")
    kb.button(text="✖️ Отмена", callback_data="cancel")
    kb.adjust(1)
    return kb.as_markup()


def cancel_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data="cancel")
    return kb.as_markup()


def account_menu(has_session: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_session:
        kb.button(text="🚪 Выйти из аккаунта", callback_data="logout")
    else:
        kb.button(text="🔑 Войти", callback_data="login")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def chats_menu(chats: list[ChatRow]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for chat in chats:
        label = chat.title or chat.identifier
        if len(label) > 40:
            label = label[:37] + "…"
        kb.button(text=f"🗑 {label}", callback_data=f"rmchat:{chat.id}")
    kb.button(text="➕ Добавить чат", callback_data="addchat")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def settings_menu(user: UserRow) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⏱ Интервал: {user.interval} сек", callback_data="set_interval")
    kb.button(text=f"🎲 Джиттер: ±{user.jitter} сек", callback_data="set_jitter")
    kb.button(text=f"🔁 Пауза между циклами: {user.cycle_delay} сек", callback_data="set_cycle")
    kb.button(
        text=f"🔀 Перемешивать чаты: {'вкл' if user.shuffle else 'выкл'}",
        callback_data="toggle_shuffle",
    )
    kb.button(
        text=f"🌀 Spintax: {'вкл' if user.spintax_enabled else 'выкл'}",
        callback_data="toggle_spintax",
    )
    kb.button(text="♻️ Сбросить статистику", callback_data="reset_stats")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()
