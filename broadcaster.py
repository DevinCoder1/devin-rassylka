"""Per-user broadcast loop manager."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from telethon.errors import FloodWaitError

from spintax import spin
from storage import Storage
from userbot import UserbotManager

log = logging.getLogger(__name__)


class Broadcaster:
    def __init__(self, storage: Storage, userbots: UserbotManager) -> None:
        self.storage = storage
        self.userbots = userbots
        self._tasks: dict[int, asyncio.Task] = {}
        self._notify = None  # optional async callback(tg_user_id, text)

    def set_notifier(self, fn) -> None:
        self._notify = fn

    def is_running(self, tg_user_id: int) -> bool:
        task = self._tasks.get(tg_user_id)
        return task is not None and not task.done()

    async def start(self, tg_user_id: int) -> tuple[bool, str]:
        if self.is_running(tg_user_id):
            return False, "Рассылка уже запущена."
        user = await self.storage.get_user(tg_user_id)
        if not user.session or not user.api_id or not user.api_hash:
            return False, "Сначала авторизуйте аккаунт (API ID/HASH + код)."
        chats = await self.storage.list_chats(tg_user_id)
        if not chats:
            return False, "Добавьте хотя бы один чат."
        if not user.message_text.strip() and not user.media_path:
            return False, "Установите текст и/или медиа для рассылки."

        await self.storage.update_user(tg_user_id, is_running=1)
        task = asyncio.create_task(self._run(tg_user_id), name=f"broadcast-{tg_user_id}")
        self._tasks[tg_user_id] = task
        return True, "Рассылка запущена."

    async def stop(self, tg_user_id: int) -> tuple[bool, str]:
        task = self._tasks.pop(tg_user_id, None)
        await self.storage.update_user(tg_user_id, is_running=0)
        if task is None or task.done():
            return False, "Рассылка не была запущена."
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("broadcast task failed while stopping")
        return True, "Рассылка остановлена."

    async def _notify_user(self, tg_user_id: int, text: str) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(tg_user_id, text)
        except Exception:
            log.exception("notify failed")

    async def _sleep_with_jitter(self, base: int, jitter: int) -> None:
        if jitter > 0:
            delta = random.uniform(-jitter, jitter)
            delay = max(0.0, base + delta)
        else:
            delay = float(base)
        if delay > 0:
            await asyncio.sleep(delay)

    async def _run(self, tg_user_id: int) -> None:
        try:
            user = await self.storage.get_user(tg_user_id)
            assert user.api_id and user.api_hash and user.session
            client = await self.userbots.get_client(
                tg_user_id, user.api_id, user.api_hash, user.session
            )
            if not await client.is_user_authorized():
                await self._notify_user(
                    tg_user_id,
                    "⚠️ Сессия аккаунта не авторизована. Пройдите авторизацию заново.",
                )
                await self.storage.update_user(tg_user_id, is_running=0)
                return

            await self._notify_user(tg_user_id, "▶️ Рассылка стартовала.")

            while True:
                user = await self.storage.get_user(tg_user_id)
                chats = await self.storage.list_chats(tg_user_id)
                if not chats:
                    await self._notify_user(tg_user_id, "⏹ Чатов больше нет, останавливаю.")
                    break
                order = list(chats)
                if user.shuffle:
                    random.shuffle(order)

                for chat in order:
                    text = spin(user.message_text) if user.spintax_enabled else user.message_text
                    target = _parse_identifier(chat.identifier)
                    try:
                        if user.media_path:
                            await client.send_file(
                                target,
                                user.media_path,
                                caption=text or None,
                                voice_note=(user.media_type == "voice"),
                                video_note=(user.media_type == "video_note"),
                            )
                        else:
                            await client.send_message(target, text)
                        await self.storage.inc_counters(tg_user_id, sent=1)
                    except FloodWaitError as exc:
                        await self._notify_user(
                            tg_user_id,
                            f"⏳ FloodWait: ждём {exc.seconds} сек (чат {chat.identifier}).",
                        )
                        await asyncio.sleep(exc.seconds + 1)
                    except Exception as exc:
                        await self.storage.inc_counters(tg_user_id, failed=1)
                        await self._notify_user(
                            tg_user_id,
                            f"❌ Ошибка в чате {chat.identifier}: {exc}",
                        )
                    await self._sleep_with_jitter(user.interval, user.jitter)

                if user.cycle_delay > 0:
                    await asyncio.sleep(user.cycle_delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("broadcast loop crashed")
            await self._notify_user(tg_user_id, f"⚠️ Рассылка остановлена из-за ошибки: {exc}")
        finally:
            await self.storage.update_user(tg_user_id, is_running=0)


def _parse_identifier(identifier: str):
    """Convert stored identifier to a Telethon-friendly form."""
    identifier = identifier.strip()
    if not identifier:
        return identifier
    # Numeric IDs (including -100... for channels)
    try:
        return int(identifier)
    except ValueError:
        pass
    # Strip t.me/ prefixes
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if identifier.startswith(prefix):
            identifier = identifier[len(prefix):]
            break
    return identifier
