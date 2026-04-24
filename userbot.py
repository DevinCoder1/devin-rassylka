"""Telethon user-bot client manager. Per-Telegram-user client lifecycle."""
from __future__ import annotations

import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

log = logging.getLogger(__name__)


class UserbotManager:
    """Keeps a TelegramClient per tg_user_id.

    Two modes:
      - login flow: temporary client stored in ``_pending`` until sign-in completes.
      - active: persistent client stored in ``_clients`` and kept connected.
    """

    def __init__(self) -> None:
        self._clients: dict[int, TelegramClient] = {}
        self._pending: dict[int, dict] = {}

    async def start_login(self, tg_user_id: int, api_id: int, api_hash: str, phone: str) -> None:
        old = self._pending.pop(tg_user_id, None)
        if old and old.get("client"):
            try:
                await old["client"].disconnect()
            except Exception:
                pass
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
        self._pending[tg_user_id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "api_id": api_id,
            "api_hash": api_hash,
        }

    async def confirm_code(self, tg_user_id: int, code: str) -> tuple[str, Optional[str]]:
        """Returns (status, data). status in {'ok','2fa','error'}. data holds session or error."""
        state = self._pending.get(tg_user_id)
        if not state:
            return "error", "Сначала запустите авторизацию заново."
        client: TelegramClient = state["client"]
        try:
            await client.sign_in(
                phone=state["phone"],
                code=code,
                phone_code_hash=state["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            return "2fa", None
        except Exception as exc:
            log.exception("sign_in failed")
            return "error", str(exc)
        session_str = client.session.save()
        await client.disconnect()
        self._pending.pop(tg_user_id, None)
        return "ok", session_str

    async def confirm_password(self, tg_user_id: int, password: str) -> tuple[str, Optional[str]]:
        state = self._pending.get(tg_user_id)
        if not state:
            return "error", "Сначала запустите авторизацию заново."
        client: TelegramClient = state["client"]
        try:
            await client.sign_in(password=password)
        except Exception as exc:
            log.exception("password sign_in failed")
            return "error", str(exc)
        session_str = client.session.save()
        await client.disconnect()
        self._pending.pop(tg_user_id, None)
        return "ok", session_str

    async def cancel_login(self, tg_user_id: int) -> None:
        state = self._pending.pop(tg_user_id, None)
        if state and state.get("client"):
            try:
                await state["client"].disconnect()
            except Exception:
                pass

    async def get_client(
        self, tg_user_id: int, api_id: int, api_hash: str, session_str: str
    ) -> TelegramClient:
        client = self._clients.get(tg_user_id)
        if client is None or not client.is_connected():
            client = TelegramClient(StringSession(session_str), api_id, api_hash)
            await client.connect()
            self._clients[tg_user_id] = client
        return client

    async def drop_client(self, tg_user_id: int) -> None:
        client = self._clients.pop(tg_user_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def close_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
        for state in list(self._pending.values()):
            try:
                await state["client"].disconnect()
            except Exception:
                pass
        self._pending.clear()
