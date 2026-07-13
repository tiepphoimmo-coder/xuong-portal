#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auth thanh vien cho che do PORTAL (VPS van phong).

- users.json  : [{user, token_sha256, role: admin|member, created}]  (KHONG luu token tho)
- sessions.json: {sid: {user, role, created}}  (giu qua restart)
Che do local (khong env STUDIO_MODE=portal) khong dung file nay.
"""
import contextvars, hashlib, json, os, secrets, string, threading, time

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


# ---------- Mat khau (pbkdf2_hmac sha256, 120000 vong) ----------
_PBKDF2_ROUNDS = 120000


def _hash_password(password, salt):
    """salt = hex string (secrets.token_hex(16)). Tra ve hex digest."""
    return hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS
    ).hex()


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


def create_user(user, role="member", token=None, password=None,
                status="active", display_name=None):
    """Tao/cap lai user. Tra ve (record, token_tho|None).
    - password co -> luu pass_salt/pass_hash, KHONG token (token_tho=None).
    - khong password -> sinh/dung token (tuong thich CLI cu), in token 1 lan.
    status: pending|active|disabled. display_name mac dinh = user."""
    user = (user or "").strip()
    if not user:
        raise ValueError("thieu ten user")
    if role not in ("admin", "member"):
        role = "member"
    if status not in ("pending", "active", "disabled"):
        status = "active"
    rec = {"user": user, "role": role, "status": status,
           "display_name": (display_name or user), "created": int(time.time())}
    tok = None
    if password:
        salt = secrets.token_hex(16)
        rec["pass_salt"] = salt
        rec["pass_hash"] = _hash_password(password, salt)
    else:
        tok = token or secrets.token_hex(16)
        rec["token_sha256"] = sha256(tok)
    with _LOCK:
        rows = load_users()
        rows = [r for r in rows if r.get("user") != user] + [rec]
        _save_users(rows)
    return rec, tok


def find_user(user):
    for r in load_users():
        if r.get("user") == user:
            return r
    return None


def bootstrap_admin():
    """Seed admin tu env ADMIN_USER/ADMIN_PASSWORD khi khoi dong.
    - Chi tao khi user do CHUA ton tai (idempotent, khong ghi de mat khau da doi).
    - Neu thieu 2 env -> bo qua (khong tao gi)."""
    u = (os.environ.get("ADMIN_USER") or "").strip()
    p = os.environ.get("ADMIN_PASSWORD") or ""
    if not u or not p:
        return None
    if find_user(u):
        return None  # da co -> ton trong mat khau user tu doi
    create_user(u, role="admin", password=p, status="active")
    return u


def check_secret(user, secret):
    """True neu secret khop mat khau HOAC token (BO QUA status). Dung cho verify + doi mat khau."""
    r = find_user(user)
    if not r:
        return False
    ph, salt = r.get("pass_hash"), r.get("pass_salt")
    if ph and salt and _hash_password(secret, salt) == ph:
        return True
    if r.get("token_sha256") and r.get("token_sha256") == sha256(secret):
        return True
    return False


def verify(user, secret):
    """Tra ve (record, error). record != None khi dang nhap OK.
    - sai user/mat khau -> (None, None)
    - dung nhung chua duyet -> (None, 'Tài khoản đang chờ duyệt')
    - dung nhung bi khoa   -> (None, 'Tài khoản bị khoá')
    Tuong thich: user cu chi co token_sha256 va thieu status (coi la active)."""
    if not check_secret(user, secret):
        return None, None
    r = find_user(user)
    st = r.get("status", "active")
    if st == "pending":
        return None, "Tài khoản đang chờ duyệt"
    if st == "disabled":
        return None, "Tài khoản bị khoá"
    return r, None


# ---------- Cap nhat ho so / quan tri ----------
def _update(user, **fields):
    with _LOCK:
        rows = load_users()
        hit = None
        for r in rows:
            if r.get("user") == user:
                r.update(fields)
                hit = r
        if hit is not None:
            _save_users(rows)
        return hit


def set_display_name(user, name):
    return _update(user, display_name=(name or user))


def set_password(user, new_password):
    salt = secrets.token_hex(16)
    return _update(user, pass_salt=salt, pass_hash=_hash_password(new_password, salt))


def set_status(user, status):
    if status not in ("pending", "active", "disabled"):
        raise ValueError("status khong hop le")
    return _update(user, status=status)


def set_role(user, role):
    if role not in ("admin", "member"):
        raise ValueError("role khong hop le")
    return _update(user, role=role)


def reset_password(user):
    """Sinh mat khau tam 10 ky tu, dat cho user, tra ve mat khau tho (1 lan)."""
    alpha = string.ascii_letters + string.digits
    tmp = "".join(secrets.choice(alpha) for _ in range(10))
    set_password(user, tmp)
    return tmp


def delete_user(user):
    with _LOCK:
        rows = load_users()
        new = [r for r in rows if r.get("user") != user]
        if len(new) != len(rows):
            _save_users(new)
            return True
        return False


def public_record(r):
    """Ban ghi user KHONG chua hash/salt/token (an toan tra ve UI)."""
    r = dict(r)
    r.setdefault("status", "active")
    r.setdefault("display_name", r.get("user"))
    r["has_password"] = bool(r.get("pass_hash"))
    for k in ("token_sha256", "pass_hash", "pass_salt"):
        r.pop(k, None)
    return r


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
