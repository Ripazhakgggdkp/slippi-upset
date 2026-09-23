"""
Download the Melee announcer clips used by upset.py into sounds/.

The clips are Nintendo's, so they aren't included in this repo. This fetches the
community rips from The Sounds Resource (https://sounds.spriters-resource.com),
pulls out the seven clips, and saves them at reduced volume.

    python get_sounds.py              # half volume (default)
    python get_sounds.py --volume 1   # original volume
"""
import array
import io
import os
import re
import sys
import urllib.request
import wave
import zipfile

# Next to the .exe when packaged with PyInstaller, otherwise next to this file.
HERE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SITE = "https://sounds.spriters-resource.com"
UA = {"User-Agent": "Mozilla/5.0"}

# asset page -> {clip filename inside the zip: name to save as}
CLIPS = {
    "/gamecube/ssbm/asset/394077/": {          # Narrator
        "nr_1p00.dsp.wav": "new_record.wav",       # "A new record!"
        "nr_1p05.dsp.wav": "incredible.wav",       # "Wow! Incredible!"
        "nr_1p01.dsp.wav": "congratulations.wav",  # "Congratulations!"
        "nr_1p06.dsp.wav": "complete.wav",         # "Complete!"
        "nr_1p0a.dsp.wav": "versus.wav",           # "Versus!"
        "nr_vs00.dsp.wav": "no_contest.wav",       # "No contest!"
    },
    "/gamecube/ssbm/asset/394097/": {          # Fanfares
        "s_newcom.hps.wav": "challenger.wav",      # Challenger Approaching jingle
    },
}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def scale(wav_bytes, volume):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    if params.sampwidth != 2:
        return wav_bytes
    samples = array.array("h", frames)
    if sys.byteorder == "big":
        samples.byteswap()
    samples = array.array("h", (max(-32768, min(32767, int(s * volume))) for s in samples))
    if sys.byteorder == "big":
        samples.byteswap()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(samples.tobytes())
    return out.getvalue()


def download(out_dir, volume=0.5):
    os.makedirs(out_dir, exist_ok=True)
    for page, wanted in CLIPS.items():
        html = fetch(SITE + page).decode("utf-8", "replace")
        m = re.search(r'href="(/media/assets/[^"]+\.zip[^"]*)"', html)
        if not m:
            raise RuntimeError(f"Couldn't find the download link on {SITE + page}; the site may have changed.")
        zip_path = m.group(1)
        print(f"Downloading {SITE + zip_path.split('?')[0]} ...")
        zf = zipfile.ZipFile(io.BytesIO(fetch(SITE + zip_path)))
        by_name = {os.path.basename(n): n for n in zf.namelist()}
        for src, dst in wanted.items():
            if src not in by_name:
                print(f"  ! {src} not found in the pack; skipping {dst}")
                continue
            with open(os.path.join(out_dir, dst), "wb") as f:
                f.write(scale(zf.read(by_name[src]), volume))
            print(f"  saved sounds/{dst}")
    print("Done.")


if __name__ == "__main__":
    vol = float(sys.argv[sys.argv.index("--volume") + 1]) if "--volume" in sys.argv else 0.5
    download(os.path.join(HERE, "sounds"), vol)
