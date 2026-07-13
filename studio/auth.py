#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auth thanh vien cho che do PORTAL (VPS van phong).

- users.json  : [{user, token_sha256, role: admin|member, created}]  (KHONG luu token tho)
- sessions.json: {sid: {user, role, created}}  (giu qua restart)
Che do local (khong env STUDIO_MODE=portal) khong dung file nay.
"""
import contextvars, hashlib, json, os, secrets, threading, time

import store

_LOCK = threading.RLock()
# User cua request hien tai (dict {user, role}) — middleware portal set.
_CUR = contextvars.ContextVar("auth_user", default=None)


def _users_path():
    return os.path.join(store.DATA, "users.json")


def _sessions_path():
    return os.path.join(store.DATA, "sessions.json")


def sha256(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def load_users():
    p = _users_path()
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


def _save_users(rows):
    p = _users_path()
    tmp = p + ".tmp"
    json.dump(rows, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def create_user(user, role="member", token=None):
    """Tao/cap lai user. Tra ve (record, token_tho). Token in ra 1 lan."""
    user = (user or "").strip()
    if not user:
        raise ValueError("thieu ten user")
    if role not in ("admin", "member"):
        role = "member"
    token = token or secrets.token_hex(16)
    with _LOCK:
        rows = load_users()
        rec = {"user": user, "token_sha256": sha256(token), "role": role,
               "created": int(time.time())}
        rows = [r for r in rows if r.get("user") != user] + [rec]
        _save_users(rows)
    return rec, token


def find_user(user):
    for r in load_users():
        if r.get("user") == user:
            return r
    return None


def verify(user, token):
    """Tra ve record neu dung, else None."""
    r = find_user(user)
    if r and r.get("token_sha256") == sha256(token):
        return r
    return None


# ---------- Sessions ----------
def _load_sessions():
    p = _sessions_path()
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _save_sessions(d):
    p = _sessions_path()
    tmp = p + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, p)


_SESSIONS = None


def _sessions():
    global _SESSIONS
    if _SESSIONS is None:
        _SESSIONS = _load_sessions()
    return _SESSIONS


def new_session(user, role):
    sid = secrets.token_hex(24)
    with _LOCK:
        s = _sessions()
        s[sid] = {"user": user, "role": role, "created": int(time.time())}
        _save_sessions(s)
    return sid


def get_session(sid):
    if not sid:
        return None
    return _sessions().get(sid)


def drop_session(sid):
    with _LOCK:
        s = _sessions()
        if sid in s:
            s.pop(sid, None)
            _save_sessions(s)


# ---------- Current request user ----------
def set_current(u):
    _CUR.set(u)


def current_user():
    return _CUR.get()


# ---------- Sync token (X-Sync-Token) ----------
def sync_ok(token):
    """Xac thuc token dong bo: khop env SYNC_TOKEN_HASH / SYNC_TOKEN (tho) / admin trong users.json."""
    if not token:
        return False
    h = sha256(token)
    env_hash = os.environ.get("SYNC_TOKEN_HASH")
    if env_hash and h == env_hash:
        return True
    env_raw = os.environ.get("SYNC_TOKEN")
    if env_raw and token == env_raw:
        return True
    for u in load_users():
        if u.get("role") == "admin" and u.get("token_sha256") == h:
            return True
    return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Tao user portal (in token 1 lan).")
    parser.add_argument("user")
    parser.add_argument("--role", default="member", choices=["admin", "member"])
    a = parser.parse_args()
    rec, tok = create_user(a.user, a.role)
    print(f"OK user='{rec['user']}' role={rec['role']}")
    print(f"TOKEN (luu lai, chi hien 1 lan): {tok}")
