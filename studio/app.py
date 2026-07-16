#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Studio backend — QUAN LY KOL + San pham (co MA, thong tin, sua, import) + soan BRIEF.

Du lieu gom vao thu muc "Xuong KOL AI" (store.DATA). Model: Claude-trong-vong-lap.
Chay: <python co fastapi> app.py   (port 8090)
"""
import json, mimetypes, os, re, subprocess, sys, threading, time, unicodedata, urllib.request, urllib.parse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse

import store
import auth
import producer  # MÁY SẢN XUẤT (deterministic, không LLM)

SD = os.path.dirname(os.path.abspath(__file__))
DATA_HOME = store.DATA
UPLOAD_DIR = os.path.join(DATA_HOME, "refs")
PROJECTS_DIR = os.path.join(DATA_HOME, "Du An")
AVATAR_DIR = os.path.join(DATA_HOME, "avatars")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(AVATAR_DIR, exist_ok=True)

app = FastAPI(title="Xuong KOL Studio")


# ==================== DICH PATH ANH (tang sync) ====================
# Store LUON luu path TUYET DOI (pipeline san xuat doc path tuyet doi).
# Chi o TANG SYNC moi dich: pull -> "refs/<basename>" (tuong doi, forward slash);
# push -> tra ve path tuyet doi cua DATA_HOME/refs. Ref la de chuyen file 2 chieu.
_REFS_ROOT = os.path.abspath(UPLOAD_DIR)


def _ref_to_rel(p):
    """Path anh -> 'refs/<basename>' NEU nam duoi DATA_HOME/refs; else giu nguyen."""
    if not p or not isinstance(p, str):
        return p
    try:
        ap = os.path.abspath(p.replace("\\", "/"))
    except Exception:
        return p
    root = _REFS_ROOT.replace("\\", "/").rstrip("/")
    apn = ap.replace("\\", "/")
    if apn.lower().startswith(root.lower() + "/"):
        return "refs/" + os.path.basename(apn)
    return p


def _ref_to_abs(r):
    """'refs/<name>' -> path tuyet doi DATA_HOME/refs/<name>; else giu nguyen."""
    if not r or not isinstance(r, str):
        return r
    rr = r.replace("\\", "/")
    if rr.startswith("refs/"):
        name = os.path.basename(rr)
        if name and name not in (".", ".."):
            return os.path.join(UPLOAD_DIR, name)
    return r


def _map_refs(rec, fn):
    """Tra ve BAN COPY cua rec voi refs (va outfits[].refs) da map qua fn. KHONG mutate rec goc."""
    out = dict(rec)
    if isinstance(out.get("refs"), list):
        out["refs"] = [fn(x) for x in out["refs"]]
    outfits = out.get("outfits")
    if isinstance(outfits, list):
        new_outfits = []
        for o in outfits:
            if isinstance(o, dict) and isinstance(o.get("refs"), list):
                o = dict(o)
                o["refs"] = [fn(x) for x in o["refs"]]
            new_outfits.append(o)
        out["outfits"] = new_outfits
    return out


def _serialize_record(rec):
    return _map_refs(rec, _ref_to_rel)


def _materialize_record(rec):
    return _map_refs(rec, _ref_to_abs)


def _safe_ref_path(rel):
    """Chan path traversal: rel PHAI bat dau 'refs/', basename sach, resolve trong DATA_HOME/refs.
    Tra ve path tuyet doi hop le hoac None."""
    if not rel or not isinstance(rel, str):
        return None
    rr = rel.replace("\\", "/")
    if not rr.startswith("refs/"):
        return None
    name = rr[len("refs/"):]
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    if os.path.basename(name) != name:
        return None
    dest = os.path.abspath(os.path.join(UPLOAD_DIR, name))
    if not dest.replace("\\", "/").lower().startswith(_REFS_ROOT.replace("\\", "/").lower() + "/"):
        return None
    return dest


# ==================== VAN PHONG (PORTAL) — auth + phan quyen ====================
def _portal():
    return os.environ.get("STUDIO_MODE") == "portal"


LOGIN_HTML = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đăng nhập · Xưởng KOL Văn phòng</title>
<style>
:root{--bg:#F1F2F4;--card:#FFFFFF;--brand:#0C66E4;--bd:#DCDFE4;--tx:#172B4D;--mut:#626F86;--ok:#1F845A}
*{box-sizing:border-box}body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--tx);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.box{width:348px;max-width:calc(100vw - 40px);background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:28px 26px;
box-shadow:0 18px 50px rgba(9,30,66,.15)}
.mk{width:44px;height:44px;border-radius:12px;background:var(--brand);
display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;margin-bottom:14px}
h1{font-size:18px;margin:0 0 3px}p.sub{margin:0 0 16px;color:var(--mut);font-size:13px}
.tabs{display:flex;gap:6px;margin-bottom:6px;background:#F1F2F4;padding:4px;border-radius:10px}
.tabs button{flex:1;height:34px;margin:0;border:0;border-radius:7px;background:transparent;color:var(--mut);
font-size:13.5px;font-weight:600;cursor:pointer}
.tabs button.on{background:var(--brand);color:#fff}
label{display:block;font-size:12px;color:var(--mut);margin:12px 0 5px}
input{width:100%;height:44px;padding:0 12px;border-radius:9px;border:1px solid var(--bd);
background:#FFFFFF;color:var(--tx);font-size:16px}
button.act{width:100%;height:46px;margin-top:18px;border:0;border-radius:9px;background:var(--brand);
color:#fff;font-size:16px;font-weight:600;cursor:pointer}
button.act:hover{filter:brightness(1.08)}
.err{color:#C9372C;font-size:13px;margin-top:12px;min-height:16px}
.ok{color:var(--ok);font-size:13px;margin-top:12px;min-height:16px}
.badge{display:inline-block;font-size:10px;letter-spacing:1px;color:var(--brand);border:1px solid var(--brand);
border-radius:6px;padding:2px 7px;margin-bottom:12px;text-transform:uppercase}
form{display:none}form.on{display:block}
</style></head><body>
<div class="box">
<div class="mk">XK</div>
<div class="badge">Văn phòng</div>
<h1>Xưởng KOL Văn phòng</h1><p class="sub">Đăng nhập hoặc đăng ký tài khoản thành viên.</p>
<div class="tabs"><button id="tab-login" class="on" onclick="showTab('login')">Đăng nhập</button>
<button id="tab-reg" onclick="showTab('reg')">Đăng ký</button></div>

<form id="f-login" class="on" onsubmit="return dologin(event)">
<label>Tên đăng nhập</label><input id="u" autocomplete="username">
<label>Mật khẩu</label><input id="t" type="password" autocomplete="current-password" placeholder="Mật khẩu (hoặc token cũ)">
<button type="submit" class="act">Đăng nhập</button>
<div class="err" id="e"></div>
</form>

<form id="f-reg" onsubmit="return doreg(event)">
<label>Tên đăng nhập</label><input id="ru" autocomplete="username" placeholder="3-24 ký tự: a-z 0-9 - _">
<label>Tên hiển thị</label><input id="rn" placeholder="Vd: Nguyễn Văn An">
<label>Mật khẩu</label><input id="rp" type="password" autocomplete="new-password" placeholder="Tối thiểu 6 ký tự">
<label>Nhắc lại mật khẩu</label><input id="rp2" type="password" autocomplete="new-password">
<button type="submit" class="act">Đăng ký</button>
<div class="err" id="re"></div><div class="ok" id="ro"></div>
</form>
</div>
<script>
function showTab(t){
 document.getElementById('tab-login').classList.toggle('on',t==='login');
 document.getElementById('tab-reg').classList.toggle('on',t==='reg');
 document.getElementById('f-login').classList.toggle('on',t==='login');
 document.getElementById('f-reg').classList.toggle('on',t==='reg');}
async function dologin(ev){ev.preventDefault();
 const u=document.getElementById('u').value.trim(),t=document.getElementById('t').value.trim();
 const e=document.getElementById('e');e.textContent='';
 try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({user:u,password:t})});
  if(r.ok){location.href='/';}else{const d=await r.json().catch(()=>({}));e.textContent=d.detail||'Sai tên hoặc mật khẩu';}}
 catch(err){e.textContent='Lỗi kết nối';}
 return false;}
async function doreg(ev){ev.preventDefault();
 const u=document.getElementById('ru').value.trim(),n=document.getElementById('rn').value.trim();
 const p=document.getElementById('rp').value,p2=document.getElementById('rp2').value;
 const e=document.getElementById('re'),o=document.getElementById('ro');e.textContent='';o.textContent='';
 if(p!==p2){e.textContent='Hai ô mật khẩu chưa khớp';return false;}
 try{const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({user:u,password:p,display_name:n})});
  const d=await r.json().catch(()=>({}));
  if(r.ok){o.textContent='✅ Đã gửi — chờ admin duyệt';
    document.getElementById('rp').value='';document.getElementById('rp2').value='';}
  else{e.textContent=d.detail||'Đăng ký không thành công';}}
 catch(err){e.textContent='Lỗi kết nối';}
 return false;}
</script></body></html>"""


def _cur():
    return auth.current_user()  # dict {user, role} hoac None


def _is_member():
    u = _cur()
    return bool(_portal() and u and u.get("role") != "admin")


def _own_guard(kind, id):
    """Portal + member: chi duoc dung record MINH tao."""
    if not _is_member():
        return
    rec = store.get(kind, id)
    if rec and rec.get("nguoi_tao") != _cur().get("user"):
        raise HTTPException(403, "khong phai record cua ban")


def _own_rows(rows):
    """Loc danh sach USER-FACING: (1) an record xoa mem (tombstone van nam trong store de sync lan sang may kia);
    (2) portal member chi thay record MINH tao; admin thay tat ca."""
    rows = [r for r in rows if not r.get("deleted")]
    if not _is_member():
        return rows
    me = _cur().get("user")
    return [r for r in rows if r.get("nguoi_tao") == me]


def _portal_blocked(method, path):
    if path.startswith("/api/sync/"):
        return False
    if method == "POST" and path == "/api/commands":
        return True
    if method == "PATCH" and path.startswith("/api/commands/"):
        return True
    if path.startswith("/api/render"):
        return True
    if path.startswith("/api/engines"):
        return True
    if path.startswith("/api/flow-accounts"):
        return True
    if path.startswith("/api/voices"):
        return True
    if method in ("POST", "PATCH", "DELETE") and path.startswith("/api/staff"):
        return True
    if path.startswith("/api/products/") and path.endswith("/nap-video"):
        return True
    if method in ("POST", "PATCH", "DELETE") and path.startswith("/api/projects"):
        return True
    if path.endswith("/storyboard_prompt") or path.endswith("/scene_upload"):
        return True
    if path.endswith("/publish_media"):   # xuat ban Media = tao command san xuat -> PC-only
        return True
    return False


_PUBLIC_API = {"/api/login", "/api/logout", "/api/config", "/api/register"}


@app.middleware("http")
async def _portal_gate(request: Request, call_next):
    path = request.url.path
    sid = request.cookies.get("sid")
    sess = auth.get_session(sid) if sid else None
    # dong dau current-user cho ca 2 che do (local: sess=None -> "admin-pc")
    auth.set_current(sess)
    store.set_current_user(sess.get("user") if sess else None)
    if not _portal():
        return await call_next(request)
    # ---- CHE DO PORTAL ----
    if path.startswith("/api/sync/"):
        return await call_next(request)  # tu xac thuc bang X-Sync-Token
    if path in _PUBLIC_API:
        return await call_next(request)
    if sess is None:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "chua dang nhap"}, status_code=401)
        return HTMLResponse(LOGIN_HTML)
    if _portal_blocked(request.method, path):
        return JSONResponse({"detail": "Che do Van phong — thao tac san xuat bi khoa"}, status_code=403)
    return await call_next(request)


@app.get("/api/sync-status")
def api_sync_status():
    """Trang thai sync agent (doc nhip tim). alive=True neu dap nhip trong 90s gan day."""
    p = os.path.join(DATA_HOME, "sync_heartbeat.json")
    try:
        hb = json.load(open(p, encoding="utf-8"))
        ago = time.time() - float(hb.get("t") or 0)
        return {"alive": ago < 90, "ago": int(ago), "portal": hb.get("portal")}
    except Exception:
        return {"alive": False, "ago": None, "portal": None}


@app.get("/api/config")
def api_config():
    u = _cur()
    return {"mode": "portal" if _portal() else "local",
            "origin": os.environ.get("STUDIO_ORIGIN", "pc"),
            "user": u.get("user") if u else None,
            "role": u.get("role") if u else None}


@app.post("/api/register")
def api_register(body: dict):
    """Dang ky thanh vien moi (chi PORTAL). Tao user status=pending, role=member. KHONG tu login."""
    if not _portal():
        raise HTTPException(403, "chi che do Van phong")
    user = (body.get("user") or "").strip().lower()
    pw = body.get("password") or ""
    dn = (body.get("display_name") or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{3,24}", user):
        raise HTTPException(400, "Tên đăng nhập 3-24 ký tự, chỉ gồm a-z 0-9 - _")
    if len(pw) < 6:
        raise HTTPException(400, "Mật khẩu tối thiểu 6 ký tự")
    if auth.find_user(user):
        raise HTTPException(409, "Tên đăng nhập đã tồn tại")
    auth.create_user(user, role="member", password=pw, status="pending", display_name=dn or user)
    return {"ok": True, "user": user, "status": "pending"}


@app.post("/api/login")
def api_login(body: dict, response: Response):
    secret = (body.get("password") or body.get("token") or "").strip()
    rec, err = auth.verify((body.get("user") or "").strip(), secret)
    if not rec:
        raise HTTPException(401, err or "Sai tên hoặc mật khẩu")
    sid = auth.new_session(rec["user"], rec["role"])
    response.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return {"ok": True, "user": rec["user"], "role": rec["role"]}


@app.get("/api/me")
def api_me():
    u = _cur()
    if not u:
        raise HTTPException(401, "chua dang nhap")
    r = auth.find_user(u["user"]) or {}
    return {"user": u["user"], "role": u["role"],
            "display_name": r.get("display_name") or u["user"],
            "avatar": _avatar_url(u["user"]),
            "has_password": bool(r.get("pass_hash"))}


@app.patch("/api/me")
def api_me_patch(body: dict):
    """Doi ten hien thi va/hoac mat khau cua chinh minh.
    Doi mat khau: neu da co pass_hash -> phai dung old_password; neu chua (login token) -> cho dat moi khong can old."""
    u = _cur()
    if not u:
        raise HTTPException(401, "chua dang nhap")
    user = u["user"]
    rec = auth.find_user(user)
    if not rec:
        raise HTTPException(404, "no user")
    if "display_name" in body:
        auth.set_display_name(user, (body.get("display_name") or "").strip() or user)
    npw = (body.get("new_password") or "").strip()
    if npw:
        if len(npw) < 6:
            raise HTTPException(400, "Mật khẩu mới tối thiểu 6 ký tự")
        if rec.get("pass_hash"):
            old = (body.get("old_password") or "").strip()
            if not auth.check_secret(user, old):
                raise HTTPException(400, "Mật khẩu hiện tại không đúng")
        auth.set_password(user, npw)
    r = auth.find_user(user)
    return {"ok": True, "display_name": r.get("display_name") or user,
            "avatar": _avatar_url(user), "has_password": bool(r.get("pass_hash"))}


# ---------- Avatar ----------
_AV_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_AV_BY_CT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp"}
_AV_BY_EXT = {".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg", ".webp": ".webp"}


def _valid_user(u):
    return bool(u) and re.fullmatch(r"[a-z0-9_-]{1,40}", u) is not None


def _avatar_files(user):
    if not _valid_user(user):
        return []
    return [os.path.join(AVATAR_DIR, user + e) for e in _AV_EXTS
            if os.path.isfile(os.path.join(AVATAR_DIR, user + e))]


def _avatar_url(user):
    return ("/api/avatar/" + user) if _avatar_files(user) else None


@app.post("/api/me/avatar")
async def api_me_avatar(file: UploadFile = File(...)):
    u = _cur()
    if not u:
        raise HTTPException(401, "chua dang nhap")
    user = u["user"]
    if not _valid_user(user):
        raise HTTPException(400, "user khong hop le")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "Ảnh tối đa 2MB")
    ext = _AV_BY_CT.get((file.content_type or "").lower()) \
        or _AV_BY_EXT.get(os.path.splitext(file.filename or "")[1].lower())
    if not ext:
        raise HTTPException(400, "Chỉ nhận ảnh PNG, JPG hoặc WEBP")
    for old in _avatar_files(user):   # xoa ext cu khac
        try:
            os.remove(old)
        except Exception:
            pass
    with open(os.path.join(AVATAR_DIR, user + ext), "wb") as fh:
        fh.write(data)
    return {"ok": True, "avatar": _avatar_url(user)}


@app.get("/api/avatar/{user}")
def api_avatar(user: str):
    # Portal: middleware da chan neu chua dang nhap. Local: mo.
    files = _avatar_files(user)
    if not files:
        raise HTTPException(404, "no avatar")
    p = files[0]
    return FileResponse(p, media_type=mimetypes.guess_type(p)[0] or "image/png")


# ---------- QUAN TRI THANH VIEN (admin, portal) ----------
def _require_admin():
    if not _portal():
        raise HTTPException(403, "chi che do Van phong")
    u = _cur()
    if not u or u.get("role") != "admin":
        raise HTTPException(403, "chi admin duoc phep")
    return u


@app.get("/api/users")
def api_users():
    _require_admin()
    rows = sorted(auth.load_users(), key=lambda r: r.get("created", 0))
    return [{**auth.public_record(r), "avatar": _avatar_url(r.get("user"))} for r in rows]


@app.patch("/api/users/{user}")
def api_users_patch(user: str, body: dict):
    _require_admin()
    if not auth.find_user(user):
        raise HTTPException(404, "no user")
    me = _cur() or {}
    if user == me.get("user") and (body.get("status") in ("disabled", "pending") or body.get("role") == "member"):
        raise HTTPException(400, "Không thể tự khoá / tự hạ quyền chính mình")
    out = {"ok": True, "user": user}
    if "status" in body:
        st = body.get("status")
        if st not in ("pending", "active", "disabled"):
            raise HTTPException(400, "status = pending|active|disabled")
        auth.set_status(user, st)
        out["status"] = st
    if "role" in body:
        rl = body.get("role")
        if rl not in ("admin", "member"):
            raise HTTPException(400, "role = admin|member")
        auth.set_role(user, rl)
        out["role"] = rl
    if body.get("reset_password"):
        out["temp_password"] = auth.reset_password(user)
    return out


@app.delete("/api/users/{user}")
def api_users_delete(user: str):
    me = _require_admin()
    if user == me.get("user"):
        raise HTTPException(400, "không thể tự xoá chính mình")
    if not auth.find_user(user):
        raise HTTPException(404, "no user")
    auth.delete_user(user)
    for f in _avatar_files(user):
        try:
            os.remove(f)
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/logout")
def api_logout(request: Request, response: Response):
    sid = request.cookies.get("sid")
    if sid:
        auth.drop_session(sid)
    response.delete_cookie("sid")
    return {"ok": True}


def _ascii_vn(s):
    """Bo dau tieng Viet -> ASCII de sinh ma slug sach (ke 3 tang, me be...)."""
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", _ascii_vn(s).lower().strip()).strip("-")
    return s or "x"


def _uniq_code(kind, name, base=None, exclude_id=None):
    code = _slug(base or name)
    if len(code) > 22:                       # cat gon o ranh gioi tu, tranh ma qua dai
        code = code[:22].rsplit("-", 1)[0] or code[:22]
    code = code.strip("-") or "x"
    existing = {r.get("code") for r in store.list_all(kind) if r.get("id") != exclude_id}
    if code not in existing:
        return code
    i = 2
    while f"{code}-{i}" in existing:
        i += 1
    return f"{code}-{i}"


def _merge_refs(cur, drop_refs, new):
    """Ket qua refs sau khi go (drop_refs = JSON list duong dan) + them anh moi.
    KHONG xoa file tren dia (ref co the tro toi anh nguon dung chung). Tra None neu khong doi."""
    kept = list(cur.get("refs") or [])
    changed = False
    if drop_refs:
        try:
            drop = set(json.loads(drop_refs))
        except Exception:
            drop = set()
        if drop:
            kept = [r for r in kept if r not in drop]
            changed = True
    if new:
        kept += new
        changed = True
    return kept if changed else None


async def _save_uploads(files, tag):
    out = []
    for f in files or []:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower() or ".png"
        dest = os.path.join(UPLOAD_DIR, f"{tag}_{int(time.time()*1000)}_{len(out)}{ext}")
        with open(dest, "wb") as fh:
            fh.write(await f.read())
        out.append(dest)
    return out


# ---------- KOL ----------
# ---------- KENH (Facebook / TikTok) — tang quan ly tren KOL + Du an ----------
@app.get("/api/channels")
def channels():
    return sorted(_own_rows(store.list_all("channels")), key=lambda c: c.get("created", 0))


@app.post("/api/channels")
def add_channel(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "thieu ten kenh")
    plat = (body.get("platform") or "facebook").strip().lower()
    if plat not in ("facebook", "tiktok", "youtube", "khac"):
        plat = "facebook"
    rec = {
        "name": name, "platform": plat,
        "code": _uniq_code("channels", name, (body.get("code") or "").strip()),
        "url": (body.get("url") or "").strip(), "note": (body.get("note") or "").strip()}
    # Liên kết trang KÊNH trên Notion (tuỳ chọn) — chỉ ghi khi có
    npid = (body.get("notion_page_id") or "").strip()
    npname = (body.get("notion_page_name") or "").strip()
    if npid:
        rec["notion_page_id"] = npid
    if npname:
        rec["notion_page_name"] = npname
    return store.upsert("channels", rec)


@app.patch("/api/channels/{id}")
def edit_channel(id: str, body: dict):
    if not store.get("channels", id):
        raise HTTPException(404, "no channel")
    up = {k: v for k, v in body.items()
          if k in ("name", "platform", "url", "note", "notion_page_id", "notion_page_name")}
    # strip liên kết Notion
    for k in ("notion_page_id", "notion_page_name"):
        if k in up:
            up[k] = (up[k] or "").strip()
    if body.get("code"):
        up["code"] = body["code"].strip()
    return store.patch("channels", id, **up)


# ---------- KÊNH trên NOTION (cache + đồng bộ qua agent worker) ----------
NOTION_KENH_FILE = os.path.join(DATA_HOME, "notion_kenh.json")
NOTION_KENH_SOURCE = "collection://2642f71c-1d3b-8211-82a3-8721615a1055"


@app.get("/api/notion/kenh")
def notion_kenh():
    """Đọc cache notion_kenh.json (không có -> rỗng)."""
    if not os.path.exists(NOTION_KENH_FILE):
        return {"synced_at": 0, "items": []}
    try:
        return json.load(open(NOTION_KENH_FILE, encoding="utf-8"))
    except Exception:
        return {"synced_at": 0, "items": []}


@app.post("/api/notion/kenh/sync")
def notion_kenh_sync():
    """Enqueue lệnh cho agent worker (có MCP Notion) đồng bộ bảng KÊNH -> ghi đè cache."""
    text = (
        f"Dùng MCP Notion query data source {NOTION_KENH_SOURCE} "
        "(bảng KÊNH trong 'Hệ Thống Kênh Affilate 2026'), lấy TOÀN BỘ page với các trường: "
        "id, tên (cột title 'Kênh'), Nền Tảng, NGÁCH, Trạng Thái, url. "
        f"GHI ĐÈ file '{NOTION_KENH_FILE}' theo schema "
        "{synced_at: <epoch giây hiện tại, số nguyên>, source: '" + NOTION_KENH_SOURCE + "', "
        "items: [{id, name, platform, ngach, trang_thai, url}]}, encoding UTF-8. "
        "Nếu KHÔNG có MCP Notion trong phiên thì trả lời 'THIẾU MCP Notion' và DỪNG. "
        "Chạy đồng bộ ĐỒNG BỘ trong phiên, xong mới trả lời."
    )
    cmd = store.upsert("commands", {"text": text, "status": "pending", "response": None,
                                    "engine": "claude", "staff": "san-xuat-video-gia-dung",
                                    "label": "🔄 Đồng bộ kênh Notion"})
    return {"ok": True, "command_id": cmd["id"]}


@app.get("/api/kols")
def kols():
    return _own_rows(store.list_all("kols"))


@app.post("/api/kols")
async def add_kol(name: str = Form(...), code: str = Form(""), voice: str = Form(""),
                  identity: str = Form(""), flow_project_id: str = Form(""), flow_board_id: str = Form(""),
                  voice_id: str = Form(""), group: str = Form(""), channel: str = Form(""),
                  refs: list[UploadFile] = File(default=[])):
    return store.upsert("kols", {"name": name, "code": _uniq_code("kols", name, code),
                                 "voice": voice, "identity": identity, "voice_id": voice_id, "group": group,
                                 "channel": channel,
                                 "flow_project_id": flow_project_id, "flow_board_id": flow_board_id,
                                 "refs": await _save_uploads(refs, "kol")})


@app.patch("/api/kols/{id}")
async def edit_kol(id: str, name: str = Form(None), code: str = Form(None), voice: str = Form(None),
                   identity: str = Form(None), flow_project_id: str = Form(None), flow_board_id: str = Form(None),
                   voice_id: str = Form(None), group: str = Form(None), channel: str = Form(None),
                   notion_db: str = Form(None),  # bảng nội dung Notion của KOL (database id/link) — auto-publish
                   drop_refs: str = Form(None), refs: list[UploadFile] = File(default=[])):
    cur = store.get("kols", id)
    if not cur:
        raise HTTPException(404, "no kol")
    _own_guard("kols", id)
    up = {k: v for k, v in {"name": name, "voice": voice, "identity": identity, "voice_id": voice_id,
                            "group": group, "channel": channel, "notion_db": notion_db,
                            "flow_project_id": flow_project_id, "flow_board_id": flow_board_id}.items()
          if v is not None}
    if code:
        up["code"] = code
    merged = _merge_refs(cur, drop_refs, await _save_uploads(refs, "kol"))
    if merged is not None:
        up["refs"] = merged
    return store.patch("kols", id, **up)


# ---------- GIONG NOI FLOW (proxy sang flowboard :8200) ----------
FLOW_API = "http://127.0.0.1:8200"
VOICE_NOTES = os.path.join(DATA_HOME, "voice_notes.json")

# Dich mo ta giong Gemini (EN) -> tieng Viet theo tung token
_VI_TOK = {
    "male": "Nam", "female": "Nữ", "neutral": "Trung tính",
    "soft": "dịu", "friendly": "thân thiện", "gravelly": "khàn", "easy-going": "thoải mái",
    "firm": "dứt khoát", "breezy": "nhẹ nhàng", "bright": "tươi sáng", "informative": "rõ ràng",
    "smooth": "mượt mà", "breathy": "thì thầm", "clear": "trong trẻo", "excitable": "phấn khích",
    "mature": "trưởng thành", "upbeat": "sôi nổi", "youthful": "trẻ trung", "forward": "hướng ngoại",
    "lively": "sống động", "knowledgeable": "am hiểu", "even": "đều đặn", "casual": "tự nhiên",
    "warm": "ấm", "gentle": "nhẹ nhàng",
    "high pitch": "tông cao", "mid pitch": "tông trung", "low pitch": "tông trầm",
    "lower pitch": "tông trầm", "mid-low pitch": "tông trầm vừa", "mid-high pitch": "tông cao vừa",
    "younger pitch": "tông trẻ",
}


def _desc_vi(desc):
    parts = [p.strip() for p in (desc or "").split(",") if p.strip()]
    return ", ".join(_VI_TOK.get(p.lower(), p) for p in parts)


def _load_notes():
    try:
        return json.load(open(VOICE_NOTES, encoding="utf-8"))
    except Exception:
        return {}


@app.get("/api/voices")
def voices(project_id: str = ""):
    """Danh sach giong Flow: 30 builtin (Gemini) + custom cloned scope theo project_id KOL.
    Them `desc_vi` = ghi chu tieng Viet user (neu co) HOAC dich tu mo ta EN.
    Proxy sang flowboard /api/voices/flow. flowboard tat -> tra {ok:False}."""
    try:
        with urllib.request.urlopen(FLOW_API + "/api/voices/flow", timeout=8) as r:
            allv = json.load(r)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "voices": []}
    notes = _load_notes()
    out = []
    for v in allv:
        if v.get("source") == "custom" and project_id and v.get("project_id") not in (project_id, None):
            continue  # custom cua project khac -> bo
        note = (notes.get(v["id"]) or "").strip()
        v["desc_vi"] = note or _desc_vi(v.get("description")) or ("Giọng clone của bạn" if v.get("source") == "custom" else "")
        v["note"] = note
        out.append(v)
    return {"ok": True, "voices": out}


@app.post("/api/voices/note")
def set_voice_note(body: dict):
    """Luu mo ta tieng Viet cho 1 giong (voice_id) -> voice_notes.json."""
    vid = (body.get("voice_id") or "").strip()
    if not vid:
        raise HTTPException(400, "thieu voice_id")
    notes = _load_notes()
    note = (body.get("note") or "").strip()
    if note:
        notes[vid] = note
    else:
        notes.pop(vid, None)
    tmp = VOICE_NOTES + ".tmp"
    json.dump(notes, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, VOICE_NOTES)
    return {"ok": True, "voice_id": vid, "note": note}


# ---------- TRANG PHUC (wardrobe) cua KOL ----------
def _outfit_id(kol):
    existing = {o.get("id") for o in (kol.get("outfits") or [])}
    i = 1
    while f"o{i}" in existing:
        i += 1
    return f"o{i}"


@app.post("/api/kols/{id}/outfits")
async def add_outfit(id: str, name: str = Form(...), note: str = Form(""), token: str = Form(""),
                     refs: list[UploadFile] = File(default=[])):
    kol = store.get("kols", id)
    if not kol:
        raise HTTPException(404, "no kol")
    outfits = list(kol.get("outfits") or [])
    outfits.append({"id": _outfit_id(kol), "name": name, "note": note, "token": token,
                    "refs": await _save_uploads(refs, "outfit")})
    store.patch("kols", id, outfits=outfits)
    return outfits[-1]


@app.patch("/api/kols/{id}/outfits/{oid}")
async def edit_outfit(id: str, oid: str, name: str = Form(None), note: str = Form(None),
                      token: str = Form(None), drop_refs: str = Form(None),
                      refs: list[UploadFile] = File(default=[])):
    kol = store.get("kols", id)
    if not kol:
        raise HTTPException(404, "no kol")
    outfits = list(kol.get("outfits") or [])
    for o in outfits:
        if o.get("id") == oid:
            for k, v in {"name": name, "note": note, "token": token}.items():
                if v is not None:
                    o[k] = v
            merged = _merge_refs(o, drop_refs, await _save_uploads(refs, "outfit"))
            if merged is not None:
                o["refs"] = merged
            store.patch("kols", id, outfits=outfits)
            return o
    raise HTTPException(404, "no outfit")


@app.delete("/api/kols/{id}/outfits/{oid}")
def del_outfit(id: str, oid: str):
    kol = store.get("kols", id)
    if not kol:
        raise HTTPException(404, "no kol")
    store.patch("kols", id, outfits=[o for o in (kol.get("outfits") or []) if o.get("id") != oid])
    return {"ok": True}


# ---------- SAN PHAM ----------
@app.get("/api/products")
def products():
    rows = _own_rows(store.list_all("products"))
    for p in rows:  # co nao SP chua? (UI badge 🧠 + noi dat hang)
        p["has_brain"] = os.path.exists(_brain_sp_path(p))
    return rows


@app.get("/api/niches")
def niches():
    """Danh muc nganh hang: {niche: so_san_pham} theo thu tu nhieu -> it."""
    c = {}
    for p in _own_rows(store.list_all("products")):
        n = (p.get("niche") or "").strip()
        if n:
            c[n] = c.get(n, 0) + 1
    return [{"niche": k, "count": v} for k, v in sorted(c.items(), key=lambda x: (-x[1], x[0]))]


@app.post("/api/products")
async def add_product(name: str = Form(...), code: str = Form(""), price: str = Form(""),
                      niche: str = Form(""), info: str = Form(""), token_block: str = Form(""),
                      refs: list[UploadFile] = File(default=[])):
    return store.upsert("products", {"name": name, "code": _uniq_code("products", name, code),
                                     "price": price, "niche": niche.strip(), "info": info,
                                     "token_block": token_block,
                                     "refs": await _save_uploads(refs, "prod")})


@app.patch("/api/products/{id}")
async def edit_product(id: str, name: str = Form(None), code: str = Form(None), price: str = Form(None),
                       niche: str = Form(None), info: str = Form(None), token_block: str = Form(None),
                       drop_refs: str = Form(None), refs: list[UploadFile] = File(default=[])):
    cur = store.get("products", id)
    if not cur:
        raise HTTPException(404, "no product")
    _own_guard("products", id)
    up = {k: v for k, v in {"name": name, "price": price,
                            "niche": (niche.strip() if niche is not None else None),
                            "info": info, "token_block": token_block}.items() if v is not None}
    if code:
        up["code"] = code
    merged = _merge_refs(cur, drop_refs, await _save_uploads(refs, "prod"))
    if merged is not None:
        up["refs"] = merged
    return store.patch("products", id, **up)


# ---------- PHEU NAP VIDEO RA DON (nap nao theo SAN PHAM — chong nham SP) ----------
SPY_SP_DIR = os.path.join(os.path.dirname(DATA_HOME), "SPY", "theo-san-pham")

# ---------- BO NAO SAN PHAM (tri thuc RA DON boc tu video ra don) ----------
# brain/san-pham/<code>.json (slug = product.code, fallback id). _media/ + _transcripts/ con.
BRAIN_SP = os.path.join(os.path.dirname(SD), "brain", "san-pham")


def _brain_sp_slug(p):
    """Slug file nao cho 1 san pham = code (fallback id)."""
    return (p.get("code") or p.get("id") or "").strip() or p.get("id")


def _brain_sp_path(p):
    """Duong dan tuyet doi file JSON nao cua san pham p."""
    return os.path.join(BRAIN_SP, _brain_sp_slug(p) + ".json")


def _brain_sp_load(p):
    """Doc nao SP tu dia (None neu chua co)."""
    fp = _brain_sp_path(p)
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _brain_sp_save(p, brain):
    """Ghi nao SP xuong dia (tao thu muc khi can)."""
    os.makedirs(BRAIN_SP, exist_ok=True)
    fp = _brain_sp_path(p)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(brain, f, ensure_ascii=False, indent=2)
    return fp


@app.post("/api/products/{id}/nap-video")
async def nap_video(id: str, links: str = Form(""), owner: str = Form("doi_thu"),
                    metrics: str = Form(""), note: str = Form(""),
                    files: list[UploadFile] = File(default=[])):
    """Nap video ra don cho 1 san pham: nhieu LINK (moi dong 1 link TikTok/FB) va/hoac FILE.
    owner: doi_thu (boc cong thuc) | cua_minh (do so lieu that vao nao).
    Tao COMMAND cho Claude: tai ve -> teardown -> nap nao brain/gia-dung + gan spy_refs vao SP."""
    p = store.get("products", id)
    if not p:
        raise HTTPException(404, "no product")
    owner = "cua_minh" if owner == "cua_minh" else "doi_thu"
    urls = [u.strip() for u in (links or "").splitlines() if u.strip().startswith("http")]
    dest = os.path.join(SPY_SP_DIR, p.get("code") or id)
    os.makedirs(dest, exist_ok=True)
    saved = []
    for f in files:
        if not f.filename:
            continue
        fp = os.path.join(dest, os.path.basename(f.filename))
        with open(fp, "wb") as fh:
            fh.write(await f.read())
        saved.append(fp)
    if not urls and not saved:
        raise HTTPException(400, "thieu link hoac file")
    # ghi spy_refs pending vao SP (dedup theo url/file)
    refs = list(p.get("spy_refs") or [])
    known = {r.get("src") for r in refs}
    new_items = []
    for src in urls + saved:
        if src in known:
            continue
        new_items.append(src)
        refs.append({"src": src, "owner": owner, "metrics": metrics.strip(), "note": note.strip(),
                     "status": "pending", "ngay": time.strftime("%Y-%m-%d")})
    store.patch("products", id, spy_refs=refs)
    if not new_items:
        return {"ok": True, "moi": 0, "ghi_chu": "tat ca link/file da nap truoc do (dedup)"}
    # lenh tu-du cho Claude
    sp_ten = p.get("name", "")
    if owner == "doi_thu":
        text = (f"PHỄU NẠP NÃO GIA DỤNG — video ĐỐI THỦ cho sản phẩm \"{sp_ten}\" (id {id}, code {p.get('code')}).\n"
                f"Nguồn ({len(new_items)}): " + " | ".join(new_items) + "\n"
                + (f"Số liệu user khai: {metrics}\n" if metrics.strip() else "CHƯA có số liệu view/đơn — weight thấp khi rút công thức.\n")
                + f"Việc: (1) link TikTok tải bằng tikwm, link FB dùng scraper spy-scan/yt-dlp, file thì dùng thẳng — gom về SPY/theo-san-pham/{p.get('code')}/; "
                  "(2) chạy teardown.py (skill spy-teardown) bóc frame+whisper+nhịp+giọng; "
                  "(3) ĐỌC brain/gia-dung/cong-thuc.json — video khớp công thức có sẵn thì CỘNG bằng chứng (bang_chung.doi_thu), "
                  "lạ hẳn thì đề xuất CÔNG THỨC MỚI (đủ trường theo schema); cập nhật ban-do-san-pham nếu loại SP chưa có; "
                  "KHÔNG lưu thoại đối thủ nguyên văn — chỉ công thức; "
                  "(4) BÓC THÔNG SỐ SẢN PHẨM từ video (whisper + frame): kích thước/chất liệu/công năng/bán điểm/giá NẾU video nêu — "
                  "đây là DỮ KIỆN thật (khác công thức), viết lại bằng LỜI MÌNH, KHÔNG chép thoại đối thủ. "
                  f"PATCH /api/products/{id}: nếu 'info' đang TRỐNG thì điền; nếu ĐÃ CÓ thì chỉ BỔ SUNG dữ kiện mới chưa có (KHÔNG ghi đè cái cũ); "
                  "nếu video nêu giá rõ mà 'price' đang trống thì điền price; "
                  "(5) PATCH product spy_refs: status=done + cong_thuc=<id công thức> cho từng nguồn; "
                  "(6) ghi 1 entry nhat-ky-hoc.md. KHÔNG tự đẻ kịch bản — dừng sau khi nạp não.")
    else:
        text = (f"PHỄU NẠP NÃO GIA DỤNG — video CỦA MÌNH đã đăng, sản phẩm \"{sp_ten}\" (id {id}).\n"
                f"Nguồn ({len(new_items)}): " + " | ".join(new_items) + "\n"
                f"Số liệu thật user khai: {metrics or '(chưa khai — hỏi lại user nếu cần)'}\n"
                "Việc: (1) tải/đọc video; (2) nhận diện nó khớp kịch bản nào trong brain/gia-dung/kich-ban-goc/ "
                "(theo sản phẩm + thoại) — chưa có thì tạo record mới; (3) đổ view/đơn vào ket_qua của kịch bản đó "
                "+ bang_chung.cua_minh của công thức tương ứng trong cong-thuc.json + do-luong.json (PATCH /api/do-luong nếu có record); "
                "(4) tính lại diem công thức (SỐ CỦA MÌNH GHI ĐÈ số đối thủ); "
                f"(5) BÓC THÔNG SỐ SẢN PHẨM từ video (kích thước/chất liệu/công năng/giá nếu có) — PATCH /api/products/{id}: "
                "'info' trống thì điền, có rồi thì bổ sung dữ kiện mới (không ghi đè); giá rõ mà price trống thì điền; "
                "(6) PATCH product spy_refs status=done; (7) ghi entry nhat-ky-hoc.md (công thức lên/xuống hạng).")
    store.upsert("commands", {"text": text, "status": "pending", "response": None,
                              "engine": "claude", "staff": "san-xuat-video-gia-dung",
                              "label": (("🧠 Nạp não: " if owner == "doi_thu" else "🧠 Đổ số: ") + sp_ten)[:80]})
    return {"ok": True, "moi": len(new_items), "owner": owner}


# ---------- TEMPLATE kich ban ra don ----------
@app.get("/api/templates")
def templates():
    return sorted(store.list_all("templates"), key=lambda t: t.get("created", 0), reverse=True)


@app.post("/api/templates")
def add_template(body: dict):
    if not body.get("name"):
        raise HTTPException(400, "thieu name")
    b = dict(body)
    b.pop("id", None)
    b["code"] = _uniq_code("templates", b["name"], b.get("code"))
    b.setdefault("beats", [])
    return store.upsert("templates", b)


@app.patch("/api/templates/{id}")
def patch_template(id: str, body: dict):
    if not store.get("templates", id):
        raise HTTPException(404, "no template")
    up = dict(body)
    up.pop("id", None)
    return store.patch("templates", id, **up)


# ---------- IMPORT hang loat (JSON) ----------
@app.post("/api/import")
def bulk_import(body: dict):
    kind = body.get("kind")
    if kind not in ("kols", "products", "templates"):
        raise HTTPException(400, "kind = kols|products|templates")
    items = body.get("items") or []
    n = 0
    for it in items:
        if not it.get("name"):
            continue
        it = dict(it)
        it.pop("id", None)
        it["code"] = _uniq_code(kind, it["name"], it.get("code"))
        if kind == "templates":
            it.setdefault("beats", [])
        else:
            it.setdefault("refs", [])
        store.upsert(kind, it)
        n += 1
    return {"ok": True, "imported": n}


SOFT_DELETE_KINDS = ("kols", "products", "scripts", "channels", "media")  # cac type dong bo -> xoa MEM (tombstone) de lenh xoa lan sang may kia; xoa cung se hoi sinh record khi seed


@app.delete("/api/{kind}/{id}")
def rm(kind: str, id: str, files: int = 0, hard: int = 0):
    if kind not in ("kols", "products", "briefs", "templates", "projects", "commands", "scripts", "channels", "media"):
        raise HTTPException(400, "bad kind")
    _own_guard(kind, id)  # portal member: chi xoa record cua minh
    if kind in SOFT_DELETE_KINDS:
        if hard:
            if _portal():
                raise HTTPException(403, "Xoa cung chi lam duoc o Xuong (PC)")
            store.delete(kind, id)  # don rac chu dich cua admin PC — khong qua guard
            return {"ok": True, "hard": True}
        if kind == "scripts":
            s = store.get("scripts", id)
            if s and s.get("status") == "producing":
                raise HTTPException(400, "Kịch bản đang sản xuất — chờ xong hoặc trả về Chờ duyệt rồi mới xoá")
        store.patch(kind, id, deleted=True)  # xoa mem: updated_at moi -> sync mang co 'deleted' sang may kia
        return {"ok": True, "soft": True}
    # Xoa DU AN: mac dinh chi go registry; files=1 -> xoa ca thu muc Du An/DA-xxxx tren dia
    # (an toan: chi rmtree khi thu muc nam DUOI "Xuong KOL AI/Du An/" — khong bao gio xoa ngoai vung nay)
    if kind == "projects" and files:
        p = store.get("projects", id)
        d = os.path.abspath((p or {}).get("dir") or "")
        root = os.path.abspath(os.path.join(DATA_HOME, "Du An"))
        if p and d and os.path.isdir(d) and d.startswith(root + os.sep):
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        else:
            raise HTTPException(400, f"thu muc du an khong hop le de xoa: {d}")
    store.delete(kind, id)
    return {"ok": True}


# ---------- DU AN (project) ----------
def _project_code():
    existing = {p.get("code") for p in store.list_all("projects")}
    i = 1
    while f"DA-{i:04d}" in existing:
        i += 1
    return f"DA-{i:04d}"


def _write_manifest(proj):
    """Ghi project.json vao thu muc du an de tren dia tu mo ta duoc."""
    d = proj.get("dir")
    if d and os.path.isdir(d):
        try:
            with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as fh:
                json.dump(proj, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass


@app.get("/api/projects")
def projects():
    return sorted(_own_rows(store.list_all("projects")), key=lambda p: p.get("created", 0), reverse=True)


@app.get("/api/projects/{id}")
def project(id: str):
    p = store.get("projects", id)
    if not p:
        raise HTTPException(404, "no project")
    return p


@app.post("/api/projects")
def add_project(body: dict):
    code = body.get("code") or _project_code()
    if any(p.get("code") == code for p in store.list_all("projects")):
        code = _project_code()
    d = os.path.join(PROJECTS_DIR, code)
    os.makedirs(os.path.join(d, "scenes"), exist_ok=True)
    proj = store.upsert("projects", {
        "code": code, "title": body.get("title", ""), "dir": d,
        "brief_id": body.get("brief_id"),
        "kol": body.get("kol", ""), "product": body.get("product", ""), "template": body.get("template", ""),
        "channel": body.get("channel", ""),
        "status": body.get("status", "producing"),
        "script": body.get("script", ""),
        "scenes": body.get("scenes", []),
        "final_video": body.get("final_video"),
    })
    _write_manifest(proj)
    return proj


@app.patch("/api/projects/{id}")
def patch_project(id: str, body: dict):
    cur = store.get("projects", id)
    if not cur:
        raise HTTPException(404, "no project")
    up = dict(body)
    for k in ("id", "dir", "code", "created"):
        up.pop(k, None)
    p = store.patch("projects", id, **up)
    _write_manifest(p)
    return p


_HOOK_BEATS = [
    "WIDE establishing shot of the environment, the person entering / present in frame",
    "MEDIUM shot, the person looks at the camera and starts talking",
    "MEDIUM shot, the person presents or points toward the product / surrounding stock",
    "MEDIUM CLOSE-UP of the person with an inviting, excited expression",
    "CLOSE-UP hero introduction of the product's overall look",
    "LOW-ANGLE shot of the person standing confidently beside the product",
    "OVER-THE-SHOULDER shot from behind the person toward the product",
    "HERO beauty shot of the product",
    "MEDIUM CLOSE-UP, the person gestures 'keep watching' (continuity to next scene)",
]
_DEMO_BEATS = [
    "MEDIUM shot, the person beside the product about to demonstrate it",
    "MACRO detail close-up of the product frame / material to show sturdiness",
    "CLOSE-UP of the product's main surface or key part",
    "CLOSE-UP of a second key feature of the product",
    "OVER-THE-SHOULDER shot, the person's hand interacting with the product",
    "MEDIUM shot, the product shown in real use",
    "MEDIUM CLOSE-UP of the person reacting positively",
    "LOW-ANGLE hero shot of the full product",
    "MEDIUM shot, the person doing a value / price-drop gesture",
]
_CTA_BEATS = [
    "MEDIUM shot, the person presents the product beside them with an open palm",
    "WIDE hero shot of the full product in the setting",
    "MEDIUM CLOSE-UP of the person raising an index finger, making a key point",
    "MEDIUM CLOSE-UP of the person with an urgent, limited-stock expression",
    "MEDIUM shot, the person gives a confident thumbs-up beside the product",
    "CTA shot, the person points toward the bottom-left corner of the frame",
    "CLOSE-UP of the person's warm reassuring smile",
    "MEDIUM shot, the person kneels beside the product, hand resting on it",
    "MEDIUM shot, final confident closing pose (arms crossed)",
]


def _scene_role(pos, total):
    if pos == 0:
        return "hook"
    if pos == total - 1:
        return "cta"
    return "demo"


def _project_locks(proj):
    """Khoa identity KOL (tu store theo ten) + design san pham (giu tu anh ref, luu y dac diem la)."""
    kol_lock = ("preserve 100% the person's face, hairstyle, glasses and clothing from the reference image; "
                "the same person in every frame.")
    prod_lock = ("preserve the EXACT product from the reference image — same colors, materials, proportions and all "
                 "parts, INCLUDING any unusual or asymmetric design features; repeat it identically in every frame; "
                 "do NOT normalize it to a generic version.")
    def _match(a, b):
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        return bool(a) and bool(b) and (a == b or a in b or b in a)

    kn = proj.get("kol")
    for k in store.list_all("kols"):
        if _match(k.get("name"), kn) and (k.get("identity") or "").strip():
            kol_lock = k["identity"].strip()
            break
    pn = proj.get("product")
    # nhieu san pham trung ten (ban ngan/dai) -> uu tien ban khop TEN DAI NHAT (cu the nhat)
    best = None
    for p in store.list_all("products"):
        if _match(p.get("name"), pn) and (p.get("token_block") or "").strip():
            if best is None or len(p.get("name", "")) > len(best.get("name", "")):
                best = p
    if best:
        prod_lock = (best["token_block"].strip() +
                     " Repeat this exact design in every frame; do NOT normalize to a generic version.")
    return kol_lock, prod_lock


# Beat 4-o (khop i2v_prompt panels=4). Vai tro hook/demo/cta.
_SB4_BEATS = {
    "hook": ["wide establishing shot: the setting with the person and product visible",
             "medium shot: the person looks warmly at camera, product beside them",
             "close-up: the product's overall look (owner's hand may enter frame)",
             "medium close-up: the person's engaged expression, continuity to next scene"],
    "demo": ["medium shot: the person beside the product, about to demonstrate it",
             "close-up: a key part/feature of the product shown clearly",
             "over-the-shoulder/POV: the product in real use, hands interacting",
             "medium close-up: the person reacting positively to the result"],
    # CTA: KHÔNG ép ô cận-mặt/close-up mặt (Veo hay chặn PROMINENT_PEOPLE + i2v tả close-up dễ sinh mặt full khung).
    # Giữ mặt ở MEDIUM, sản phẩm luôn trong khung — bám đúng storyboard.
    "cta": ["medium shot: the person presents the product with an OPEN PALM (open hand, NOT a thumbs-up), product in frame",
            "medium shot: the full product clean and clear on the desk beside the person",
            "medium shot: the person makes a warm key point to camera, product visible",
            "medium shot: the person's warm reassuring smile with the product in frame, gentle closing (no tight face close-up)"],
}


def _scene_beats(role, n):
    """4-o beat cho 1 vai tro (hook/demo/cta), lap den n o. Luu vao scene.sb_beats khi sinh prompt
    -> i2v dien DUNG beat cua tam anh user ve (khop tuyet doi anh <-> video)."""
    b = _SB4_BEATS.get(role, _SB4_BEATS["demo"])
    return (b + [b[-1]] * n)[:n]


def _fmt_json(fmt):
    """Doc formats/{fmt}.json (rong neu thieu)."""
    try:
        fp = os.path.expanduser(f"~/.claude/skills/san-xuat-video-gia-dung/formats/{(fmt or '').strip()}.json")
        if (fmt or "").strip() and os.path.exists(fp):
            return json.load(open(fp, encoding="utf-8"))
    except Exception:
        pass
    return {}


def _sb_panels(fmt):
    """So o storyboard = sb_panels cua format json skill (mac dinh 4) — PHAI khop i2v_prompt panels."""
    return int(_fmt_json(fmt).get("sb_panels", 4)) or 4


def _find_img(rows, name, keys):
    """Tim path anh (ref/image) cua record khop TEN (uu tien ten dai nhat)."""
    def _m(a, b):
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        return bool(a) and bool(b) and (a == b or a in b or b in a)
    best = None
    for r in rows:
        if not _m(r.get("name"), name):
            continue
        for k in keys:
            v = r.get(k)
            if isinstance(v, list) and v:
                v = v[0]
            if isinstance(v, str) and v.strip():
                if best is None or len(r.get("name", "")) > len(best[0]):
                    best = (r.get("name", ""), v.strip())
                break
    return best[1] if best else ""


def _scene_attach_lines(proj):
    """Dong nhac user dinh kem anh ref vao ChatGPT (giu dong nhat nhan vat/san pham)."""
    pimg = _find_img(store.list_all("products"), proj.get("product"), ("image", "images", "ref", "refs"))
    kimg = _find_img(store.list_all("kols"), proj.get("kol"), ("ref", "refs", "image", "images"))
    L = ["", "📎 TRƯỚC KHI GỬI — đính kèm các ảnh sau vào ChatGPT (kéo-thả vào ô chat):"]
    if pimg:
        L.append(f"   • Ảnh SẢN PHẨM: {pimg}")
    if kimg:
        L.append(f"   • Ảnh NHÂN VẬT/KOL: {kimg}")
    if proj.get("accessory_ref"):
        L.append(f"   • Ảnh PHỤ KIỆN: {proj['accessory_ref']}")
    if not (pimg or kimg):
        L.append("   • (chưa thấy ảnh ref trong kho — tự đính kèm ảnh sản phẩm/nhân vật thật)")
    L.append("⚠️ Dùng CÙNG 1 cuộc hội thoại ChatGPT cho TẤT CẢ các cảnh của video này — nhân vật/sản phẩm mới đồng nhất.")
    return L


def _scene_sb_prompt(proj, scene, role, kol_lock, prod_lock):
    """Prompt STORYBOARD GENERATOR khop ENGINE i2v (luoi vuong sb_panels o, mac dinh 2x2=4).
    Nhoi bai hoc L1-L5: logic vat ly (L2), ti le that (L4/L5), khoa phu kien (L3), cam thumbs-up (L5),
    khong icon gia (luat rieng). User dan prompt nay vao ChatGPT web + dinh kem anh ref -> tao anh thu cong."""
    dlg = (scene.get("voice") or "").strip()
    title = (scene.get("title") or f"Scene {scene.get('idx')}").strip()
    n = _sb_panels(proj.get("format"))
    cols = 2 if n <= 4 else 3
    grows = (n + cols - 1) // cols
    beats = _scene_beats(role, n)
    has_p = bool((proj.get("product") or "").strip())
    has_k = bool((proj.get("kol") or "").strip())
    case = "PRODUCT + PERSON" if (has_p and has_k) else ("PERSON ONLY" if has_k else "PRODUCT ONLY")
    # PROMPT TỐI ƯU (2026-07-16, sau L1-L7): thêm MOTION CONTINUITY (ô kề nhau chỉ khác 1 cử động
    # -> i2v mượt, ít morph), PRODUCT FIDELITY (cấm bịa nhãn/chữ bao bì), PANEL 1 = frame mở màn,
    # ánh sáng đồng nhất, cấm mặt người lạ nhận diện được (né PROMINENT_PEOPLE + trôi nhân vật).
    L = [f"STORYBOARD GENERATOR — 9:16 vertical. CASE: {case}. SCENE: {title}.",
         f"OUTPUT: ONE clean {cols}x{grows} grid = {n} sequential numbered panels (small number badges 1-{n}, thin "
         "white gutters), read top-left to bottom-right — a cinematic breakdown of THIS single ~10-second scene. "
         "Each panel is a FULL-BLEED vertical 9:16 photograph (no captions, no borders inside panels).",
         "PANEL 1 = the OPENING FRAME of the video: a clean, stable composition that works as frame zero.", "",
         f"IDENTITY LOCK (identical in all {n} panels):", f"- PERSON: {kol_lock}",
         # L7: mặt vẽ quá "idol" -> Veo PROMINENT_PEOPLE chặn i2v. Ép mặt đại trà, đời thường.
         "- FACE RULE (compliance, HIGH PRIORITY): natural, ORDINARY everyday Vietnamese features with slight "
         "natural imperfections — must NOT resemble any celebrity, idol, actress or public figure; no flawless "
         "K-beauty idol styling. No other recognizable faces anywhere (background people, if the setting needs "
         "them, must be far away, out of focus and unrecognizable).",
         f"- PRODUCT: {prod_lock}",
         "- PRODUCT FIDELITY: draw the product EXACTLY as in the attached reference photo — same shape, colors, "
         "proportions, materials and label design. NEVER invent, translate or alter any text on the packaging; "
         "if label text is too small, keep it soft/illegible rather than making words up. The label should be "
         "clearly readable in at least one closer panel."]
    if proj.get("accessory_lock"):
        L.append(f"- ACCESSORY LOCK: {proj['accessory_lock']}")
    L += ["",
          "MOTION CONTINUITY (for animation — QUAN TRỌNG): the panels form ONE continuous take, not separate "
          "shots. Between consecutive panels change ONLY ONE natural movement (a hand reaches, the head turns, "
          "the product is lifted...) — same person position/pose base, same product placement unless hands move "
          "it, identical outfit/hair/jewelry, identical props layout. No teleporting, no jump in blocking.",
          "REALISM (physical logic): every action physically logical and safe (e.g. never pour into a lamp/candle "
          "that is already lit — fill first, light after). Hands hold objects naturally with correct fingers.",
          "SCALE: every prop at realistic real-world size relative to the person, hands and furniture — nothing "
          "oversized or shrunken; proportions consistent across panels.",
          "★ ABSOLUTELY NO price tags/numbers/%/discount, NO freeship/sale/deal badges, NO delivery icons, NO "
          "promo graphics, NO text overlays, NO speech bubbles, NO watermarks — pure photographic frames "
          "(CTA is expressed by gesture + facial warmth only)."]
    if dlg:
        L += ["", f'SCENE CONTEXT: the person is speaking this Vietnamese line during the scene: "{dlg}" — '
                  "let the mood, gestures and pacing of the panels match what is being said."]
    # BỐI CẢNH: cảnh có riêng -> dùng; trống -> mặc định của format (ảnh storyboard bám đúng format)
    env = (scene.get("environment") or "").strip() or (_fmt_json(proj.get("format")).get("environment") or "").strip()
    if env:
        L += [f"SETTING (one continuous location for ALL {n} panels): {env}",
              "LIGHTING CONTINUITY: same light direction, color temperature and time-of-day in every panel."]
    L += ["", f"PANELS ({n} sequential action beats of THIS scene):"]
    for i, b in enumerate(beats):
        L.append(f"{i + 1}. {b}")
    L += ["", "VISUAL QUALITY: ultra realistic, photorealistic, high-end commercial, cinematic lighting, realistic "
          "shadows, shallow depth of field, physically accurate materials; vary the camera SIZE each panel "
          "(wide/medium/close) while keeping the same continuous take feeling.",
          "ASPECT RATIO: 9:16 vertical.",
          "NEGATIVE: extra grid lines beyond the labeled panels, distorted anatomy, duplicate subjects, "
          "inconsistent product, invented packaging text, extra fingers, thumbs-up gesture, OK-sign, cheesy "
          "salesman pose, blurry objects, text/captions/logos, low quality, AI artifacts, floating objects, "
          "mirrored or repeated panels."]
    L += _scene_attach_lines(proj)
    return "\n".join(L)


@app.post("/api/projects/{pid}/storyboard_prompt")
def make_storyboard_prompt(pid: str):
    """Sinh prompt STORYBOARD GENERATOR (tao ANH) rieng cho TUNG canh -> scene.storyboard_prompt.
    KHONG tu sinh Flow VIDEO prompt (scene.motion) — buoc do can CLAUDE ĐOC ANH storyboard user Import
    roi moi viet (STEP1 converter = 'Analyze the uploaded storyboard image')."""
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    kol_lock, prod_lock = _project_locks(proj)
    scenes = sorted(proj.get("scenes") or [], key=lambda s: s.get("idx", 0))
    n = _sb_panels(proj.get("format"))
    for pos, s in enumerate(scenes):
        role = _scene_role(pos, len(scenes))
        s["storyboard_prompt"] = _scene_sb_prompt(proj, s, role, kol_lock, prod_lock)
        s["sb_beats"] = _scene_beats(role, n)  # i2v diễn đúng beat của ảnh user vẽ
    p = store.patch("projects", pid, scenes=scenes)
    _write_manifest(p)
    return {"scenes": len(scenes), "roles": [_scene_role(i, len(scenes)) for i in range(len(scenes))]}


@app.post("/api/projects/{pid}/scene_upload")
async def scene_upload(pid: str, idx: int = Form(...), slot: str = Form("storyboard"),
                       file: UploadFile = File(...)):
    """User tu tao anh storyboard (thu cong) roi IMPORT vao 1 canh cua du an.
    slot = storyboard | video. Luu vao <dir>/scenes/ + cap nhat scene."""
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    if slot not in ("storyboard", "video"):
        raise HTTPException(400, "slot = storyboard|video")
    d = proj.get("dir")
    scenes_dir = os.path.join(d, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or (".png" if slot == "storyboard" else ".mp4")
    dest = os.path.join(scenes_dir, f"scene{idx}_{slot}{ext}")
    with open(dest, "wb") as fh:
        fh.write(await file.read())
    scenes = proj.get("scenes") or []
    hit = next((s for s in scenes if s.get("idx") == idx), None)
    if hit is None:
        hit = {"idx": idx}
        scenes.append(hit)
        scenes.sort(key=lambda s: s.get("idx", 0))
    hit[slot] = dest
    p = store.patch("projects", pid, scenes=scenes)
    _write_manifest(p)
    return p


def _chatgpt_quota_guard():
    """FAIL-FAST khi ChatGPT chạm trần ảnh/giờ (fix 2026-07-16): TRƯỚC ĐÂY request vẫn xếp hàng
    -> đợi quá timeout 300s -> Studio báo lỗi NHƯNG job vẫn gen sau đó (ảnh mồ côi, đốt quota,
    'tạo liên tục mà không cập nhật'). Giờ chặn ngay từ cửa, báo rõ chờ bao lâu."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8200/api/chatgpt/status", timeout=5) as f:
            q = (json.load(f).get("queue") or {})
    except Exception:
        return  # backend chưa chạy -> để bước sau báo lỗi kết nối như cũ
    if q.get("paused"):
        rem = int(q.get("paused_remaining_s") or 0)
        raise HTTPException(429, f"ChatGPT đang nghỉ (chạm trần ảnh/giờ) — thử lại sau ~{max(1, rem // 60)} phút. Ảnh đã vẽ vẫn giữ nguyên.")
    if int(q.get("in_last_hour") or 0) >= int(q.get("max_per_hour") or 12):
        raise HTTPException(429, "ChatGPT đã chạm trần ảnh/giờ — chờ sang cửa sổ giờ mới rồi vẽ tiếp. Ảnh đã vẽ vẫn giữ nguyên.")


def _sb_gen_one(pid: str, idx: int) -> dict:
    """RUỘT của scene_gen_chatgpt (bóc ra 2026-07-16 để job nền 'Vẽ tất cả' dùng lại):
    gen ảnh storyboard 1 cảnh QUA ChatGPT bridge — build prompt + TỰ ĐÍNH ref (sản phẩm + KOL),
    lưu png, patch scenes + chatgpt_conversation_id, ghi manifest. raise HTTPException như cũ.
    KHÔNG chứa guard _is_member (endpoint/ job nền tự lo). Cần: extension-chatgpt (:8200)."""
    _chatgpt_quota_guard()
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    scenes = proj.get("scenes") or []
    sc = next((s for s in scenes if s.get("idx") == idx), None)
    if not sc:
        raise HTTPException(404, "no scene")
    # ĐẠO DIỄN HÌNH ẢNH: format bối cảnh động + cảnh thiếu environment -> AI sinh trước khi build prompt
    if _fmt_json(proj.get("format")).get("dynamic_environment") and not (sc.get("environment") or "").strip():
        try:
            s_src = next((x for x in store.list_all("scripts") if x.get("project_id") == pid), None)
            if s_src and _ensure_dynamic_env(s_src, proj):
                proj = store.get("projects", pid) or proj
                scenes = proj.get("scenes") or []
                sc = next((s for s in scenes if s.get("idx") == idx), None) or sc
        except HTTPException:
            raise  # bridge lỗi -> user cần biết
    pr = (sc.get("storyboard_prompt") or "").strip()
    if not pr:  # chua co prompt -> tu sinh (khong bat user bam 🎨 truoc)
        kol_lock, prod_lock = _project_locks(proj)
        ordered = sorted(scenes, key=lambda x: x.get("idx", 0))
        pr = _scene_sb_prompt(proj, sc, _scene_role(ordered.index(sc), len(ordered)), kol_lock, prod_lock)
        sc["storyboard_prompt"] = pr
    pr = pr.split("📎")[0].strip()  # khoi 📎 la huong dan cho NGUOI — bridge tu dinh ref
    import base64 as _b64
    refs = []
    for label, path in (
            ("product", _find_img(store.list_all("products"), proj.get("product"), ("image", "images", "ref", "refs"))),
            ("kol", _find_img(store.list_all("kols"), proj.get("kol"), ("ref", "refs", "image", "images")))):
        if path and os.path.exists(path):
            ext = os.path.splitext(path)[1].lower()
            mime = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/" + (ext.lstrip(".") or "png"))
            refs.append({"data_url": f"data:{mime};base64," + _b64.b64encode(open(path, "rb").read()).decode(),
                         "filename": label + (ext or ".png")})
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8200/api/chatgpt/generate-image",
            data=json.dumps({"prompt": pr, "refs": refs or None, "timeout_ms": 240000,
                             # 1 DỰ ÁN = 1 CUỘC CHAT ChatGPT (user 2026-07-15): cảnh sau nối tiếp
                             # cuộc chat của cảnh trước — GPT thấy ảnh cũ nên giữ đồng nhất, sidebar gọn.
                             "conversation_id": proj.get("chatgpt_conversation_id") or None}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300) as f:
            r = json.load(f)
    except Exception as e:
        raise HTTPException(502, f"chatgpt bridge loi: {e}")
    if not r.get("ok"):
        raise HTTPException(502, f"chatgpt bridge: {r.get('error')}")
    if r.get("conversation_id") and r["conversation_id"] != proj.get("chatgpt_conversation_id"):
        proj = store.patch("projects", pid, chatgpt_conversation_id=r["conversation_id"])
    with urllib.request.urlopen(f"http://127.0.0.1:8200/media/{r['media_id']}", timeout=60) as f:
        img = f.read()
    d = os.path.join(proj.get("dir"), "scenes")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"scene{idx}_storyboard.png")
    open(dest, "wb").write(img)
    sc["storyboard"] = dest
    p = store.patch("projects", pid, scenes=scenes)
    _write_manifest(p)
    return {"ok": True, "path": dest, "size_kb": len(img) // 1024}


@app.post("/api/projects/{pid}/scene_gen_chatgpt")
def scene_gen_chatgpt(pid: str, body: dict):
    """Nut '🤖 ChatGPT' (user yeu cau 2026-07-15): gen anh storyboard 1 canh QUA ChatGPT bridge —
    tu gui prompt + TU DINH KEM anh ref (san pham + KOL) vao tab chatgpt.com, cho anh ve, luu vao scene.
    Thay the viec user copy prompt + dinh anh thu cong. Can: extension-chatgpt connected (:8200)."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    return _sb_gen_one(pid, int(body.get("idx") or 0))


# ─────────── VẼ TẤT CẢ STORYBOARD (job nền server-side — user 2026-07-16) ───────────
def _sbgen_scene_missing(proj):
    """Danh sách idx các cảnh THIẾU storyboard, sắp theo idx (dùng cho job 'Vẽ tất cả')."""
    return sorted(s.get("idx", 0) for s in (proj.get("scenes") or []) if not (s.get("storyboard") or "").strip())


def _sbgen_active_job(pid):
    """Job sbgen ĐANG chạy (queued/running) của project pid, mới nhất — hoặc None."""
    rows = [r for r in store.list_all("sbgen_jobs")
            if r.get("project_id") == pid and r.get("status") in ("queued", "running")]
    return sorted(rows, key=lambda r: r.get("created", 0), reverse=True)[0] if rows else None


def _sbgen_run(job_id):
    """Vòng lặp nền: mỗi vòng NẠP LẠI proj, vẽ cảnh thiếu storyboard kế tiếp (theo idx).
    CHỐNG LẶP VÔ HẠN (fix 2026-07-16): mỗi cảnh chỉ THỬ 1 LẦN/job — cảnh fail bị bỏ qua,
    không nhặt lại (trước đây missing[0] nhặt lại đúng cảnh vừa fail -> gen liên tục đốt quota).
    Bridge chết / chạm trần quota -> status=failed + DỪNG. User hủy -> dừng."""
    attempted = set()
    while True:
        job = store.get("sbgen_jobs", job_id)
        if not job or job.get("status") == "cancelled":  # user hủy -> dừng
            return
        pid = job.get("project_id")
        proj = store.get("projects", pid)
        if not proj:
            store.patch("sbgen_jobs", job_id, status="failed", error="no project", updated=int(time.time()))
            return
        missing = [i for i in _sbgen_scene_missing(proj) if i not in attempted]
        if not missing:  # hết cảnh CHƯA THỬ -> kết
            j = store.get("sbgen_jobs", job_id) or {}
            still = _sbgen_scene_missing(proj)
            st = "done" if not still or j.get("done", 0) > 0 else "failed"
            store.patch("sbgen_jobs", job_id, status=st, current_idx=None, updated=int(time.time()))
            return
        idx = missing[0]
        attempted.add(idx)
        store.patch("sbgen_jobs", job_id, current_idx=idx, updated=int(time.time()))
        try:
            _sb_gen_one(pid, idx)
            j = store.get("sbgen_jobs", job_id) or {}
            store.patch("sbgen_jobs", job_id, done=(j.get("done", 0) + 1), updated=int(time.time()))
        except HTTPException as e:
            detail = str(e.detail)
            j = store.get("sbgen_jobs", job_id) or {}
            store.patch("sbgen_jobs", job_id, fails=(j.get("fails", 0) + 1),
                        error=detail[:200], updated=int(time.time()))
            # bridge chết / CHẠM TRẦN quota -> vẽ tiếp vô ích, dừng job ngay
            if ("chưa kết nối" in detail or "disconnected" in detail
                    or "chạm trần" in detail or "đang nghỉ" in detail):
                store.patch("sbgen_jobs", job_id, status="failed", current_idx=None, updated=int(time.time()))
                return


@app.post("/api/projects/{pid}/sb_gen_all")
def sb_gen_all(pid: str):
    """Vẽ TẤT CẢ storyboard còn thiếu — job nền server-side (sống qua F5). Đang có job active
    cùng project -> trả job cũ. Ngược lại tạo record 'running' + thread daemon _sbgen_run."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    act = _sbgen_active_job(pid)
    if act:
        return {"ok": True, "job_id": act["id"], "already": True}
    rec = store.upsert("sbgen_jobs", {
        "project_id": pid, "status": "running", "total": len(_sbgen_scene_missing(proj)),
        "done": 0, "fails": 0, "current_idx": None, "error": "",
        "created": int(time.time()), "updated": int(time.time())})
    threading.Thread(target=_sbgen_run, args=(rec["id"],), daemon=True).start()
    return {"ok": True, "job_id": rec["id"]}


@app.get("/api/sbgen_jobs")
def sbgen_jobs(project_id: str = None):
    """List job vẽ-tất-cả (mới nhất trước). Có project_id -> 10 gần nhất của project đó;
    không -> mọi job active (queued/running) + 10 job gần nhất (gộp, khử trùng)."""
    rows = sorted(store.list_all("sbgen_jobs"), key=lambda r: r.get("created", 0), reverse=True)
    if project_id:
        return [r for r in rows if r.get("project_id") == project_id][:10]
    active = [r for r in rows if r.get("status") in ("queued", "running")]
    recent = rows[:10]
    seen, out = set(), []
    for r in active + recent:
        if r.get("id") not in seen:
            seen.add(r.get("id"))
            out.append(r)
    return out


@app.post("/api/sbgen_jobs/{jid}/cancel")
def sbgen_job_cancel(jid: str):
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    r = store.patch("sbgen_jobs", jid, status="cancelled", updated=int(time.time()))
    if not r:
        raise HTTPException(404, "no job")
    return {"ok": True}


# ═══════════ BỘ NÃO SẢN PHẨM — BÓC VIDEO RA ĐƠN (job nền, user 2026-07-16) ═══════════
# GET/POST nao + job BÓC: tai tikwm -> whisper -> Sonnet boc tung video -> tong hop nao.
def _brain_ffbin(name):
    import shutil as _sh
    return _sh.which(name) or name


def _brain_duration(video):
    """Do do dai video (giay) qua ffprobe; 0 neu loi."""
    try:
        out = subprocess.run([_brain_ffbin("ffprobe"), "-v", "error", "-show_entries",
                              "format=duration", "-of", "default=nk=1:nw=1", video],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out or 0)
    except Exception:
        return 0.0


def _brain_whisper(video, txt_path):
    """Transcribe video (vi) -> tra text + ghi ra txt_path. Loi -> raise."""
    import shutil as _sh
    wav = txt_path + ".wav"
    try:
        subprocess.run([_brain_ffbin("ffmpeg"), "-y", "-i", video, "-vn", "-ar", "16000",
                        "-ac", "1", wav], capture_output=True, timeout=240)
        from faster_whisper import WhisperModel
        m = WhisperModel("small", device="cpu", compute_type="int8")
        segs, _ = m.transcribe(wav, language="vi", vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segs).strip()
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
    finally:
        try:
            if os.path.exists(wav):
                os.remove(wav)
        except Exception:
            pass


def _tikwm_download(url, dest, timeout_s=120):
    """Tai video TikTok qua tikwm -> file dest. Tra True/False. Khong chet cho video khac."""
    try:
        api = "https://www.tikwm.com/api/?url=" + urllib.parse.quote(url, safe="")
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        d = (data or {}).get("data") or {}
        play = d.get("hdplay") or d.get("play") or d.get("wmplay")
        if not play:
            return False
        if play.startswith("/"):
            play = "https://www.tikwm.com" + play
        vreq = urllib.request.Request(play, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(vreq, timeout=timeout_s) as vr, open(dest, "wb") as fh:
            while True:
                chunk = vr.read(262144)
                if not chunk:
                    break
                fh.write(chunk)
        return os.path.getsize(dest) > 10240
    except Exception:
        return False


def _parse_don_view(metrics):
    """Boc so don + so view tho tu chuoi metrics user go tay (best-effort, giu nguyen chuoi)."""
    m = (metrics or "").strip()
    if not m:
        return "", ""
    don = ""
    mo = re.search(r"([\d.,]+\s*[kКmMtỷ]?\w*)\s*đơn", m, re.I)
    if mo:
        don = mo.group(1).strip()
    view = ""
    vo = re.search(r"([\d.,]+\s*[kmM]?)\s*(?:view|lượt xem|xem)", m, re.I)
    if vo:
        view = vo.group(1).strip()
    return don, view


def _bocnao_active_job(product_id):
    """Job boc-nao DANG chay (running) cua product, moi nhat — hoac None."""
    rows = [r for r in store.list_all("bocnao_jobs")
            if r.get("product_id") == product_id and r.get("status") == "running"]
    return sorted(rows, key=lambda r: r.get("created", 0), reverse=True)[0] if rows else None


def _bocnao_run(job_id):
    """Vong nen: boc TUNG spy_ref chua 'da_boc' -> tai + whisper + Sonnet boc -> tong hop nao.
    Job huy giua chung -> dung; loi 1 video -> fails++, khong chet ca job."""
    job = store.get("bocnao_jobs", job_id)
    if not job:
        return
    pid = job.get("product_id")
    p = store.get("products", pid)
    if not p:
        store.patch("bocnao_jobs", job_id, status="failed", error="no product", updated=int(time.time()))
        return
    os.makedirs(os.path.join(BRAIN_SP, "_media"), exist_ok=True)
    os.makedirs(os.path.join(BRAIN_SP, "_transcripts"), exist_ok=True)
    slug = _brain_sp_slug(p)
    limit = job.get("limit") or 0  # 0 = het (mac dinh); >0 = chi boc N video (dung cho E2E)
    brain = _brain_sp_load(p) or {}
    vids_new = []          # cac video_ra_don moi build o luot nay
    extractions = []       # extraction JSON cua tung video (dau vao tong hop)
    done = 0
    fails = 0
    last_err = ""
    # danh sach spy_ref chua boc (giu index de patch dung phan tu)
    refs = list(p.get("spy_refs") or [])
    todo = [(i, r) for i, r in enumerate(refs) if r.get("status") != "da_boc"]
    if limit > 0:
        todo = todo[:limit]
    total = len(todo)
    store.patch("bocnao_jobs", job_id, total=total, updated=int(time.time()))
    for n, (ridx, ref) in enumerate(todo, 1):
        j = store.get("bocnao_jobs", job_id)
        if not j or j.get("status") == "cancelled":  # user huy -> dung
            return
        src = (ref.get("src") or "").strip()
        vpath = os.path.join(BRAIN_SP, "_media", f"{slug}-v{ridx+1}.mp4")
        # a. tai video
        store.patch("bocnao_jobs", job_id, current=f"tải video {n}/{total}", updated=int(time.time()))
        got = False
        if src.startswith("http"):
            got = _tikwm_download(src, vpath, timeout_s=120)
        elif os.path.exists(src):  # file local da nap san
            try:
                import shutil as _sh
                _sh.copyfile(src, vpath)
                got = True
            except Exception:
                got = False
        if not got:
            fails += 1
            last_err = f"tải lỗi: {src[:60]}"
            refs = list(store.get("products", pid).get("spy_refs") or [])
            if ridx < len(refs):
                refs[ridx]["status"] = "loi_tai"
                store.patch("products", pid, spy_refs=refs)
            store.patch("bocnao_jobs", job_id, fails=fails, error=last_err, updated=int(time.time()))
            continue
        # b. whisper + do dai + nhip am tiet/10s
        store.patch("bocnao_jobs", job_id, current=f"whisper {n}/{total}", updated=int(time.time()))
        txt_path = os.path.join(BRAIN_SP, "_transcripts", f"{slug}-v{ridx+1}.txt")
        try:
            transcript = _brain_whisper(vpath, txt_path)
        except Exception as e:  # noqa: BLE001
            fails += 1
            last_err = f"whisper lỗi: {str(e)[:80]}"
            store.patch("bocnao_jobs", job_id, fails=fails, error=last_err, updated=int(time.time()))
            continue
        dur = _brain_duration(vpath)
        n_words = len(transcript.split())
        nhip = round(n_words / dur * 10) if dur > 0 else 0  # tu/10s (xap xi am tiet vi tieng Viet)
        don, view = _parse_don_view(ref.get("metrics"))
        # c. Sonnet boc 1 video
        store.patch("bocnao_jobs", job_id, current=f"Sonnet bóc {n}/{total}", updated=int(time.time()))
        prompt = (
            "Bạn là chuyên gia bóc tách video bán hàng TikTok để rút công thức RA ĐƠN.\n"
            f"SẢN PHẨM: {p.get('name','')}\n"
            f"THÔNG TIN SP: {(p.get('info') or '(chưa có)')}\n"
            f"GIÁ: {(p.get('price') or '(chưa rõ)')}\n"
            f"SỐ LIỆU user khai: {(ref.get('metrics') or '(không có — weight thấp)')}\n"
            f"GHI CHÚ: {(ref.get('note') or '')}\n"
            f"THỜI LƯỢNG: {dur:.0f}s · NHỊP: {nhip} âm tiết/10s\n"
            f"TRANSCRIPT (giọng đọc video):\n{transcript[:6000]}\n\n"
            "Trả về DUY NHẤT một JSON (không giải thích, không markdown) đúng schema, mỗi mảng ≤4 mục "
            "NGẮN GỌN tiếng Việt, KHÔNG chép nguyên văn thoại đối thủ (viết lại bằng lời mình):\n"
            '{"hook":"câu hook mở đầu","tom_tat_cau_truc":["beat 1...","beat 2..."],'
            '"khach_va_khoanh_khac":["ai xem / khoảnh khắc chạm"],'
            '"objections":["cản mua -> video trả lời thế nào"],'
            '"winning_shots":["shot cụ thể giữ chân"],'
            '"ngon_ngu_khach":["cụm từ khách hay dùng"],'
            '"cau_neo_gia":["cách neo giá trong video"],'
            '"thong_so_boc":["thông số SP video nêu"],'
            '"diem_cam":["điều nên tránh"]}')
        try:
            ext = _extract_json_obj(_ask_claude(prompt, timeout_s=240)) or {}
        except HTTPException as e:
            fails += 1
            last_err = f"Sonnet lỗi: {str(e.detail)[:80]}"
            store.patch("bocnao_jobs", job_id, fails=fails, error=last_err, updated=int(time.time()))
            continue
        # d. append video_ra_don + danh dau da_boc
        vid = {"src": src, "don": don, "view": view, "hook": ext.get("hook", ""),
               "tom_tat_cau_truc": ext.get("tom_tat_cau_truc", []), "nhip_syl_10s": nhip,
               "transcript_file": os.path.relpath(txt_path, os.path.dirname(SD)).replace("\\", "/"),
               "ngay_boc": time.strftime("%Y-%m-%d")}
        vids_new.append(vid)
        extractions.append(ext)
        refs = list(store.get("products", pid).get("spy_refs") or [])
        if ridx < len(refs):
            refs[ridx]["status"] = "da_boc"
            store.patch("products", pid, spy_refs=refs)
        done += 1
        # luu nao TAM (video_ra_don) sau moi video -> khong mat neu dut giua chung
        brain.setdefault("video_ra_don", [])
        brain["video_ra_don"].append(vid)
        _brain_sp_save(p, brain)
        store.patch("bocnao_jobs", job_id, done=done, updated=int(time.time()))
    # ── TỔNG HỢP NÃO (Sonnet lan cuoi) ──
    if extractions:
        store.patch("bocnao_jobs", job_id, current="tổng hợp não", updated=int(time.time()))
        old = _brain_sp_load(p) or {}
        old_for_prompt = {k: v for k, v in old.items() if k not in ("video_ra_don", "nhat_ky")}
        prompt = (
            "Bạn là chuyên gia hệ thống hoá tri thức bán hàng. Tổng hợp NÃO SẢN PHẨM từ các bản bóc video ra đơn.\n"
            f"SẢN PHẨM: {p.get('name','')} (id {pid})\n"
            f"NÃO CŨ (nếu có, hợp nhất — GIỮ cái đúng, bổ sung cái mới): {json.dumps(old_for_prompt, ensure_ascii=False)[:3000]}\n"
            f"CÁC BẢN BÓC MỚI: {json.dumps(extractions, ensure_ascii=False)[:8000]}\n\n"
            "Quy tắc: TINH CHẤT, toàn não ≤3KB; mỗi khối ≤5 gạch đầu dòng; mục nào kèm số đơn thì GIỮ số đơn làm "
            "trọng số (ưu tiên video nhiều đơn); KHÔNG bịa; viết lại bằng lời mình, KHÔNG chép thoại đối thủ.\n"
            "Trả về DUY NHẤT JSON đúng schema (KHÔNG tự sinh video_ra_don/nhat_ky — server tự giữ):\n"
            '{"product_id":"' + pid + '","name":"' + p.get("name", "").replace('"', "'") + '",'
            '"cap_nhat":"auto","thong_so":[],"khach_va_khoanh_khac":[],"objections":[],"winning_shots":[],'
            '"ngon_ngu_khach":[],"gia_neo":{"gia_hien_tai":"","cau_neo_ra_don":[],"bien_the_chay":""},'
            '"dna":{"hook_formula":[],"cau_truc":[],"cta_style":[],"nhip_syl_10s":""},'
            '"diem_cam":[],"video_ra_don":[],"nhat_ky":[]}')
        try:
            synth = _extract_json_obj(_ask_claude(prompt, timeout_s=240)) or {}
        except HTTPException as e:
            synth = {}
            last_err = f"tổng hợp lỗi: {str(e.detail)[:80]}"
        # merge: video_ra_don + nhat_ky GIU cua server
        final = _brain_sp_load(p) or {}
        for k, v in synth.items():
            if k in ("video_ra_don", "nhat_ky"):
                continue
            final[k] = v
        final["product_id"] = pid
        final.setdefault("name", p.get("name", ""))
        final["cap_nhat"] = time.strftime("%Y-%m-%d")
        final.setdefault("video_ra_don", [])
        # dam bao video moi da nam trong video_ra_don (da append o vong lap)
        final.setdefault("nhat_ky", [])
        final["nhat_ky"].append(f"{time.strftime('%Y-%m-%d')} bóc {done} video, fails {fails}")
        _brain_sp_save(p, final)
        # lam giau SP: token_block RONG + co thong_so -> build token_block ngan (KHONG dung info)
        prod_now = store.get("products", pid) or {}
        if not (prod_now.get("token_block") or "").strip() and final.get("thong_so"):
            tb = "; ".join(str(x) for x in final["thong_so"] if x)[:600]
            if tb:
                store.patch("products", pid, token_block=tb)
    # ── kết ──
    j = store.get("bocnao_jobs", job_id) or {}
    if j.get("status") == "cancelled":
        return
    store.patch("bocnao_jobs", job_id, status="done", current="", error=last_err,
                updated=int(time.time()))


@app.get("/api/products/{id}/brain")
def get_brain(id: str):
    """Doc nao 1 san pham -> {exists, brain, path}."""
    p = store.get("products", id)
    if not p:
        raise HTTPException(404, "no product")
    brain = _brain_sp_load(p)
    return {"exists": brain is not None, "brain": brain, "path": _brain_sp_path(p)}


@app.post("/api/products/{id}/brain")
def save_brain(id: str, body: dict):
    """Ghi de nao 1 san pham (nut 'Sua JSON' tren UI). Chan portal member."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    p = store.get("products", id)
    if not p:
        raise HTTPException(404, "no product")
    brain = body.get("brain")
    if not isinstance(brain, dict):
        raise HTTPException(400, "thieu brain (object)")
    fp = _brain_sp_save(p, brain)
    return {"ok": True, "path": fp}


def _kalodata_parse(data: bytes):
    """Đọc bytes xlsx Kalodata -> (rows, cols dict). raise HTTPException nếu sai định dạng."""
    import io as _io
    import openpyxl
    try:
        wb = openpyxl.load_workbook(_io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"File không đọc được (cần .xlsx Kalodata): {e}")
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(400, "File rỗng")
    return rows


@app.post("/api/products/spy_import_xlsx")
async def spy_import_xlsx(file: UploadFile = File(...), preview: int = 0):
    """IMPORT EXCEL KALODATA (user 2026-07-16): đọc file export Video của Kalodata ->
    TỰ KHỚP sản phẩm trong kho theo cột 'Tiêu đề sản phẩm' -> append spy_refs (dedupe theo
    link TikTok, sort Lượt bán giảm dần để bóc não video nhiều đơn trước).
    preview=1 (user 2026-07-16 — CHO CHỌN SP): chỉ PHÂN TÍCH, lưu file tạm, trả về danh sách
    nhóm + gợi ý SP khớp để UI hiện bảng chọn; sau đó gọi /spy_import_confirm với mapping."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    data = await file.read()
    rows = _kalodata_parse(data)
    head = [str(c or "").strip().lower() for c in rows[0]]

    def _col(*keys):
        for i, h in enumerate(head):
            if any(k in h for k in keys):
                return i
        return None
    c_link = _col("link tiktok")
    c_title = _col("tiêu đề sản phẩm", "tieu de san pham", "product")
    c_sold = _col("lượt bán", "luot ban", "sold")
    c_rev = _col("doanh thu (", "revenue")
    c_view = _col("lượt xem", "luot xem", "views")
    c_gpm = _col("gpm")
    c_acc = _col("tài khoản", "tai khoan", "creator")
    c_desc = _col("mô tả video", "mo ta video")
    c_date = _col("ngày đăng", "ngay dang")
    if c_link is None:
        raise HTTPException(400, "Không thấy cột 'Link TikTok' — đúng file export Video của Kalodata chứ?")

    def _num(v):
        try:
            return float(str(v).replace(",", ""))
        except Exception:
            return 0.0
    # gom theo tiêu đề SP (1 file có thể nhiều SP)
    groups = {}
    for r in rows[1:]:
        link = str(r[c_link] or "").strip() if c_link < len(r) else ""
        if not link.startswith("http"):
            continue
        title = str(r[c_title] or "").strip() if (c_title is not None and c_title < len(r)) else ""
        groups.setdefault(title, []).append(r)

    prods = store.list_all("products")

    def _match(title):
        t = title.lower()
        best = None
        for p in prods:
            nm = (p.get("name") or "").lower()
            if nm and (nm in t or t[:40] in nm or nm[:40] in t):
                if best is None or len(p.get("name", "")) > len(best.get("name", "")):
                    best = p
        return best
    # PREVIEW (cho CHỌN SP — user 2026-07-16): không nạp gì, lưu file tạm + trả nhóm + gợi ý khớp
    if preview:
        import uuid as _uuid
        os.makedirs(os.path.join(BRAIN_SP, "_imports"), exist_ok=True)
        token = _uuid.uuid4().hex[:12]
        open(os.path.join(BRAIN_SP, "_imports", token + ".xlsx"), "wb").write(data)
        out = []
        for title, rws in groups.items():
            sg = _match(title)
            tops = sorted((int(_num(r[c_sold])) if c_sold is not None else 0) for r in rws)[::-1][:3]
            out.append({"title": title[:80], "videos": len(rws), "top_don": tops,
                        "suggest_id": sg and sg["id"], "suggest_name": sg and sg.get("name", "")[:50]})
        return {"ok": True, "preview": True, "token": token, "groups": out}

    def _ingest(p, rws):
        refs = list(p.get("spy_refs") or [])
        by_src = {(x.get("src") or "").split("?")[0]: x for x in refs}
        rws.sort(key=lambda r: -_num(r[c_sold]) if (c_sold is not None and c_sold < len(r)) else 0)
        added = skipped = updated = 0
        for r in rws:
            link = str(r[c_link]).strip()
            key = link.split("?")[0]
            sold = int(_num(r[c_sold])) if c_sold is not None else 0
            rev = int(_num(r[c_rev])) if c_rev is not None else 0
            view = int(_num(r[c_view])) if c_view is not None else 0
            gpm = int(_num(r[c_gpm])) if c_gpm is not None else 0
            metrics = f"{sold} đơn · {rev:,}đ · {view:,} view" + (f" · GPM {gpm:,}đ" if gpm else "")
            note = " · ".join(x for x in (
                str(r[c_acc] or "").strip() if c_acc is not None else "",
                (str(r[c_desc] or "").strip()[:60]) if c_desc is not None else "") if x)
            ngay = str(r[c_date] or "")[:10] if c_date is not None else ""
            if key in by_src:
                ex = by_src[key]
                # link ĐÃ có nhưng thiếu số -> ĐỔ BÙ metrics từ file (trọng số cho não), không bỏ phí
                if not (ex.get("metrics") or "").strip():
                    ex["metrics"] = metrics
                    if not (ex.get("note") or "").strip():
                        ex["note"] = note
                    if not (ex.get("ngay") or "").strip():
                        ex["ngay"] = ngay
                    updated += 1
                else:
                    skipped += 1
                continue
            refs.append({"src": link, "owner": "doi_thu", "metrics": metrics, "note": note,
                         "status": "pending", "ngay": ngay, "nguon": "kalodata"})
            by_src[key] = refs[-1]
            added += 1
        store.patch("products", p["id"], spy_refs=refs)
        return added, updated, skipped

    matched, unmatched = [], []
    for title, rws in groups.items():
        p = _match(title)
        if not p:
            unmatched.append({"title": title[:60], "videos": len(rws)})
            continue
        added, updated, skipped = _ingest(p, rws)
        matched.append({"product": p.get("name", "")[:50], "product_id": p["id"],
                        "added": added, "updated": updated, "skipped": skipped})
    return {"ok": True, "matched": matched, "unmatched": unmatched}


@app.post("/api/products/spy_import_confirm")
def spy_import_confirm(body: dict):
    """Bước 2 của import CÓ CHỌN SP: nhận {token, mapping:{title: product_id|""}} — nạp theo
    lựa chọn của user (title -> SP đã chọn; "" = bỏ qua nhóm đó). Xoá file tạm sau khi xong."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    token = re.sub(r"[^0-9a-f]", "", str(body.get("token") or ""))[:12]
    fp = os.path.join(BRAIN_SP, "_imports", token + ".xlsx")
    if not token or not os.path.exists(fp):
        raise HTTPException(404, "phiên import hết hạn — chọn lại file")
    mapping = body.get("mapping") or {}
    rows = _kalodata_parse(open(fp, "rb").read())
    head = [str(c or "").strip().lower() for c in rows[0]]

    def _col(*keys):
        for i, h in enumerate(head):
            if any(k in h for k in keys):
                return i
        return None
    c_link, c_title = _col("link tiktok"), _col("tiêu đề sản phẩm", "tieu de san pham", "product")
    c_sold, c_rev = _col("lượt bán", "luot ban", "sold"), _col("doanh thu (", "revenue")
    c_view, c_gpm = _col("lượt xem", "luot xem", "views"), _col("gpm")
    c_acc, c_desc = _col("tài khoản", "tai khoan", "creator"), _col("mô tả video", "mo ta video")
    c_date = _col("ngày đăng", "ngay dang")

    def _num(v):
        try:
            return float(str(v).replace(",", ""))
        except Exception:
            return 0.0
    groups = {}
    for r in rows[1:]:
        link = str(r[c_link] or "").strip() if c_link < len(r) else ""
        if not link.startswith("http"):
            continue
        title = str(r[c_title] or "").strip() if (c_title is not None and c_title < len(r)) else ""
        groups.setdefault(title, []).append(r)
    matched, skipped_groups = [], []
    for title, rws in groups.items():
        pid = (mapping.get(title[:80]) or mapping.get(title) or "").strip()
        if not pid:
            skipped_groups.append(title[:60])
            continue
        p = store.get("products", pid)
        if not p:
            skipped_groups.append(title[:60] + " (SP không tồn tại)")
            continue
        refs = list(p.get("spy_refs") or [])
        by_src = {(x.get("src") or "").split("?")[0]: x for x in refs}
        rws.sort(key=lambda r: -_num(r[c_sold]) if (c_sold is not None and c_sold < len(r)) else 0)
        added = updated = skipped = 0
        for r in rws:
            link = str(r[c_link]).strip()
            key = link.split("?")[0]
            sold = int(_num(r[c_sold])) if c_sold is not None else 0
            rev = int(_num(r[c_rev])) if c_rev is not None else 0
            view = int(_num(r[c_view])) if c_view is not None else 0
            gpm = int(_num(r[c_gpm])) if c_gpm is not None else 0
            metrics = f"{sold} đơn · {rev:,}đ · {view:,} view" + (f" · GPM {gpm:,}đ" if gpm else "")
            note = " · ".join(x for x in (
                str(r[c_acc] or "").strip() if c_acc is not None else "",
                (str(r[c_desc] or "").strip()[:60]) if c_desc is not None else "") if x)
            ngay = str(r[c_date] or "")[:10] if c_date is not None else ""
            if key in by_src:
                ex = by_src[key]
                if not (ex.get("metrics") or "").strip():
                    ex["metrics"] = metrics
                    if not (ex.get("note") or "").strip():
                        ex["note"] = note
                    if not (ex.get("ngay") or "").strip():
                        ex["ngay"] = ngay
                    updated += 1
                else:
                    skipped += 1
                continue
            refs.append({"src": link, "owner": "doi_thu", "metrics": metrics, "note": note,
                         "status": "pending", "ngay": ngay, "nguon": "kalodata"})
            by_src[key] = refs[-1]
            added += 1
        store.patch("products", pid, spy_refs=refs)
        matched.append({"product": p.get("name", "")[:50], "product_id": pid,
                        "added": added, "updated": updated, "skipped": skipped})
    try:
        os.remove(fp)
    except Exception:
        pass
    return {"ok": True, "matched": matched, "skipped_groups": skipped_groups}


@app.post("/api/products/{id}/boc_nao")
def boc_nao(id: str, limit: int = 0):
    """Khoi dong job BÓC NÃO cho 1 SP (tai + whisper + Sonnet boc + tong hop). Chan portal.
    limit>0: chi boc N spy_ref dau (dung cho E2E/thu nghiem); 0 = het."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    p = store.get("products", id)
    if not p:
        raise HTTPException(404, "no product")
    act = _bocnao_active_job(id)
    if act:
        return {"ok": True, "job_id": act["id"], "already": True}
    pend = [r for r in (p.get("spy_refs") or []) if r.get("status") != "da_boc"]
    total = min(len(pend), limit) if limit and limit > 0 else len(pend)
    if total == 0:
        raise HTTPException(400, "khong co video cho boc (spy_refs pending rong)")
    rec = store.upsert("bocnao_jobs", {
        "product_id": id, "status": "running", "total": total, "done": 0, "fails": 0,
        "current": "", "error": "", "limit": (limit if limit and limit > 0 else 0),
        "created": int(time.time()), "updated": int(time.time())})
    threading.Thread(target=_bocnao_run, args=(rec["id"],), daemon=True).start()
    return {"ok": True, "job_id": rec["id"]}


@app.get("/api/bocnao_jobs")
def bocnao_jobs(product_id: str = None):
    """List job boc-nao (moi nhat truoc). Co product_id -> 10 gan nhat cua SP do."""
    rows = sorted(store.list_all("bocnao_jobs"), key=lambda r: r.get("created", 0), reverse=True)
    if product_id:
        return [r for r in rows if r.get("product_id") == product_id][:10]
    active = [r for r in rows if r.get("status") == "running"]
    recent = rows[:10]
    seen, out = set(), []
    for r in active + recent:
        if r.get("id") not in seen:
            seen.add(r.get("id"))
            out.append(r)
    return out


@app.post("/api/bocnao_jobs/{jid}/cancel")
def bocnao_job_cancel(jid: str):
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    r = store.patch("bocnao_jobs", jid, status="cancelled", updated=int(time.time()))
    if not r:
        raise HTTPException(404, "no job")
    return {"ok": True}


# ─────────── MÁY SẢN XUẤT (deterministic, không LLM — user 2026-07-15) ───────────
def _ensure_project_from_script(s):
    """Trả project cho script (tạo DA mới nếu chưa có). Dùng bởi máy sản xuất + storyboard thủ công."""
    pid = s.get("project_id")
    proj = store.get("projects", pid) if pid else None
    if proj:
        return proj
    scenes = [{"idx": sc.get("idx", i + 1), "title": sc.get("title", ""),
               "voice": sc.get("voice", ""), "voice_direction": sc.get("voice_direction", ""),
               "environment": sc.get("environment", "")}
              for i, sc in enumerate(sorted(s.get("scenes") or [], key=lambda x: x.get("idx", 0)))]
    proj = add_project({"title": (s.get("hook") or s.get("product") or "")[:120],
                        "kol": s.get("kol", ""), "product": s.get("product", ""),
                        "channel": s.get("channel", ""), "scenes": scenes, "status": "producing"})
    store.patch("projects", proj["id"], format=s.get("format", ""), tts_voice=s.get("tts_voice", ""),
                nguoi_tao=s.get("nguoi_tao"))
    store.patch("scripts", s["id"], project_id=proj["id"])
    return store.get("projects", proj["id"])


@app.post("/api/scripts/{id}/produce")
def script_produce(id: str):
    """MÁY sản xuất: validate -> tạo project -> job runner code thuần (KHÔNG agent headless).
    Lỗi validate (thiếu format / thoại lệch / thiếu ref) -> 400 kèm danh sách (không đốt quota)."""
    if _is_member():
        raise HTTPException(403, "san xuat chay o Xuong (PC)")
    s = store.get("scripts", id)
    if not s:
        raise HTTPException(404, "no script")
    # ĐẠO DIỄN HÌNH ẢNH: format bối cảnh động -> AI sinh environment per-cảnh (merge scenes phía dưới mang sang project)
    if _ensure_dynamic_env(s):
        s = store.get("scripts", id) or s
    proj = _ensure_project_from_script(s)
    # đồng bộ scenes mới nhất của script vào project (thoại đã cân)
    if s.get("scenes"):
        cur = {c.get("idx"): c for c in (proj.get("scenes") or [])}
        merged = []
        for sc in sorted(s["scenes"], key=lambda x: x.get("idx", 0)):
            base = dict(cur.get(sc.get("idx"), {}))
            base.update({k: sc[k] for k in ("idx", "title", "voice", "voice_direction", "environment", "sb_beats")
                         if k in sc})
            merged.append(base)
        proj = store.patch("projects", proj["id"], scenes=merged, format=s.get("format", proj.get("format", "")),
                           tts_voice=s.get("tts_voice", proj.get("tts_voice", "")))
    try:  # validate SỚM (build thử) — sai thì báo ngay, chưa tạo job
        producer.build_episode(s, proj)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"build lỗi: {e}")
    job = producer.start_produce(proj["id"], s["id"])
    store.patch("scripts", id, status="producing")
    return {"ok": True, "job_id": job["id"], "project_id": proj["id"]}


def _ask_gpt(prompt: str, timeout_s: int = 90) -> str:
    """Hoi ChatGPT web (text) qua backend :8200 — mien phi, khong ton OpenAI API.
    Tra ve text tra loi; raise HTTPException neu bridge chua ket noi / loi."""
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8200/api/chatgpt/ask",
            data=json.dumps({"prompt": prompt, "timeout_ms": timeout_s * 1000}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_s + 30) as f:
            r = json.load(f)
    except urllib.error.HTTPError as e:
        if e.code == 503:
            raise HTTPException(502, "ChatGPT chua ket noi — mo Chrome + tab chatgpt.com da dang nhap roi thu lai.")
        raise HTTPException(502, f"chatgpt ask loi: {e}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"chatgpt ask loi: {e}")
    if not r.get("ok"):
        raise HTTPException(502, f"chatgpt ask: {r.get('error')}")
    return (r.get("text") or "").strip()


def _ask_claude(prompt: str, timeout_s: int = 120, model: str = "claude-sonnet-5") -> str:
    """Hoi CLAUDE (CLI, mac dinh Sonnet 5) — user 2026-07-16 chi dinh dung cho buoc TOI UU
    KICH BAN / CAN AM TIET (viet lai thoai chat luong hon ChatGPT web). Prompt qua STDIN
    (ne quoting); Windows: claude la .CMD -> phai goi qua cmd /c."""
    cb = _shutil.which("claude") or _shutil.which("claude.cmd") or "claude"
    base = ["cmd", "/c", cb] if (os.name == "nt" and cb.lower().endswith((".cmd", ".bat"))) else [cb]
    cmd = base + ["-p", "--model", model, "--output-format", "json", "--permission-mode", "bypassPermissions"]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout_s,
                           encoding="utf-8", errors="replace",
                           creationflags=(0x08000000 if os.name == "nt" else 0))
    except subprocess.TimeoutExpired:
        raise HTTPException(502, f"Claude ({model}) qua {timeout_s}s khong tra loi — thu lai.")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Claude CLI loi: {e}")
    out = (r.stdout or "").strip()
    try:  # --output-format json boc ngoai {"result": "..."}
        env = json.loads(out)
        txt = env.get("result") or env.get("text") or ""
        if env.get("is_error"):
            raise HTTPException(502, f"Claude tra loi loi: {str(txt)[:150]}")
    except HTTPException:
        raise
    except Exception:
        txt = out
    if not (txt or "").strip():
        raise HTTPException(502, f"Claude ({model}) tra ve rong (exit {r.returncode}) — kiem `claude` CLI da login.")
    return txt.strip()


def _extract_json_obj(txt: str):
    """Boc JSON object dau tien tu reply cua GPT (co the co ```json ... ``` hoac chu thua)."""
    if not txt:
        return None
    t = txt.strip()
    if "```" in t:  # bo code fence
        import re as _re
        m = _re.search(r"```(?:json)?\s*(.+?)```", t, _re.S)
        if m:
            t = m.group(1).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except Exception:
        return None


def _ensure_dynamic_env(script, proj=None):
    """Format có dynamic_environment: AI (Claude Sonnet 5) đọc kịch bản -> sinh bối cảnh per-cảnh
    (tiếng Anh, để prompt ảnh/i2v) GHI vào scenes[].environment CHỖ TRỐNG (user gõ tay thì giữ).
    Trả True nếu có thay đổi. Best-effort: bridge lỗi -> raise HTTPException từ _ask_claude."""
    fmt = (script.get("format") or (proj or {}).get("format") or "").strip()
    prof = _fmt_json(fmt)
    if not prof.get("dynamic_environment"):
        return False
    scenes = script.get("scenes") or []
    missing = [sc for sc in scenes if not (sc.get("environment") or "").strip()]
    if not missing:
        return False
    # Mô tả sản phẩm (token_block/desc/info) để đạo diễn chọn bối cảnh hợp SP — khớp tên kiểu _find_img
    prod_name = (script.get("product") or "").strip()

    def _m(a, b):
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        return bool(a) and bool(b) and (a == b or a in b or b in a)
    prod_rec = None
    for r in store.list_all("products"):
        if _m(r.get("name"), prod_name) and (prod_rec is None or len(r.get("name", "")) > len(prod_rec.get("name", ""))):
            prod_rec = r
    prod_desc = ""
    if prod_rec:
        prod_desc = (prod_rec.get("token_block") or prod_rec.get("desc") or prod_rec.get("info") or "").strip()
    hook = (script.get("hook") or "").strip()
    # danh sách cảnh (idx + thoại) cho đạo diễn
    scene_lines = "\n".join(
        f'Cảnh {sc.get("idx")}: {(sc.get("voice") or "").strip() or "(không thoại)"}'
        for sc in sorted(scenes, key=lambda x: x.get("idx", 0)))
    prompt = (
        "Bạn là PRODUCTION DESIGNER cho video bán hàng TikTok DỌC 9:16.\n"
        f"SẢN PHẨM: {prod_name or '(không rõ)'}"
        + (f" — {prod_desc}" if prod_desc else "") + "\n"
        + (f"HOOK: {hook}\n" if hook else "")
        + "CÁC CẢNH (theo thoại):\n" + scene_lines + "\n\n"
        "YÊU CẦU:\n"
        "1) Chọn 1 ĐỊA ĐIỂM CHÍNH nhất quán, hợp với sản phẩm + câu chuyện (KHÔNG mặc định nhà kho).\n"
        "2) Viết cho MỖI CẢNH 1 mô tả bối cảnh TIẾNG ANH 1-2 câu: địa điểm + chi tiết props + ánh sáng + không khí; "
        "cùng địa điểm chính nhưng khác góc/chi tiết theo thoại từng cảnh.\n"
        "3) TRÁNH mọi chữ/logo/giá xuất hiện trong cảnh.\n"
        'TRẢ VỀ DUY NHẤT 1 JSON object, key = chỉ số cảnh (chuỗi), value = mô tả tiếng Anh. '
        'Ví dụ: {"1":"...","2":"..."}. KHÔNG kèm giải thích.')
    reply = _ask_claude(prompt, timeout_s=120)  # user 2026-07-16: bối cảnh động dùng Claude
    obj = _extract_json_obj(reply) or {}
    changed = False
    for sc in missing:
        v = obj.get(str(sc.get("idx")))
        if isinstance(v, str) and v.strip():
            sc["environment"] = v.strip()
            changed = True
    if not changed:
        return False
    store.patch("scripts", script["id"], scenes=scenes)
    if proj:  # đồng bộ environment sang project theo idx
        pscenes = proj.get("scenes") or []
        by_idx = {sc.get("idx"): (sc.get("environment") or "") for sc in scenes}
        for ps in pscenes:
            ev = by_idx.get(ps.get("idx"))
            if ev and not (ps.get("environment") or "").strip():
                ps["environment"] = ev
        store.patch("projects", proj["id"], scenes=pscenes)
    return True


@app.post("/api/scripts/{id}/rebalance")
def script_rebalance(id: str):
    """TU CAN THOAI (user 2026-07-15): AI viet lai cac canh lech khoang am tiet cho khop FORMAT.
    KHONG luu — tra ve {old,new} de user duyet roi moi apply. Dung ChatGPT web (mien phi)."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    s = store.get("scripts", id)
    if not s:
        raise HTTPException(404, "no script")
    fmt = (s.get("format") or "").strip()
    if not fmt:
        raise HTTPException(400, "Chua chon FORMAT cho kich ban — chon Format truoc khi tu can.")
    prof = producer.load_format(fmt)
    smin = int(prof.get("syllables_min") or producer.SYL_MIN)
    smax = int(prof.get("syllables_max") or producer.SYL_MAX)
    scenes = sorted(s.get("scenes") or [], key=lambda x: x.get("idx", 0))
    off = []  # canh lech (ngoai [smin-2, smax+2])
    for sc in scenes:
        dlg = (sc.get("voice") or "").strip()
        n = producer._syl(dlg)
        if dlg and not (smin - 2 <= n <= smax + 2):
            off.append({"idx": sc.get("idx"), "title": sc.get("title", ""), "old": dlg, "old_n": n})
    if not off:
        return {"ok": True, "changed": [], "msg": "Tat ca thoai da nam trong khoang format — khong can can."}

    tgt = (smin + smax) // 2
    lines = "\n".join(f'Canh {o["idx"]} (hien {o["old_n"]} tieng, can {smin}-{smax}): "{o["old"]}"' for o in off)
    prompt = (
        "Ban la bien tap vien thoai video ban hang tieng Viet. Viet lai cac cau thoai duoi day cho DUNG "
        f"so tieng yeu cau, GIU nguyen y va chat giong ban hang tu nhien.\n\n"
        "QUY TAC DEM: moi TIENG cach nhau 1 dau cach; so tieng = so tu cach nhau boi space. "
        'Vi du \"tui dung chan man sieu tien loi\" = 7 tieng.\n\n'
        "YEU CAU:\n"
        f"- Moi cau phai nam trong khoang {smin}-{smax} tieng (ly tuong ~{tgt}).\n"
        "- GIU dung noi dung, KHONG them thong tin/gia moi, KHONG bo bot y chinh.\n"
        "- KHONG viet HOA ca tu, KHONG dat ten rieng/tu khoa trong dau ngoac kep.\n"
        "- Tieng Viet tu nhien, doc troi trong ~10 giay, dung dau cau.\n\n"
        "Tra ve DUY NHAT mot JSON object: key = so canh (chuoi), value = cau thoai moi. Khong giai thich.\n\n"
        "Cac canh can viet lai:\n" + lines
    )

    result = {}  # idx(str) -> new text
    remain = {str(o["idx"]): o for o in off}
    for attempt in range(2):  # tu sua toi da 2 vong cho canh con lech
        if not remain:
            break
        p = prompt if attempt == 0 else (
            "Cac cau sau VAN chua dung so tieng. Viet lai cho DUNG khoang, tra JSON nhu truoc:\n" +
            "\n".join(f'Canh {k} (can {smin}-{smax}): "{v.get("try") or v["old"]}"' for k, v in remain.items()))
        # TỐI ƯU THOẠI bằng CLAUDE Sonnet 5 (user 2026-07-16) — viết lại chất hơn ChatGPT web
        obj = _extract_json_obj(_ask_claude(p))
        if not obj:
            break
        for k, o in list(remain.items()):
            nv = (obj.get(k) or obj.get(int(k)) if isinstance(obj, dict) else None)
            nv = (nv or "").strip().strip('"')
            if not nv:
                continue
            nn = producer._syl(nv)
            if smin - 2 <= nn <= smax + 2:
                result[k] = nv
                remain.pop(k, None)
            else:
                o["try"] = nv  # gan cho vong sau

    changed = []
    for o in off:
        k = str(o["idx"])
        nv = result.get(k) or o.get("try")
        changed.append({"idx": o["idx"], "title": o["title"], "old": o["old"], "old_n": o["old_n"],
                        "new": nv or "", "new_n": producer._syl(nv) if nv else 0,
                        "ok": bool(nv) and (smin - 2 <= producer._syl(nv or "") <= smax + 2)})
    return {"ok": True, "range": [smin, smax], "changed": changed}


def _script_for_project(pid):
    return next((s for s in store.list_all("scripts") if s.get("project_id") == pid), None)


@app.post("/api/projects/{pid}/scene_rerender")
def scene_rerender(pid: str, body: dict):
    """Render LẠI 1 clip lẻ rồi dựng lại final (user 2026-07-15)."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    idx = int(body.get("idx") or 0)
    sc = next((s for s in (proj.get("scenes") or []) if s.get("idx") == idx), None)
    if not sc:
        raise HTTPException(404, "no scene")
    if not sc.get("storyboard"):
        raise HTTPException(400, f"Cảnh {idx} chưa có ảnh storyboard — tạo ảnh trước khi render.")
    scr = _script_for_project(pid)
    job = producer.start_rerender_clip(pid, idx, script_id=None)
    return {"ok": True, "job_id": job["id"], "project_id": pid, "idx": idx,
            "script_id": (scr or {}).get("id")}


@app.post("/api/projects/{pid}/reassemble")
def reassemble(pid: str):
    """Dựng LẠI khâu hoàn thiện (ghép + grade + final) từ các clip đã có (user 2026-07-15)."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    have = [s for s in (proj.get("scenes") or []) if s.get("video")]
    if not have:
        raise HTTPException(400, "Chưa có clip nào để dựng — render các clip trước đã.")
    job = producer.start_reassemble(pid, script_id=None)
    return {"ok": True, "job_id": job["id"], "project_id": pid}


@app.get("/api/produce_jobs")
def produce_jobs(project_id: str = None):
    rows = store.list_all("produce_jobs")
    if project_id:
        rows = [r for r in rows if r.get("project_id") == project_id]
    return sorted(rows, key=lambda r: r.get("created", 0), reverse=True)[:30]


@app.get("/api/produce_jobs/{jid}")
def produce_job(jid: str):
    j = store.get("produce_jobs", jid)
    if not j:
        raise HTTPException(404, "no job")
    return j


@app.post("/api/produce_jobs/{jid}/cancel")
def produce_job_cancel(jid: str):
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    r = producer.cancel_job(jid)
    if not r:
        raise HTTPException(404, "no job")
    return {"ok": True}


@app.get("/api/recent_downloads")
def recent_downloads(minutes: int = 30):
    """KHAY NOI nap anh storyboard (user 2026-07-15): liet ke anh MOI trong ~/Downloads (user vua
    'Tai xuong' tu ChatGPT) de bam-la-nap vao canh — khoi phai mo file picker."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    out, now = [], time.time()
    try:
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if not os.path.isfile(p):
                continue
            if os.path.splitext(fn)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            st = os.stat(p)
            if now - st.st_mtime > minutes * 60 or st.st_size < 40 * 1024:
                continue
            out.append({"name": fn, "path": p, "mtime": int(st.st_mtime), "size_kb": st.st_size // 1024})
    except Exception:
        pass
    return sorted(out, key=lambda x: -x["mtime"])[:12]


@app.post("/api/projects/{pid}/scene_import_path")
def scene_import_path(pid: str, body: dict):
    """Nap anh storyboard vao 1 canh tu DUONG DAN local (khay noi bam thumbnail Downloads)."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    idx = int(body.get("idx") or 0)
    src = (body.get("path") or "").strip()
    if not (src and os.path.isfile(src)):
        raise HTTPException(400, "file khong ton tai")
    if os.path.splitext(src)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "khong phai file anh")
    import shutil
    d = os.path.join(proj.get("dir"), "scenes")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"scene{idx}_storyboard" + os.path.splitext(src)[1].lower())
    shutil.copyfile(src, dest)
    scenes = proj.get("scenes") or []
    hit = next((s for s in scenes if s.get("idx") == idx), None)
    if hit is None:
        hit = {"idx": idx}
        scenes.append(hit)
        scenes.sort(key=lambda s: s.get("idx", 0))
    hit["storyboard"] = dest
    p = store.patch("projects", pid, scenes=scenes)
    _write_manifest(p)
    return {"ok": True, "path": dest}


@app.get("/api/file")
def serve_file(path: str):
    """Phuc vu file bat ky (anh storyboard, video scene, video hoan thien) theo duong dan tuyet doi."""
    if not os.path.isfile(path):
        raise HTTPException(404, "no file")
    mt = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mt)


# ---------- LENH (command) — cau noi UI <-> Claude agent ----------
AGENT_STATE = os.path.join(DATA_HOME, "agent.json")


@app.post("/api/agent/cancel")
def agent_cancel():
    """Nut ⛔ Hủy trong agent noi (user 2026-07-15): dat co — agent_worker poll thay co
    (mtime >= luc job start) thi taskkill /T ca cay tien trinh dang chay + tra '⛔ Đã hủy'."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    with open(os.path.join(DATA_HOME, "agent_cancel.flag"), "w", encoding="utf-8") as fh:
        fh.write(str(time.time()))
    return {"ok": True}


@app.get("/api/commands")
def commands():
    return sorted(store.list_all("commands"), key=lambda c: c.get("created", 0), reverse=True)[:50]


@app.post("/api/commands")
def add_command(body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "thieu text")
    rec = {"text": text, "status": "pending", "response": None}
    if body.get("staff"):
        rec["staff"] = body["staff"]
    if body.get("label"):
        rec["label"] = str(body["label"])[:80]
    if body.get("resume_session"):  # chat noi tiep CUNG PHIEN claude (worker them --resume)
        rec["resume_session"] = str(body["resume_session"])[:64]
    rec["engine"] = (body.get("engine") or "claude").strip() or "claude"
    return store.upsert("commands", rec)


# ---------- BO NAO (engine) — Claude / Codex / ... ----------
import shutil as _shutil


def _has(cmd):
    return bool(_shutil.which(cmd))


def _gemini_logged_in():
    """Co credential Google (GCA) chua? Gemini CLI luu oauth sau khi login."""
    g = os.path.expanduser("~/.gemini")
    for f in ("oauth_creds.json", "google_accounts.json", "google_account_id"):
        if os.path.exists(os.path.join(g, f)):
            return True
    return False


@app.get("/api/engines")
def engines():
    """Danh sach 'bo nao' kha dung tren may (UI cho chon khi giao viec)."""
    gem_ok = _has("gemini")
    return [
        {"id": "claude", "ten": "Claude", "emoji": "🧠", "available": _has("claude"),
         "note": "Não chính — mạnh nhất ở sản xuất/sáng tạo; đọc được skill."},
        {"id": "codex", "ten": "Codex (OpenAI)", "emoji": "⚡", "available": _has("codex"),
         "note": "Não phụ — hợp code/tự động hoá; KHÔNG đọc skill của Claude."},
        {"id": "gemini", "ten": "Gemini (Google)", "emoji": "✦",
         "available": gem_ok and _gemini_logged_in(),
         "note": ("Não Google (Gemini CLI). KHÔNG đọc skill Claude; dùng login Google riêng "
                  "(không phải quota Antigravity/Ultra)." + ("" if not gem_ok else
                  ("" if _gemini_logged_in() else " ⚠ CHƯA login — chạy studio/LOGIN-GEMINI.bat.")))},
        # OSS local (Ollama/LM Studio) — bat khi cai dat, chay qua `codex --oss`.
        {"id": "oss", "ten": "OSS local", "emoji": "🖥️", "available": _has("ollama"),
         "note": "Model mã nguồn mở chạy tại máy (rẻ/offline) — cần cài Ollama."},
    ]


# ---------- NHAN VIEN (skill = nhan vien) ----------
SKILLS_DIR = os.path.expanduser("~/.claude/skills")

# Ho so nhan su: moi skill = 1 nhan vien. trigger = cau kich hoat skill (ghep truoc
# viec de agent_worker goi `claude -p` dinh dung skill). vd = goi y o cong giao viec.
STAFF = [
    # --- Phong Video ---
    {"slug": "san-xuat-video-gia-dung", "ten": "Sản Xuất Video Bán Hàng", "phong": "Phòng Media", "emoji": "🛒",
     "mo_ta": "Video bán hàng affiliate ĐA NGÁCH, NHIỀU FORMAT (chọn qua format): kho xưởng neo giá · review UGC · giấu mặt lồng tiếng mẹo · KOL talking-head (phong thủy/tâm linh). Storyboard→i2v→dựng đồng bộ thoại, khoá ref per-clip.",
     "trigger": "Làm video bán hàng", "vd": "Bán [sản phẩm] — kho xưởng neo giá / review / giấu mặt mẹo / KOL nói phong thủy."},
    {"slug": "video-me-be", "ten": "Chuyên viên video Mẹ & Bé", "phong": "Phòng Media", "emoji": "👶",
     "mo_ta": "Video affiliate ngách Mẹ & Bé tả thực: mẹ ôm bé, chạm nỗi lo (sốt, biếng ăn…) → sản phẩm → CTA bình luận.",
     "trigger": "Làm video mẹ và bé", "vd": "Chủ đề bé [mọc răng/sốt/biếng ăn], sản phẩm [X]."},
    {"slug": "video-co-nhan", "ten": "Đạo diễn video Cổ Nhân", "phong": "Phòng Media", "emoji": "📜",
     "mo_ta": "Remake video cổ trang Trung Hoa (truyện đạo lý/nhân quả) style sơn dầu, giữ audio gốc, làm lại 100% b-roll Veo3.",
     "trigger": "Làm video cổ nhân", "vd": "Remake video [đường dẫn/tên] sang b-roll cổ trang nhất quán."},
    {"slug": "video-chi-dau-day-con", "ten": "Đạo diễn Chị Dậu Dạy Con", "phong": "Phòng Media", "emoji": "🎋",
     "mo_ta": "Sản xuất 1 tập hoạt hình 'Chị Dậu Dạy Con' (mẹ quê dạy con đạo lý) folk-anime, giọng Việt miền Bắc, ≤30s.",
     "trigger": "Làm video Chị Dậu Dạy Con chủ đề", "vd": "Chủ đề: dạy con về [lòng biết ơn / kiên nhẫn / trung thực]."},
    {"slug": "video-chi-dau-3d", "ten": "Đạo diễn Chị Dậu 3D", "phong": "Phòng Media", "emoji": "🧸",
     "mo_ta": "Bản 3D Pixar của Chị Dậu Dạy Con — cùng nhân vật/bối cảnh quê, chất liệu render 3D CGI mềm.",
     "trigger": "Làm video Chị Dậu 3D chủ đề", "vd": "Chủ đề: [bài học sống] phong cách 3D."},
    # --- Phong Noi dung ---
    {"slug": "san-xuat-bai-viet-viral-facebook", "ten": "Cây viết bài viral Facebook", "phong": "Nội dung", "emoji": "✍️",
     "mo_ta": "Viết bài TEXT viral đăng Facebook ngách sách (đạo lý/chữa lành), thuần giá trị, link Shopee mềm ở bình luận; đẩy Notion theo kênh.",
     "trigger": "Viết bài Facebook ngách sách", "vd": "[N] bài mỗi fanpage cho các sách [danh sách], các fanpage [danh sách]."},
    {"slug": "nhan-ban-dong-bo-notion", "ten": "Điều phối Nhân bản + Notion", "phong": "Nội dung", "emoji": "🔁",
     "mo_ta": "Nhân bản 1 kịch bản bán sách thành N bản, chọn kênh KOL từng bản, đẩy thẳng lên Notion 'Hệ Thống Nội Dung KOL 2026'.",
     "trigger": "Nhân bản và đẩy Notion", "vd": "Dán kịch bản gốc + số bản + kênh cần rải."},
    {"slug": "nhan-ban-kich-ban-sach", "ten": "Biên kịch nhân bản (bán sách)", "phong": "Nội dung", "emoji": "📚",
     "mo_ta": "Xử lý hàng đợi nhân bản kịch bản BÁN SÁCH (queue local) → đẩy Notion, tuần tự từng job.",
     "trigger": "Xử lý hàng đợi nhân bản sách", "vd": "Gặt sạch hàng đợi nhân bản sách (mỗi lần 1 job)."},
    {"slug": "nhan-ban-kich-ban-nhan-thuc", "ten": "Biên kịch nhân bản (đạo lý)", "phong": "Nội dung", "emoji": "🧘",
     "mo_ta": "Xử lý hàng đợi nhân bản kịch bản NHẬN THỨC/ĐẠO LÝ thuần giá trị (engine R-S-S-C) → đẩy Notion tag Đạo Lý.",
     "trigger": "Xử lý hàng đợi nhận thức", "vd": "Xử lý liên tục toàn bộ hàng đợi nhận thức tới khi rỗng."},
    # --- Phong Nghien cuu doi thu ---
    {"slug": "spy-scan", "ten": "Trinh sát quét đối thủ", "phong": "Nghiên cứu đối thủ", "emoji": "🔍",
     "mo_ta": "Quét kênh Facebook/TikTok từ 1 link → lọc top video nhiều view/share (≥300k) → tải về SPY/ để nghiên cứu.",
     "trigger": "Quét kênh đối thủ", "vd": "Quét [link fanpage/kênh TikTok], lấy top 20 view."},
    {"slug": "spy-teardown", "ten": "Chuyên gia bóc tách đối thủ", "phong": "Nghiên cứu đối thủ", "emoji": "🧬",
     "mo_ta": "Bóc tách video đối thủ thành 'DNA format' tái lập được rồi sinh kịch bản của mình theo format đó (nội dung nguyên bản).",
     "trigger": "Bóc tách video đối thủ", "vd": "Bóc tách [video đã tải], viết lại cho ngách [X]."},
    {"slug": "kalopilot", "ten": "Nhà phân tích TikTok Shop", "phong": "Nghiên cứu đối thủ", "emoji": "📊",
     "mo_ta": "Truy vấn dữ liệu TikTok Shop qua Kalodata: sản phẩm/shop/creator/video/ngành hàng bán chạy, doanh thu, xu hướng.",
     "trigger": "Hỏi KaloPilot", "vd": "Top sản phẩm [ngành] bán chạy 7 ngày; hoặc shop [tên] doanh thu?"},
    # --- Phong Ky thuat (nao CODEX, khong phai skill) ---
    {"slug": "codex-automation", "ten": "Kỹ sư Tự động hoá", "phong": "Kỹ thuật", "emoji": "🛠️", "brain": "codex",
     "mo_ta": "Viết/sửa script, tự động hoá tác vụ trên máy, xử lý file & dữ liệu, việc lập trình. Chạy bằng Codex (OpenAI).",
     "trigger": "", "vd": "Viết script Python đổi tên hàng loạt file trong thư mục [X] theo mẫu [Y]."},
    {"slug": "codex-devops", "ten": "Trợ lý Vận hành máy", "phong": "Kỹ thuật", "emoji": "🧰", "brain": "codex",
     "mo_ta": "Kiểm tra dịch vụ, sửa lỗi cấu hình, dọn dẹp, tác vụ hệ thống trên máy này. Chạy bằng Codex.",
     "trigger": "", "vd": "Kiểm tra vì sao START-AGENT.bat báo lỗi exit 4 và đề xuất cách sửa."},
]
_STAFF_BY = {s["slug"]: s for s in STAFF}


def _skill_desc(slug):
    try:
        txt = open(os.path.join(SKILLS_DIR, slug, "SKILL.md"), encoding="utf-8").read()
        m = re.search(r"^description:\s*(.+)$", txt, re.M)
        return (m.group(1).strip().strip('"').strip("'") if m else "")[:500]
    except Exception:
        return ""


def _staff_formats(slug):
    """Doc formats/*.json cua skill -> danh sach format {id,label,emoji}. Rong = skill 1 format."""
    fdir = os.path.join(SKILLS_DIR, slug, "formats")
    if not os.path.isdir(fdir):
        return []
    out = []
    for fn in sorted(os.listdir(fdir)):
        if not fn.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(fdir, fn), encoding="utf-8"))
        except Exception:
            d = {}
        # th = talking-head: lay talking_head neu khai, khong thi suy tu identity_mc/mc_ref
        th = bool(d.get("talking_head") if d.get("talking_head") is not None else (d.get("identity_mc") or d.get("mc_ref")))
        out.append({"id": fn[:-5], "label": d.get("label", fn[:-5]), "emoji": d.get("emoji", "🎬"),
                    "syl_min": int(d.get("syllables_min") or 40), "syl_max": int(d.get("syllables_max") or 58),
                    "env": (d.get("environment") or ""), "th": th})  # bối cảnh mặc định + talking-head
    return out


@app.get("/api/staff")
def staff():
    cmds = store.list_all("commands")
    out = []
    binds = _staff_accounts()
    for s in STAFF:
        jobs = [c for c in cmds if c.get("staff") == s["slug"]]
        busy = any(c.get("status") in ("pending", "running") for c in jobs)
        brain = s.get("brain", "claude")
        is_skill = os.path.isdir(os.path.join(SKILLS_DIR, s["slug"]))
        # nhan vien skill -> can thu muc skill; nhan vien Codex -> can co codex
        installed = is_skill if brain == "claude" else _has(brain if brain != "codex" else "codex")
        out.append({**s, "brain": brain, "is_skill": is_skill,
                    "installed": installed,
                    "flow_account": binds.get(s["slug"]),
                    "formats": _staff_formats(s["slug"]),
                    "desc_full": _skill_desc(s["slug"]) if is_skill else s.get("mo_ta", ""),
                    "jobs": len(jobs),
                    "busy": busy,
                    "last": max([c.get("created", 0) for c in jobs], default=0)})
    return out


@app.get("/api/staff/{slug}/jobs")
def staff_jobs(slug: str):
    cmds = [c for c in store.list_all("commands") if c.get("staff") == slug]
    return sorted(cmds, key=lambda c: c.get("created", 0), reverse=True)[:20]


# ---------- KICH BAN CHO DUYET (kanban) ----------
# Moi ban nhap = {kol, product, niche, staff(slug nhan vien), cau_truc(A/B/C...), tags[], hook,
#                 ly_do, scenes:[{idx,title,voice}], status, project_id, note}
# Map NGACH -> nhan vien/format (de-dau). Kich ban tu suy ra nhan vien phu trach.
_STAFF_NICHE = {
    "gia dung": "san-xuat-video-gia-dung", "nha bep": "san-xuat-video-gia-dung", "noi that": "san-xuat-video-gia-dung",
    "do gia dung": "san-xuat-video-gia-dung", "gia dung nha bep": "san-xuat-video-gia-dung",
    "me be": "video-me-be", "me va be": "video-me-be", "me and be": "video-me-be", "mom baby": "video-me-be",
}


def _resolve_staff(it):
    """staff explicit -> niche map -> mac dinh san-xuat-video-gia-dung (xuong video ban hang chung)."""
    s = (it.get("staff") or "").strip()
    if s and s in _STAFF_BY:
        return s
    nz = _ascii_vn((it.get("niche") or "")).strip().lower()
    if nz in _STAFF_NICHE:
        return _STAFF_NICHE[nz]
    for k, v in _STAFF_NICHE.items():
        if nz and (k in nz or nz in k):
            return v
    return "san-xuat-video-gia-dung"


@app.get("/api/scripts")
def scripts_list():
    return sorted(_own_rows(store.list_all("scripts")), key=lambda s: s.get("created", 0), reverse=True)


@app.post("/api/scripts")
def scripts_create(body: dict):
    """Claude day ban nhap: {items:[...]} hoac 1 ban don. Tu gan `staff` theo ngach neu thieu."""
    items = body.get("items") if isinstance(body.get("items"), list) else [body]
    member = _is_member()  # portal member: kich ban luon pending
    out = []
    for it in items:
        if not (it.get("product") or it.get("scenes") or it.get("script_text")):
            continue
        status = "pending" if member else it.get("status", "pending")
        out.append(store.upsert("scripts", {
            "kol": it.get("kol", ""), "product": it.get("product", ""),
            "niche": it.get("niche", ""), "staff": _resolve_staff(it),
            "format": (it.get("format") or "").strip(),
            "tts_voice": (it.get("tts_voice") or "").strip(),
            "channel": (it.get("channel") or "").strip(),
            "cau_truc": it.get("cau_truc", ""), "tags": it.get("tags") or [],
            "hook": it.get("hook", ""), "ly_do": it.get("ly_do", ""),
            "script_text": (it.get("script_text") or "").strip(),  # kịch bản NGUYÊN KHỐI (chia cảnh khi duyệt)
            "scenes": it.get("scenes") or [], "status": status,
            "project_id": it.get("project_id"), "note": it.get("note", "")}))
    return {"created": len(out), "items": out}


@app.post("/api/scripts/{id}/approve")
def script_approve(id: str):
    """DUYỆT = Claude Sonnet 5 CHIA CẢNH + CÂN ÂM TIẾT theo format (user 2026-07-16).
    Nguồn chữ: script_text (nguyên khối) nếu có, else ghép thoại scenes hiện có.
    Scenes đã có + TẤT CẢ trong khoảng format -> fast-path: chỉ set approved (không gọi AI)."""
    if _is_member():
        raise HTTPException(403, "chi admin duoc duyet")
    s = store.get("scripts", id)
    if not s:
        raise HTTPException(404, "no script")
    fmt = (s.get("format") or "").strip()
    if not fmt:
        raise HTTPException(400, "Chọn FORMAT trước khi duyệt (Claude cần biết nhịp thoại).")
    prof = producer.load_format(fmt)
    smin = int(prof.get("syllables_min") or 40)
    smax = int(prof.get("syllables_max") or 58)
    scenes_cur = s.get("scenes") or []
    raw_txt = (s.get("script_text") or "").strip()

    # FAST-PATH: scenes có sẵn ĐỦ (mọi cảnh có thoại, mọi âm tiết trong [smin-2, smax+2])
    # VÀ không có script_text NGUYÊN KHỐI chưa-chia (script_text còn mà chưa có scenes) -> khỏi gọi AI.
    def _scene_ok(sc):
        v = (sc.get("voice") or "").strip()
        return bool(v) and (smin - 2 <= producer._syl(v) <= smax + 2)
    raw_unchia = bool(raw_txt) and not scenes_cur  # nguyên khối chưa chia cảnh
    if scenes_cur and all(_scene_ok(sc) for sc in scenes_cur) and not raw_unchia:
        store.patch("scripts", id, status="approved")
        return {"ok": True, "fast": True, "scenes": scenes_cur}

    # Nguồn chữ để chia: script_text nguyên khối, else ghép thoại scenes hiện có.
    raw = raw_txt or " ".join((sc.get("voice") or "").strip() for sc in scenes_cur).strip()
    if not raw.strip():
        raise HTTPException(400, "Chưa có nội dung kịch bản.")

    prod = (s.get("product") or "").strip()
    hook = (s.get("hook") or "").strip()
    prompt = (
        "Bạn là ĐẠO DIỄN chia cảnh video bán hàng dọc 9:16 (mỗi cảnh = 1 clip 10 giây).\n"
        f"SẢN PHẨM: {prod or '(không rõ)'}\n"
        + (f"HOOK: {hook}\n" if hook else "")
        + "KỊCH BẢN (nguyên văn):\n" + raw + "\n\n"
        "YÊU CẦU:\n"
        f"- Chia thành các CẢNH, TỰ QUYẾT số cảnh (2-6) sao cho MỖI cảnh {smin}-{smax} tiếng.\n"
        '  (đếm tiếng = số từ cách nhau bởi dấu cách, ví dụ "túi đựng chăn màn siêu tiện" = 6 tiếng).\n'
        "- GIỮ TRỌN nội dung + giọng văn gốc; được chỉnh nhẹ câu chữ cho tròn nhịp đọc.\n"
        "- KHÔNG thêm thông tin/giá mới, KHÔNG viết HOA cả từ, KHÔNG từ khoá đặt trong ngoặc kép.\n"
        "- Mỗi cảnh 1 title 2-4 chữ (vd hook/demo/chốt).\n"
        'TRẢ VỀ DUY NHẤT 1 JSON: {"scenes":[{"idx":1,"title":"...","voice":"..."}]}. Không giải thích.')
    obj = _extract_json_obj(_ask_claude(prompt, timeout_s=180))
    if not isinstance(obj, dict) or not isinstance(obj.get("scenes"), list) or not obj["scenes"]:
        raise HTTPException(502, "Claude trả về không đúng định dạng — thử lại.")

    # Chuẩn hoá scenes mới (idx tăng dần từ 1)
    new_scenes = []
    for i, sc in enumerate(obj["scenes"], 1):
        if not isinstance(sc, dict):
            continue
        new_scenes.append({"idx": i, "title": str(sc.get("title") or "").strip(),
                            "voice": str(sc.get("voice") or "").strip()})
    if not new_scenes:
        raise HTTPException(502, "Claude trả về không đúng định dạng — thử lại.")

    # KIỂM âm tiết -> RETRY 1 LẦN cho các cảnh lệch ngoài [smin-2, smax+2]
    off = [sc for sc in new_scenes if not (smin - 2 <= producer._syl(sc["voice"]) <= smax + 2)]
    if off:
        lines = "\n".join(
            f'Cảnh {sc["idx"]} hiện {producer._syl(sc["voice"])} tiếng, cần {smin}-{smax}: "{sc["voice"]}"'
            for sc in off)
        p2 = ("Các cảnh sau chưa đúng số tiếng. Viết lại CHỈ các cảnh này, GIỮ ý, mỗi cảnh "
              f"{smin}-{smax} tiếng (đếm = số từ cách nhau dấu cách).\n" + lines +
              '\nTrả JSON {"<idx>":"thoại mới"}. Không giải thích.')
        fix = _extract_json_obj(_ask_claude(p2, timeout_s=180)) or {}
        if isinstance(fix, dict):
            for sc in new_scenes:
                nv = fix.get(str(sc["idx"]))
                if nv is None:
                    nv = fix.get(sc["idx"])
                nv = (str(nv).strip() if nv is not None else "")
                if nv:
                    sc["voice"] = nv

    warnings = [f"Cảnh {sc['idx']}: {producer._syl(sc['voice'])} âm tiết (cần {smin}-{smax})"
                for sc in new_scenes if not (smin - 2 <= producer._syl(sc["voice"]) <= smax + 2)]
    # GIỮ script_text để chia lại được
    store.patch("scripts", id, scenes=new_scenes, status="approved")
    return {"ok": True, "scenes": new_scenes, "warnings": warnings}


@app.post("/api/scripts/{id}/duplicate")
def scripts_duplicate(id: str):
    """SAO CHÉP CARD (user 2026-07-16, kiểu Trello Copy card): nhân bản kịch bản thành card MỚI
    ở cột Chờ duyệt — copy nội dung (KOL/SP/format/thoại/bối cảnh...), KHÔNG mang theo
    project_id/trạng thái sản xuất. Dùng để đổi KOL/format hoặc làm biến thể."""
    s = store.get("scripts", id)
    if not s:
        raise HTTPException(404, "no script")
    if _is_member():
        _own_guard("scripts", id)
    scenes = [{k: sc.get(k) for k in ("idx", "title", "voice", "voice_direction", "environment", "sb_beats")
               if sc.get(k) is not None} for sc in (s.get("scenes") or [])]
    dup = store.upsert("scripts", {
        "kol": s.get("kol", ""), "product": s.get("product", ""),
        "niche": s.get("niche", ""), "staff": s.get("staff", ""),
        "format": s.get("format", ""), "tts_voice": s.get("tts_voice", ""),
        "channel": s.get("channel", ""), "cau_truc": s.get("cau_truc", ""),
        "tags": list(s.get("tags") or []), "hook": s.get("hook", ""),
        "ly_do": s.get("ly_do", ""), "scenes": scenes,
        "status": "pending", "project_id": None,
        "note": s.get("note", ""), "copied_from": id})
    return {"ok": True, "id": dup["id"]}


@app.patch("/api/scripts/{id}")
def scripts_patch(id: str, body: dict):
    if _is_member():  # portal member: chi sua kich ban cua minh, KHONG duoc tu duyet
        _own_guard("scripts", id)
        if (body.get("status") or "pending") != "pending":
            raise HTTPException(403, "chi admin duoc duyet kich ban")
    r = store.patch("scripts", id, **body)
    if not r:
        raise HTTPException(404, "no script")
    return r


@app.post("/api/scripts/{id}/storyboard")
def script_to_storyboard(id: str):
    """Chuyen kich ban sang cot STORYBOARD (che do THU CONG): tao/dung lai du an DA + sinh prompt storyboard
    tung canh (khop engine 2x2, nhoi L1-L5). User tu tao anh qua ChatGPT web roi Import. KHONG render."""
    if _is_member():
        raise HTTPException(403, "storyboard/san xuat chay o Xuong (PC)")
    s = store.get("scripts", id)
    if not s:
        raise HTTPException(404, "no script")
    pid = s.get("project_id")
    proj = store.get("projects", pid) if pid else None
    if not proj:
        scenes = [{"idx": sc.get("idx", i + 1), "title": sc.get("title", ""),
                   "voice": sc.get("voice", ""), "environment": sc.get("environment", "")}
                  for i, sc in enumerate(sorted(s.get("scenes") or [], key=lambda x: x.get("idx", 0)))]
        proj = add_project({"title": (s.get("hook") or s.get("product") or "")[:120],
                            "kol": s.get("kol", ""), "product": s.get("product", ""),
                            "channel": s.get("channel", ""), "scenes": scenes, "status": "producing"})
        pid = proj["id"]
        proj = store.patch("projects", pid, format=s.get("format", ""), tts_voice=s.get("tts_voice", ""),
                           storyboard_mode="manual", nguoi_tao=s.get("nguoi_tao"))
    else:
        proj = store.patch("projects", pid, storyboard_mode="manual")
    # ĐẠO DIỄN HÌNH ẢNH: format bối cảnh động -> AI sinh environment per-cảnh trước khi ra prompt
    if _ensure_dynamic_env(s, proj):
        s = store.get("scripts", id) or s
        proj = store.get("projects", pid) or proj
    kol_lock, prod_lock = _project_locks(proj)
    scenes = sorted(proj.get("scenes") or [], key=lambda x: x.get("idx", 0))
    n = _sb_panels(proj.get("format"))
    for pos, sc in enumerate(scenes):
        role = _scene_role(pos, len(scenes))
        sc["storyboard_prompt"] = _scene_sb_prompt(proj, sc, role, kol_lock, prod_lock)
        sc["sb_beats"] = _scene_beats(role, n)  # i2v diễn đúng beat của ảnh user vẽ
    proj = store.patch("projects", pid, scenes=scenes)
    _write_manifest(proj)
    store.patch("scripts", id, status="storyboard", project_id=pid)
    return {"ok": True, "project_id": pid, "code": proj.get("code")}


# ---------- GAN TAI KHOAN FLOW CHO NHAN VIEN (moi nhan vien 1 account -> song song) ----------
STAFF_ACCOUNTS = os.path.join(DATA_HOME, "staff_accounts.json")


def _staff_accounts():
    try:
        return json.load(open(STAFF_ACCOUNTS, encoding="utf-8"))
    except Exception:
        return {}


def _save_staff_accounts(d):
    tmp = STAFF_ACCOUNTS + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, STAFF_ACCOUNTS)


def _flow_get(path, timeout=6):
    with urllib.request.urlopen(FLOW_API + path, timeout=timeout) as r:
        return json.load(r)


def _flow_post(path, body, timeout=30):
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(FLOW_API + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------- SO DO LUONG (B3 — khep vong so lieu: nhan video ↔ ket qua that) ----------
DO_LUONG = os.path.join(DATA_HOME, "do-luong.json")


@app.get("/api/do-luong")
def do_luong():
    """Bang do luong: moi video 1 ban ghi {da_code, format, cau_truc, labels, metrics}.
    xuong_core.meta.record() tu ghi khi video xong; view/don that cap nhat vao metrics."""
    if os.path.exists(DO_LUONG):
        try:
            return json.load(open(DO_LUONG, encoding="utf-8"))
        except Exception:
            pass
    return {"videos": []}


@app.patch("/api/do-luong/{key:path}")
def do_luong_patch(key: str, body: dict):
    """Cap nhat metrics/published cho 1 ban ghi (key = da_code::filename)."""
    d = do_luong()
    for v in d.get("videos", []):
        if v.get("key") == key:
            if "metrics" in body:
                v.setdefault("metrics", {}).update(body["metrics"])
            if "published" in body:
                v.setdefault("published", {}).update(body["published"])
            tmp = DO_LUONG + ".tmp"
            json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, DO_LUONG)
            return v
    raise HTTPException(404, "no record")


# ---------- THU VIEN MEDIA (video hoan thien + player Drive + trang thai dang + chi so) ----------
# Store type "media": PC tao khi publish (upload Drive); VPS sua caption/trang thai/link/chi so.
_MEDIA_STATUS = ("chua_dang", "da_dang", "len_lich")


def _clean_metrics(m):
    """Chuan hoa metrics {view, binh_luan, don} -> so (int/float) hoac None."""
    m = m if isinstance(m, dict) else {}

    def num(x):
        if x is None or x == "":
            return None
        try:
            return int(x)
        except Exception:
            try:
                return float(x)
            except Exception:
                return None

    return {"view": num(m.get("view")), "binh_luan": num(m.get("binh_luan")), "don": num(m.get("don"))}


def _media_do_luong(rec):
    """CHI o mode local (PC): do metrics cua 1 media vao do-luong.json (append/update theo project_code).
    Nuoi nao — so lieu that tu VPS ve, gan vao ban ghi do luong theo ma DA."""
    if _portal():
        return
    code = (rec.get("project_code") or "").strip()
    if not code:
        return
    m = rec.get("metrics") or {}
    try:
        d = json.load(open(DO_LUONG, encoding="utf-8")) if os.path.exists(DO_LUONG) else {"videos": []}
    except Exception:
        d = {"videos": []}
    vids = d.setdefault("videos", [])
    key = "media::" + code
    metrics = {"views": m.get("view"), "binh_luan": m.get("binh_luan"), "orders": m.get("don"),
               "updated": rec.get("metrics_at") or time.strftime("%Y-%m-%d %H:%M")}
    hit = next((v for v in vids if v.get("key") == key), None)
    if hit is None:
        vids.append({"key": key, "da_code": code, "date": time.strftime("%Y-%m-%d"),
                     "source": "media-library", "title": rec.get("title", ""),
                     "kol": rec.get("kol", ""), "product": rec.get("product", ""),
                     "channel": rec.get("channel", ""), "link_dang": rec.get("link_dang", ""),
                     "status_dang": rec.get("status_dang", ""), "metrics": metrics})
    else:
        hit.setdefault("metrics", {}).update(metrics)
        hit["status_dang"] = rec.get("status_dang", hit.get("status_dang"))
        hit["link_dang"] = rec.get("link_dang", hit.get("link_dang"))
    tmp = DO_LUONG + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, DO_LUONG)


@app.get("/api/media")
def media_list():
    return sorted(_own_rows(store.list_all("media")), key=lambda m: m.get("created", 0), reverse=True)


THUMB_DIR = os.path.join(DATA_HOME, "thumbs")


@app.get("/api/media/{id}/thumb")
def media_thumb(id: str):
    """Anh thumbnail cho card Thu vien Media: cache -> trich khung video local -> anh storyboard scene -> 404.
    Moi loi ffmpeg nuot gon roi roi xuong fallback; het cach -> 404 (UI hien placeholder)."""
    rec = store.get("media", id)
    if not rec:
        raise HTTPException(404, "no media")
    os.makedirs(THUMB_DIR, exist_ok=True)
    cache_path = os.path.join(THUMB_DIR, f"media-{id}.jpg")
    if os.path.exists(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg")

    # 1) Trich khung hinh giay 1.0 tu video local
    vp = (rec.get("video_path") or "").strip()
    if vp and os.path.exists(vp):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", vp,
                 "-frames:v", "1", "-vf", "scale=-2:480", cache_path],
                timeout=30, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return FileResponse(cache_path, media_type="image/jpeg")

    # 2) Fallback: anh storyboard cua 1 scene trong du an
    pid = rec.get("project_id")
    if pid:
        proj = store.get("projects", pid)
        if proj:
            for sc in (proj.get("scenes") or []):
                sb = (sc.get("storyboard") or "").strip() if isinstance(sc.get("storyboard"), str) else ""
                if sb and os.path.exists(sb):
                    return FileResponse(sb, media_type=mimetypes.guess_type(sb)[0] or "image/png")

    raise HTTPException(404, "no thumb")


@app.post("/api/media")
def media_create(body: dict):
    """Tao ban ghi media (thuong do luong publish_media POST sau khi upload Drive)."""
    rec = {
        "title": (body.get("title") or "").strip(),
        "project_id": body.get("project_id"),
        "project_code": (body.get("project_code") or "").strip(),
        "script_id": body.get("script_id"),
        "kol": (body.get("kol") or "").strip(),
        "product": (body.get("product") or "").strip(),
        "channel": (body.get("channel") or "").strip(),
        "drive_id": (body.get("drive_id") or "").strip(),
        "drive_link": (body.get("drive_link") or "").strip(),
        "video_path": (body.get("video_path") or "").strip(),
        "caption": body.get("caption") or "",
        "status_dang": body.get("status_dang") if body.get("status_dang") in _MEDIA_STATUS else "chua_dang",
        "link_dang": (body.get("link_dang") or "").strip(),
        "metrics": _clean_metrics(body.get("metrics")),
        "metrics_at": body.get("metrics_at"),
    }
    return store.upsert("media", rec)


@app.patch("/api/media/{id}")
def media_patch(id: str, body: dict):
    cur = store.get("media", id)
    if not cur:
        raise HTTPException(404, "no media")
    _own_guard("media", id)
    up = {}
    for k in ("title", "project_id", "project_code", "script_id", "kol", "product", "channel",
              "drive_id", "drive_link", "video_path", "caption", "link_dang"):
        if k in body:
            up[k] = body[k]
    if "status_dang" in body and body["status_dang"] in _MEDIA_STATUS:
        up["status_dang"] = body["status_dang"]
    if "metrics" in body:
        up["metrics"] = _clean_metrics(body.get("metrics"))
        up["metrics_at"] = body.get("metrics_at") or time.strftime("%Y-%m-%d %H:%M")
    r = store.patch("media", id, **up)
    if not r:
        raise HTTPException(404, "no media")
    # PC (local): metrics sua truc tiep -> do vao do-luong.json (nuoi nao)
    if not _portal() and "metrics" in up:
        _media_do_luong(r)
    return r


@app.post("/api/projects/{pid}/publish_media")
def publish_media(pid: str):
    """PC-only: tao COMMAND cho Claude upload final_video len Drive + POST /api/media.
    KHONG goi Drive truc tiep tu app.py (Drive MCP nam o tang Claude)."""
    proj = store.get("projects", pid)
    if not proj:
        raise HTTPException(404, "no project")
    fv = (proj.get("final_video") or "").strip()
    if not fv:
        raise HTTPException(400, "du an chua co video hoan thien")
    ten = proj.get("title") or proj.get("code") or pid
    script = (proj.get("script") or "").strip()
    text = (
        f"XUẤT BẢN THƯ VIỆN MEDIA — dự án {proj.get('code')} (id {pid}): \"{ten}\".\n"
        f"Video hoàn thiện (final_video): {fv}\n"
        f"KOL: {proj.get('kol') or '(chưa gán)'} · Sản phẩm: {proj.get('product') or '(chưa gán)'} · "
        f"Kênh: {proj.get('channel') or '(chưa gán)'}\n"
        "Việc:\n"
        "(1) Upload đúng file final_video ở trên lên Google Drive bằng MCP tiepphoi-publish "
        "(upload_to_drive), đặt quyền chia sẻ 'anyone with link – viewer'; lấy drive_id + drive_link.\n"
        "(2) POST http://127.0.0.1:8090/api/media (JSON) tạo bản ghi media với: "
        "title (tên video), project_id, project_code, kol, product, channel (copy từ dự án), "
        "drive_id, drive_link, video_path=final_video, "
        "caption = gợi ý caption đăng viết theo HOOK của kịch bản dưới đây (giọng bán hàng ngắn gọn, có CTA "
        "'để link dưới bình luận', KHÔNG chèn giá/badge), status_dang=chua_dang.\n"
        "(3) KHÔNG đăng lên bất kỳ nền tảng nào khác — chỉ upload Drive + tạo bản ghi. Dừng sau khi tạo xong.\n"
        + (f"\n--- KỊCH BẢN (lấy hook cho caption) ---\n{script[:1500]}" if script else ""))
    cmd = store.upsert("commands", {"text": text, "status": "pending", "response": None,
                                    "engine": "claude", "staff": "san-xuat-video-gia-dung",
                                    "label": ("⬆ Xuất bản: " + ten)[:80]})
    return {"ok": True, "command_id": cmd["id"]}


# ---------- GIONG TTS (TiepPhoi Voice :8008) — cho format long tieng (giau-mat-meo...) ----------
def _tpv_key():
    """Doc TPV_API_KEY tu .mcp.json cua workspace (nguon duy nhat, khong hardcode)."""
    try:
        mcp = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                          ".mcp.json"), encoding="utf-8"))
        env = (mcp.get("mcpServers", {}).get("tiepphoi-voice", {}) or {}).get("env", {}) or {}
        return env.get("TPV_API_KEY", ""), env.get("TPV_BASE_URL", "http://localhost:8008").rstrip("/")
    except Exception:
        return "", "http://localhost:8008"


@app.get("/api/tts-voices")
def tts_voices():
    """Proxy danh sach giong TTS tu app TiepPhoi Voice (:8008). App tat -> tra []."""
    if _portal():  # VPS khong co app :8008 -> tra rong
        return []
    key, base = _tpv_key()
    try:
        req = urllib.request.Request(base + "/api/v1/voices", headers={"X-API-Key": key} if key else {})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.load(r)
        vs = data if isinstance(data, list) else data.get("voices", [])
        return [{"id": v.get("id"), "code": v.get("code"), "name": v.get("name"),
                 "gender": v.get("gender"), "age": v.get("age"),
                 "description": v.get("description"), "preview_url": v.get("preview_url")} for v in vs]
    except Exception:
        return []


@app.get("/api/flow-accounts")
def flow_accounts_proxy():
    """Proxy danh sach tai khoan Flow tu backend :8200 (panel Tai khoan + gan nhan vien)."""
    try:
        d = _flow_get("/api/flow-accounts")
        accts = [{"email": a["email"], "label": a.get("profile_label") or a.get("display_name"),
                  "online": a.get("online"), "status": a.get("status"), "credits": a.get("credits"),
                  "cooldown_remaining_s": a.get("cooldown_remaining_s"), "token_age_s": a.get("token_age_s"),
                  "request_count": a.get("request_count"), "success_count": a.get("success_count"),
                  "failed_count": a.get("failed_count"), "gen_count_total": a.get("gen_count_total"),
                  "profile_dir": a.get("profile_dir")} for a in d.get("accounts", [])]
        return {"accounts": accts, "bridge_count": d.get("bridge_count", 0),
                "unidentified_bridges": d.get("unidentified_bridges", 0),
                "default_pin": d.get("default_account_email")}
    except Exception as e:
        return {"accounts": [], "bridge_count": 0, "error": str(e)[:150]}


@app.post("/api/flow-accounts/default")
def flow_set_default(body: dict):
    """Ghim 1 account lam default, hoac email='' de bat Auto/LRU (bo ghim)."""
    try:
        return _flow_post("/api/flow-accounts/default", {"email": (body.get("email") or "").strip()})
    except Exception as e:
        raise HTTPException(502, f"backend :8200 loi: {e}")


@app.post("/api/flow-accounts/launch-all")
def flow_launch_all():
    """Mo Chrome cho tat ca account da setup profile_dir (spawn nhieu cua so 1 lan)."""
    try:
        return _flow_post("/api/flow-accounts/launcher/launch-all", {}, timeout=60)
    except Exception as e:
        raise HTTPException(502, f"backend :8200 loi: {e}")


@app.post("/api/staff/{slug}/account")
def set_staff_account(slug: str, body: dict):
    """Khoa 1 tai khoan Flow cho nhan vien. email='' de bo gan."""
    d = _staff_accounts()
    email = (body.get("email") or "").strip().lower()
    if email:
        d[slug] = email
    else:
        d.pop(slug, None)
    _save_staff_accounts(d)
    return {"slug": slug, "flow_account": d.get(slug)}


# ---------- RENDER JOBS (hub <-> may render cam, khong LLM) ----------
# Vong doi: queued -> claimed -> rendering -> qc_pending -> approved|retry -> done|failed
RENDER_ASSETS = os.path.join(DATA_HOME, "render_jobs")
os.makedirs(RENDER_ASSETS, exist_ok=True)


@app.get("/api/render")
def render_list():
    return sorted(store.list_all("renderjobs"), key=lambda j: j.get("created", 0), reverse=True)[:100]


@app.post("/api/render")
def render_create(body: dict):
    """Hub (nao) tao job: {slug, title, spec(storyboard.json dict), ref_files[](path hub), project_id?}."""
    slug = (body.get("slug") or "").strip()
    if not slug:
        raise HTTPException(400, "thieu slug")
    job = store.upsert("renderjobs", {
        "slug": slug, "title": body.get("title", ""), "spec": body.get("spec") or {},
        "assets": [], "status": "queued", "project_id": body.get("project_id"),
        "auto_pilot": bool(body.get("auto_pilot")),  # skill on dinh -> node tu duyet neu auto-QC dat
        "node": None, "evidence": None, "verdict": None, "autoqc": None, "updated": int(time.time())})
    jdir = os.path.join(RENDER_ASSETS, job["id"])
    os.makedirs(jdir, exist_ok=True)
    assets = []
    for p in (body.get("ref_files") or []):
        if os.path.isfile(p):
            _shutil.copy(p, os.path.join(jdir, os.path.basename(p)))
            assets.append(os.path.basename(p))
    if assets:
        job = store.patch("renderjobs", job["id"], assets=assets)
    return job


@app.post("/api/render/claim")
def render_claim(body: dict = None):
    """May render goi de nhan 1 job cu nhat dang queued (atomic)."""
    node = (body or {}).get("node") or "node"
    with store._LOCK:
        rows = store._load("renderjobs")
        cand = sorted([r for r in rows if r.get("status") == "queued"], key=lambda r: r.get("created", 0))
        if not cand:
            return {"job": None}
        job = cand[0]
        job["status"] = "claimed"
        job["node"] = node
        job["updated"] = int(time.time())
        store._save("renderjobs", rows)
    return {"job": job}


@app.post("/api/render/{id}/status")
def render_status(id: str, body: dict):
    return store.patch("renderjobs", id, status=body.get("status", "rendering"),
                       node=body.get("node"), updated=int(time.time()))


@app.post("/api/render/{id}/evidence")
async def render_evidence(id: str, contact: UploadFile = File(None),
                          transcript: str = Form(""), autoqc: str = Form("")):
    """May render nop bang chung QC (contact sheet nhe + transcript + bao cao auto-QC)."""
    jdir = os.path.join(RENDER_ASSETS, id)
    os.makedirs(jdir, exist_ok=True)
    ev = {}
    if contact is not None:
        dst = os.path.join(jdir, "contact.jpg")
        with open(dst, "wb") as fh:
            fh.write(await contact.read())
        ev["contact_sheet"] = dst
    if transcript:
        ev["transcript"] = transcript
    aq = None
    if autoqc:
        try:
            aq = json.loads(autoqc)
        except Exception:
            aq = {"raw": autoqc[:500]}
    return store.patch("renderjobs", id, evidence=ev, autoqc=aq,
                       status="qc_pending", updated=int(time.time()))


@app.get("/api/render/{id}/verdict")
def render_get_verdict(id: str):
    j = store.get("renderjobs", id)
    if not j:
        raise HTTPException(404, "no job")
    return {"status": j.get("status"), "verdict": j.get("verdict")}


@app.post("/api/render/{id}/verdict")
def render_set_verdict(id: str, body: dict):
    """Hub (nao QC) duyet: {action: approve|retry, scenes?:[...], note?}."""
    action = (body.get("action") or "approve").strip()
    st = "approved" if action == "approve" else "retry"
    return store.patch("renderjobs", id, verdict=body, status=st, updated=int(time.time()))


@app.post("/api/render/{id}/done")
def render_done(id: str, body: dict = None):
    """May render bao da hoan tat (sau approve): co the kem {final, drive_url}."""
    body = body or {}
    return store.patch("renderjobs", id, status=body.get("status", "done"),
                       final=body.get("final"), drive_url=body.get("drive_url"),
                       updated=int(time.time()))


@app.get("/api/render/{id}/asset/{name}")
def render_asset(id: str, name: str):
    p = os.path.join(RENDER_ASSETS, id, os.path.basename(name))
    if not os.path.isfile(p):
        raise HTTPException(404, "no asset")
    return FileResponse(p, media_type=mimetypes.guess_type(p)[0] or "application/octet-stream")


@app.patch("/api/commands/{id}")
def patch_command(id: str, body: dict):
    return store.patch("commands", id, **body)


@app.get("/api/agent/status")
def agent_status():
    """Worker ghi heartbeat vao agent.json; UI doc de biet agent online."""
    try:
        with open(AGENT_STATE, encoding="utf-8") as fh:
            st = json.load(fh)
        st["online"] = (time.time() - st.get("beat", 0)) < 15
        return st
    except Exception:
        return {"online": False}


# ---------- BRIEF ----------
@app.get("/api/briefs")
def briefs():
    return sorted(store.list_all("briefs"), key=lambda b: b.get("created", 0), reverse=True)


@app.post("/api/briefs")
def create_brief(body: dict):
    kol = store.get("kols", body.get("kol_id"))
    product = store.get("products", body.get("product_id"))
    if not kol or not product:
        raise HTTPException(400, "kol/product khong ton tai")
    outfit = None
    oid = body.get("outfit_id")
    if oid:
        outfit = next((o for o in (kol.get("outfits") or []) if o.get("id") == oid), None)
    tpl = store.get("templates", body.get("template_id")) if body.get("template_id") else None
    return store.upsert("briefs", {
        "kol": {"name": kol["name"], "code": kol.get("code"), "identity": kol.get("identity", ""),
                "voice": kol.get("voice", ""), "refs": kol.get("refs", []), "outfit": outfit,
                "flow_project_id": kol.get("flow_project_id", ""), "voice_id": kol.get("voice_id", "")},
        "product": {"name": product["name"], "code": product.get("code"), "price": product.get("price", ""),
                    "niche": product.get("niche", ""), "info": product.get("info", ""),
                    "token_block": product.get("token_block", ""), "refs": product.get("refs", [])},
        "template": ({"name": tpl["name"], "code": tpl.get("code"), "hook": tpl.get("hook", ""),
                      "beats": tpl.get("beats", []), "notes": tpl.get("notes", ""),
                      "format": tpl.get("format", "")} if tpl else None),
        "chapters": int(body.get("chapters", 3)), "sheet_engine": body.get("sheet_engine", "chatgpt"),
        "grade": body.get("grade", "tiktok"), "format": body.get("format", "kho_xuong"),
        "instruction": body.get("instruction", ""), "status": "pending", "output": None,
    })


@app.patch("/api/briefs/{id}")
def patch_brief(id: str, body: dict):
    return store.patch("briefs", id, **body)


# ---------- output ----------
@app.get("/api/video/{id}")
def video(id: str):
    b = store.get("briefs", id)
    if not b or not b.get("output") or not os.path.exists(b["output"]):
        raise HTTPException(404, "chua co video")
    return FileResponse(b["output"], media_type="video/mp4")


@app.get("/api/image")
def image(path: str):
    if not os.path.isfile(path):
        raise HTTPException(404, "no file")
    return FileResponse(path)


# ==================== SYNC API (PC <-> VAN PHONG) ====================
SYNC_TYPES = ("kols", "products", "scripts", "media", "channels")
SYNC_LOG = os.path.join(DATA_HOME, "sync_log.jsonl")


def _sync_auth(request: Request):
    if not auth.sync_ok(request.headers.get("X-Sync-Token") or ""):
        raise HTTPException(401, "sync token khong hop le")


@app.get("/api/sync/pull")
def sync_pull(request: Request, since: float = 0.0, types: str = "kols,products,scripts,media"):
    _sync_auth(request)
    want = [t.strip() for t in (types or "").split(",") if t.strip() in SYNC_TYPES] or list(SYNC_TYPES)
    out = {}
    for kind in want:
        rows = store.list_all(kind)
        # since<=0 -> chup toan bo (ke ca record cu chua co updated_at) de SEED day du.
        rows = rows if since <= 0 else [r for r in rows if float(r.get("updated_at") or 0) > since]
        # Dich refs -> tuong doi ('refs/<name>') tren BAN COPY (kols/products co anh; scripts khong).
        if kind in ("kols", "products"):
            rows = [_serialize_record(r) for r in rows]
        out[kind] = rows
    return {"now": time.time(), "records": out}


# ---------- File sync (chuyen bytes anh ref, token-gated, ca 2 che do) ----------
@app.get("/api/sync/file/stat")
def sync_file_stat(request: Request, rel: str = ""):
    _sync_auth(request)
    dest = _safe_ref_path(rel)
    if dest is None:
        raise HTTPException(400, "rel khong hop le")
    if os.path.isfile(dest):
        return {"exists": True, "size": os.path.getsize(dest)}
    return {"exists": False, "size": 0}


@app.get("/api/sync/file")
def sync_file_get(request: Request, rel: str = ""):
    _sync_auth(request)
    dest = _safe_ref_path(rel)
    if dest is None:
        raise HTTPException(400, "rel khong hop le")
    if not os.path.isfile(dest):
        raise HTTPException(404, "khong co file")
    return FileResponse(dest, media_type=mimetypes.guess_type(dest)[0] or "application/octet-stream")


@app.post("/api/sync/file")
async def sync_file_post(request: Request, rel: str = Form(...), file: UploadFile = File(...)):
    _sync_auth(request)
    dest = _safe_ref_path(rel)
    if dest is None:
        raise HTTPException(400, "rel khong hop le")
    data = await file.read()
    if os.path.isfile(dest) and os.path.getsize(dest) == len(data):
        return {"ok": True, "skipped": True, "size": len(data)}   # idempotent
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dest)
    return {"ok": True, "skipped": False, "size": len(data)}


def _portal_allowed_fields(kind, rec):
    """Portal NHAN tu PC: chi mo field ket qua san xuat (+ co 'deleted' — lenh xoa lan 2 chieu)."""
    if kind == "scripts":
        allowed = []
        if rec.get("status") in ("producing", "done", "error"):
            allowed.append("status")
        for f in ("project_id", "final_video", "ket_qua", "video_name", "deleted"):
            if f in rec:
                allowed.append(f)
        return allowed
    if kind == "products":
        return [f for f in ("spy_refs", "deleted") if f in rec]
    if kind in ("kols", "channels"):
        return [k for k in rec.keys() if k not in ("id", "created")]
    if kind == "media":   # PC la nguon tao -> portal nhan full (title/drive/caption goi y/kol/product/channel/project)
        return [k for k in rec.keys() if k not in ("id", "created")]
    return []


def _pc_allowed_fields(kind, rec, existing):
    """PC NHAN tu portal: full — nhung KHONG ha status dang producing/done ve pending/approved."""
    if kind == "media":   # media: PC CHI nhan ket qua VPS nhap (+ deleted), khong cho portal ghi de field goc
        return [k for k in ("caption", "status_dang", "link_dang", "metrics", "metrics_at", "deleted") if k in rec]
    allowed = [k for k in rec.keys() if k not in ("id", "created")]
    if kind == "scripts" and existing.get("status") in ("producing", "done") \
            and rec.get("status") in ("pending", "approved") and "status" in allowed:
        allowed.remove("status")
    return allowed


def _apply_incoming(kind, rec, mode):
    rid = rec.get("id")
    if not rid:
        return "skip"
    # Dich refs tuong doi ('refs/<name>') -> path tuyet doi cua may nay truoc khi merge.
    if kind in ("kols", "products"):
        rec = _materialize_record(rec)
    inc_ut = float(rec.get("updated_at") or 0)
    existing = store.get(kind, rid)
    if existing is None:                       # record moi -> tao nguyen ven, giu id
        store.upsert(kind, dict(rec), stamp=False)
        return "new"
    allowed = _portal_allowed_fields(kind, rec) if mode == "portal" \
        else _pc_allowed_fields(kind, rec, existing)
    if not allowed:
        return "skip"
    if inc_ut <= float(existing.get("updated_at") or 0):   # ban dia moi hon -> giu (LWW)
        return "conflict"
    fields = {k: rec[k] for k in allowed if k in rec}
    if not fields:
        return "skip"
    fields["updated_at"] = inc_ut
    fields["origin"] = rec.get("origin") or existing.get("origin")
    store.patch(kind, rid, _stamp=False, **fields)
    # PC nhan metrics media moi tu VPS -> nuoi do-luong.json (chi mode local)
    if kind == "media" and mode == "pc" and "metrics" in fields:
        _media_do_luong(store.get("media", rid))
    return "update"


@app.post("/api/sync/push")
async def sync_push(request: Request):
    _sync_auth(request)
    body = await request.json()
    records = (body or {}).get("records") or {}
    mode = "portal" if _portal() else "pc"
    counts, conflicts = {}, 0
    for kind, recs in records.items():
        if kind not in SYNC_TYPES or not isinstance(recs, list):
            continue
        c = {"new": 0, "update": 0, "skip": 0, "conflict": 0}
        for rec in recs:
            res = _apply_incoming(kind, rec, mode)
            c[res] = c.get(res, 0) + 1
            if res == "conflict":
                conflicts += 1
        counts[kind] = c
    try:
        with open(SYNC_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "mode": mode, "from": (body or {}).get("from"),
                                "counts": counts, "conflicts": conflicts}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"ok": True, "mode": mode, "counts": counts, "conflicts": conflicts}


# ==================== KET NOI HE THONG (bat/tat/health dich vu nen) ====================
# Panel cho user bat/tat/xem health cac dich vu nen ma Xuong phu thuoc — thay viec
# chay tay cac file .bat. Nguon lenh khoi dong: dichvu/_services.ps1. Thuan stdlib.
_WS = os.path.dirname(SD)  # workspace "TiepPhoi Space" (SD = .../studio)
_AGENT_PY = os.path.join(_WS, "flowboard", "agent", ".venv", "Scripts", "python.exe")
_TTS_PY = r"C:\Users\Admin\AppData\Local\com.debpalash.omnivoice-studio\project\.venv\Scripts\python.exe"
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008

SERVICES = {
    "backend": {
        "ten": "Máy render (Flowboard :8200)", "port": 8200,
        "health": "http://127.0.0.1:8200/api/health",
        "cmd": [_AGENT_PY, "-m", "uvicorn", "flowboard.main:app", "--port", "8200",
                "--timeout-graceful-shutdown", "2"],
        "cwd": os.path.join(_WS, "flowboard", "agent"),
        "mota": "Gen ảnh/video Flow + bridge ChatGPT (bắt buộc để sản xuất)"},
    "tts": {
        "ten": "Giọng nói TTS (:8008)", "port": 8008,
        "health": "http://127.0.0.1:8008/api/v1/health",
        "cmd": [(_TTS_PY if os.path.exists(_TTS_PY) else "python"), "app.py"],
        "cwd": r"D:\AFFILATE SHOPEE 2026\CONG CU AI\TiepPhoi Voice\VN_TTS_App",
        "mota": "Lồng tiếng cho format giấu mặt (khởi động chậm ~1-3 phút)"},
    "sync": {
        "ten": "Đồng bộ Văn phòng VPS", "port": None, "health": None,
        "proc_match": "sync_agent.py",  # nhan dien qua command line
        # goi THANG python (fix 2026-07-16: bat chet ngam khi chay an — timeout/console; sync_agent tu doc sync.env + tu loop)
        "cmd": [sys.executable, os.path.join(_WS, "studio", "sync_agent.py")], "cwd": os.path.join(_WS, "studio"),
        "mota": "Đẩy dữ liệu 2 chiều PC ↔ VPS (chỉ cần khi dùng Văn phòng)"},
    "frontend": {
        "ten": "Space TiepphoiAI (:5173)", "port": 5173, "health": None,
        "cmd": ["cmd", "/c", "npm", "run", "dev"],
        "cwd": os.path.join(_WS, "flowboard", "frontend"),
        "mota": "Canvas thí nghiệm (tuỳ chọn — không bắt buộc để sản xuất)"},
}
_SVC_ORDER = ["backend", "tts", "sync", "frontend"]


def _ps(cmd_str):
    """Chay 1 lenh PowerShell, tra ve stdout ('' neu loi/timeout)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd_str],
                           capture_output=True, text=True, timeout=8,
                           creationflags=_CREATE_NO_WINDOW)
        return r.stdout or ""
    except Exception:
        return ""


def _port_pids(port):
    """PID dang LISTEN tren <port> (list int)."""
    if not port:
        return []
    out = _ps("Get-NetTCPConnection -LocalPort %d -State Listen "
              "| Select-Object -ExpandProperty OwningProcess -Unique" % int(port))
    return [int(x) for x in out.split() if x.strip().isdigit()]


def _proc_pids_by_cmdline(sub):
    """PID tien trinh python/cmd co command line chua <sub> — loai chinh studio (getpid)."""
    if not sub:
        return []
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name like '%python%' or Name like '%cmd%'\" "
              "| Where-Object { $_.CommandLine -like '*" + sub + "*' } "
              "| Select-Object -ExpandProperty ProcessId")
    me = os.getpid()
    return [int(x) for x in out.split() if x.strip().isdigit() and int(x) != me]


def _svc_running(key):
    s = SERVICES[key]
    if s.get("port"):
        return bool(_port_pids(s["port"]))
    return bool(_proc_pids_by_cmdline(s.get("proc_match") or ""))


def _svc_health(key):
    """None neu dich vu khong khai health; else True/False."""
    url = SERVICES[key].get("health")
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            return 200 <= r.getcode() < 300
    except Exception:
        return False


@app.get("/api/services")
def api_services():
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    out = []
    for key in _SVC_ORDER:
        s = SERVICES[key]
        running = _svc_running(key)
        health = _svc_health(key) if running else None  # tat -> khoi check
        detail = ""
        if key == "backend" and running:
            # trang thai bridge ChatGPT (backend con song moi hoi)
            try:
                with urllib.request.urlopen("http://127.0.0.1:8200/api/chatgpt/status", timeout=3) as r:
                    d = json.loads(r.read().decode("utf-8") or "{}")
                conn = bool((d.get("bridge") or {}).get("connected"))
                detail = "bridge ChatGPT: ✓ đã nối" if conn else "bridge ChatGPT: ✗ chưa nối (mở tab chatgpt.com)"
            except Exception:
                detail = ""
        elif key == "sync":
            try:
                ss = api_sync_status()
                detail = ("vừa đồng bộ %ss trước" % ss.get("ago")) if ss.get("alive") else "chưa hoạt động"
            except Exception:
                detail = "chưa hoạt động"
        out.append({"key": key, "ten": s["ten"], "mota": s["mota"],
                    "running": running, "health": health, "detail": detail})
    return out


@app.post("/api/services/chatgpt/open-tab")
def api_service_open_chatgpt():
    """Mo tab chatgpt.com cho user bam khi bridge chua noi."""
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "https://chatgpt.com/"],
                         creationflags=_CREATE_NO_WINDOW)
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/services/{key}/start")
def api_service_start(key: str):
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    s = SERVICES.get(key)
    if not s:
        raise HTTPException(404, "dich vu la")
    if _svc_running(key):
        return {"ok": True, "already": True}
    # khoi dong nen, KHONG cho — UI tu poll /api/services.
    # LUU Y (fix 2026-07-16): CREATE_NO_WINDOW va DETACHED_PROCESS XUNG KHAC (di cung -> co an
    # bi vo hieu -> cua so den cmd hien). Chi dung CREATE_NO_WINDOW + STARTUPINFO SW_HIDE.
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    subprocess.Popen(s["cmd"], cwd=s["cwd"],
                     creationflags=_CREATE_NO_WINDOW, startupinfo=si,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL)
    return {"ok": True}


@app.post("/api/services/{key}/stop")
def api_service_stop(key: str):
    if _is_member():
        raise HTTPException(403, "chay o Xuong (PC)")
    s = SERVICES.get(key)
    if not s:
        raise HTTPException(404, "dich vu la")
    if key == "backend":
        # chan tat may render khi con job san xuat dang chay/cho
        for j in store.list_all("produce_jobs"):
            if j.get("status") in ("queued", "running"):
                raise HTTPException(409, "Đang có job sản xuất chạy — hủy job trước khi tắt máy render.")
    if s.get("port"):
        pids = _port_pids(s["port"])
    elif key == "sync":
        # sync = ca cmd chay START-SYNC lan python sync_agent.py
        pids = sorted(set(_proc_pids_by_cmdline("sync_agent.py") + _proc_pids_by_cmdline("START-SYNC")))
    else:
        pids = _proc_pids_by_cmdline(s.get("proc_match") or "")
    killed = []
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=8,
                           creationflags=_CREATE_NO_WINDOW)
            killed.append(pid)
        except Exception:
            pass
    return {"ok": True, "killed": killed}


from fastapi.staticfiles import StaticFiles


@app.get("/")
@app.get("/index.html")
def _serve_index():
    """Serve index.html voi no-cache (user 2026-07-15): SPA 1-file (inline CSS+JS) — moi
    lan cap nhat giao dien, browser TU lay ban moi (revalidate 304 neu khong doi), khong
    con phai Ctrl+F5. StaticFiles ben duoi van phuc vu cac tai nguyen khac."""
    return FileResponse(
        os.path.join(SD, "web", "index.html"), media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"})


app.mount("/", StaticFiles(directory=os.path.join(SD, "web"), html=True), name="web")


def _sweep_orphan_jobs():
    """Studio khởi động (fix 2026-07-16): job produce/sbgen còn 'running' là MỒ CÔI
    (thread chết cùng tiến trình cũ — vd đóng cửa sổ app giữa chừng) -> đánh dấu failed
    kèm hướng dẫn, để UI không hiện 'đang chạy' ma + hiện nút Sản xuất lại."""
    now = int(time.time())
    for kind, msg in (("produce_jobs", "Studio khởi động lại giữa chừng (job mồ côi) — bấm 🎬 Sản xuất để chạy tiếp."),
                      ("sbgen_jobs", "Studio khởi động lại giữa chừng — bấm 🤖 Vẽ tất cả để vẽ tiếp (ảnh đã vẽ vẫn còn)."),
                      ("bocnao_jobs", "Studio khởi động lại giữa chừng — bấm 🧬 Bóc não để chạy tiếp (video đã bóc vẫn còn).")):
        try:
            for j in store.list_all(kind):
                if j.get("status") in ("queued", "running"):
                    store.patch(kind, j["id"], status="failed", error=msg, updated=now)
                    if kind == "produce_jobs":
                        producer._reset_script_after_stop(j)
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8090"))
    host = os.environ.get("HOST", "127.0.0.1")  # container: HOST=0.0.0.0 de cong anh xa ra ngoai
    _sweep_orphan_jobs()  # dọn job 'running' ma từ tiến trình trước
    seeded = auth.bootstrap_admin()  # tao admin mac dinh tu ADMIN_USER/ADMIN_PASSWORD neu chua co
    if seeded:
        print(f"[bootstrap] Da tao admin mac dinh: {seeded}", flush=True)
    print(f"Xuong KOL Studio -> http://{host}:{port}  (data: {DATA_HOME})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
