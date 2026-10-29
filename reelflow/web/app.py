"""ReelFlow web app: client pages (upload, voice sample, review + Yes/Change), admin (sign-up, all clients),
an API for the publisher (Claude routine with the Uplika connector), and the minute scheduler.

Run:  ADMIN_TOKEN=... PUBLIC_BASE_URL=https://your.host uvicorn web.app:app --host 0.0.0.0 --port 8000  (from reelflow/)
"""
import datetime as dt
import glob
import hmac
import json
import os
import shutil
import sys
import tempfile
import threading
import time

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reelflow import notify, onboard, pipeline, scheduler  # noqa: E402
from reelflow.common import (REPO, ReelFlowError, cpath, list_clients, load_client, load_state,  # noqa: E402
                             media_kind, save_client, save_state)

app = FastAPI(title="ReelFlow")
T = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
LOG = []

STAGE_TEXT = {"idle": "Photos ka intezaar", "nudged": "Aaj ki photos ka intezaar", "rendering": "Reel ban rahi hai...",
              "in_review": "Reel tayyar - aapka jawab chahiye", "approved": "Approved - post ho rahi hai"}


def log(*a):
    LOG.append(f"{time.strftime('%d %b %H:%M:%S')} " + " ".join(str(x) for x in a))
    del LOG[:-300]


@app.on_event("startup")
def _start():
    if os.environ.get("REELFLOW_SCHEDULER", "1") == "1":
        scheduler.start_background(log=log)


# ---------- auth ----------
def admin(tok):
    want = os.environ.get("ADMIN_TOKEN")
    if not want or not hmac.compare_digest(tok, want):
        raise HTTPException(404)


def client_auth(cid, tok):
    try:
        c = load_client(cid)
    except ReelFlowError:
        raise HTTPException(404)
    if not hmac.compare_digest(tok, onboard.client_token(c)):
        raise HTTPException(404)
    return c


def base_url(request):
    return os.environ.get("PUBLIC_BASE_URL", str(request.base_url)).rstrip("/")


def reel_url(request, c, name):
    return f"{base_url(request)}/files/{c['id']}/{onboard.client_token(c)}/reel/{name}.mp4"


def run_bg(fn, *a, **k):
    def go():
        try:
            log(fn.__name__, "->", fn(*a, **k))
        except Exception as e:  # shown on the page via state["error"]
            log(fn.__name__, "failed:", e)
    threading.Thread(target=go, daemon=True).start()


# ---------- client pages ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return T.TemplateResponse(request, "landing.html", {})


@app.get("/c/{cid}/{tok}", response_class=HTMLResponse)
def client_home(request: Request, cid: str, tok: str, msg: str = ""):
    c = client_auth(cid, tok)
    st = load_state(c)
    inbox = cpath(c, "inbox")
    waiting = [f.split("__", 1)[-1] for f in sorted(os.listdir(inbox)) if media_kind(f)] if os.path.isdir(inbox) else []
    return T.TemplateResponse(request, "client.html", {
        "c": c, "st": st, "tok": tok, "msg": msg, "stage_text": STAGE_TEXT.get(st.get("stage"), st.get("stage")),
        "waiting": waiting, "busy": pipeline.busy(cid) or st.get("stage") == "rendering",
        "reel": f"/files/{cid}/{tok}/reel/{st['name']}.mp4?v={st.get('version', 1)}" if st.get("stage") in ("in_review", "approved") else "",
        "history": list(reversed(st.get("history", [])))[:10]})


@app.post("/c/{cid}/{tok}/upload")
async def upload(cid: str, tok: str, files: list[UploadFile] = File(...)):
    c = client_auth(cid, tok)
    inbox = cpath(c, "inbox")
    os.makedirs(inbox, exist_ok=True)
    batch, n = time.strftime("%Y%m%d%H%M%S"), 0
    for f in files[:5]:
        name = os.path.basename(f.filename or "file")
        if not media_kind(name):
            continue
        with open(os.path.join(inbox, f"{batch}__{name}"), "wb") as out:
            shutil.copyfileobj(f.file, out)
        n += 1
    if not n:
        return RedirectResponse(f"/c/{cid}/{tok}?msg=Sirf photo/video upload kijiye (jpg, png, mp4, mov)", 303)
    st = load_state(c)
    if st.get("stage") in ("idle", "nudged", None):
        run_bg(pipeline.make, c)
        m = f"{n} file mil gayi. Reel ban rahi hai, 5-15 minute me yahin dikhegi."
    else:
        m = f"{n} file mil gayi. Abhi wali Reel post hone ke baad inki Reel banegi."
    return RedirectResponse(f"/c/{cid}/{tok}?msg={m}", 303)


@app.post("/c/{cid}/{tok}/approve")
def approve(request: Request, cid: str, tok: str):
    c = client_auth(cid, tok)
    st = load_state(c)
    if st.get("stage") != "in_review":
        return RedirectResponse(f"/c/{cid}/{tok}?msg=Abhi koi Reel review me nahi hai", 303)
    pipeline.approve(c, media_url=reel_url(request, c, st["name"]))
    return RedirectResponse(f"/c/{cid}/{tok}?msg=Shukriya! Reel post ho rahi hai, link yahin aayega.", 303)


@app.post("/c/{cid}/{tok}/change")
def change(cid: str, tok: str, text: str = Form(...)):
    c = client_auth(cid, tok)
    if load_state(c).get("stage") != "in_review" or not text.strip():
        return RedirectResponse(f"/c/{cid}/{tok}?msg=Change likh ke bhejiye", 303)
    run_bg(pipeline.make, c, change_request=text.strip())
    return RedirectResponse(f"/c/{cid}/{tok}?msg=Change mil gaya. Nayi Reel 5-15 minute me yahin.", 303)


@app.get("/c/{cid}/{tok}/status.json")
def status(cid: str, tok: str):
    c = client_auth(cid, tok)
    st = load_state(c)
    return {"stage": st.get("stage"), "busy": pipeline.busy(cid), "version": st.get("version"), "error": st.get("error")}


@app.get("/c/{cid}/{tok}/voice", response_class=HTMLResponse)
def voice_page(request: Request, cid: str, tok: str, msg: str = ""):
    c = client_auth(cid, tok)
    return T.TemplateResponse(request, "voice.html", {"c": c, "tok": tok, "msg": msg, "sample_text": onboard.SAMPLE_TEXT_HI})


@app.post("/c/{cid}/{tok}/voice")
async def voice_upload(cid: str, tok: str, file: UploadFile = File(...)):
    client_auth(cid, tok)
    with tempfile.NamedTemporaryFile(suffix=os.path.splitext(file.filename or "a.webm")[1] or ".webm", delete=False) as t:
        shutil.copyfileobj(file.file, t)
    try:
        d = onboard.save_voice_sample(cid, t.name)
        m = f"Awaaz save ho gayi ({d:.0f} sec). Ab har Reel isi awaaz me banegi."
    except ReelFlowError as e:
        m = str(e)
    finally:
        os.remove(t.name)
    return RedirectResponse(f"/c/{cid}/{tok}?msg={m}", 303)


@app.get("/files/{cid}/{tok}/reel/{name}.mp4")
def reel_file(cid: str, tok: str, name: str):
    c = client_auth(cid, tok)
    for d in (cpath(c, "review"), cpath(c, "posted_reels")):
        f = os.path.join(d, f"{os.path.basename(name)}-reel.mp4")
        if os.path.exists(f):
            return FileResponse(f, media_type="video/mp4")
    raise HTTPException(404)


@app.get("/files/{cid}/{tok}/voice.wav")
def voice_file(cid: str, tok: str):
    c = client_auth(cid, tok)
    f = os.path.join(c["_dir"], c["voice"].get("sample") or "voice/sample.wav")
    if not os.path.exists(f):
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav")


# ---------- admin ----------
def _overview(request):
    rows = []
    for cid in list_clients():
        c = load_client(cid)
        st = load_state(c)
        rows.append({"c": c, "st": st, "link": f"{base_url(request)}/c/{cid}/{onboard.client_token(c)}",
                     "busy": pipeline.busy(cid), "voice_ok": bool(c["voice"].get("sample") or c["voice"].get("sarvam_voice_id")),
                     "stage_text": STAGE_TEXT.get(st.get("stage"), st.get("stage"))})
    return rows


@app.get("/admin/{tok}", response_class=HTMLResponse)
def admin_home(request: Request, tok: str, msg: str = ""):
    admin(tok)
    return T.TemplateResponse(request, "admin.html", {"tok": tok, "rows": _overview(request), "msg": msg,
                                                       "pending": _pending(), "log": list(reversed(LOG))[:40]})


@app.get("/admin/{tok}/signup", response_class=HTMLResponse)
def signup_page(request: Request, tok: str):
    admin(tok)
    return T.TemplateResponse(request, "signup.html", {"tok": tok})


@app.post("/admin/{tok}/signup")
async def signup(request: Request, tok: str, logo: UploadFile | None = File(None)):
    admin(tok)
    form = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    lp = None
    if logo is not None and logo.filename:
        with tempfile.NamedTemporaryFile(suffix=os.path.splitext(logo.filename)[1], delete=False) as t:
            shutil.copyfileobj(logo.file, t)
            lp = t.name
    try:
        c, ctok = onboard.create_client(form, lp)
    except ReelFlowError as e:
        return RedirectResponse(f"/admin/{tok}?msg={e}", 303)
    finally:
        if lp:
            os.remove(lp)
    return RedirectResponse(f"/admin/{tok}/client/{c['id']}?msg=Client ban gaya. Link client ko bhejiye.", 303)


@app.get("/admin/{tok}/client/{cid}", response_class=HTMLResponse)
def admin_client(request: Request, tok: str, cid: str, msg: str = ""):
    admin(tok)
    c = load_client(cid)
    return T.TemplateResponse(request, "admin_client.html", {
        "tok": tok, "c": c, "st": load_state(c), "msg": msg,
        "link": f"{base_url(request)}/c/{cid}/{onboard.client_token(c)}",
        "json": json.dumps({k: v for k, v in c.items() if not k.startswith('_')}, ensure_ascii=False, indent=1)})


@app.post("/admin/{tok}/client/{cid}")
async def admin_client_save(request: Request, tok: str, cid: str):
    admin(tok)
    c = load_client(cid)
    f = await request.form()
    try:
        new = json.loads(f["json"])
        assert new.get("id") == cid, "id cannot change"
    except Exception as e:  # noqa: BLE001
        return RedirectResponse(f"/admin/{tok}/client/{cid}?msg=Not saved: {e}", 303)
    new["_dir"] = c["_dir"]
    save_client(new)
    return RedirectResponse(f"/admin/{tok}/client/{cid}?msg=Saved", 303)


@app.post("/admin/{tok}/client/{cid}/{action}")
async def admin_action(request: Request, tok: str, cid: str, action: str):
    admin(tok)
    c = load_client(cid)
    f = await request.form()
    if action == "nudge":
        run_bg(pipeline.nudge, c)
    elif action == "make":
        run_bg(pipeline.make, c)
    elif action == "posted":
        pipeline.posted(c, f.get("permalink", "").strip())
    elif action == "reset":
        st = load_state(c)
        st.update(stage="idle", error=None)
        st.pop("failed_batch", None)
        save_state(c, st)
    elif action == "newlink":
        onboard.issue_token(c)
    return RedirectResponse(f"/admin/{tok}?msg={cid}: {action} done", 303)


# ---------- publisher API (used by the Claude routine that holds the Uplika connector) ----------
def _pending():
    out = []
    for cid in list_clients():
        c = load_client(cid)
        for f in sorted(glob.glob(os.path.join(c["_dir"], "outbox", "*-publish_request.json"))):
            out.append({"client": cid, "name": c["name"], "file": os.path.basename(f), **json.load(open(f))})
    return out


@app.get("/api/{tok}/pending")
def api_pending(tok: str):
    admin(tok)
    return _pending()


@app.post("/api/{tok}/posted")
async def api_posted(tok: str, request: Request):
    """Body: {"client": "<id>", "permalink": "https://www.instagram.com/reel/..."}"""
    admin(tok)
    b = await request.json()
    c = load_client(b["client"])
    try:
        pipeline.posted(c, b["permalink"])
    except ReelFlowError as e:
        return JSONResponse({"ok": False, "error": str(e)}, 409)
    sent = os.path.join(c["_dir"], "outbox", "sent")
    os.makedirs(sent, exist_ok=True)
    for f in glob.glob(os.path.join(c["_dir"], "outbox", "*-publish_request.json")):
        shutil.move(f, os.path.join(sent, os.path.basename(f)))
    return {"ok": True}


@app.get("/api/{tok}/status")
def api_status(request: Request, tok: str):
    admin(tok)
    return [{"client": r["c"]["id"], "stage": r["st"].get("stage"), "error": r["st"].get("error"),
             "updated": r["st"].get("updated"), "link": r["link"]} for r in _overview(request)]


@app.get("/healthz")
def health():
    return {"ok": True, "clients": len(list_clients()), "time": dt.datetime.now().isoformat(timespec="seconds")}
