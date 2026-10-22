"""Human-in-the-loop CAPTCHA relay for GitHub Actions.

This module forwards a CAPTCHA image to an allowlisted private Telegram chat.
A human reads the image and replies directly to that image; no CAPTCHA solver
is used. It does not persist browser cookies or ETLE session state.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import requests


class TelegramCaptchaError(RuntimeError):
    """Safe, non-secret-bearing Telegram CAPTCHA workflow error."""


class TelegramCaptchaClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        wait_seconds: int = 300,
        poll_seconds: int = 4,
        http: Any = requests,
    ) -> None:
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.wait_seconds = max(1, min(int(wait_seconds), 600))
        self.poll_seconds = max(1, min(int(poll_seconds), 10))
        self.http = http
        if not self.token or not self.chat_id:
            raise TelegramCaptchaError("TELEGRAM_CONFIGURATION_MISSING")
        try:
            self.owner_id = int(self.chat_id)
        except ValueError as exc:
            raise TelegramCaptchaError("TELEGRAM_CHAT_ID_INVALID") from exc

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _api_json(self, method: str, *, params=None, data=None, files=None, timeout=20):
        try:
            response = self.http.post(
                self._url(method), params=params, data=data, files=files, timeout=timeout
            ) if files is not None else self.http.get(
                self._url(method), params=params or data, timeout=timeout
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # Do not propagate request URLs or raw response bodies: URLs contain the bot token.
            raise TelegramCaptchaError("TELEGRAM_API_REQUEST_FAILED") from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise TelegramCaptchaError("TELEGRAM_API_RESPONSE_INVALID")
        return payload.get("result")

    def send_captcha_image(self, image_path: str, *, run_label: str) -> int:
        path = Path(image_path)
        if not path.is_file():
            raise TelegramCaptchaError("CAPTCHA_IMAGE_NOT_FOUND")
        caption = (
            f"CAPTCHA ETLE Hub — run {run_label}.\n"
            "Balas langsung pesan foto ini dengan kode yang terlihat. "
            f"Waktu tunggu maksimal {self.wait_seconds} detik."
        )
        try:
            with path.open("rb") as image_file:
                result = self._api_json(
                    "sendPhoto",
                    data={"chat_id": self.chat_id, "caption": caption},
                    files={"photo": image_file},
                    timeout=30,
                )
        except OSError as exc:
            raise TelegramCaptchaError("CAPTCHA_IMAGE_READ_FAILED") from exc
        if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
            raise TelegramCaptchaError("TELEGRAM_PHOTO_MESSAGE_ID_MISSING")
        return result["message_id"]

    @staticmethod
    def _answer_from_update(update: dict, *, owner_id: int, photo_message_id: int):
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        reply = message.get("reply_to_message") or {}
        # Require the configured private chat, the same sender, and a reply to
        # this exact challenge photo. Old/unrelated messages cannot answer it.
        if str(chat.get("id", "")) != str(owner_id):
            return None
        if chat.get("type") != "private" or sender.get("id") != owner_id:
            return None
        if reply.get("message_id") != photo_message_id:
            return None
        text = message.get("text")
        if not isinstance(text, str):
            return None
        answer = "".join(text.split())
        if not re.fullmatch(r"[A-Za-z0-9]{5}", answer or ""):
            return None
        return answer

    def wait_for_answer(self, *, photo_message_id: int) -> str:
        deadline = time.monotonic() + self.wait_seconds
        offset = None
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            params = {"timeout": min(self.poll_seconds, remaining)}
            if offset is not None:
                params["offset"] = offset
            updates = self._api_json("getUpdates", params=params, timeout=self.poll_seconds + 10)
            if not isinstance(updates, list):
                raise TelegramCaptchaError("TELEGRAM_UPDATES_INVALID")
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset or 0, update_id + 1)
                answer = self._answer_from_update(
                    update, owner_id=self.owner_id, photo_message_id=photo_message_id
                )
                if answer is not None:
                    return answer
        try:
            self._api_json(
                "sendMessage",
                data={
                    "chat_id": self.chat_id,
                    "text": "Waktu tunggu CAPTCHA habis. Proses ETLE dihentikan dengan aman.",
                },
                timeout=15,
            )
        except TelegramCaptchaError:
            pass
        raise TelegramCaptchaError("CAPTCHA_REPLY_TIMEOUT")

    def request_answer(self, image_path: str, *, run_label: str) -> str:
        message_id = self.send_captcha_image(image_path, run_label=run_label)
        return self.wait_for_answer(photo_message_id=message_id)



def login_with_telegram_captcha(
    page,
    email: str,
    password: str,
    *,
    login_url: str,
    run_label: str,
    max_attempts: int = 3,
) -> None:
    """Log in through the real ETLE form, asking a human for each visible CAPTCHA.

    Success requires leaving the login route on the same HTTPS host and no
    visible login form. CAPTCHA answers and credentials are never logged or persisted.
    """
    attempts = max(1, min(int(max_attempts), 3))
    page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

    for attempt in range(1, attempts + 1):
        page.locator('input[placeholder="Email"]').fill(email, timeout=30000)
        page.locator('input[placeholder="Password"]').fill(password, timeout=30000)

        captcha_image = page.locator("#captchaImg")
        if captcha_image.count() and captcha_image.is_visible():
            captcha_input = page.locator('input[name="captcha"]')
            captcha_input.wait_for(state="visible", timeout=15000)
            page.wait_for_timeout(300)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(prefix="etle-captcha-", suffix=".png", delete=False) as tmp:
                    temp_path = tmp.name
                captcha_image.screenshot(path=temp_path, timeout=15000)
                answer = client_from_environment().request_answer(
                    temp_path, run_label=f"{run_label}-{attempt}"
                )
                if not re.fullmatch(r"[A-Za-z0-9]{5}", answer or ""):
                    raise TelegramCaptchaError("CAPTCHA_ANSWER_FORMAT_INVALID")
                captcha_input.fill(answer.upper(), timeout=15000)
            finally:
                if temp_path:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

        page.locator('button[type="submit"].btn-theme').click(timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        expected = urlparse(login_url)
        current = urlparse(page.url)
        same_https_host = (
            current.scheme == "https"
            and current.hostname == expected.hostname
            and current.port == expected.port
        )
        on_login_route = current.path.rstrip("/").endswith("/main")
        login_form_visible = False
        try:
            for selector in (
                'input[placeholder="Email"]',
                'input[placeholder="Password"]',
                'button[type="submit"].btn-theme',
            ):
                locator = page.locator(selector)
                if locator.count() and locator.first.is_visible():
                    login_form_visible = True
                    break
        except Exception:
            # Fail closed if the page state cannot be checked safely.
            raise TelegramCaptchaError("ETLE_LOGIN_STATE_UNVERIFIED") from None

        if same_https_host and not on_login_route and not login_form_visible:
            return

        if not (captcha_image.count() and captcha_image.is_visible()):
            # Without a visible challenge, repeating the same submit could loop on bad credentials.
            raise TelegramCaptchaError("ETLE_LOGIN_FAILED_OR_DASHBOARD_NOT_REACHED")
        if attempt < attempts:
            # Refresh the challenge before asking for another human answer.
            captcha_image.click(timeout=10000)
            page.wait_for_timeout(500)

    raise TelegramCaptchaError("ETLE_LOGIN_FAILED_OR_DASHBOARD_NOT_REACHED")

def client_from_environment() -> TelegramCaptchaClient:
    token = os.getenv("TG_TOKEN", "")
    chat_id = os.getenv("TG_CHAT_ID", "")
    try:
        wait_seconds = int(os.getenv("CAPTCHA_WAIT_SECONDS", "300"))
    except ValueError as exc:
        raise TelegramCaptchaError("CAPTCHA_WAIT_SECONDS_INVALID") from exc
    return TelegramCaptchaClient(token, chat_id, wait_seconds=wait_seconds)
