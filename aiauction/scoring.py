"""Єдиний Scoring Engine (ТЗ §33).

Рівень A — справді придбані речі; B — агрегація ресурсів; C — prereq/синергії/конфлікти;
D — суб'єктивні критерії (AI або резервна рубрика); E — ваги, штрафи, cap, місця.
"""
from .themes import CAP_LABELS

DEFAULT_SYNERGY_CAP = 1.5  # 15% шкали критерію (ТЗ §17)

_OPS = {
    "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b, "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b, "eq": lambda a, b: a == b,
}


def fmt(v):
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.1f}".replace(".", ",")
    return str(int(v))


def resolve(theme, items):
    """Визначає, які предмети працюють (виконані requires), і агрегує властивості."""
    env = set(theme.get("env_caps", []))
    working = [False] * len(items)
    changed = True
    caps = set(env)
    while changed:
        changed = False
        caps = set(env)
        for i, it in enumerate(items):
            if working[i]:
                caps |= set(it.get("provides", []))
        for i, it in enumerate(items):
            if not working[i] and all(r in caps for r in it.get("requires", [])):
                working[i] = True
                changed = True
    totals, tag_counts, categories, keys, nonworking = {}, {}, set(), set(), []
    for i, it in enumerate(items):
        if not working[i]:
            missing = [CAP_LABELS.get(r, r) for r in it.get("requires", []) if r not in caps]
            nonworking.append({"lot_id": it.get("lot_id"), "name": it["name"], "missing": missing,
                               "text": f"«{it['name']}» не працює: бракує — {', '.join(missing)}."})
            continue
        for a, v in it.get("attrs", {}).items():
            totals[a] = totals.get(a, 0) + v
        for tag in it.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        categories.add(it["category"])
        keys.add(it["key"])
    return {"working": working, "caps": caps, "totals": totals, "tag_counts": tag_counts,
            "categories": categories, "keys": keys, "nonworking": nonworking}


def eval_cond(cond, ctx):
    if "all" in cond:
        return all(eval_cond(c, ctx) for c in cond["all"])
    if "any" in cond:
        return any(eval_cond(c, ctx) for c in cond["any"])
    if "attr" in cond:
        v = ctx["totals"].get(cond["attr"], 0)
    elif "count_tag" in cond:
        v = ctx["tag_counts"].get(cond["count_tag"], 0)
    elif "has_cap" in cond:
        v = 1 if cond["has_cap"] in ctx["caps"] else 0
    else:
        raise ValueError(f"невідома умова {cond}")
    for op, fn in _OPS.items():
        if op in cond:
            return fn(v, cond[op])
    raise ValueError(f"умова без оператора {cond}")


def _base(c, theme, ctx, starting, spent, computed):
    t = c["type"]
    labels = theme["attr_labels"]
    if t == "sum":
        v = ctx["totals"].get(c["attr"], 0)
        label, unit = labels[c["attr"]]
        return 10 * min(1.0, v / c["target"]), f"{label}: {fmt(v)} {unit} з {fmt(c['target'])} потрібних."
    if t == "profiles":
        got = [labels[a][0].lower() for a in c["attrs"] if ctx["totals"].get(a, 0) >= c["threshold"]]
        txt = f"Виражені смаки: {', '.join(got) if got else 'жодного'} ({len(got)} з {c['target']})."
        return 10 * min(1.0, len(got) / c["target"]), txt
    if t == "categories":
        n = len(ctx["categories"])
        return 10 * min(1.0, n / c["target"]), f"Різних груп продуктів: {n} з {c['target']}."
    if t == "inverse_sum":
        v = ctx["totals"].get(c["attr"], 0)
        over = max(0.0, v - c["limit"])
        s = max(0.0, 10 - over * c["per_unit"])
        return s, f"Вага: {fmt(round(v, 2))} кг при ліміті {fmt(c['limit'])} кг."
    if t == "economy":
        rem = starting - spent
        return (10 * rem / starting if starting else 0.0), f"Залишок бюджету: ${rem} з ${starting}."
    if t == "avg":
        vals = [computed[x] for x in c["of"]]
        names = ", ".join(next(cc["title"].lower() for cc in theme["criteria"] if cc["id"] == x) for x in c["of"])
        return sum(vals) / len(vals), f"Резервна рубрика: середнє з критеріїв «{names}» + вдалі поєднання."
    raise ValueError(f"невідомий тип критерію {t}")


def score_player(theme, items, starting, spent, ai=None):
    """items — список предметів гравця (кожен з key/attrs/...); ai — {criterion_id: {...}} або None."""
    ctx = resolve(theme, items)
    ai = ai or {}
    computed, rows = {}, {}
    order = sorted(theme["criteria"], key=lambda c: c["type"] == "avg")
    for c in order:
        base, expl = _base(c, theme, ctx, starting, spent, computed)
        source, rationale, evidence = "formula", None, []
        if c.get("subjective"):
            if c["id"] in ai:
                base = float(ai[c["id"]]["numeric_score"])
                rationale = ai[c["id"]].get("rationale")
                evidence = ai[c["id"]].get("evidence_item_ids", [])
                source = "ai"
            else:
                source = "fallback"
        computed[c["id"]] = base
        rows[c["id"]] = {"id": c["id"], "title": c["title"], "weight": c["weight"], "priority": c["priority"],
                         "base": base, "synergy": 0.0, "penalty": 0.0, "explanation": expl, "source": source,
                         "rationale": rationale, "evidence_item_ids": evidence, "notes": []}

    syn_cap = theme.get("synergy_cap", DEFAULT_SYNERGY_CAP)
    active_syn, missing_syn = [], []
    item_names = {k: v["name"] for k, v in theme["item_index"].items()}
    for s in theme.get("synergies", []):
        owned = [k for k in s["all"] if k in ctx["keys"]]
        caps_ok = all(cap in ctx["caps"] for cap in s.get("caps", []))
        if len(owned) == len(s["all"]) and caps_ok:
            row = rows[s["criterion"]]
            add = min(s["bonus"], max(0.0, syn_cap - row["synergy"]))
            row["synergy"] += add
            row["notes"].append(f"+{fmt(add)} {s['text']}")
            active_syn.append({"id": s["id"], "criterion": s["criterion"], "bonus": add, "text": s["text"]})
        elif owned:
            lacking = [item_names[k] for k in s["all"] if k not in ctx["keys"]]
            lacking += [CAP_LABELS.get(c, c) for c in s.get("caps", []) if c not in ctx["caps"]]
            missing_syn.append({"id": s["id"], "text": s["text"], "lacking": lacking})

    penalties = []
    for p in theme.get("penalties", []):
        if eval_cond(p["cond"], ctx):
            row = rows[p["criterion"]]
            row["penalty"] += p["value"]
            row["notes"].append(f"−{fmt(p['value'])} {p['text']}")
            penalties.append({"id": p["id"], "criterion": p["criterion"], "value": p["value"], "text": p["text"]})

    criteria = []
    total_raw = 0.0
    for c in theme["criteria"]:
        row = rows[c["id"]]
        row["score"] = max(0.0, min(10.0, row["base"] + row["synergy"] - row["penalty"]))
        total_raw += row["score"] * row["weight"] / 100
        criteria.append(row)

    caps = [{"id": cp["id"], "cap": cp["cap"], "text": cp["text"]}
            for cp in theme.get("caps", []) if eval_cond(cp["cond"], ctx)]
    cap_value = min((cp["cap"] for cp in caps), default=None)
    total = min(total_raw, cap_value) if cap_value is not None else total_raw
    return {"criteria": criteria, "total_raw": total_raw, "total": total, "caps": caps,
            "cap_applied": cap_value is not None and total_raw > cap_value,
            "synergies": active_syn, "missing_synergies": missing_syn, "penalties": penalties,
            "nonworking": ctx["nonworking"], "totals": ctx["totals"]}


def rank_key(res):
    return (round(res["total"], 9),) + tuple(round(r["score"], 9) for r in sorted(res["criteria"], key=lambda r: r["priority"]))


def assign_places(entries):
    """entries: [(player_id, result)]. Повертає {player_id: place}; рівні — спільне місце (1, 1, 3)."""
    ordered = sorted(entries, key=lambda e: rank_key(e[1]), reverse=True)
    places, prev_key, prev_place = {}, None, 0
    for i, (pid, res) in enumerate(ordered):
        k = rank_key(res)
        place = prev_place if k == prev_key else i + 1
        places[pid] = place
        prev_key, prev_place = k, place
    return places, [pid for pid, _ in ordered]


def score_game(theme, snapshot, ai_by_player=None, judge_status="not_required"):
    ai_by_player = ai_by_player or {}
    results = {}
    for p in snapshot["players"]:
        results[p["id"]] = score_player(theme, p["items"], p["starting"], p["spent"], ai_by_player.get(p["id"]))
    places, order = assign_places(list(results.items()))
    pmap = {p["id"]: p for p in snapshot["players"]}

    ranking = []
    for pid in order:
        p, res = pmap[pid], results[pid]
        by_impact = sorted(res["criteria"], key=lambda r: r["score"] * r["weight"], reverse=True)
        by_loss = sorted(res["criteria"], key=lambda r: (10 - r["score"]) * r["weight"], reverse=True)
        ranking.append({
            "player_id": pid, "name": p["name"], "place": places[pid], "is_bot": p.get("is_bot", False),
            "total": res["total"], "total_display": round(res["total"], 1), "total_raw": res["total_raw"],
            "cap_applied": res["cap_applied"], "caps": res["caps"], "criteria": res["criteria"],
            "strengths": [r["title"] for r in by_impact[:2] if r["score"] >= 5],
            "weaknesses": [r["title"] for r in by_loss[:2] if r["score"] < 7],
            "synergies": res["synergies"], "missing_synergies": res["missing_synergies"],
            "penalties": res["penalties"], "nonworking": res["nonworking"],
            "inventory": [{"lot_id": it["lot_id"], "seq": it["seq"], "name": it["name"], "emoji": it["emoji"],
                           "visual_key": it["key"],
                           "quantity": it["quantity"], "unit": it["unit"], "price": it["price"]} for it in p["items"]],
            "spent": p["spent"], "remaining": p["starting"] - p["spent"], "starting": p["starting"],
        })
    return {"ranking": ranking, "nominations": nominations(theme, snapshot, results, places),
            "judge_status": judge_status,
            "criteria": [{"id": c["id"], "title": c["title"], "weight": c["weight"], "subjective": bool(c.get("subjective"))}
                         for c in theme["criteria"]],
            "lots": snapshot["lots"]}


def nominations(theme, snapshot, results, places):
    """Алгоритми номінацій за замовчуванням (ТЗ §9). Рівні значення — номінація всім."""
    players = snapshot["players"]
    out = []

    def award(nid, title, scored, fmt_value):
        scored = [s for s in scored if s[1] > 0]
        if not scored:
            return
        best = max(v for _, v, _ in scored)
        winners = [(pid, extra) for pid, v, extra in scored if abs(v - best) < 1e-9]
        names = {p["id"]: p["name"] for p in players}
        out.append({"id": nid, "title": title, "winners": [names[w] for w, _ in winners],
                    "player_ids": [w for w, _ in winners], "detail": fmt_value(best, winners[0][1])})

    n = len(players)
    top_half = sorted(places.values())[max(0, (n + 1) // 2 - 1)] if players else 0
    award("thrifty", "Найекономніший",
          [(p["id"], p["starting"] - p["spent"], None) for p in players if places[p["id"]] <= top_half],
          lambda v, _: f"залишок ${int(v)}, а місце — у верхній половині")

    best_buys = []
    for p in players:
        full = results[p["id"]]["total"]
        for it in p["items"]:
            rest = [x for x in p["items"] if x is not it]
            without = score_player(theme, rest, p["starting"], p["spent"])["total"]
            if it["price"]:
                best_buys.append((p["id"], (full - without) / it["price"], it["name"]))
    award("best_buy", "Найкраща покупка", best_buys,
          lambda v, extra: f"«{extra}»: +{fmt(round(v, 2))} бала за кожен $")

    priciest = [(p["id"], it["price"], it["name"]) for p in players for it in p["items"]]
    award("priciest", "Найдорожчий предмет", priciest, lambda v, extra: f"«{extra}» за ${int(v)}")

    award("synergy", "Найкраща синергія",
          [(p["id"], sum(s["bonus"] for s in results[p["id"]]["synergies"]), None) for p in players],
          lambda v, _: f"+{fmt(v)} бала від вдалих поєднань")

    risky = [(p["id"], it["price"] / p["starting"], it["name"]) for p in players for it in p["items"] if p["starting"]]
    award("risky", "Найризикованіша стратегія", risky,
          lambda v, extra: f"{round(v * 100)}% бюджету на «{extra}»")
    return out
