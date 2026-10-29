"""CLI:  python3 -m reelflow <command> <client> [args]

  nudge   <client>              9 am trend + shot-list message
  make    <client>              next upload -> Reel in review (does nothing if no upload)
  change  <client> "<request>"  re-make the Reel in review with the owner's change
  approve <client> <commit>     owner said yes -> Uplika publish request (Reel pushed at <commit>)
  posted  <client> <link>       publish confirmed -> archive files, back to idle
  daily                         every client: nudge, then make if photos are waiting
  status  [client]
  tick                          one scheduler pass (cron every minute if not using the web app's thread)
  serve                         web app on :8000 (needs ADMIN_TOKEN, PUBLIC_BASE_URL)
"""
import json
import sys

from . import pipeline
from .common import ReelFlowError, list_clients, load_client, load_state


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "daily":
            for cid in list_clients():
                c = load_client(cid)
                print(cid, "nudge ->", pipeline.nudge(c))
                print(cid, "make  ->", pipeline.make(c))
        elif cmd == "tick":
            from . import scheduler
            scheduler.tick()
        elif cmd == "serve":
            import os
            import uvicorn
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            uvicorn.run("web.app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
        elif cmd == "status":
            for cid in args or list_clients():
                st = load_state(load_client(cid))
                print(cid, st.get("stage"), st.get("name", ""), st.get("updated", ""))
        else:
            c = load_client(args[0])
            fn = {"nudge": lambda: pipeline.nudge(c), "make": lambda: pipeline.make(c),
                  "change": lambda: pipeline.make(c, change_request=args[1]),
                  "approve": lambda: pipeline.approve(c, args[1]),
                  "posted": lambda: pipeline.posted(c, args[1])}[cmd]
            out = fn()
            print(out or "nothing to do (no upload waiting)")
            if out:
                print(json.dumps(json.load(open(out)), ensure_ascii=False, indent=1)[:3000])
    except (ReelFlowError, KeyError, IndexError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
