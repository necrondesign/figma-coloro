"""Клиент Figma REST: только чтение.

- Одно соединение на поток — без нового TLS-рукопожатия на каждый запрос.
- Лимит Figma (429): ждём столько, сколько просит Retry-After, и все потоки ждут вместе —
  иначе соседние потоки продолжают долбить и продлевают блокировку.
- Сбой сервера Figma (5xx) и обрыв сети: повтор с нарастающей паузой.
- Ответ, оборванный на середине, поднимается как Truncated: загрузчик дробит запрос мельче.
- Токен не попадает ни в сообщения об ошибках, ни в журналы.
"""

from __future__ import annotations

import gzip
import http.client
import json
import socket
import ssl
import threading
import time
from urllib.parse import urlencode

HOST = "api.figma.com"
TIMEOUT = 120
ATTEMPTS = 6

# Общая пауза на все потоки: когда Figma ответила 429, ждут все.
_pause_until = 0.0
_pause_lock = threading.Lock()


def _wait_shared(on_wait=None) -> None:
    while True:
        with _pause_lock:
            left = _pause_until - time.monotonic()
        if left <= 0:
            return
        if on_wait:
            on_wait(left)
        time.sleep(min(left, 5.0))


def _pause_all(seconds: float) -> None:
    global _pause_until
    with _pause_lock:
        _pause_until = max(_pause_until, time.monotonic() + seconds)


class FigmaError(Exception):
    """Ошибка, которую стоит показать человеку как есть: без кодов и трассировок."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.status = code, status


class Truncated(FigmaError):
    """Ответ пришёл, но оборван или не разбирается — запрос надо раздробить."""

    def __init__(self, message: str = "ответ Figma оборвался на середине"):
        super().__init__("truncated", message)


class Figma:
    def __init__(self, token: str, on_wait=None):
        token = "".join(ch for ch in (token or "") if 33 <= ord(ch) <= 126)
        if len(token) < 20:
            raise FigmaError("no_token", "токен Figma не задан или повреждён")
        self._token = token
        self._on_wait = on_wait
        self._local = threading.local()

    def _conn(self) -> http.client.HTTPSConnection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = http.client.HTTPSConnection(HOST, timeout=TIMEOUT, context=ssl.create_default_context())
            self._local.conn = c
        return c

    def _drop(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        self._local.conn = None

    def get_bytes(self, path: str, params: dict | None = None) -> bytes:
        url = "/v1" + path + ("?" + urlencode(params) if params else "")
        last = None
        for attempt in range(1, ATTEMPTS + 1):
            _wait_shared(self._on_wait)
            try:
                c = self._conn()
                c.request("GET", url, headers={
                    "X-Figma-Token": self._token,
                    "Accept-Encoding": "gzip",
                    "User-Agent": "coloro",
                })
                r = c.getresponse()
                body = r.read()
                status = r.status
                retry_after = r.getheader("Retry-After")
                encoding = (r.getheader("Content-Encoding") or "").lower()
            except (socket.timeout, TimeoutError):
                self._drop()
                last = FigmaError("timeout", "Figma не ответила вовремя")
                time.sleep(10 * attempt)
                continue
            except (http.client.IncompleteRead, http.client.RemoteDisconnected) as e:
                # Обрыв посреди большого ответа: повтор тем же куском обычно обрывается
                # там же, поэтому сразу отдаём наверх — пусть загрузчик раздробит.
                self._drop()
                raise Truncated() from e
            except (OSError, http.client.HTTPException):
                self._drop()
                last = FigmaError("network", "нет связи с Figma")
                time.sleep(10 * attempt)
                continue

            if status == 200:
                if encoding == "gzip":
                    try:
                        body = gzip.decompress(body)
                    except (OSError, EOFError) as e:
                        raise Truncated() from e
                return body
            if status == 429:
                try:
                    wait = float(retry_after)
                except (TypeError, ValueError):
                    wait = 30.0 * attempt
                _pause_all(max(wait, 5.0))
                last = FigmaError("rate_limited", "Figma просит подождать: слишком много запросов", 429)
                continue
            if status in (500, 502, 503, 504):
                last = FigmaError("figma_unavailable", "Figma временно не отвечает", status)
                time.sleep(15 * attempt)
                continue
            if status == 400:
                # Figma так отвечает и на слишком тяжёлый запрос — дробим.
                raise Truncated("запрос слишком велик для одного ответа Figma")
            if status in (401, 403):
                raise FigmaError("forbidden", "токен не подходит или у него нет доступа к этому файлу", status)
            if status == 404:
                raise FigmaError("not_found", "файл не найден — проверьте ссылку и доступ", status)
            raise FigmaError("http", f"Figma ответила кодом {status}", status)
        raise last or FigmaError("network", "нет связи с Figma")

    def get_json(self, path: str, params: dict | None = None) -> dict:
        body = self.get_bytes(path, params)
        try:
            return json.loads(body)
        except ValueError as e:
            raise Truncated() from e

    # --- Запросы, которые нужны загрузчику ---

    def file_head(self, key: str, depth: int = 1) -> dict:
        """Имя, версия, дата изменения и страницы. depth=2 — ещё и верхние слои каждой страницы."""
        return self.get_json(f"/files/{key}", {"depth": depth})

    def nodes(self, key: str, ids: list[str], depth: int | None = None) -> dict:
        params = {"ids": ",".join(ids)}
        if depth is not None:
            params["depth"] = depth
        return self.get_json(f"/files/{key}/nodes", params)
