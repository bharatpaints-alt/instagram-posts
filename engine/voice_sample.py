#!/usr/bin/env python3
"""Make a quick voiceover sample to compare voices.

  python3 engine/voice_sample.py azure  out.wav      # needs AZURE_SPEECH_KEY (+ AZURE_SPEECH_REGION)
  python3 engine/voice_sample.py piper  out.wav      # free built-in Hindi voice, no key
Optional 3rd arg: Azure voice name (default hi-IN-MadhurNeural; female: hi-IN-SwaraNeural).
"""
import os, sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_reel as m  # noqa: E402

# (text, speed, pitch in semitones, pause after) - short seepage ad, ~15 s
SCRIPT = [
    ("रुकिए! दीवार पर सीलन?", 0.95, 1.0, 0.35),
    ("पेंट बार-बार उखड़ रहा है?", 0.95, 0.5, 0.45),
    ("सिर्फ़ पेंट बदलने से सीपेज नहीं जाएगा... पहले वजह पकड़िए!", 0.92, 0, 0.45),
    ("भारत पेंट्स... सिर्फ़ पाँच सौ रुपये में, साइट विज़िट और पूरी रिपोर्ट।", 0.9, -0.5, 0.45),
    ("आज ही वॉट्सऐप करें!", 0.95, 1.0, 0.6),
]


def main(engine, out, voice="hi-IN-MadhurNeural"):
    work = os.path.join(m.CACHE, "sample")
    os.makedirs(work, exist_ok=True)
    parts, sr = [], 24000
    if engine == "azure":
        tts = m.AzureTTS(voice, work)
        make = lambda t, s, p: tts.create([(t, "hi")], s, p)
    else:
        tts = m.Piper("hi_IN-rohan-medium", m.load_tts())
        make = lambda t, s, p: tts.create([(t, "hi")], s)
    for text, speed, pitch, pause in SCRIPT:
        a, sr = make(text, speed, pitch)
        parts += [a.astype(np.float32), np.zeros(int(sr * pause), dtype=np.float32)]
    raw = os.path.join(work, "raw.wav")
    sf.write(raw, np.concatenate(parts), sr)
    chain = m.VOICE_CHAIN if engine == "piper" else "highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=8:release=120:makeup=2"
    m.run(f"ffmpeg -v error -y -i {raw} -af \"{chain},loudnorm=I=-16:TP=-1.5\" -ar 44100 {out}")
    print("saved", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
