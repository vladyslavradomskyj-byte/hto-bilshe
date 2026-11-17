"""Авторитетний ігровий рушій: кімнати, сесії, партії, ставки, таймери, результати.

Уся зміна стану відбувається під одним блокуванням self.lock, тому ставки серіалізуються
(ТЗ §24). Час — лише серверний (self.clock).
"""
import copy
import hashlib
import random
import secrets
import threading
import time
import unicodedata

from . import bots
from . import media
from . import themes as T
from .scoring import score_game, score_player

ERRORS = {
    "VALIDATION_ERROR": (400, "Некоректні дані запиту."),
    "UNAUTHORIZED": (401, "Сесія недійсна. Оновіть сторінку."),
    "FORBIDDEN": (403, "Ця дія вам недоступна."),
    "NOT_A_PLAYER": (403, "Ви не є гравцем цієї партії."),
    "ROOM_NOT_FOUND": (404, "Кімнату не знайдено. Перевірте код."),
    "GAME_NOT_FOUND": (404, "Партію не знайдено."),
    "INVALID_LOT": (404, "Цей лот зараз не торгується."),
    "ROOM_FULL": (409, "Кімната заповнена."),
    "GAME_NOT_READY": (409, "Гра ще не готова до цієї дії."),
    "GAME_PAUSED": (409, "Гру призупинено."),
    "LOT_CLOSED": (409, "Торги за цим лотом уже завершено."),
    "STALE_VERSION": (409, "Дані застаріли — екран оновлено, спробуйте ще раз."),
    "IDEMPOTENCY_CONFLICT": (409, "Повтор запиту з іншими даними."),
    "BID_TOO_LOW": (422, "Ставка замала."),
    "ALREADY_LEADER": (422, "Ваша ставка вже найвища."),
    "INSUFFICIENT_FUNDS": (422, "Недостатньо коштів."),
    "RATE_LIMITED": (429, "Забагато запитів, зачекайте мить."),
    "AI_UNAVAILABLE": (503, "AI-сервіс недоступний."),
    "INTERNAL_ERROR": (500, "Внутрішня помилка сервера."),
}
# Відмови, що зберігаються для ідемпотентного повтору (ТЗ §24).
STORED_REJECTIONS = {"LOT_CLOSED", "BID_TOO_LOW", "ALREADY_LEADER", "INSUFFICIENT_FUNDS", "INVALID_LOT", "GAME_PAUSED"}


class GameError(Exception):
    def __init__(self, code, message=None, details=None):
        super().__init__(code)
        self.code = code
        self.http = ERRORS[code][0]
        self.message = message or ERRORS[code][1]
        self.details = details or {}


SESSION_TTL = 30 * 24 * 3600
INTRO_SECONDS = 8
RESULT_PAUSE = 3
EXTEND_WINDOW = 5
EXTEND_CAP = 30
HOST_TRANSFER_TIMEOUT = 120
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

SETTINGS_OPTIONS = {
    "theme_id": None,  # перевіряється за каталогом
    "lot_count": [8, 15, 20],
    "budget": [20, 30, 50, 100],
    "timer": [15, 25, 45],
    "difficulty": ["easy", "normal", "hard", "expert"],
    "host_style": ["auctioneer", "comedian", "expert"],
    "family": [True, False],
    "show_weights": [True, False],
    "allow_spectators": [True, False],
    "max_players": [2, 3, 4, 5, 6, 7, 8],
}
DEFAULT_SETTINGS = {"theme_id": "shelter_5d", "lot_count": 15, "budget": 30, "timer": 25, "difficulty": "normal",
                    "host_style": "auctioneer", "family": True, "show_weights": True, "allow_spectators": True,
                    "max_players": 8, "bid_step": 1, "game_mode": "classic"}

BOT_NAMES = ["Бот Борис", "Бот Ада", "Бот Тарас", "Бот Ліна", "Бот Остап", "Бот Мія", "Бот Гліб", "Бот Яра"]

HOST_LINES = {
    "auctioneer": {
        "sold": "Продано! «{item}» дістається {name} за ${price}.",
        "big": "{name} віддає понад половину бюджету за «{item}» — сміливий хід!",
        "cheap": "«{item}» іде за символічний $1. {name} вміє чекати.",
        "unsold": "«{item}» лишається без власника. Іноді найкраща ставка — жодної.",
        "intro": "Пані та панове, торги відкрито! Тема: «{theme}».",
    },
    "comedian": {
        "sold": "«{item}» їде додому з {name}. Ціна — ${price}, емоції — безцінні.",
        "big": "{name} щойно витратив(-ла) половину статків на «{item}». Гаманець плаче, але тримається.",
        "cheap": "$1 за «{item}»? {name}, це не аукціон, це пограбування!",
        "unsold": "«{item}» ніхто не захотів. Лот пішов плакати в куток.",
        "intro": "Вітаю на найчеснішому аукціоні у світі! Сьогодні: «{theme}».",
    },
    "expert": {
        "sold": "Лот «{item}»: {name}, ${price}.",
        "big": "Ризикова концентрація: {name} — понад 50% бюджету на «{item}».",
        "cheap": "Ефективна покупка: «{item}» за $1 ({name}).",
        "unsold": "Лот «{item}» не продано. Попит відсутній.",
        "intro": "Сесію відкрито. Сценарій: «{theme}». Оцінювання — за 10 критеріями.",
    },
}


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def clean_text(s, max_len=20):
    if not isinstance(s, str):
        return ""
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")
    s = " ".join(s.split())
    return s[:max_len]


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(5)}"


class Engine:
    def __init__(self, clock=time.time, ai=None, rng=None):
        self.clock = clock
        self.ai = ai
        self.rng = rng or random.Random()
        self.lock = threading.RLock()
        self.users, self.sessions, self.rooms, self.games, self.codes = {}, {}, {}, {}, {}
        self.usage = []
        self.subs = {}      # room_id -> set(queue)
        self.online = {}    # (room_id, user_id) -> кількість з'єднань
        self.dirty = False
        self._judging = set()

    # ------------------------------------------------------------ сервісне
    def _notify(self, room_id):
        self.dirty = True
        for q in list(self.subs.get(room_id, ())):
            try:
                q.put_nowait(1)
            except Exception:
                pass

    def subscribe(self, room_id, q):
        with self.lock:
            self.subs.setdefault(room_id, set()).add(q)

    def unsubscribe(self, room_id, q):
        with self.lock:
            self.subs.get(room_id, set()).discard(q)

    def set_online(self, room_id, user_id, delta):
        with self.lock:
            k = (room_id, user_id)
            self.online[k] = max(0, self.online.get(k, 0) + delta)
            room = self.rooms.get(room_id)
            if room:
                m = self._member(room, user_id)
                if m:
                    m["last_seen"] = self.clock()
                self._notify(room_id)

    def is_online(self, room_id, member):
        return member["is_bot"] or self.online.get((room_id, member["id"]), 0) > 0

    # ------------------------------------------------------------ сесії
    def new_session(self):
        with self.lock:
            token = secrets.token_urlsafe(32)
            uid = new_id("u")
            self.users[uid] = {"id": uid, "name": "", "created": self.clock()}
            self.sessions[_h(token)] = {"user_id": uid, "expires": self.clock() + SESSION_TTL}
            self.dirty = True
            return token, self.users[uid]

    def user_by_token(self, token):
        if not token:
            return None
        with self.lock:
            s = self.sessions.get(_h(token))
            if not s or s["expires"] < self.clock():
                return None
            s["expires"] = self.clock() + SESSION_TTL
            return self.users.get(s["user_id"])

    def revoke_session(self, token):
        with self.lock:
            self.sessions.pop(_h(token), None)
            self.dirty = True

    def set_name(self, user, name):
        with self.lock:
            name = clean_text(name)
            if not name:
                raise GameError("VALIDATION_ERROR", "Введіть ім'я (1–20 символів).")
            user["name"] = name
            self.dirty = True
            return user

    def active_room_for(self, user):
        with self.lock:
            best = None
            for room in self.rooms.values():
                m = self._member(room, user["id"])
                if room["status"] != "CLOSED" and m and not m.get("left"):
                    if not best or room["created"] > best["created"]:
                        best = room
            return best["id"] if best else None

    # ------------------------------------------------------------ кімнати
    @staticmethod
    def _member(room, mid):
        return next((m for m in room["members"] if m["id"] == mid), None)

    def _room(self, room_id):
        room = self.rooms.get(room_id)
        if not room or room["status"] == "CLOSED":
            raise GameError("ROOM_NOT_FOUND")
        return room

    def _require_host(self, room, user):
        if room["host_id"] != user["id"]:
            raise GameError("FORBIDDEN", "Ця дія доступна лише організатору.")

    def _unique_name(self, room, name, exclude=None):
        taken = {m["name"].lower() for m in room["members"] if m["id"] != exclude}
        if name.lower() not in taken:
            return name
        i = 2
        while f"{name} {i}".lower() in taken:
            i += 1
        return f"{name} {i}"

    def _validate_settings(self, patch, base):
        s = dict(base)
        for k, v in (patch or {}).items():
            if k not in SETTINGS_OPTIONS:
                continue
            if k == "theme_id":
                if v not in T.THEMES:
                    raise GameError("VALIDATION_ERROR", "Невідома тема.")
            elif v not in SETTINGS_OPTIONS[k] or isinstance(v, bool) != isinstance(SETTINGS_OPTIONS[k][0], bool):
                raise GameError("VALIDATION_ERROR", f"Недопустиме значення параметра {k}.")
            s[k] = v
        return s

    def _new_code(self):
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            if code not in self.codes:
                return code

    def _new_member(self, mid, name, role, is_bot=False, bot_level=None):
        now = self.clock()
        return {"id": mid, "name": name, "role": role, "is_bot": is_bot, "bot_level": bot_level,
                "ready": is_bot, "joined": now, "last_seen": now}

    def create_room(self, user, name, settings=None):
        with self.lock:
            self.set_name(user, name)
            s = self._validate_settings(settings, DEFAULT_SETTINGS)
            rid = new_id("r")
            code = self._new_code()
            room = {"id": rid, "code": code, "host_id": user["id"], "status": "OPEN", "settings": s,
                    "members": [self._new_member(user["id"], user["name"], "PLAYER")], "game_id": None,
                    "games": [], "version": 1, "created": self.clock(), "recent_items": [], "log": []}
            self.rooms[rid] = room
            self.codes[code] = rid
            self._log(room, "room:created", {"by": user["id"]})
            self._notify(rid)
            return room

    def _log(self, room, etype, payload):
        room["log"].append({"t": self.clock(), "type": etype, "payload": payload})
        room["log"] = room["log"][-200:]

    def join_room(self, user, code, name, spectator=False):
        with self.lock:
            code = (code or "").strip().upper()
            rid = self.codes.get(code)
            room = self.rooms.get(rid) if rid else None
            if not room or room["status"] == "CLOSED":
                raise GameError("ROOM_NOT_FOUND")
            if name:
                self.set_name(user, name)
            elif not user["name"]:
                raise GameError("VALIDATION_ERROR", "Введіть ім'я.")
            m = self._member(room, user["id"])
            if m:  # повернення на своє місце (ТЗ §23), зокрема після виходу під час гри
                if m.pop("left", None):
                    room["version"] += 1
                    self._notify(room["id"])
                return room
            in_game = room["status"] != "OPEN"
            role = "SPECTATOR" if (spectator or in_game) else "PLAYER"
            if role == "SPECTATOR" and not room["settings"]["allow_spectators"]:
                raise GameError("FORBIDDEN", "Гра вже триває, а глядачі в цій кімнаті вимкнені."
                                if in_game else "Глядачі в цій кімнаті вимкнені.")
            if role == "PLAYER" and self._player_count(room) >= room["settings"]["max_players"]:
                raise GameError("ROOM_FULL", details={"can_spectate": room["settings"]["allow_spectators"]})
            room["members"].append(self._new_member(user["id"], self._unique_name(room, user["name"]), role))
            room["version"] += 1
            self._log(room, "room:joined", {"user": user["id"], "role": role})
            self._notify(room["id"])
            return room

    @staticmethod
    def _player_count(room):
        return sum(1 for m in room["members"] if m["role"] == "PLAYER")

    def _require_lobby(self, room):
        if room["status"] != "OPEN":
            raise GameError("GAME_NOT_READY", "Це можна змінити лише в лобі.")

    def set_ready(self, user, room_id, ready):
        with self.lock:
            room = self._room(room_id)
            self._require_lobby(room)
            m = self._member(room, user["id"])
            if not m or m["role"] != "PLAYER":
                raise GameError("NOT_A_PLAYER")
            m["ready"] = bool(ready)
            room["version"] += 1
            self._notify(room_id)

    def update_settings(self, user, room_id, patch, expected_version=None):
        with self.lock:
            room = self._room(room_id)
            self._require_host(room, user)
            self._require_lobby(room)
            if expected_version is not None and expected_version != room["version"]:
                raise GameError("STALE_VERSION", details={"version": room["version"]})
            s = self._validate_settings(patch, room["settings"])
            if s["max_players"] < self._player_count(room):
                raise GameError("VALIDATION_ERROR", "У лобі вже більше гравців, ніж цей ліміт.")
            if s != room["settings"]:
                room["settings"] = s
                for m in room["members"]:  # після зміни умов гравці підтверджують готовність знову
                    if not m["is_bot"] and m["id"] != room["host_id"]:
                        m["ready"] = False
                room["version"] += 1
                self._notify(room_id)
            return room

    def add_bot(self, user, room_id, level="regular"):
        with self.lock:
            room = self._room(room_id)
            self._require_host(room, user)
            self._require_lobby(room)
            if level not in bots.LEVELS:
                raise GameError("VALIDATION_ERROR", "Невідомий рівень бота.")
            if self._player_count(room) >= room["settings"]["max_players"]:
                raise GameError("ROOM_FULL")
            used = {m["name"] for m in room["members"]}
            name = next((n for n in BOT_NAMES if n not in used), f"Бот {len(used) + 1}")
            room["members"].append(self._new_member(new_id("bot"), name, "PLAYER", True, level))
            room["version"] += 1
            self._notify(room_id)

    def remove_member(self, user, room_id, member_id):
        with self.lock:
            room = self._room(room_id)
            self._require_lobby(room)
            if member_id != user["id"]:
                self._require_host(room, user)
            m = self._member(room, member_id)
            if not m:
                raise GameError("VALIDATION_ERROR", "Учасника не знайдено.")
            room["members"].remove(m)
            if member_id == room["host_id"]:
                self._pick_new_host(room)
            room["version"] += 1
            self._notify(room_id)

    def leave_room(self, user, room_id):
        """Вихід. У лобі — учасника видалено. Під час гри він лишається власником покупок і
        бюджету (ТЗ §8, §23), але кімната більше не відкривається йому автоматично; повернутися
        можна за кодом кімнати."""
        with self.lock:
            room = self._room(room_id)
            m = self._member(room, user["id"])
            if not m:
                return
            if room["status"] == "OPEN":
                return self.remove_member(user, room_id, user["id"])
            m["left"] = True
            m["ready"] = False
            if room["host_id"] == user["id"]:
                others = sorted((x for x in room["members"] if not x["is_bot"] and not x.get("left")
                                 and self.is_online(room_id, x)), key=lambda x: x["joined"])
                if others:
                    self._set_host(room, others[0])
            room["version"] += 1
            self._log(room, "room:left", {"user": user["id"]})
            self._notify(room_id)

    def set_role(self, user, room_id, member_id, role):
        with self.lock:
            room = self._room(room_id)
            self._require_lobby(room)
            if member_id != user["id"]:
                self._require_host(room, user)
            m = self._member(room, member_id)
            if not m or m["is_bot"] or role not in ("PLAYER", "SPECTATOR"):
                raise GameError("VALIDATION_ERROR")
            if role == m["role"]:
                return
            if role == "PLAYER" and self._player_count(room) >= room["settings"]["max_players"]:
                raise GameError("ROOM_FULL")
            m["role"], m["ready"] = role, False
            room["version"] += 1
            self._notify(room_id)

    def transfer_host(self, user, room_id, member_id):
        with self.lock:
            room = self._room(room_id)
            self._require_host(room, user)
            m = self._member(room, member_id)
            if not m or m["is_bot"]:
                raise GameError("VALIDATION_ERROR", "Роль організатора можна передати лише людині.")
            self._set_host(room, m)

    def _set_host(self, room, m):
        room["host_id"] = m["id"]
        room["version"] += 1
        self._log(room, "host:changed", {"to": m["id"]})
        self._notify(room["id"])

    def _pick_new_host(self, room, prefer_online=True):
        humans = sorted((m for m in room["members"] if not m["is_bot"]), key=lambda m: m["joined"])
        online = [m for m in humans if self.is_online(room["id"], m)]
        pick = (online or ([] if prefer_online else humans))
        if pick:
            self._set_host(room, pick[0])
        elif not humans:
            room["status"] = "CLOSED"
            self.codes.pop(room["code"], None)

    def start_block_reason(self, room):
        players = [m for m in room["members"] if m["role"] == "PLAYER"]
        humans = [m for m in players if not m["is_bot"]]
        if len(players) < 2:
            return "Потрібно щонайменше 2 гравці — запросіть друзів або додайте бота."
        if not humans:
            return "Потрібна хоча б одна людина-гравець."
        offline = [m["name"] for m in humans if not self.is_online(room["id"], m)]
        if offline:
            return f"Офлайн: {', '.join(offline)}. Переведіть у глядачі або видаліть."
        waiting = [m["name"] for m in humans if m["id"] != room["host_id"] and not m["ready"]]
        if waiting:
            return f"Чекаємо готовності: {', '.join(waiting)}."
        return None

    # ------------------------------------------------------------ старт гри
    def start_game(self, user, room_id):
        with self.lock:
            room = self._room(room_id)
            self._require_host(room, user)
            self._require_lobby(room)
            reason = self.start_block_reason(room)
            if reason:
                raise GameError("GAME_NOT_READY", reason)
            now = self.clock()
            params = copy.deepcopy(room["settings"])  # параметри фіксуються на старті (ТЗ §4)
            theme = T.get(params["theme_id"])
            gid = new_id("g")
            seed = secrets.randbits(32)
            game = {"id": gid, "room_id": room_id, "status": "GENERATING", "mode": params["game_mode"],
                    "params": params, "theme_id": theme["id"], "seed": seed, "lots": [], "current": -1,
                    "players": {}, "order": [], "ledger": [], "bids": [], "idem": {}, "version": 1,
                    "phase_until": None, "paused": None, "last_result": None, "feed": [], "results": None,
                    "simulations": [], "created": now, "completed_at": None, "snapshot": None,
                    "content_version": "templates-v1", "judge": None}
            items = T.generate_lots(theme, params["lot_count"], seed, room["recent_items"], params["difficulty"])
            for i, it in enumerate(items):
                game["lots"].append({"id": new_id("lot"), "seq": i + 1, "item": it, "status": "PENDING",
                                     "current_bid": 0, "leader": None, "version": 0, "opens_at": None,
                                     "closes_at": None, "hard_closes_at": None, "winner": None, "price": None,
                                     "bids": 0, "extended": 0.0})
            players = [m for m in room["members"] if m["role"] == "PLAYER"]
            anon = list(range(1, len(players) + 1))
            random.Random(seed).shuffle(anon)
            for m, a in zip(players, anon):
                b = params["budget"]
                game["players"][m["id"]] = {"id": m["id"], "name": m["name"], "is_bot": m["is_bot"],
                                            "bot_level": m["bot_level"], "public_id": f"anon-p{a}",
                                            "starting": b, "available": b, "reserved": 0, "spent": 0}
                game["order"].append(m["id"])
            self.games[gid] = game
            game["status"] = "READY"
            room["status"], room["game_id"] = "IN_GAME", gid
            room["games"].append(gid)
            room["version"] += 1
            game["status"] = "INTRO"
            game["phase_until"] = now + INTRO_SECONDS
            self._say(game, "intro", theme=theme["title"])
            self._log(room, "game:started", {"game_id": gid})
            self._touch(game)
            return game

    def _say(self, game, kind, **kw):
        style = game["params"].get("host_style", "auctioneer")
        text = HOST_LINES.get(style, HOST_LINES["auctioneer"])[kind].format(**kw)
        game["feed"].append({"t": self.clock(), "text": text})
        game["feed"] = game["feed"][-20:]

    def _touch(self, game):
        game["version"] += 1
        self._notify(game["room_id"])

    def _ledger(self, game, pid, etype, amount, lot, bid_id=None):
        game["ledger"].append({"seq": len(game["ledger"]) + 1, "player_id": pid, "type": etype, "amount": amount,
                               "lot_id": lot["id"], "bid_id": bid_id, "t": self.clock()})

    def _game(self, game_id):
        g = self.games.get(game_id)
        if not g:
            raise GameError("GAME_NOT_FOUND")
        return g

    # ------------------------------------------------------------ лоти й таймер
    def _open_lot(self, game, idx, now):
        lot = game["lots"][idx]
        if lot["status"] != "PENDING":  # повторне відкриття заборонене (ТЗ §22)
            return
        dur = game["params"]["timer"]
        lot.update(status="OPEN", opens_at=now, closes_at=now + dur, hard_closes_at=now + dur + EXTEND_CAP, version=1)
        game["current"] = idx
        game["status"] = "AUCTION_OPEN"
        game["last_result"] = None
        self._touch(game)

    def _close_lot(self, game, lot, now, early=False):
        if lot["status"] != "OPEN":  # ідемпотентне закриття: другий запуск нічого не робить
            return
        game["status"] = "AUCTION_CLOSING"
        name = lot["item"]["name"]
        if lot["leader"]:
            p = game["players"][lot["leader"]]
            price = lot["current_bid"]
            p["reserved"] -= price
            p["spent"] += price
            self._ledger(game, p["id"], "SPEND", price, lot)
            lot.update(status="SOLD", winner=p["id"], price=price)
            if price == 1:
                self._say(game, "cheap", item=name, name=p["name"])
            elif price * 2 > p["starting"]:
                self._say(game, "big", item=name, name=p["name"])
            else:
                self._say(game, "sold", item=name, name=p["name"], price=price)
        else:
            lot["status"] = "UNSOLD"
            self._say(game, "unsold", item=name)
        lot["closed_at"] = now
        lot["version"] += 1
        game["last_result"] = {"lot_id": lot["id"], "seq": lot["seq"], "name": name, "emoji": lot["item"]["emoji"],
                               "visual_key": lot["item"]["key"],
                               "winner_id": lot["winner"],
                               "winner_name": game["players"][lot["winner"]]["name"] if lot["winner"] else None,
                               "price": lot["price"], "early": early}
        game["status"] = "LOT_RESULT"
        game["phase_until"] = now + RESULT_PAUSE
        self._touch(game)

    def _nobody_can_bid(self, game, lot):
        need = lot["current_bid"] + game["params"]["bid_step"] if lot["leader"] else 1
        return all(p["id"] == lot["leader"] or p["available"] < need for p in game["players"].values())

    def tick(self, now=None):
        with self.lock:
            now = self.clock() if now is None else now
            for game in list(self.games.values()):
                st = game["status"]
                if st == "INTRO" and now >= game["phase_until"]:
                    self._open_lot(game, 0, now)
                elif st == "AUCTION_OPEN":
                    lot = game["lots"][game["current"]]
                    if now >= lot["closes_at"]:
                        self._close_lot(game, lot, now)
                    elif now - lot["opens_at"] >= 2 and self._nobody_can_bid(game, lot):
                        self._close_lot(game, lot, now, early=True)
                    else:
                        bots.act(self, game, lot, now)
                elif st == "LOT_RESULT" and now >= game["phase_until"]:
                    if game["current"] + 1 < len(game["lots"]):
                        self._open_lot(game, game["current"] + 1, now)
                    else:
                        self._start_scoring(game, now)
                elif st == "SCORING" and game["id"] not in self._judging:
                    self._start_scoring(game, now)  # відновлення після рестарту
            for room in self.rooms.values():
                if room["status"] == "CLOSED":
                    continue
                host = self._member(room, room["host_id"])
                if host is None or (not self.is_online(room["id"], host)
                                    and now - host["last_seen"] > HOST_TRANSFER_TIMEOUT):
                    others = [m for m in room["members"] if not m["is_bot"] and m["id"] != room["host_id"]
                              and self.is_online(room["id"], m)]
                    if others:
                        self._set_host(room, sorted(others, key=lambda m: m["joined"])[0])

    # ------------------------------------------------------------ ставки
    def bid(self, user, game_id, lot_id, amount, idempotency_key, expected_lot_version=None):
        with self.lock:
            game = self._game(game_id)
            p = game["players"].get(user["id"])
            if not p or p["is_bot"]:
                raise GameError("NOT_A_PLAYER")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount > 1_000_000:
                raise GameError("VALIDATION_ERROR", "Сума ставки має бути цілим числом.")
            if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
                raise GameError("VALIDATION_ERROR", "Некоректний idempotency_key.")
            if not isinstance(lot_id, str):
                raise GameError("VALIDATION_ERROR")
            return self.place_bid(game, p["id"], lot_id, amount, idempotency_key, expected_lot_version)

    def place_bid(self, game, pid, lot_id, amount, key, expected_lot_version=None):
        now = self.clock()
        k = f"{lot_id}|{pid}|{key}"
        prev = game["idem"].get(k)
        if prev:
            if prev["amount"] != amount:
                raise GameError("IDEMPOTENCY_CONFLICT")
            if prev.get("error"):
                e = prev["error"]
                raise GameError(e["code"], e.get("message"), dict(e["details"], replayed=True))
            return dict(prev["result"], replayed=True, server_time=now)
        try:
            res = self._apply_bid(game, pid, lot_id, amount, now)
        except GameError as e:
            if e.code in STORED_REJECTIONS:
                game["idem"][k] = {"amount": amount, "error": {"code": e.code, "message": e.message,
                                                               "details": e.details}}
                game["bids"].append({"id": new_id("bid"), "lot_id": lot_id, "player_id": pid, "amount": amount,
                                     "status": "REJECTED", "reason": e.code, "t": now})
                self.dirty = True
            raise
        game["idem"][k] = {"amount": amount, "result": res}
        return res

    def _lot_state(self, lot):
        return {"lot_id": lot["id"], "current_bid": lot["current_bid"], "leader_player_id": lot["leader"],
                "lot_version": lot["version"], "closes_at": lot["closes_at"]}

    def _apply_bid(self, game, pid, lot_id, amount, now):
        visible = {l["id"]: l for l in game["lots"] if l["status"] != "PENDING"}
        lot = visible.get(lot_id)
        if game["status"] == "PAUSED":
            raise GameError("GAME_PAUSED")
        if not lot:  # майбутній і неіснуючий лот — однакова відповідь (ТЗ §26)
            raise GameError("INVALID_LOT")
        current = game["lots"][game["current"]] if game["current"] >= 0 else None
        if lot is not current or lot["status"] != "OPEN" or game["status"] != "AUCTION_OPEN" or now >= lot["closes_at"]:
            raise GameError("LOT_CLOSED", details=self._lot_state(lot))
        step = game["params"]["bid_step"]
        minimum = lot["current_bid"] + step if lot["leader"] else 1
        if amount < minimum:
            raise GameError("BID_TOO_LOW", f"Мінімальна ставка зараз — ${minimum}.",
                            dict(self._lot_state(lot), minimum=minimum))
        if lot["leader"] == pid:
            raise GameError("ALREADY_LEADER", details=self._lot_state(lot))
        p = game["players"][pid]
        if amount > p["available"]:
            raise GameError("INSUFFICIENT_FUNDS", f"Доступно лише ${p['available']}.",
                            dict(self._lot_state(lot), available=p["available"]))
        bid_id = new_id("bid")
        if lot["leader"]:
            prev = game["players"][lot["leader"]]
            prev["available"] += lot["current_bid"]
            prev["reserved"] -= lot["current_bid"]
            self._ledger(game, prev["id"], "RELEASE", lot["current_bid"], lot, bid_id)
        p["available"] -= amount
        p["reserved"] += amount
        self._ledger(game, pid, "RESERVE", amount, lot, bid_id)
        lot["current_bid"], lot["leader"] = amount, pid
        lot["version"] += 1
        lot["bids"] += 1
        if lot["closes_at"] - now < EXTEND_WINDOW:  # подовження таймера (ТЗ §7)
            new_close = min(now + EXTEND_WINDOW, lot["hard_closes_at"])
            if new_close > lot["closes_at"]:
                lot["closes_at"] = new_close
        game["bids"].append({"id": bid_id, "lot_id": lot["id"], "player_id": pid, "amount": amount,
                             "status": "ACCEPTED", "t": now})
        self._touch(game)
        return {"bid_id": bid_id, "accepted": True, "current_bid": amount, "leader_player_id": pid,
                "lot_version": lot["version"], "closes_at": lot["closes_at"], "available_balance": p["available"],
                "reserved_balance": p["reserved"], "server_time": now}

    # ------------------------------------------------------------ пауза, скасування, реванш
    def pause(self, user, game_id):
        with self.lock:
            game = self._game(game_id)
            room = self._room(game["room_id"])
            self._require_host(room, user)
            if game["status"] not in ("INTRO", "AUCTION_OPEN", "LOT_RESULT"):
                raise GameError("GAME_NOT_READY", "Зараз гру не можна призупинити.")
            now = self.clock()
            info = {"from": game["status"]}
            if game["status"] == "AUCTION_OPEN":
                lot = game["lots"][game["current"]]
                info["remaining"] = max(0.0, lot["closes_at"] - now)
                info["hard_remaining"] = max(0.0, lot["hard_closes_at"] - now)
            else:
                info["phase_remaining"] = max(0.0, game["phase_until"] - now)
            game["paused"], game["status"] = info, "PAUSED"
            self._touch(game)

    def resume(self, user, game_id):
        with self.lock:
            game = self._game(game_id)
            room = self._room(game["room_id"])
            self._require_host(room, user)
            if game["status"] != "PAUSED":
                raise GameError("GAME_NOT_READY", "Гра не на паузі.")
            now, info = self.clock(), game["paused"]
            if info["from"] == "AUCTION_OPEN":
                lot = game["lots"][game["current"]]
                lot["closes_at"] = now + max(info["remaining"], 3)
                lot["hard_closes_at"] = max(now + info["hard_remaining"], lot["closes_at"])
            else:
                game["phase_until"] = now + info["phase_remaining"]
            game["status"], game["paused"] = info["from"], None
            self._touch(game)

    def cancel(self, user, game_id):
        with self.lock:
            game = self._game(game_id)
            room = self._room(game["room_id"])
            self._require_host(room, user)
            if game["status"] in ("COMPLETED", "CANCELLED"):
                raise GameError("GAME_NOT_READY")
            for lot in game["lots"]:
                if lot["status"] == "OPEN":
                    if lot["leader"]:
                        p = game["players"][lot["leader"]]
                        p["available"] += lot["current_bid"]
                        p["reserved"] -= lot["current_bid"]
                        self._ledger(game, p["id"], "RELEASE", lot["current_bid"], lot)
                    lot["status"] = "UNSOLD"
            game["status"] = "CANCELLED"
            self._back_to_lobby(room, game)

    def rematch(self, user, game_id):
        with self.lock:
            game = self._game(game_id)
            room = self._room(game["room_id"])
            self._require_host(room, user)
            if game["status"] not in ("COMPLETED", "CANCELLED") or room["game_id"] != game_id:
                raise GameError("GAME_NOT_READY", "Реванш доступний після завершення партії.")
            self._back_to_lobby(room, game)
            return room

    def _back_to_lobby(self, room, game):
        room["recent_items"] = [l["item"]["key"] for l in game["lots"]]
        room["status"], room["game_id"] = "OPEN", None
        room["members"] = [m for m in room["members"] if not m.get("left")]  # ті, хто вийшов, не блокують старт
        for m in room["members"]:
            m["ready"] = m["is_bot"]
        room["version"] += 1
        self._touch(game)

    # ------------------------------------------------------------ оцінювання
    def _snapshot(self, game):
        players = []
        for pid in game["order"]:
            p = game["players"][pid]
            items = [dict(l["item"], lot_id=l["id"], seq=l["seq"], price=l["price"])
                     for l in game["lots"] if l["winner"] == pid]
            players.append({"id": pid, "name": p["name"], "is_bot": p["is_bot"], "public_id": p["public_id"],
                            "starting": p["starting"], "spent": p["spent"], "items": items})
        lots = [{"lot_id": l["id"], "seq": l["seq"], "name": l["item"]["name"], "emoji": l["item"]["emoji"],
                 "visual_key": l["item"]["key"],
                 "quantity": l["item"]["quantity"], "unit": l["item"]["unit"], "status": l["status"],
                 "winner_id": l["winner"],
                 "winner_name": game["players"][l["winner"]]["name"] if l["winner"] else None,
                 "price": l["price"]} for l in game["lots"]]
        return {"theme_id": game["theme_id"], "players": players, "lots": lots}

    def _start_scoring(self, game, now):
        game["status"] = "SCORING"
        if not game["snapshot"]:
            game["snapshot"] = copy.deepcopy(self._snapshot(game))  # immutable final snapshot (ТЗ §9)
        self._touch(game)
        theme = T.get(game["theme_id"])
        needs_ai = any(c.get("subjective") for c in theme["criteria"])
        if needs_ai and self.ai and self.ai.enabled:
            self._judging.add(game["id"])
            threading.Thread(target=self._run_judge, args=(game["id"],), daemon=True).start()
        else:
            self._finish_scoring(game, None, "fallback" if needs_ai else "not_required")

    def _run_judge(self, game_id):
        with self.lock:
            game = self.games[game_id]
            theme = T.get(game["theme_id"])
            snapshot = copy.deepcopy(game["snapshot"])
        ai_scores, usage, status = None, [], "fallback"
        try:
            ai_scores, usage = self.ai.judge(theme, snapshot, game_id)
            status = "ai" if ai_scores else "fallback"
        except Exception as e:  # збій AI не впливає на ставки й бюджети (ТЗ §36)
            usage = [{"operation": "judge", "game_id": game_id, "status": "error", "error": str(e)[:200]}]
        with self.lock:
            self.usage.extend(usage)
            game = self.games[game_id]
            if game["status"] == "SCORING":
                self._finish_scoring(game, ai_scores, status)
            self._judging.discard(game_id)

    def _finish_scoring(self, game, ai_scores, status):
        theme = T.get(game["theme_id"])
        game["judge"] = {"status": status, "scores": ai_scores}
        game["results"] = score_game(theme, game["snapshot"], ai_scores, status)
        game["status"] = "COMPLETED"
        game["completed_at"] = self.clock()
        room = self.rooms.get(game["room_id"])
        if room:
            self._log(room, "game:completed", {"game_id": game["id"]})
        self._touch(game)

    # ------------------------------------------------------------ «А що, якби?» (ТЗ §45)
    def whatif(self, user, game_id, lot_id, buyer_id, price):
        with self.lock:
            game = self._game(game_id)
            room = self.rooms.get(game["room_id"])
            if not room or not self._member(room, user["id"]):
                raise GameError("FORBIDDEN")
            if game["status"] != "COMPLETED":
                raise GameError("GAME_NOT_READY", "Симуляція доступна після завершення партії.")
            if isinstance(price, bool) or not isinstance(price, int) or price < 1:
                raise GameError("BID_TOO_LOW", "Мінімальна ставка — $1.")
            snap = game["snapshot"]
            lot = next((l for l in snap["lots"] if l["lot_id"] == lot_id), None)
            pl = {p["id"]: p for p in snap["players"]}
            if not lot or buyer_id not in pl:
                raise GameError("VALIDATION_ERROR", "Оберіть лот і покупця.")
            if lot["winner_id"] == buyer_id:
                raise GameError("VALIDATION_ERROR", "Цей лот і так належить цьому гравцеві.")
            buyer = pl[buyer_id]
            spent_before = sum(it["price"] for it in buyer["items"] if it["seq"] < lot["seq"])
            avail = buyer["starting"] - spent_before
            if price > avail:
                raise GameError("INSUFFICIENT_FUNDS",
                                f"Перед лотом {lot['seq']} у гравця {buyer['name']} було лише ${avail}.",
                                {"available_before": avail})
            sim = {"id": new_id("sim"), "lot_id": lot_id, "buyer_id": buyer_id, "price": price,
                   "created": self.clock(), "mode": "simple",
                   "assumption": "Інші результати торгів вважаються незмінними (простий режим)."}
            running = spent_before + price
            for it in sorted((x for x in buyer["items"] if x["seq"] > lot["seq"]), key=lambda x: x["seq"]):
                running += it["price"]
                if running > buyer["starting"]:
                    sim.update(valid=False, reason=(
                        f"Варіант недійсний у простому режимі: тоді {buyer['name']} не зміг би оплатити "
                        f"лот {it['seq']} «{it['name']}» (${it['price']}). Потрібна повна симуляція торгів."))
                    game["simulations"].append(sim)
                    return sim
            theme = T.get(game["theme_id"])
            new_snap = copy.deepcopy(snap)
            npl = {p["id"]: p for p in new_snap["players"]}
            full_item = next(l["item"] for l in game["lots"] if l["id"] == lot_id)
            if lot["winner_id"]:
                old = npl[lot["winner_id"]]
                old["items"] = [it for it in old["items"] if it["lot_id"] != lot_id]
                old["spent"] -= lot["price"]
            nb = npl[buyer_id]
            nb["items"].append(dict(full_item, lot_id=lot_id, seq=lot["seq"], price=price))
            nb["items"].sort(key=lambda it: it["seq"])
            nb["spent"] += price
            affected = {buyer_id, lot["winner_id"]}
            ai = {pid: s for pid, s in ((game["judge"] or {}).get("scores") or {}).items() if pid not in affected}
            res = score_game(theme, new_snap, ai, "simulation")
            before = {r["player_id"]: r for r in game["results"]["ranking"]}
            sim.update(valid=True, ranking=[{
                "player_id": r["player_id"], "name": r["name"], "place": r["place"], "total": r["total_display"],
                "before_place": before[r["player_id"]]["place"], "before_total": before[r["player_id"]]["total_display"],
            } for r in res["ranking"]])
            game["simulations"].append(sim)
            self.dirty = True
            return sim

    # ------------------------------------------------------------ подання стану клієнту
    def public_item(self, theme, it):
        labels = theme["attr_labels"]
        props = [{"label": labels[a][0], "value": v, "unit": labels[a][1]} for a, v in it["attrs"].items() if v]
        return {"name": it["name"], "emoji": it["emoji"], "quantity": it["quantity"], "unit": it["unit"],
                "description": it["description"], "props": props, "image": media.image(it["key"]) if theme.get("photos") else None,
                "requires": [T.CAP_LABELS[c] for c in it["requires"]],
                "provides": [T.CAP_LABELS[c] for c in it["provides"]]}

    def view(self, user, room_id):
        with self.lock:
            room = self.rooms.get(room_id)
            if not room or room["status"] == "CLOSED":
                raise GameError("ROOM_NOT_FOUND")
            me = self._member(room, user["id"])
            if not me:
                raise GameError("FORBIDDEN", "Ви не учасник цієї кімнати.")
            theme = T.get(room["settings"]["theme_id"])
            r = {"id": room["id"], "code": room["code"], "status": room["status"], "host_id": room["host_id"],
                 "settings": room["settings"], "version": room["version"],
                 "theme": {"id": theme["id"], "title": theme["title"], "emoji": theme["emoji"]},
                 "members": [{"id": m["id"], "name": m["name"], "role": m["role"], "is_bot": m["is_bot"],
                              "bot_level": m["bot_level"], "ready": m["ready"],
                              "online": self.is_online(room["id"], m), "is_host": m["id"] == room["host_id"]}
                             for m in room["members"]],
                 "start_block": self.start_block_reason(room) if room["status"] == "OPEN" else None}
            g = self.games.get(room["game_id"]) if room["game_id"] else None
            return {"server_time": self.clock(),
                    "me": {"id": user["id"], "name": me["name"], "role": me["role"],
                           "is_host": room["host_id"] == user["id"]},
                    "room": r, "game": self._game_view(g, user["id"]) if g else None}

    def _game_view(self, game, uid):
        theme = T.get(game["theme_id"])
        done = game["status"] == "COMPLETED"
        show_w = game["params"]["show_weights"] or done
        cur = game["lots"][game["current"]] if game["current"] >= 0 else None
        current = None
        if cur and cur["status"] != "PENDING":
            current = {"id": cur["id"], "seq": cur["seq"], "status": cur["status"], "item": self.public_item(theme, cur["item"]),
                       "current_bid": cur["current_bid"], "leader_id": cur["leader"], "version": cur["version"],
                       "closes_at": cur["closes_at"], "hard_closes_at": cur["hard_closes_at"], "bids": cur["bids"]}
        history = [{"id": l["id"], "seq": l["seq"], "status": l["status"], "name": l["item"]["name"],
                    "emoji": l["item"]["emoji"], "quantity": l["item"]["quantity"], "unit": l["item"]["unit"],
                    "winner_id": l["winner"], "price": l["price"], "visual_key": l["item"]["key"]}
                   for l in game["lots"] if l["status"] in ("SOLD", "UNSOLD")]
        # Фото лише для вже відкритих лотів — бібліотека майбутніх предметів не розкривається.
        revealed = [h["visual_key"] for h in history] + ([cur["item"]["key"]] if current else [])
        media_map = {k: media.image(k) for k in revealed if media.image(k)} if theme.get("photos") else {}
        players = []
        for pid in game["order"]:
            p = game["players"][pid]
            players.append({"id": pid, "name": p["name"], "is_bot": p["is_bot"], "available": p["available"],
                            "reserved": p["reserved"], "spent": p["spent"], "starting": p["starting"],
                            "items": [h for h in history if h["winner_id"] == pid]})
        me = game["players"].get(uid)
        return {"id": game["id"], "status": game["status"], "version": game["version"], "mode": game["mode"],
                "params": {k: game["params"][k] for k in ("lot_count", "budget", "timer", "bid_step", "show_weights")},
                "theme": {"id": theme["id"], "title": theme["title"], "emoji": theme["emoji"],
                          "objective": theme["objective"], "intro": theme["intro"],
                          "environment": theme["environment"],
                          "criteria": [{"id": c["id"], "title": c["title"],
                                        "weight": c["weight"] if show_w else None} for c in theme["criteria"]]},
                "lot_count": len(game["lots"]), "current_index": game["current"], "current_lot": current,
                "history": history, "players": players, "phase_until": game["phase_until"], "media": media_map,
                "paused": game["paused"], "last_result": game["last_result"], "feed": game["feed"][-4:],
                "wallet": ({k: me[k] for k in ("available", "reserved", "spent", "starting")} if me else None),
                "results": game["results"] if done else None,
                "simulations": [s for s in game["simulations"]][-5:] if done else []}

    # ------------------------------------------------------------ збереження
    def export(self):
        with self.lock:
            return {"users": self.users, "sessions": self.sessions, "rooms": self.rooms, "games": self.games,
                    "codes": self.codes, "usage": self.usage[-1000:]}

    def load(self, data):
        with self.lock:
            for k in ("users", "sessions", "rooms", "games", "codes"):
                setattr(self, k, data.get(k, {}))
            self.usage = data.get("usage", [])
            now = self.clock()
            for room in self.rooms.values():
                for m in room["members"]:
                    m["last_seen"] = now  # даємо час перепідключитися після рестарту

    # ------------------------------------------------------------ перевірка інваріантів
    def check_invariants(self, game):
        errs = []
        for p in game["players"].values():
            if min(p["available"], p["reserved"], p["spent"]) < 0:
                errs.append(f"{p['name']}: від'ємний баланс")
            if p["available"] + p["reserved"] + p["spent"] != p["starting"]:
                errs.append(f"{p['name']}: порушено available+reserved+spent=starting")
            sold = sum(l["price"] for l in game["lots"] if l["winner"] == p["id"])
            if sold != p["spent"]:
                errs.append(f"{p['name']}: spent не збігається з покупками")
        for l in game["lots"]:
            if l["closes_at"] and l["closes_at"] > l["hard_closes_at"] + 1e-9:
                errs.append(f"лот {l['seq']}: closes_at > hard_closes_at")
        return errs
