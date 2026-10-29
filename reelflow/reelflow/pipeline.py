"""The daily pipeline for one client. Each step is idempotent and records its stage in state.json.

nudge   -> trend + shot list message (9 am)
make    -> next upload batch -> frames -> script (Claude) -> voice -> render -> review package
change  -> same media, owner's change request -> new version -> review package
approve -> publish request (Uplika) ; posted -> archive files, back to idle
"""
import datetime as dt
import json
import os
import re
import shutil
import threading

from . import media, script, trends, voice
from .common import REPO, ReelFlowError, cpath, load_state, outbox, render_lock, save_state, sh


def nudge(client):
    st = load_state(client)
    trend = trends.todays_angle(client)
    st.update(stage="nudged" if st["stage"] in ("idle", "posted", "nudged") else st["stage"], trend=trend)
    save_state(client, st)
    msg = (f"Aaj ka trend: {trend['trend_line']}\n\nAaj ye shoot kijiye (phone khada, 9:16):\n" +
           "\n".join(f"{i + 1}. {s}" for i, s in enumerate(trend["shots"])) +
           f"\n\nUpload: {client['upload_link']}")
    return outbox(client, "nudge", {"text": msg, "trend": trend})


def _name(batch):
    base = os.path.splitext(os.path.basename(batch[0]))[0]
    return f"{dt.date.today():%Y%m%d}-" + re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:30]


_locks = {}


def busy(cid):
    return _locks.setdefault(cid, threading.Lock()).locked()


def make(client, change_request=None):
    """One make per client at a time (upload, scheduler and change can race)."""
    lock = _locks.setdefault(client["id"], threading.Lock())
    if not lock.acquire(blocking=False):
        raise ReelFlowError("a Reel is being made right now")
    try:
        return _make(client, change_request)
    finally:
        lock.release()


def _make(client, change_request=None):
    st = load_state(client)
    st["error"] = None
    if change_request:
        if st.get("stage") != "in_review":
            raise ReelFlowError("no Reel in review to change")
        batch, name, prev = st["batch"], st["name"], json.dumps(st["plan"], ensure_ascii=False)
        version = st.get("version", 1) + 1
    else:
        if st.get("stage") in ("in_review", "approved"):
            raise ReelFlowError(f"a Reel is already {st['stage']}; approve/post it first (never post twice)")
        batch = media.next_batch(client)
        if not batch:
            return None  # nothing uploaded: the nudge already asked for photos
        name, prev, version = _name(batch), None, 1
    before = st.get("stage")
    st.update(stage="rendering", rendering=name)
    save_state(client, st)
    try:
        return _render(client, st, batch, name, prev, version, change_request)
    except Exception as e:
        st = load_state(client)
        st.update(stage=before, error=f"{type(e).__name__}: {e}"[:800])
        save_state(client, st)
        outbox(client, "error", {"text": f"Reel {name} could not be made: {e}"[:800]})
        raise


def _render(client, st, batch, name, prev, version, change_request):
    work = os.path.join(client["_dir"], "work", name)
    frames, index = media.describe(batch, os.path.join(work, "frames"))
    plan = script.write_plan(client, frames, index, st.get("trend", {}), change_request, prev)
    review = cpath(client, "review")
    os.makedirs(review, exist_ok=True)
    spec = script.to_spec(client, plan, work, {})
    voice_dir = os.path.join(review, "voice", name)
    vfields, engine, vnote = voice.prepare(client, spec, name, work, voice_dir)
    spec.update(vfields)
    if "voice_dir" in spec:
        spec["voice_dir"] = os.path.relpath(spec["voice_dir"], REPO)
    spec_path = os.path.join(review, f"{name}-spec.json")
    reel = os.path.join(review, f"{name}-reel.mp4")
    json.dump(spec, open(spec_path, "w"), ensure_ascii=False, indent=1)
    with render_lock():
        sh(["python3", os.path.join(REPO, "engine", "make_reel.py"), spec_path, reel])
    cap = script.caption(client, plan)
    open(os.path.join(review, f"{name}-caption.txt"), "w").write(cap)
    json.dump(plan, open(os.path.join(review, f"{name}-plan.json"), "w"), ensure_ascii=False, indent=1)
    st.update(stage="in_review", batch=batch, name=name, plan=plan, version=version, reel=os.path.relpath(reel, REPO),
              spec=os.path.relpath(spec_path, REPO), caption=cap, voice_engine=engine)
    save_state(client, st)
    return outbox(client, "review", {
        "reel": st["reel"], "caption": cap, "script": plan.get("script_roman", []),
        "hooks": plan.get("hooks"), "trend_line": st.get("trend", {}).get("trend_line", ""),
        "voice_engine": engine, "voice_note": vnote, "version": version, "problems": plan.get("_problems", []),
        "ask": "Reply yes to post, or tell me what to change."})


def approve(client, commit_sha=None, media_url=None):
    """Owner said yes. Returns the Uplika publish request. The Reel must be at a public https URL:
    the web app's own /files URL (media_url), or GitHub raw at commit_sha (pilot)."""
    st = load_state(client)
    if st.get("stage") != "in_review":
        raise ReelFlowError(f"nothing in review (stage = {st.get('stage')})")
    url = media_url or f"{client['raw_base']}/{commit_sha}/{st['reel']}"
    req = {"media_url": url, "caption": st["caption"],
           "accountIds": [client["uplika_connection_id"]],
           "options": {"instagram": {"contentType": "reel", "shareToFeed": True}}, "wait": True}
    st["stage"] = "approved"
    st["publish_request"] = req
    save_state(client, st)
    return outbox(client, "publish_request", req)


def _mv(src, dst):
    """git mv inside the repo (keeps history), plain move elsewhere (server data disk)."""
    if not os.path.exists(src):
        return
    if sh(["git", "-C", REPO, "ls-files", "--error-unmatch", src], check=False).strip():
        sh(["git", "-C", REPO, "mv", src, dst])
    else:
        shutil.move(src, dst)


def posted(client, permalink):
    st = load_state(client)
    if st.get("stage") != "approved":
        raise ReelFlowError(f"not approved (stage = {st.get('stage')})")
    pm, pr = cpath(client, "posted_media"), cpath(client, "posted_reels")
    os.makedirs(pr, exist_ok=True)
    os.makedirs(pm, exist_ok=True)
    moved = []
    for f in st["batch"]:
        dst = os.path.join(pm, os.path.basename(f))
        _mv(f, dst)
        moved.append(dst)
    review = cpath(client, "review")
    for f in os.listdir(review):
        if f.startswith(st["name"]):
            _mv(os.path.join(review, f), os.path.join(pr, f))
    vd = os.path.join(review, "voice", st["name"])
    if os.path.isdir(vd):
        os.makedirs(os.path.join(pr, "voice"), exist_ok=True)
        _mv(vd, os.path.join(pr, "voice", st["name"]))
    st["history"].append({"name": st["name"], "permalink": permalink, "date": f"{dt.date.today()}"})
    for k in ("batch", "plan", "publish_request", "caption"):
        st.pop(k, None)
    st["stage"] = "idle"
    st.pop("reel", None)
    save_state(client, st)
    return outbox(client, "posted", {"text": f"Reel live: {permalink}", "permalink": permalink})
