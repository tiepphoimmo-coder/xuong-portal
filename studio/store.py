#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Studio store — luu KOL / San pham / Job vao JSON (don gian, ben, de sua tay).

3 file trong data/: kols.json, products.json, jobs.json.
Moi entity co id (uuid ngan). Anh ref luu duong dan tuyet doi tren dia.
"""
import contextvars, json, os, threading, time, uuid

SD = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SD)
# Toan bo du lieu studio gom vao 1 thu muc de tim: "Xuong KOL AI".
# Cho phep env DATA_HOME de chay instance rieng (VPS portal / test) — default giu nguyen.
DATA = os.environ.get("DATA_HOME") or os.path.join(WORKSPACE, "Xuong KOL AI")
os.makedirs(DATA, exist_ok=True)
_LOCK = threading.RLock()

# User dang dang nhap (portal) — middleware set moi request; None o che do local.
_CURRENT_USER = contextvars.ContextVar("studio_user", default=None)


def set_current_user(u):
    """u = ten user (str) hoac None."""
    _CURRENT_USER.set(u)


def current_user():
    return _CURRENT_USER.get()


def _origin():
    return os.environ.get("STUDIO_ORIGIN", "pc")


def _now():
    return time.time()


def _path(kind):
    return os.path.join(DATA, f"{kind}.json")


def _load(kind):
    p = _path(kind)
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


def _save(kind, rows):
    tmp = _path(kind) + ".tmp"
    json.dump(rows, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, _path(kind))


def list_all(kind):
    with _LOCK:
        return _load(kind)


def get(kind, id):
    with _LOCK:
        for r in _load(kind):
            if r.get("id") == id:
                return r
    return None


def upsert(kind, obj, stamp=True):
    """stamp=True: tu dong dong dau updated_at/origin (+ nguoi_tao khi tao moi).
    stamp=False: giu nguyen updated_at/origin trong obj (dung cho sync merge)."""
    with _LOCK:
        rows = _load(kind)
        if not obj.get("id"):
            obj["id"] = uuid.uuid4().hex[:8]
            obj["created"] = int(time.time())
            if not obj.get("nguoi_tao"):
                obj["nguoi_tao"] = current_user() or "admin-pc"
            if stamp:
                obj["updated_at"] = _now()
                obj["origin"] = _origin()
            rows.append(obj)
        else:
            if "created" not in obj:
                obj["created"] = int(time.time())
            if stamp:
                obj["updated_at"] = _now()
                obj["origin"] = _origin()
            rows = [obj if r.get("id") == obj["id"] else r for r in rows]
            if obj["id"] not in [r.get("id") for r in rows]:
                rows.append(obj)
        _save(kind, rows)
        return obj


def patch(kind, id, _stamp=True, **fields):
    with _LOCK:
        rows = _load(kind)
        for r in rows:
            if r.get("id") == id:
                r.update(fields)
                if _stamp:
                    r["updated_at"] = _now()
                    r["origin"] = _origin()
                _save(kind, rows)
                return r
    return None


def delete(kind, id):
    with _LOCK:
        rows = [r for r in _load(kind) if r.get("id") != id]
        _save(kind, rows)
