# Free voice clone server (ReelFlow "opensource" engine)

Open-source Chatterbox Multilingual (Resemble AI, MIT licence; Hindi supported). The client's 30 s sample is sent with each
line as the voice reference, so one server serves every client.

- `server.py`: the HTTP API ReelFlow's `voice.py` calls (`OPENVOICE_URL`, `OPENVOICE_TOKEN`).
- `modal_app.py`: one-command GPU deploy (T4, sleeps when idle).
- Any GPU box: `pip install chatterbox-tts fastapi uvicorn && uvicorn server:app --port 8100`.

Status: written 30 Oct, not yet run on a GPU (this workspace cannot download PyTorch fast enough). First check after deploy:
`curl -X POST $URL -H "authorization: Bearer $TOKEN" -H content-type:application/json -d '{"text":"रुको! ये देखिए!","language":"hi"}' -o t.wav`
then a full Reel with a client's sample. If Hindi quality is not good enough, the same API can wrap IndicF5 instead.
