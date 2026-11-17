"""Фото предметів (visual_key → файл + авторство з public/img/credits.json).

Файл перечитується автоматично, якщо змінився (наприклад, після tools/fetch_images.py).
Якщо фото немає, клієнт показує емодзі-іконку (ТЗ §43: fallback — іконка категорії).
"""
import json
from pathlib import Path

CREDITS = Path(__file__).resolve().parent.parent / "public" / "img" / "credits.json"
_cache = {"mtime": None, "data": {}}


def credits():
    try:
        m = CREDITS.stat().st_mtime
    except OSError:
        return {}
    if m != _cache["mtime"]:
        try:
            _cache["data"] = json.loads(CREDITS.read_text(encoding="utf-8"))
            _cache["mtime"] = m
        except (ValueError, OSError):
            pass
    return _cache["data"]


def image(key):
    c = credits().get(key)
    if not c:
        return None
    return {"url": c["file"], "author": c.get("author", ""), "license": c.get("license", ""),
            "license_url": c.get("license_url", ""), "source": c.get("source", "")}
