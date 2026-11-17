"""Бот-гравці: локальний алгоритм без доступу до прихованого порядку лотів (ТЗ §19).

Бот бачить те саме, що й людина: поточний лот, свої покупки, кількість лотів, що лишилися,
і публічні критерії. Ставки бота проходять ту саму транзакцію, що й людські.
"""
import secrets

from . import themes as T
from .scoring import score_player

LEVELS = {
    "novice": {"title": "Початківець", "aggr": 1.0, "noise": 0.5, "think": (1.5, 5.0), "jump": 0.05},
    "regular": {"title": "Звичайний", "aggr": 1.0, "noise": 0.25, "think": (1.0, 4.0), "jump": 0.1},
    "strategist": {"title": "Стратег", "aggr": 1.1, "noise": 0.1, "think": (1.0, 3.5), "jump": 0.1},
    "economist": {"title": "Економіст", "aggr": 0.75, "noise": 0.15, "think": (1.5, 4.5), "jump": 0.0},
    "adventurer": {"title": "Авантюрист", "aggr": 1.45, "noise": 0.3, "think": (0.8, 3.0), "jump": 0.3},
}


def valuation(game, pid, lot, rng):
    """Максимальна ціна, яку бот готовий заплатити за поточний лот."""
    theme = T.get(game["theme_id"])
    p = game["players"][pid]
    cfg = LEVELS.get(p["bot_level"] or "regular", LEVELS["regular"])
    inv = [l["item"] for l in game["lots"] if l["winner"] == pid]  # лише власні завершені покупки
    before = score_player(theme, inv, p["starting"], p["spent"])["total_raw"]
    after = score_player(theme, inv + [lot["item"]], p["starting"], p["spent"])["total_raw"]
    gain = max(0.0, after - before)
    lots_left = len(game["lots"]) - lot["seq"] + 1  # публічна інформація: номер лота та загальна кількість
    money = p["available"]
    per_lot = money / max(1.0, lots_left * 0.55)
    value = per_lot * (0.3 + gain * 1.6) * cfg["aggr"] * (1 + cfg["noise"] * rng.uniform(-1, 1))
    if lots_left <= 1:
        value = max(value, money * min(1.0, gain))  # останній лот: гроші більше не знадобляться
    return max(0, min(money, int(round(value))))


def act(engine, game, lot, now):
    rng = engine.rng
    state = game.setdefault("bot_state", {})
    for pid in game["order"]:
        p = game["players"][pid]
        if not p["is_bot"]:
            continue
        cfg = LEVELS.get(p["bot_level"] or "regular", LEVELS["regular"])
        st = state.get(pid)
        if not st or st["lot_id"] != lot["id"]:
            st = state[pid] = {"lot_id": lot["id"], "max": valuation(game, pid, lot, rng),
                               "next_at": now + rng.uniform(*cfg["think"])}
        if now < st["next_at"] or lot["leader"] == pid:
            continue
        st["next_at"] = now + rng.uniform(*cfg["think"])
        need = lot["current_bid"] + game["params"]["bid_step"] if lot["leader"] else 1
        if need > st["max"] or need > p["available"]:
            continue
        amount = need
        if rng.random() < cfg["jump"]:
            amount = min(st["max"], p["available"], need + rng.choice([1, 2, 4]))
        try:
            engine.place_bid(game, pid, lot["id"], amount, secrets.token_hex(8))
        except Exception:
            pass
