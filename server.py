"""Хто більше? — сервер без сторонніх залежностей (Python 3.10+).

Запуск:  py server.py      (або python3 server.py)
Відкрити: http://localhost:8787   — з телефонів у тій самій Wi-Fi: http://<IP-комп'ютера>:8787

Змінні середовища: PORT, HOST, DATA_FILE, COOKIE_SECURE=1 (для HTTPS), ADMIN_TOKEN,
OPENAI_API_KEY + OPENAI_MODEL (вмикають AI-суддю), OPENAI_*_RATE (тарифи за 1 млн токенів).
"""
import json
import mimetypes
import os
import queue
import re
import secrets
import socket
import sys
import threading
import time
from collections import defaultdict, deque
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from aiauction import themes as T
from aiauction.ai import OpenAIJudge
from aiauction.engine import ERRORS, Engine, GameError

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA_FILE = Path(os.environ.get("DATA_FILE", ROOT / "data" / "state.json"))
COOKIE = "aa_sid"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

engine = Engine(ai=OpenAIJudge())

# ------------------------------------------------------------------ збереження стану
_save_lock = threading.Lock()


def save_state():
    with _save_lock:
        with engine.lock:
            data = json.dumps(engine.export(), ensure_ascii=False)
            engine.dirty = False
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, DATA_FILE)


def load_state():
    if DATA_FILE.exists():
        try:
            engine.load(json.loads(DATA_FILE.read_text(encoding="utf-8")))
            print(f"Стан відновлено з {DATA_FILE}")
        except Exception as e:  # пошкоджений файл не повинен блокувати запуск
            print(f"Не вдалося прочитати {DATA_FILE}: {e}", file=sys.stderr)


def ticker():
    last_save = 0.0
    while True:
        try:
            engine.tick()
            if engine.dirty and time.time() - last_save > 1.0:
                save_state()
                last_save = time.time()
        except Exception as e:
            print(f"tick error: {e!r}", file=sys.stderr)
        time.sleep(0.1)


# ------------------------------------------------------------------ rate limiting
_rate = defaultdict(deque)
_rate_lock = threading.Lock()


def rate_ok(key, limit, window=1.0):
    now = time.time()
    with _rate_lock:
        q = _rate[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


# ------------------------------------------------------------------ HTTP
ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version = "AIAuction/1.0"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("ACCESS_LOG") == "1":
            super().log_message(fmt, *args)

    # ---- допоміжне
    def _user(self, create=False):
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        token = jar[COOKIE].value if COOKIE in jar else None
        user = engine.user_by_token(token)
        if user is None and create:
            token, user = engine.new_session()
            self._new_cookie = token
        return user

    def _send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        if getattr(self, "_new_cookie", None):
            self.send_header("Set-Cookie", self._cookie_header(self._new_cookie))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cookie_header(self, token):
        attrs = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={30 * 24 * 3600}"
        return attrs + ("; Secure" if COOKIE_SECURE else "")

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64 * 1024:
            raise GameError("VALIDATION_ERROR", "Запит завеликий.")
        if not n:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise GameError("VALIDATION_ERROR", "Некоректний JSON.")
        if not isinstance(data, dict):
            raise GameError("VALIDATION_ERROR")
        return data

    def _dispatch(self, method):
        self.request_id = "req-" + secrets.token_hex(6)
        self._new_cookie = None
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._static(path) if method == "GET" else self._send_json(405, {"error": {"code": "VALIDATION_ERROR"}})
        if method != "GET" and self.headers.get("X-Requested-With") != "aiauction":  # захист від CSRF
            return self._error(GameError("FORBIDDEN", "Запит відхилено (CSRF)."))
        for m, rx, fn in ROUTES:
            mt = rx.match(path)
            if m == method and mt:
                try:
                    result = fn(self, *mt.groups())
                    if result is not None:
                        with engine.lock:
                            result.setdefault("server_time", engine.clock())
                        result["request_id"] = self.request_id
                        self._send_json(200, result)
                except GameError as e:
                    self._error(e)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except Exception as e:
                    print(f"[{self.request_id}] {path}: {e!r}", file=sys.stderr)
                    self._error(GameError("INTERNAL_ERROR"))
                return
        self._send_json(404, {"error": {"code": "NOT_FOUND", "message": "Маршрут не знайдено."}})

    def _error(self, e):
        self._send_json(e.http, {"error": {"code": e.code, "message": e.message, "details": e.details},
                                 "request_id": self.request_id})

    def _static(self, path):
        if path == "/" or path.startswith("/r/"):
            path = "/index.html"
        target = (PUBLIC / path.lstrip("/")).resolve()
        if PUBLIC not in target.parents or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def need_user(self):
        u = self._user()
        if not u:
            raise GameError("UNAUTHORIZED")
        if not rate_ok(("req", u["id"]), 30):
            raise GameError("RATE_LIMITED")
        return u


def _room_resp(user, room_id):
    return {"state": engine.view(user, room_id)}


# ------------------------------------------------------------------ маршрути
@route("GET", r"/api/me")
def r_me(h):
    user = h._user(create=True)
    return {"user": {"id": user["id"], "name": user["name"]}, "active_room_id": engine.active_room_for(user),
            "ai_enabled": engine.ai.enabled}


@route("POST", r"/api/me")
def r_set_name(h):
    user = h.need_user()
    engine.set_name(user, h._body().get("name"))
    return {"user": {"id": user["id"], "name": user["name"]}}


@route("GET", r"/api/themes")
def r_themes(h):
    return {"themes": T.catalog()}


@route("POST", r"/api/rooms")
def r_create(h):
    user = h.need_user()
    b = h._body()
    room = engine.create_room(user, b.get("name"), b.get("settings") or {})
    return {"room_id": room["id"], "invite_code": room["code"], "join_url": f"/r/{room['code']}",
            "status": room["status"], "version": room["version"]}


@route("POST", r"/api/rooms/join")
def r_join(h):
    user = h.need_user()
    b = h._body()
    room = engine.join_room(user, b.get("code"), b.get("name"), bool(b.get("spectator")))
    return {"room_id": room["id"], "version": room["version"]}


@route("GET", r"/api/rooms/([\w-]+)/state")
def r_state(h, rid):
    return _room_resp(h.need_user(), rid)


@route("POST", r"/api/rooms/([\w-]+)/ready")
def r_ready(h, rid):
    user = h.need_user()
    engine.set_ready(user, rid, bool(h._body().get("ready", True)))
    return _room_resp(user, rid)


@route("PATCH", r"/api/rooms/([\w-]+)/settings")
def r_settings(h, rid):
    user = h.need_user()
    b = h._body()
    engine.update_settings(user, rid, b.get("settings") or {}, b.get("expected_version"))
    return _room_resp(user, rid)


@route("POST", r"/api/rooms/([\w-]+)/bots")
def r_bot(h, rid):
    user = h.need_user()
    engine.add_bot(user, rid, h._body().get("level", "regular"))
    return _room_resp(user, rid)


@route("POST", r"/api/rooms/([\w-]+)/members/([\w-]+)/remove")
def r_remove(h, rid, mid):
    user = h.need_user()
    engine.remove_member(user, rid, mid)
    return {"ok": True}


@route("POST", r"/api/rooms/([\w-]+)/members/([\w-]+)/role")
def r_role(h, rid, mid):
    user = h.need_user()
    engine.set_role(user, rid, mid, h._body().get("role"))
    return _room_resp(user, rid)


@route("POST", r"/api/rooms/([\w-]+)/host")
def r_host(h, rid):
    user = h.need_user()
    engine.transfer_host(user, rid, h._body().get("member_id"))
    return _room_resp(user, rid)


@route("POST", r"/api/rooms/([\w-]+)/leave")
def r_leave(h, rid):
    engine.leave_room(h.need_user(), rid)
    return {"ok": True}


@route("POST", r"/api/rooms/([\w-]+)/start")
def r_start(h, rid):
    user = h.need_user()
    game = engine.start_game(user, rid)
    return {"game_id": game["id"]}


@route("POST", r"/api/games/([\w-]+)/bids")
def r_bid(h, gid):
    user = h.need_user()
    if not rate_ok(("bid", user["id"]), 5):
        raise GameError("RATE_LIMITED")
    b = h._body()
    return engine.bid(user, gid, b.get("lot_id"), b.get("amount"), b.get("idempotency_key"),
                      b.get("expected_lot_version"))


@route("POST", r"/api/games/([\w-]+)/(pause|resume|cancel|rematch)")
def r_game_action(h, gid, action):
    user = h.need_user()
    getattr(engine, action)(user, gid)
    return {"ok": True}


@route("GET", r"/api/games/([\w-]+)/results")
def r_results(h, gid):
    user = h.need_user()
    with engine.lock:
        game = engine.games.get(gid)
        if not game:
            raise GameError("GAME_NOT_FOUND")
        room = engine.rooms.get(game["room_id"])
        if not room or not engine._member(room, user["id"]):
            raise GameError("FORBIDDEN")
        if game["status"] != "COMPLETED":
            raise GameError("GAME_NOT_READY")
        return {"results": game["results"], "version": game["version"]}


@route("POST", r"/api/games/([\w-]+)/simulations")
def r_whatif(h, gid):
    user = h.need_user()
    b = h._body()
    return {"simulation": engine.whatif(user, gid, b.get("lot_id"), b.get("buyer_id"), b.get("price"))}


@route("GET", r"/api/admin/usage")
def r_admin_usage(h):
    if not ADMIN_TOKEN or h.headers.get("X-Admin-Token") != ADMIN_TOKEN:
        raise GameError("FORBIDDEN")
    with engine.lock:
        games = list(engine.games.values())
        return {"usage": engine.usage[-200:],
                "total_cost": round(sum(u.get("usage_cost", 0) for u in engine.usage), 6),
                "rooms": len(engine.rooms), "games": len(games),
                "games_completed": sum(1 for g in games if g["status"] == "COMPLETED")}


@route("GET", r"/api/rooms/([\w-]+)/stream")
def r_stream(h, rid):
    """Server-Sent Events: кожна подія — повний персоналізований стан з game_version (ТЗ §39, C.2)."""
    user = h.need_user()
    engine.view(user, rid)  # перевірка доступу до відкриття потоку
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()
    q = queue.Queue(maxsize=100)
    engine.subscribe(rid, q)
    engine.set_online(rid, user["id"], +1)
    try:
        while True:
            try:
                state = engine.view(user, rid)
            except GameError as e:
                h.wfile.write(f"event: gone\ndata: {json.dumps({'code': e.code})}\n\n".encode())
                h.wfile.flush()
                break
            h.wfile.write(f"event: state\ndata: {json.dumps(state, ensure_ascii=False)}\n\n".encode())
            h.wfile.flush()
            try:
                q.get(timeout=15)
                time.sleep(0.03)  # згортаємо пачку змін в одну подію
                while not q.empty():
                    q.get_nowait()
            except queue.Empty:
                h.wfile.write(b": ping\n\n")
                h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        engine.unsubscribe(rid, q)
        engine.set_online(rid, user["id"], -1)
    return None


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
        sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    for t in T.THEMES.values():
        errs = T.validate_theme(t)
        if errs:
            raise SystemExit(f"Тема {t['id']} некоректна: {errs}")
    load_state()
    threading.Thread(target=ticker, daemon=True).start()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8787"))
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    print(f"Хто більше? запущено: http://localhost:{port}")
    ip = lan_ip()
    if ip and host == "0.0.0.0":
        print(f"З телефонів у тій самій мережі: http://{ip}:{port}")
    print("AI-суддя: " + ("увімкнено (" + engine.ai.model + ")" if engine.ai.enabled else
                          "вимкнено — суб'єктивні критерії за резервною рубрикою"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        save_state()  # graceful shutdown: прийняті ставки не втрачаються


if __name__ == "__main__":
    main()
