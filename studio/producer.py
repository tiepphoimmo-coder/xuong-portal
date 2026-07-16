# -*- coding: utf-8 -*-
"""MÁY SẢN XUẤT — dựng episode.json + chạy produce_v2 3 stage bằng CODE THUẦN (không LLM).

Gốc bệnh: agent headless `claude -p` điều phối sản xuất -> chậm (5-11') + hay treo + đắt.
Giải pháp (PLAN-MAY-SAN-XUAT.md): build_episode() lắp script->episode.json <1s, job runner chạy
subprocess produce_v2 tuần tự, ghi tiến độ vào store 'produce_jobs', hủy được. Claude rút về mép.

Kiến thức đạo diễn ĐÃ nằm trong code: cân âm tiết (bước duyệt), VOICE DIRECTION (scene), ref per-clip,
format profile, L1-L5 (xuong_core). Máy chỉ LẮP RÁP — validate sớm để không đốt quota khi sai.
"""
import json, os, re, shutil, subprocess, threading, time, unicodedata, urllib.request

import store

SD = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(SD)
CORE_DIR = WORKSPACE
SKILL_DIR = os.path.expanduser("~/.claude/skills/san-xuat-video-gia-dung")
FORMATS_DIR = os.path.join(SKILL_DIR, "formats")
PRODUCE_V2 = os.path.join(SKILL_DIR, "produce_v2.py")
PY = os.path.join(WORKSPACE, "flowboard", "agent", ".venv", "Scripts", "python.exe")
JOBS_DIR = os.path.join(WORKSPACE, "VIDEO STORYBOARD")
PROJECTS_DIR = os.path.join(WORKSPACE, "Xuong KOL AI", "Du An")
COST_LOG = os.path.join(WORKSPACE, "Xuong KOL AI", "production_cost.jsonl")

SYL_MIN, SYL_MAX = 40, 58          # âm tiết/clip 10s (talking-head native)
STAGE_TIMEOUT = {"sb": 15 * 60, "videos": 25 * 60, "assemble": 10 * 60}

_VN = "àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"


def _syl(t):
    return len(re.sub(rf"[^\w\s{_VN}]", " ", (t or "").lower()).split())


def _slug(s):
    s = (s or "").strip().lower().replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")  # bỏ dấu -> ASCII
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")[:16] or "video"


def _find_rec(kind, name):
    """Record khớp TÊN (ưu tiên tên dài nhất = cụ thể nhất)."""
    def _m(a, b):
        a, b = (a or "").strip().lower(), (b or "").strip().lower()
        return bool(a) and bool(b) and (a == b or a in b or b in a)
    best = None
    for r in store.list_all(kind):
        if _m(r.get("name"), name) and (best is None or len(r.get("name", "")) > len(best.get("name", ""))):
            best = r
    return best


def _img_of(rec, keys):
    if not rec:
        return ""
    for k in keys:
        v = rec.get(k)
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, str) and v.strip() and os.path.exists(v.strip()):
            return v.strip()
    return ""


def load_format(fmt):
    fp = os.path.join(FORMATS_DIR, f"{(fmt or '').strip()}.json")
    if (fmt or "").strip() and os.path.exists(fp):
        try:
            return json.load(open(fp, encoding="utf-8"))
        except Exception:
            pass
    return {}


# ─────────────────────────── BUILD EPISODE (thuần, unit-test được) ───────────────────────────
def build_episode(script, project, strict=True):
    """script + project registry -> episode.json dict. RAISE ValueError liệt kê lỗi nếu không hợp lệ
    (job fail sớm, không đốt quota Flow).
    strict=False (render lẻ / dựng lại): BỎ các cổng chất-lượng (âm tiết, thiếu ref, thiếu thoại) —
    clip/final đã tồn tại, chỉ dựng lại; chỉ giữ lỗi cấu trúc (thiếu FORMAT / không có cảnh)."""
    errs = []
    fmt = (script.get("format") or project.get("format") or "").strip()
    if not fmt:
        errs.append("Thiếu FORMAT — chọn Format trên thẻ kịch bản trước khi sản xuất.")
    prof = load_format(fmt)
    scenes = sorted(project.get("scenes") or script.get("scenes") or [], key=lambda s: s.get("idx", 0))
    if not scenes:
        errs.append("Không có phân cảnh nào.")

    prod_name = project.get("product") or script.get("product") or ""
    kol_name = project.get("kol") or script.get("kol") or ""
    prod_rec = _find_rec("products", prod_name)
    kol_rec = _find_rec("kols", kol_name)
    prod_img = _img_of(prod_rec, ("image", "images", "ref", "refs"))
    kol_img = _img_of(kol_rec, ("ref", "refs", "image", "images"))
    if not prod_img and strict:
        errs.append(f"Không tìm thấy ảnh sản phẩm cho '{prod_name}' trong kho (cần ít nhất 1 ảnh ref).")

    talking_head = prof.get("talking_head")
    if talking_head is None:
        talking_head = bool(prof.get("identity_mc") or prof.get("mc_ref"))

    # ÂM TIẾT theo ĐÚNG FORMAT (bám profile) — thiếu khai thì mặc định 40-58 (native talking-head 10s).
    smin = int(prof.get("syllables_min") or SYL_MIN)
    smax = int(prof.get("syllables_max") or SYL_MAX)

    clips = []
    for sc in scenes:
        dlg = (sc.get("voice") or "").strip()
        n = _syl(dlg)
        idx = sc.get("idx")
        if not dlg and strict:
            errs.append(f"Cảnh {idx}: chưa có thoại.")
        elif dlg and strict and not (smin - 2 <= n <= smax + 2):
            errs.append(f"Cảnh {idx}: thoại {n} âm tiết (format {fmt} cần {smin}-{smax}) — cân lại ở bước duyệt.")
        vdir = (sc.get("voice_direction") or "").strip()
        if not vdir and talking_head:
            vdir = "VOICE DIRECTION: " + (prof.get("voice") or "giọng tự nhiên, ngắt nghỉ hợp lý, không đọc dồn.")
        clip = {"id": idx, "dialogue": dlg}
        if vdir:
            clip["voice_direction"] = vdir
        env = (sc.get("environment") or "").strip() or prof.get("environment", "")
        if env:
            clip["environment"] = env
        if sc.get("sb_beats"):
            clip["sb_beats"] = sc["sb_beats"]
        # ref per-clip: scene ghi đè -> mặc định KOL cho talking-head (đã validate DA-0001/0002).
        ref = (sc.get("i2v_ref") or "").strip().lower()
        clip["i2v_ref"] = ref if ref in ("product", "kol", "none") else ("kol" if talking_head else "none")
        clips.append(clip)

    if errs:
        raise ValueError("Không sản xuất được:\n- " + "\n- ".join(errs))

    ep = {
        "slug": f"{(project.get('code') or 'da').lower()}-{_slug(prod_name)}",
        "format": fmt, "talking_head": bool(talking_head),
        "pov_hands": bool(prof.get("pov_hands", not talking_head)),
        "i2v_ref_kol": True,
        "tts_voice": (script.get("tts_voice") or prof.get("tts_voice") or "").strip(),
        "product": {"image": prod_img,
                    "token_block": (prod_rec or {}).get("token_block") or f"the product: {prod_name}"},
        "clips": clips,
    }
    if talking_head:
        ep["kol"] = {
            "ref": kol_img,
            "identity": ((kol_rec or {}).get("identity") or prof.get("identity_mc") or "").strip(),
            "voice": prof.get("voice") or "a natural Vietnamese voice",
        }
        if (script.get("tts_voice") or "").strip():
            ep["kol"]["voice_id"] = script["tts_voice"].strip()
    if project.get("accessory_lock"):
        ep["accessory_lock"] = project["accessory_lock"]
    if project.get("accessory_refs"):
        ep["accessory_refs"] = project["accessory_refs"]
    return ep


# ─────────────────────────── JOB RUNNER ───────────────────────────
_LOCK = threading.Lock()  # serialize: 1 render/lúc (Flow dễ reCAPTCHA khi song song)


def _jpatch(job_id, **f):
    store.patch("produce_jobs", job_id, **f)
    if f.get("status") == "failed":  # lỗi -> tra script ve trang thai cho San xuat lai
        j = store.get("produce_jobs", job_id)
        if j:
            _reset_script_after_stop(j)


def _cancelled(job_id):
    j = store.get("produce_jobs", job_id)
    return not j or j.get("status") == "cancelled"


def _run_stage(job_id, args, stage, tail_cb):
    """Chạy produce_v2 1 stage. Trả (ok, missing_clip_ids). Hủy -> taskkill /T."""
    job = store.get("produce_jobs", job_id)
    cwd = job["job_dir"]
    if os.environ.get("PRODUCE_DRY") == "1":  # nghiệm thu khô — giả lập, KHÔNG gọi Flow
        ep = json.load(open(os.path.join(cwd, "episode.json"), encoding="utf-8"))
        if stage == "sb":
            for c in ep["clips"]:
                open(os.path.join(cwd, "scenes", f"sb{c['id']}.png"), "a").close()
        elif stage == "videos":
            os.makedirs(os.path.join(cwd, "clips"), exist_ok=True)
            for c in ep["clips"]:
                open(os.path.join(cwd, "clips", f"c{c['id']}.mp4"), "a").close()
                tail_cb(stage, f"clip {c['id']}: DONE (DRY)", f"clip {c['id']} DRY")
                time.sleep(0.3)
        elif stage == "assemble":
            open(os.path.join(cwd, f"{ep['slug']}_v3_1080.mp4"), "a").close()
        return True, ""
    cmd = [PY, PRODUCE_V2] + args
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         encoding="utf-8", errors="replace", env=env, bufsize=1)
    tail, deadline = [], time.time() + STAGE_TIMEOUT.get(stage, 20 * 60)
    while True:
        line = p.stdout.readline()
        if line:
            tail.append(line.rstrip())
            tail[:] = tail[-30:]
            tail_cb(stage, line.rstrip(), "\n".join(tail))
        elif p.poll() is not None:
            break
        else:
            time.sleep(0.2)
        if _cancelled(job_id) or time.time() > deadline:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            try:
                p.wait(timeout=10)
            except Exception:
                pass
            reason = "cancelled" if _cancelled(job_id) else "timeout"
            return False, reason
    return p.returncode == 0, ""


def _run_job(job_id):
    with _LOCK:
        job = store.get("produce_jobs", job_id)
        if not job or job.get("status") == "cancelled":
            return
        t0 = time.time()
        _jpatch(job_id, status="running", stage="build", updated=int(t0))
        try:
            proj = store.get("projects", job["project_id"])
            scr = store.get("scripts", job["script_id"]) if job.get("script_id") else {}
            # render lẻ / dựng lại (có scope) -> KHÔNG kiểm cổng chất-lượng (clip/final đã có)
            ep = build_episode(scr or {}, proj, strict=not bool(job.get("scope")))
        except ValueError as e:
            _jpatch(job_id, status="failed", stage="build", error=str(e), updated=int(time.time()))
            return
        except Exception as e:  # noqa: BLE001
            _jpatch(job_id, status="failed", stage="build", error=f"build lỗi: {e}", updated=int(time.time()))
            return

        job_dir = os.path.join(JOBS_DIR, ep["slug"])
        # LÀM LẠI = LÀM MỚI (user 2026-07-16): sản xuất lại 1 dự án ĐÃ done (đổi format/thoại) ->
        # XOÁ job_dir cũ để KHÔNG dùng job_state.json (media_id clip cũ) + storyboard/clip cũ ->
        # gen lại đúng theo bản mới. Job LỖI trước đó -> GIỮ để resume (không phí quota).
        # Storyboard user tự import vẫn an toàn (nằm ở Du An/scenes, copy lại bên dưới).
        if not job.get("scope") and os.path.isdir(job_dir):
            others = [j for j in store.list_all("produce_jobs") if j.get("id") != job_id]
            prior_done = any(j.get("status") == "done" and j.get("project_id") == job["project_id"]
                             for j in others)
            # RESUME chỉ khi job TRƯỚC là bản LỖI của CHÍNH dự án này + CÙNG slug (đỡ phí quota).
            # FIX va chạm slug (2026-07-16): dự án xoá đi tạo lại TRÙNG mã DA + tên SP -> slug cũ
            # còn job_state.json với clip THOẠI CŨ -> final sai (thoại khớp 59%). Không phải ca
            # resume hợp lệ -> XOÁ làm mới.
            resumable = any(j.get("status") in ("failed", "cancelled")
                            and j.get("project_id") == job["project_id"]
                            and j.get("slug") == ep["slug"] for j in others)
            if prior_done or not resumable:
                try:
                    shutil.rmtree(job_dir)
                    _jpatch(job_id, stage_detail="làm mới: xoá job cũ, gen lại từ đầu")
                except Exception:
                    pass
        os.makedirs(os.path.join(job_dir, "scenes"), exist_ok=True)
        json.dump(ep, open(os.path.join(job_dir, "episode.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        _jpatch(job_id, job_dir=job_dir, slug=ep["slug"])

        # copy storyboard user vẽ -> sb{idx}.png (produce_v2 tự skip khi có). Cảnh thiếu -> --sb.
        pdir = proj.get("dir") or os.path.join(PROJECTS_DIR, proj.get("code", ""))
        missing = []
        for c in ep["clips"]:
            src = os.path.join(pdir, "scenes", f"scene{c['id']}_storyboard.png")
            dst = os.path.join(job_dir, "scenes", f"sb{c['id']}.png")
            if os.path.exists(src):
                if not os.path.exists(dst):
                    shutil.copyfile(src, dst)
            elif not os.path.exists(dst):
                missing.append(c["id"])

        def tail_cb(stage, line, tail):
            det = line
            m = re.search(r"clip (\d+): (DONE|tai ve|pass)", line)
            if m:
                det = f"clip {m.group(1)}: {m.group(2)}"
            # LIVE PER-CLIP (user 2026-07-15): clip vừa tải xong -> copy sang Dự án + gắn scene.video
            # NGAY để xem trong tab Dự án, không chờ dựng xong toàn bộ.
            dl = re.search(r"clip (\d+): tai ve", line)
            if dl:
                _push_clip_preview(job_id, proj["id"], job_dir, pdir, int(dl.group(1)))
            # LIVE STORYBOARD (user 2026-07-16): tấm sb vừa lưu ("sbN: ...KB)") -> đẩy về Dự án ngay
            sbm = re.search(r"^sb(\d+): .+KB\)", line.strip())
            if sbm:
                _push_sb_preview(proj["id"], job_dir, pdir, int(sbm.group(1)))
            # TRẠNG THÁI TỪNG CẢNH lúc gen video (user 2026-07-16): submit -> 'gen', tải về -> 'done'
            m2 = re.search(r"clip (\d+): (ref khoa|sb->media)", line)
            if m2:
                _set_clip_state(job_id, int(m2.group(1)), "gen")
            if dl:  # "clip N: tai ve" đã bắt ở trên
                _set_clip_state(job_id, int(dl.group(1)), "done")
            mf = re.search(r"clip (\d+): FAIL", line)
            if mf:
                _set_clip_state(job_id, int(mf.group(1)), "fail")
            _jpatch(job_id, stage=stage, stage_detail=det[:80], log_tail=tail, updated=int(time.time()))

        # SCOPE (user 2026-07-15): chạy lẻ thay vì full.
        #   None            -> full (sb thiếu -> videos -> assemble)
        #   {kind:clip,idx} -> render lại 1 clip -> assemble (final phải dựng lại)
        #   {kind:assemble} -> chỉ dựng lại khâu hoàn thiện
        scope = job.get("scope") or {}
        kind = scope.get("kind")
        if kind == "clip":
            only = str(scope.get("idx"))
            _restore_clips(job_dir, pdir, ep, skip={only})  # clip khác phải có để assemble
            stages = [("videos", ["--videos", "--only=" + only]), ("assemble", ["--assemble"])]
        elif kind == "assemble":
            _restore_clips(job_dir, pdir, ep)  # cần đủ clip cho assemble
            stages = [("assemble", ["--assemble"])]
        else:
            # KHÂU SB = CHATGPT extension (user 2026-07-16, bỏ SnapGen --sb): vẽ các cảnh thiếu
            # TRƯỚC khi vào videos; ảnh lên UI live (lưu thẳng vào Dự án).
            if missing:
                ok_sb, why_sb = _sb_via_chatgpt(job_id, proj["id"], ep, job_dir, pdir, missing)
                if not ok_sb:
                    if why_sb == "cancelled":
                        _jpatch(job_id, status="cancelled", updated=int(time.time()))
                    else:
                        _jpatch(job_id, status="failed", stage="sb", error=f"Khâu 'sb' lỗi · {why_sb}",
                                updated=int(time.time()))
                    return
            stages = [("videos", ["--videos"]), ("assemble", ["--assemble"])]
        healed = False     # tự chữa bridge tối đa 1 lần/job
        pp_fixed = False   # tự chữa mặt-bị-chặn tối đa 1 lần/job
        for stage, args in stages:
            if _cancelled(job_id):
                _jpatch(job_id, status="cancelled", updated=int(time.time()))
                return
            _jpatch(job_id, stage=stage, stage_detail="bắt đầu…", updated=int(time.time()))
            ok, why = _run_stage(job_id, args, stage, tail_cb)
            if not ok and why != "cancelled" and not healed:
                # TỰ CHỮA BRIDGE (user 2026-07-16): lỗi mang chữ ký 502/Bad Gateway = bridge Flow
                # zombie -> kill Chrome profile + relaunch + chờ nối lại -> THỬ LẠI khâu này 1 lần.
                tail = (store.get("produce_jobs", job_id) or {}).get("log_tail") or ""
                if re.search(r"502|Bad Gateway", tail + " " + str(why), re.I):
                    _jpatch(job_id, stage_detail="🔧 bridge Flow treo (502) — tự kill + relaunch…",
                            updated=int(time.time()))
                    if _heal_flow_bridge(say=lambda m: _jpatch(job_id, stage_detail=m[:80],
                                                               updated=int(time.time()))):
                        healed = True
                        ok, why = _run_stage(job_id, args, stage, tail_cb)  # retry 1 lần
            if not ok and why != "cancelled" and stage == "videos" and not pp_fixed:
                # TỰ CHỮA MẶT BỊ CHẶN (L7, user 2026-07-16): Veo PROMINENT_PEOPLE do ảnh sheet
                # (mặt idol) -> vẽ lại cảnh lỗi với FACE RULE rồi thử lại khâu videos 1 lần.
                tail = (store.get("produce_jobs", job_id) or {}).get("log_tail") or ""
                ids = sorted({int(n) for n in re.findall(r"clip (\d+): FAIL \S*PROMINENT_PEOPLE", tail)})
                if ids:
                    okpp, whypp = _redraw_blocked_faces(job_id, proj["id"], ep, job_dir, pdir, ids)
                    pp_fixed = True
                    if okpp:
                        _jpatch(job_id, stage=stage, stage_detail="🎬 gen lại clip với gương mặt mới…",
                                updated=int(time.time()))
                        ok, why = _run_stage(job_id, args, stage, tail_cb)  # retry videos
                    else:
                        _jpatch(job_id, stage_detail=whypp[:80], updated=int(time.time()))
            if not ok:
                if why == "cancelled":
                    _jpatch(job_id, status="cancelled", updated=int(time.time()))
                else:
                    _jpatch(job_id, status="failed", stage=stage,
                            error=_key_error(job_id, stage, why), updated=int(time.time()))
                return

        # finish: copy final -> Du An, PATCH project/script
        final_job = os.path.join(job_dir, f"{ep['slug']}_v3_1080.mp4")
        if not os.path.exists(final_job):
            _jpatch(job_id, status="failed", stage="finish", error="không thấy file final sau assemble",
                    updated=int(time.time()))
            return
        os.makedirs(pdir, exist_ok=True)
        final_dst = os.path.join(pdir, f"{ep['slug']}_FINAL_1080.mp4")
        shutil.copyfile(final_job, final_dst)
        # ĐẢM BẢO per-clip preview đủ (fix 2026-07-16): clip lấy từ cache không có log "tai ve"
        # -> preview chưa đẩy -> QC báo 'không thấy clip'. Finish quét đẩy bù toàn bộ.
        for c in ep["clips"]:
            _push_clip_preview(job_id, proj["id"], job_dir, pdir, c["id"])
        # GIỮ scene.video = per-clip preview (đã set live khi render) — final vào project.final_video riêng.
        store.patch("projects", proj["id"], final_video=final_dst, status="done")
        _write_manifest(proj["id"])
        if job.get("script_id"):
            store.patch("scripts", job["script_id"], status="done")
        dur = int(time.time() - t0)
        _log_cost(ep["slug"], dur)
        _jpatch(job_id, status="done", stage="finish", stage_detail="xong",
                final_video=final_dst, duration_s=dur, qc_status="running", updated=int(time.time()))
        # ⭐ QC video cuối (user 2026-07-15): chạy NỀN, KHÔNG chặn giao video. 2 lớp:
        # cơ học (Whisper thoại + thời lượng + audio + rò lưới) + mắt AI (Claude soi sản phẩm/nhân vật).
        threading.Thread(target=_qc_run, args=(job_id,), daemon=True).start()


_ERR_HINTS = [
    ("PROMINENT_PEOPLE", "Veo chặn (filter người nổi tiếng) — kiểm THOẠI có tên nghệ sĩ/người nổi tiếng "
                         "không (vd Cát Tường, Trấn Thành...); có → đổi chữ đó. Xem L6."),
    ("UNUSUAL_ACTIVITY", "Veo dính reCAPTCHA — nghỉ vài phút rồi chạy lại (đừng gen dồn)."),
    ("no_bridge_for_account", "Flow bridge chưa sẵn sàng — mở Space TiepphoiAI, kiểm tài khoản Flow online."),
    ("502", "Bridge Flow treo — máy ĐÃ tự kill+relaunch và thử lại 1 lần; vẫn lỗi nghĩa là chưa hồi, "
            "chờ 1-2 phút bấm thử lại, hoặc kiểm tài khoản Flow (đăng nhập/credits)."),
    ("SSL", "SnapGen/mạng chập lúc gen storyboard — chạy lại (idempotent, chỉ gen phần thiếu)."),
    ("timeout", "Quá thời gian cho phép của khâu — Flow chậm/kẹt; chạy lại."),
    ("THIEU clip", "Có clip gen KHÔNG ra — xem dòng FAIL phía trên để biết clip nào + vì sao."),
]


def _key_error(job_id, stage, why):
    """Trích dòng lỗi CỤ THỂ từ log_tail (thay 'exit≠0' chung chung) + gợi ý cách xử."""
    j = store.get("produce_jobs", job_id) or {}
    tail = (j.get("log_tail") or "")
    key = ""
    lines = tail.splitlines()
    for pat in (r"FAIL|PROMINENT|Traceback|Exception|Error|error", r"THIEU"):  # FAIL ưu tiên hơn THIEU
        for ln in reversed(lines):
            if re.search(pat, ln):
                key = ln.strip()[:180]
                break
        if key:
            break
    hint = next((h for k, h in _ERR_HINTS if k.lower() in tail.lower()), "")
    parts = [f"Khâu '{stage}' lỗi" + (f" ({why})" if why else "")]
    if key:
        parts.append(key)
    if hint:
        parts.append("→ " + hint)
    return " · ".join(parts)


_FLOW_API = "http://127.0.0.1:8200"


def _heal_flow_bridge(say=None):
    """TỰ CHỮA bridge Flow zombie (user 2026-07-16, bệnh án flowboard-bridge-stuck-timeout-fix):
    bridge nhìn online nhưng MỌI request 502/timeout. Phác đồ DUY NHẤT hiệu quả:
    KILL SẠCH Chrome của từng profile bridge -> relaunch qua launcher -> chờ nối lại.
    Trả True nếu bridge sống lại. say(msg) = báo tiến trình lên job."""
    say = say or (lambda m: None)
    try:
        acc = json.load(urllib.request.urlopen(_FLOW_API + "/api/flow-accounts", timeout=8))
    except Exception:
        say("🔧 không gọi được backend :8200 — bỏ qua tự chữa")
        return False
    items = acc if isinstance(acc, list) else (acc.get("items") or acc.get("accounts") or [])
    profiles = [a.get("profile_dir") for a in items if (a.get("profile_dir") or "").strip()]
    if not profiles:
        say("🔧 không có profile bridge nào khai — bỏ qua")
        return False
    # 1) kill sạch chrome của từng profile (match theo tên thư mục profile — đủ đặc trưng)
    killed = 0
    for pd in profiles:
        base = os.path.basename(pd.rstrip("\\/"))
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
              f"Where-Object {{ $_.CommandLine -like '*{base}*' }} | "
              "Select-Object -ExpandProperty ProcessId")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            for pid in re.findall(r"\d+", r.stdout or ""):
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                               capture_output=True, timeout=15, creationflags=0x08000000)
                killed += 1
        except Exception:
            pass
    say(f"🔧 đã kill {killed} tiến trình Chrome bridge — relaunch…")
    time.sleep(3)
    # 2) relaunch tất cả (launcher tự skip account đang online)
    try:
        req = urllib.request.Request(_FLOW_API + "/api/flow-accounts/launcher/launch-all",
                                     data=b"{}", headers={"Content-Type": "application/json"},
                                     method="POST")
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        say(f"🔧 relaunch lỗi: {str(e)[:80]}")
        return False
    # 3) chờ bridge nối lại (tối đa 120s) + 10s cho token ổn định
    for _ in range(40):
        time.sleep(3)
        try:
            h = json.load(urllib.request.urlopen(_FLOW_API + "/api/health", timeout=6))
            ws = h.get("ws_stats") or {}
            if ws.get("connected") and int(ws.get("bridge_count") or 0) >= 1:
                time.sleep(10)
                say("🔧 bridge đã nối lại — thử lại khâu vừa lỗi")
                return True
        except Exception:
            pass
    say("🔧 bridge KHÔNG nối lại sau 120s")
    return False


def _restore_clips(job_dir, pdir, ep, skip=None):
    """Job dir hay bị xoá .mp4 sau vài phút (chỉ png sống). Trước khi --assemble / render
    lẻ, copy NGƯỢC clip đã lưu bền ở Dự án (Du An/scenes/sceneN_clip.mp4) về job/clips/cN.mp4
    để produce_v2 tìm thấy. skip = set id KHÔNG khôi phục (clip sắp render lại)."""
    skip = {str(s) for s in (skip or set())}
    cdir = os.path.join(job_dir, "clips")
    os.makedirs(cdir, exist_ok=True)
    for c in ep.get("clips", []):
        cid = str(c["id"])
        if cid in skip:
            continue
        dst = os.path.join(cdir, f"c{cid}.mp4")
        if os.path.exists(dst):
            continue
        src = os.path.join(pdir, "scenes", f"scene{cid}_clip.mp4")
        if os.path.exists(src):
            try:
                shutil.copyfile(src, dst)
            except Exception:
                pass


def _sb_via_chatgpt(job_id, proj_id, ep, job_dir, pdir, missing):
    """KHÂU STORYBOARD qua CHATGPT extension (user 2026-07-16 — BỎ SnapGen):
    tái dùng _sb_gen_one của app (prompt + đính ref SP/KOL + 1 dự án 1 cuộc chat +
    fail-fast quota) cho TỪNG cảnh thiếu; ảnh tự lưu vào Dự án (live UI) rồi copy
    vào job/scenes/sbN.png cho produce_v2 --videos. Trả (ok, why)."""
    import app as _app  # lazy import — app đã nạp xong khi job chạy (né vòng lặp import)
    total = len(ep["clips"])
    for i, idx in enumerate(sorted(missing)):
        if _cancelled(job_id):
            return False, "cancelled"
        _jpatch(job_id, stage="sb",
                stage_detail=f"🎨 ChatGPT vẽ cảnh {idx} ({i + 1}/{len(missing)}, tổng {total} cảnh)",
                updated=int(time.time()))
        _set_clip_state(job_id, idx, "sb")
        try:
            _app._sb_gen_one(proj_id, idx)
            _set_clip_state(job_id, idx, "sb_done")
        except Exception as e:  # HTTPException (quota/bridge/timeout) hoặc lỗi khác
            _set_clip_state(job_id, idx, "fail")
            detail = getattr(e, "detail", None) or str(e)
            return False, f"ChatGPT vẽ cảnh {idx} lỗi: {str(detail)[:150]}"
        src = os.path.join(pdir, "scenes", f"scene{idx}_storyboard.png")
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(job_dir, "scenes", f"sb{idx}.png"))
    still = [c["id"] for c in ep["clips"]
             if not os.path.exists(os.path.join(job_dir, "scenes", f"sb{c['id']}.png"))]
    if still:
        return False, f"vẫn thiếu ảnh cảnh {still}"
    return True, ""


def _set_clip_state(job_id, idx, state):
    """Trạng thái TỪNG CẢNH (user 2026-07-16: hiện 'đang gen video' trên card cảnh):
    job.clip_states = {idx: sb|gen|done|fail} — UI đọc để vẽ badge live trên thẻ cảnh."""
    j = store.get("produce_jobs", job_id) or {}
    cs = dict(j.get("clip_states") or {})
    cs[str(idx)] = state
    _jpatch(job_id, clip_states=cs, updated=int(time.time()))


_FACE_RULE = ("\nFACE RULE (compliance, HIGHEST PRIORITY): draw a DIFFERENT person than in previous images — "
              "an ordinary everyday Vietnamese woman with natural, slightly imperfect features; the face must "
              "NOT resemble any celebrity, idol, actress or public figure; no flawless K-beauty idol styling.")


def _redraw_blocked_faces(job_id, proj_id, ep, job_dir, pdir, ids):
    """TỰ CHỮA PROMINENT_PEOPLE do ẢNH (L7, 2026-07-16): mặt vẽ kiểu idol -> Veo nghi người
    nổi tiếng, chặn i2v (đổi ref/không ref đều vô ích). Phác đồ: VẼ LẠI ảnh cảnh lỗi qua
    ChatGPT với FACE RULE (mặt đại trà, người KHÁC), copy sheet mới vào job, xoá media_id
    clip trong job_state để produce_v2 gen lại. Trả (ok, why)."""
    import app as _app  # lazy — né vòng lặp import
    for idx in ids:
        _jpatch(job_id, stage="sb",
                stage_detail=f"🧑‍🎨 Veo chặn mặt cảnh {idx} — vẽ lại gương mặt đại trà…",
                updated=int(time.time()))
        _set_clip_state(job_id, idx, "sb")
        try:
            proj = store.get("projects", proj_id) or {}
            scenes = proj.get("scenes") or []
            for sc in scenes:
                if sc.get("idx") == idx and (sc.get("storyboard_prompt") or "").strip():
                    if "FACE RULE" not in sc["storyboard_prompt"]:
                        sc["storyboard_prompt"] = sc["storyboard_prompt"] + _FACE_RULE
            store.patch("projects", proj_id, scenes=scenes)
            _app._sb_gen_one(proj_id, idx)
            _set_clip_state(job_id, idx, "sb_done")
        except Exception as e:  # quota/bridge...
            _set_clip_state(job_id, idx, "fail")
            return False, f"vẽ lại cảnh {idx} lỗi: {str(getattr(e, 'detail', e))[:120]}"
        src = os.path.join(pdir, "scenes", f"scene{idx}_storyboard.png")
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(job_dir, "scenes", f"sb{idx}.png"))
        # xoá state clip -> produce_v2 --videos coi là CHƯA gen, gen lại với sheet mới
        try:
            sp = os.path.join(job_dir, "job_state.json")
            stj = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
            (stj.get("clips") or {}).pop(str(idx), None)
            json.dump(stj, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return True, ""


def _push_sb_preview(proj_id, job_dir, pdir, idx):
    """Đẩy ảnh storyboard máy vừa gen (job/scenes/sbN.png) về Dự án NGAY (user 2026-07-16:
    'tạo ảnh xong chưa thấy lên giao diện') — copy sang Du An/scenes/sceneN_storyboard.png
    + gắn scene.storyboard để thẻ cảnh hiện ảnh live trong lúc job còn chạy."""
    src = os.path.join(job_dir, "scenes", f"sb{idx}.png")
    if not os.path.exists(src):
        return
    try:
        d = os.path.join(pdir, "scenes")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"scene{idx}_storyboard.png")
        shutil.copyfile(src, dst)
        proj = store.get("projects", proj_id) or {}
        scenes = proj.get("scenes") or []
        for sc in scenes:
            if sc.get("idx") == idx:
                sc["storyboard"] = dst
        store.patch("projects", proj_id, scenes=scenes)
        _write_manifest(proj_id)
    except Exception:
        pass


def _push_clip_preview(job_id, proj_id, job_dir, pdir, clip_id):
    """Copy clip vừa render (job/clips/cN.mp4) sang Dự án + gắn scene.video -> xem LIVE trong tab Dự án
    ngay khi clip xong (không chờ dựng final). Final ghi đè scene.video ở bước finish."""
    src = os.path.join(job_dir, "clips", f"c{clip_id}.mp4")
    if not os.path.exists(src):
        return
    try:
        d = os.path.join(pdir, "scenes")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"scene{clip_id}_clip.mp4")
        shutil.copyfile(src, dst)
        # PROMPT VIDEO (user 2026-07-15): produce_v2 ghi _i2v_prompt_<id>.txt — đọc lại lưu
        # vào scene.motion để hiện ở modal Chi tiết ("prompt tạo video").
        motion = ""
        pf = os.path.join(job_dir, f"_i2v_prompt_{clip_id}.txt")
        if os.path.exists(pf):
            try:
                motion = open(pf, encoding="utf-8").read().strip()
            except Exception:
                motion = ""
        proj = store.get("projects", proj_id) or {}
        scenes = proj.get("scenes") or []
        for sc in scenes:
            if sc.get("idx") == clip_id:
                sc["video"] = dst
                if motion:
                    sc["motion"] = motion
        store.patch("projects", proj_id, scenes=scenes)
        _write_manifest(proj_id)
    except Exception:
        pass


def _write_manifest(pid):
    p = store.get("projects", pid)
    d = p.get("dir") if p else None
    if d and os.path.isdir(d):
        try:
            json.dump(p, open(os.path.join(d, "project.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass


def _log_cost(slug, dur):
    try:
        with open(COST_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"slug": slug, "engine": "machine", "cost": 0,
                                 "duration_s": dur, "ts": int(time.time())}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─────────────────────────── ⭐ QC VIDEO CUỐI (2 lớp, chạy nền) ───────────────────────────
def _load_qc():
    """Nạp xuong_core/qc.py (transcript_score, qc_clip, grid_suspect…). None nếu lỗi."""
    try:
        import importlib.util
        p = os.path.join(WORKSPACE, "xuong_core", "qc.py")
        spec = importlib.util.spec_from_file_location("xuong_core_qc", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


def _ffmpeg_frames(video, out_dir, idx, n=2):
    """Trích n frame (≈25% và 70% clip) -> jpg. Trả list path."""
    out = []
    try:
        dur = 10.0
        r = subprocess.run(["ffmpeg", "-i", video], capture_output=True, text=True, timeout=20)
        mm = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", (r.stderr or ""))
        if mm:
            dur = int(mm.group(1)) * 3600 + int(mm.group(2)) * 60 + float(mm.group(3))
    except Exception:
        dur = 10.0
    for k, frac in enumerate((0.25, 0.7)[:n]):
        fp = os.path.join(out_dir, f"qc_s{idx}_{k}.jpg")
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur * frac:.2f}",
                            "-i", video, "-frames:v", "1", "-vf", "scale=540:-1", fp],
                           check=False, timeout=25)
            if os.path.exists(fp):
                out.append(fp)
        except Exception:
            pass
    return out


def _has_claude():
    return bool(shutil.which("claude") or shutil.which("claude.cmd"))


def _claude_vision_qc(frames_by_scene, ep, prod_desc, kol_desc, talking_head, timeout=300):
    """Mắt AI: Claude Read các frame -> chấm sản phẩm/nhân vật/giải phẫu mỗi cảnh.
    Best-effort: None nếu không có claude / timeout / parse lỗi (KHÔNG chặn QC)."""
    if not _has_claude() or not frames_by_scene:
        return None
    lines = []
    for c in ep["clips"]:
        fs = frames_by_scene.get(c["id"]) or []
        if not fs:
            continue
        role = "cảnh có mặt người (talking-head)" if c.get("i2v_ref") == "kol" else \
               ("cảnh cận sản phẩm" if c.get("i2v_ref") == "product" else "cảnh chung")
        lines.append(f'CẢNH {c["id"]} ({role}) — thoại: "{c.get("dialogue", "")[:80]}"\n'
                     f'  Frame: ' + " ".join(fs))
    prompt = (
        "Bạn là QC video bán hàng. ĐỌC (Read) từng ảnh frame dưới đây và chấm chất lượng MỖI CẢNH.\n\n"
        f"SẢN PHẨM đúng phải là: {prod_desc or '(xem frame cận sản phẩm)'}\n"
        + (f"NHÂN VẬT (KOL) đúng phải là: {kol_desc}\n" if talking_head and kol_desc else "")
        + "\nVỚI MỖI CẢNH, kiểm:\n"
        "- product_ok: sản phẩm trong hình có ĐÚNG mô tả trên không (đúng loại/nhãn/kết cấu, không bị AI vẽ méo/đổi)?\n"
        + ("- character_ok: người có nhất quán (cùng 1 người, không đổi mặt/tuổi/trang phục giữa cảnh)?\n" if talking_head else "")
        + "- anatomy_ok: giải phẫu ổn (không thừa/thiếu ngón tay, không cụt chân trong khung, tư thế tự nhiên)?\n"
        "- note: 1 câu tiếng Việt nêu lỗi CỤ THỂ nếu có (không lỗi thì để rỗng).\n\n"
        "TRẢ VỀ DUY NHẤT 1 JSON: {\"scenes\":[{\"id\":1,\"product_ok\":true,\"character_ok\":true,"
        "\"anatomy_ok\":true,\"note\":\"\"}, ...]}. Không giải thích thêm.\n\n"
        "Các cảnh:\n" + "\n".join(lines)
    )
    try:
        cb = shutil.which("claude") or shutil.which("claude.cmd") or "claude"
        # Windows: claude là .CMD -> subprocess KHÔNG chạy trực tiếp, phải qua cmd /c.
        # Prompt DÀI -> truyền qua STDIN (né lỗi quoting/độ dài dòng lệnh).
        base = ["cmd", "/c", cb] if (os.name == "nt" and cb.lower().endswith((".cmd", ".bat"))) else [cb]
        cmd = base + ["-p", "--output-format", "json", "--permission-mode", "bypassPermissions"]
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "").strip()
        # --output-format json bọc ngoài {"result": "...text..."}
        txt = out
        try:
            env = json.loads(out)
            txt = env.get("result") or env.get("text") or out
        except Exception:
            pass
        i, j = txt.find("{"), txt.rfind("}")
        if i < 0 or j <= i:
            return None
        return json.loads(txt[i:j + 1])
    except Exception:
        return None


def _qc_run(job_id):
    """Chạy NỀN sau khi video done. Ghi job.qc = {overall, mechanical, vision, scenes, issues}."""
    qcm = _load_qc()
    job = store.get("produce_jobs", job_id)
    if not job:
        return
    proj = store.get("projects", job.get("project_id")) or {}
    pdir = proj.get("dir") or os.path.join(PROJECTS_DIR, proj.get("code", ""))
    job_dir = job.get("job_dir") or ""
    try:
        ep = json.load(open(os.path.join(job_dir, "episode.json"), encoding="utf-8"))
    except Exception:
        _jpatch(job_id, qc_status="skipped", qc={"overall": "skip", "reason": "không đọc được episode.json"})
        return

    issues, scene_rows, frames_by_scene = [], [], {}
    qc_dir = os.path.join(job_dir, "qc")
    os.makedirs(qc_dir, exist_ok=True)

    # ── LỚP 1: cơ học từng clip (thời lượng / audio / rò lưới) ──
    for c in ep["clips"]:
        cid = c["id"]
        clip = os.path.join(pdir, "scenes", f"scene{cid}_clip.mp4")
        row = {"id": cid, "clip": os.path.basename(clip) if os.path.exists(clip) else None}
        if os.path.exists(clip):
            if qcm:
                try:
                    r = qcm.qc_clip(clip, expect_dur=10.0)
                    row["mech"] = r.get("verdict")
                    ch = r.get("checks", {})
                    if not ch.get("duration", {}).get("ok", True):
                        issues.append(f"Cảnh {cid}: thời lượng lệch ({ch['duration'].get('value')}s)")
                    if not ch.get("audio_stream", {}).get("ok", True):
                        issues.append(f"Cảnh {cid}: THIẾU tiếng")
                    if not ch.get("grid_leak", {}).get("ok", True):
                        issues.append(f"Cảnh {cid}: nghi lộ lưới storyboard")
                except Exception:
                    pass
            frames_by_scene[cid] = _ffmpeg_frames(clip, qc_dir, cid)
        else:
            row["mech"] = "no_clip"
            issues.append(f"Cảnh {cid}: không thấy clip")
        scene_rows.append(row)

    # ── LỚP 1b: Whisper thoại trên video final ──
    transcript = {}
    final = proj.get("final_video")
    if qcm and final and os.path.exists(final):
        try:
            from faster_whisper import WhisperModel  # noqa
            m = WhisperModel("small", device="cpu", compute_type="int8")
            segs, _ = m.transcribe(final, language="vi", vad_filter=True)
            got = " ".join(s.text.strip() for s in segs)
            expect = " ".join(c.get("dialogue", "") for c in ep["clips"])
            recall = qcm.transcript_score(expect, got)
            transcript = {"recall": round(recall, 3), "ok": recall >= 0.72, "got": got[:400]}
            if recall < 0.72:
                issues.append(f"Thoại lệch kịch bản (khớp {int(recall * 100)}% — nghi nuốt/độn chữ)")
        except Exception as e:  # faster_whisper chưa cài / lỗi -> bỏ qua lớp thoại
            transcript = {"ok": None, "skip": str(e)[:80]}

    # ── LỚP 2: mắt AI (best-effort) ──
    prod_rec = _find_rec("products", proj.get("product") or "")
    kol_rec = _find_rec("kols", proj.get("kol") or "")
    prod_desc = (prod_rec or {}).get("token_block") or (prod_rec or {}).get("desc") or \
                (prod_rec or {}).get("note") or (proj.get("product") or "")
    kol_desc = (kol_rec or {}).get("identity") or (kol_rec or {}).get("token_block") or \
               (kol_rec or {}).get("desc") or (proj.get("kol") or "")
    talking_head = any(c.get("i2v_ref") == "kol" for c in ep["clips"])
    vision = _claude_vision_qc(frames_by_scene, ep, str(prod_desc)[:400], str(kol_desc)[:400], talking_head)
    if vision and isinstance(vision.get("scenes"), list):
        vmap = {s.get("id"): s for s in vision["scenes"]}
        for row in scene_rows:
            v = vmap.get(row["id"])
            if not v:
                continue
            row["vision"] = {k: v.get(k) for k in ("product_ok", "character_ok", "anatomy_ok", "note")}
            if v.get("product_ok") is False:
                issues.append(f"Cảnh {row['id']}: sản phẩm SAI/méo — {v.get('note', '')}".strip(" —"))
            if talking_head and v.get("character_ok") is False:
                issues.append(f"Cảnh {row['id']}: nhân vật không nhất quán — {v.get('note', '')}".strip(" —"))
            if v.get("anatomy_ok") is False:
                issues.append(f"Cảnh {row['id']}: lỗi giải phẫu — {v.get('note', '')}".strip(" —"))

    overall = "fix" if issues else "pass"
    qc = {"overall": overall, "issues": issues, "scenes": scene_rows,
          "transcript": transcript, "vision_ran": bool(vision),
          "mech_ran": bool(qcm), "ts": int(time.time())}
    _jpatch(job_id, qc_status="done", qc=qc)
    # ⭐ AUTO-PUBLISH (user 2026-07-16): QC xong -> tự gửi lệnh đẩy Drive + Notion của KOL.
    _auto_publish(job_id, proj, qc)


def _auto_publish(job_id, proj, qc):
    """AUTO-PUBLISH sau khi video XONG (user 2026-07-16): enqueue 1 COMMAND cho Claude agent
    (có MCP tiepphoi-publish) upload final_video lên Drive + tạo/cập nhật page Notion của KOL
    (KỊCH BẢN đầy đủ + CAPTION tự sinh + LINK VIDEO Drive). KHÔNG chặn QC — agent_worker tự nhặt.
    Guard: chỉ FULL produce (không scope), có final_video, và CHƯA publish (proj.auto_pub_cmd rỗng
    -> không lặp). VẪN publish khi qc.overall='fix' (user muốn tự động) — trạng thái QC ghi vào Notion."""
    try:
        job = store.get("produce_jobs", job_id) or {}
        if job.get("scope"):
            return  # chỉ full produce mới auto-publish (render lẻ/dựng lại -> bỏ qua)
        pid = proj.get("id")
        if not pid:
            return
        proj = store.get("projects", pid) or proj  # tra bản mới nhất (đọc auto_pub_cmd + final_video)
        final_video = (proj.get("final_video") or "").strip()
        if not final_video or not os.path.exists(final_video):
            return
        if (proj.get("auto_pub_cmd") or "").strip():
            return  # đã gửi lệnh xuất bản trước đó -> không lặp

        da = proj.get("code") or pid
        name = proj.get("title") or da
        kol = proj.get("kol") or ""
        product = proj.get("product") or ""
        kol_rec = _find_rec("kols", kol)
        notion_db = ((kol_rec or {}).get("notion_db") or "").strip()
        # ── Resolve KÊNH đăng (nền tảng + trang Notion để nối relation) ──
        chan_name = (proj.get("channel") or (kol_rec or {}).get("channel") or "").strip()
        # proj.channel có thể là ID record (vd "ead86b5b") — tra ID trước, tên sau
        chan_rec = (store.get("channels", chan_name) or _find_rec("channels", chan_name)) if chan_name else None
        platform = ((chan_rec or {}).get("platform") or "").lower()
        notion_kenh = ((chan_rec or {}).get("notion_page_name") or "").strip()
        # KỊCH BẢN đầy đủ = ghép thoại các cảnh (fallback: script gốc của dự án)
        scenes = sorted(proj.get("scenes") or [], key=lambda s: s.get("idx", 0))
        script_full = "\n".join(
            f"Cảnh {sc.get('idx')}: {(sc.get('voice') or '').strip()}"
            for sc in scenes if (sc.get("voice") or "").strip()
        ) or (proj.get("script") or "").strip()
        qc_overall = (qc or {}).get("overall") or "?"
        notion_line = (f" trên DATABASE của KOL: {notion_db}" if notion_db else " (bảng mặc định)")

        # ── Bước 2: CAPTION theo nền tảng kênh ──
        if platform == "tiktok":
            caption_line = (
                "2. VIẾT CAPTION bán hàng TikTok (tiếng Việt, 1-2 câu chạm nỗi đau + lợi ích): "
                f'BẮT BUỘC nhắc TÊN SẢN PHẨM "{product}" tự nhiên trong caption; TUYỆT ĐỐI KHÔNG dùng '
                "'link ở bình luận' hay bất kỳ CTA dẫn link nào (CTA bằng hành động: 'lưu lại', "
                "'thử ngay'…); 3-5 hashtag ngách; KHÔNG số giá. Dựa kịch bản sau: "
                f'"{script_full}".\n'
            )
        else:
            caption_line = (
                "2. VIẾT CAPTION bán hàng TikTok (tiếng Việt, 1-2 câu chạm nỗi đau + lợi ích, 3-5 hashtag "
                "ngách, kết 'link ở bình luận' — KHÔNG số giá): dựa kịch bản sau: "
                f'"{script_full}".\n'
            )

        # ── Bước 4: chỉ dẫn nối relation KÊNH trên Notion ──
        _NEN_TANG = {"tiktok": "Tiktok", "facebook": "Facebook", "youtube": "YouTube"}
        nen_tang = _NEN_TANG.get(platform, "")
        if notion_kenh:
            nt_part = f' và nen_tang="{nen_tang}"' if nen_tang else ""
            kenh_line = (
                f" · liên kết relation KÊNH: khi gọi MCP tiepphoi-publish create_video_page/publish_full "
                f'truyền kenh="{notion_kenh}"{nt_part}.'
            )
        else:
            kenh_line = " · kênh chưa nối Notion — bỏ trống relation KÊNH."

        # Command text TỰ CHỨA (build từng phần cho sạch, né f-string lồng {} JSON).
        text = (
            f"Xuất bản video {da} — {name}:\n"
            f'1. Video final: "{final_video}" (đường dẫn tuyệt đối).\n'
            + caption_line +
            "3. Upload video lên Google Drive bằng MCP tiepphoi-publish (upload_to_drive / publish_full "
            "theo đúng cẩm nang memory tiepphoi-publish-mcp).\n"
            f"4. Tạo/cập nhật page Notion cho video theo mã {da}{notion_line} — điền: tiêu đề "
            f"{da} · {product}, KỊCH BẢN đầy đủ (thoại từng cảnh), CAPTION vừa viết, LINK VIDEO Drive, "
            f'KOL "{kol}", sản phẩm "{product}", trạng thái QC: {qc_overall}, ngày.'
            + kenh_line + "\n"
            f"5. PATCH http://127.0.0.1:8090/api/projects/{pid} JSON "
            '{"drive_link": <link>, "caption": <caption>, "published_at": <ISO>} và tạo bản ghi '
            "Thư viện Media như luồng Xuất bản hiện có (xem hướng dẫn trong lệnh publishMedia nếu cần).\n"
            "Chạy ĐỒNG BỘ trong phiên, xong mới trả lời."
        )
        cmd = store.upsert("commands", {"text": text, "status": "pending", "response": None,
                                        "engine": "claude", "staff": "san-xuat-video-gia-dung",
                                        "label": (f"📤 Xuất bản {da}")[:80]})
        store.patch("projects", pid, auto_pub_cmd=cmd["id"])
        _jpatch(job_id, stage_detail="📤 đã gửi lệnh xuất bản Drive+Notion (Claude đang chạy)")
    except Exception:
        pass  # auto-publish best-effort — KHÔNG làm hỏng QC/job


def start_produce(project_id, script_id=None, scope=None):
    """Tạo job + chạy thread nền. Trả job record. Đang có job running -> job mới xếp queued
    (thread vẫn start nhưng _LOCK serialize). scope: None=full · {kind:clip,idx} · {kind:assemble}."""
    rec = {
        "project_id": project_id, "script_id": script_id,
        "status": "queued", "stage": "queued", "stage_detail": "", "log_tail": "",
        "error": "", "created": int(time.time()), "updated": int(time.time())}
    if scope:
        rec["scope"] = scope
    job = store.upsert("produce_jobs", rec)
    threading.Thread(target=_run_job, args=(job["id"],), daemon=True).start()
    return job


def start_rerender_clip(project_id, idx, script_id=None):
    """Render lại DUY NHẤT clip idx rồi dựng lại final (user 2026-07-15)."""
    return start_produce(project_id, script_id, scope={"kind": "clip", "idx": int(idx)})


def start_reassemble(project_id, script_id=None):
    """Dựng lại KHÂU HOÀN THIỆN (ghép + grade + final) từ các clip đã có (user 2026-07-15)."""
    return start_produce(project_id, script_id, scope={"kind": "assemble"})


def _reset_script_after_stop(job):
    """Huy/loi -> tra script ve trang thai cho phep San xuat lai (khong ket 'producing').
    Co storyboard -> 'storyboard'; chua co -> 'approved'. Project ve 'planning'."""
    sid = job.get("script_id")
    if sid and store.get("scripts", sid):
        proj = store.get("projects", job.get("project_id")) or {}
        has_sb = any(sc.get("storyboard") for sc in (proj.get("scenes") or []))
        cur = (store.get("scripts", sid) or {}).get("status")
        if cur == "producing":  # chi reset khi dang ket o producing
            store.patch("scripts", sid, status="storyboard" if has_sb else "approved")
    if job.get("project_id"):
        p = store.get("projects", job["project_id"])
        if p and p.get("status") == "producing":
            store.patch("projects", job["project_id"], status="planning")


def cancel_job(job_id):
    j = store.get("produce_jobs", job_id)
    if not j:
        return None
    r = store.patch("produce_jobs", job_id, status="cancelled", updated=int(time.time()))
    _reset_script_after_stop(j)
    return r
