"""Runs every minute (thread in the web app, or `python3 -m reelflow tick` from cron):
- at each client's nudge time (their timezone): today's trend + shot list
- whenever photos are waiting and nothing is in review: make the Reel
- deliver new outbox messages (notify.py)"""
import datetime as dt
import threading
import time
import traceback
from zoneinfo import ZoneInfo

from . import notify, pipeline
from .common import list_clients, load_client, load_state, save_state
from .media import next_batch


def tick(now=None, log=print):
    for cid in list_clients():
        try:
            c = load_client(cid)
            local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(c.get("timezone", "Asia/Kolkata")))
            st = load_state(c)
            today = f"{local.date()}"
            if (st.get("last_nudge") != today and local.strftime("%H:%M") >= c.get("nudge_time", "09:00")
                    and st.get("stage") in ("idle", "nudged")):
                st["last_nudge"] = today
                save_state(c, st)
                log(cid, "nudge", pipeline.nudge(c))
            st = load_state(c)
            if st.get("stage") in ("idle", "nudged") and not pipeline.busy(cid) and next_batch(c) and st.get("failed_batch") != next_batch(c):
                try:
                    log(cid, "make", pipeline.make(c))
                except Exception as e:  # noqa: BLE001
                    st = load_state(c)
                    st["failed_batch"] = next_batch(c)  # don't retry the same files every minute
                    save_state(c, st)
                    log(cid, "make failed", e)
            notify.deliver(c)
        except Exception:
            log(cid, "tick error", traceback.format_exc()[-800:])


def start_background(interval=60, log=print):
    def loop():
        while True:
            tick(log=log)
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True, name="reelflow-scheduler")
    t.start()
    return t
