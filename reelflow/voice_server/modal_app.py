"""Deploy the free voice clone server on a pay-per-second GPU (Modal):
  pip install modal && modal setup
  modal secret create reelflow-voice OPENVOICE_TOKEN=<choose-a-long-random-string>
  modal deploy modal_app.py          # prints the URL -> ReelFlow OPENVOICE_URL (+ OPENVOICE_TOKEN)
The GPU sleeps after 5 idle minutes, so you pay only while Reels are being voiced."""
import modal

image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("ffmpeg")
         .pip_install("chatterbox-tts", "fastapi[standard]")
         .add_local_file("server.py", "/root/server.py"))
app = modal.App("reelflow-voice")


@app.function(image=image, gpu="T4", timeout=600, scaledown_window=300,
              secrets=[modal.Secret.from_name("reelflow-voice")])
@modal.asgi_app()
def web():
    import sys
    sys.path.insert(0, "/root")
    import server
    return server.app
