"""
Slippi upset alert: plays a sound when you beat someone rated higher than you.

First run:                            python get_sounds.py
Run it in a terminal while playing:   python upset.py
Test it on an existing replay:        python upset.py --test path/to/Game.slp

Windows only, standard library only. It checks the replay folder every second,
reads the first 2 KB of a replay when a game starts and the whole replay once
after it ends, and runs at below-normal CPU priority, so it shouldn't affect Dolphin.
"""
import ctypes
import json
import os
import re
import struct
import sys
import time
import urllib.request
import winsound

# ---------------------------------------------------------------- config ----
HERE = os.path.dirname(os.path.abspath(__file__))
MY_CODE = None      # e.g. "ABCD#123"; None = read it from Slippi Launcher
REPLAY_DIR = None   # e.g. r"D:\Replays"; None = read it from Slippi Launcher's settings
POLL_SECONDS = 1

# Any .wav file works. Put your own clips in sounds/ and point these at them.
# Win sounds, highest precedence first:
SOUND_RECORD = os.path.join(HERE, "sounds", "new_record.wav")     # "A new record!" - highest-rated opponent you've ever beaten
SOUND_PEAK = os.path.join(HERE, "sounds", "incredible.wav")       # "Wow! Incredible!" - opp best season > your best
SOUND_CURRENT = os.path.join(HERE, "sounds", "congratulations.wav")  # "Congratulations!" - opp current rating > yours
SOUND_WIN = os.path.join(HERE, "sounds", "complete.wav")          # "Complete!" - any other win
# First game vs a new opponent:
SOUND_CHALLENGER = os.path.join(HERE, "sounds", "challenger.wav") # Challenger Approaching jingle - they're rated higher
SOUND_CONNECT = None                                              # everyone else (e.g. sounds/versus.wav); None = silent
# Opponent quits (resets) mid-game:
SOUND_QUIT = os.path.join(HERE, "sounds", "no_contest.wav")      # "No contest!"

RECORD_FILE = os.path.join(HERE, "record.json")                   # your best win so far
# -----------------------------------------------------------------------------

LAUNCHER_DIR = os.path.join(os.environ.get("APPDATA", ""), "Slippi Launcher")


def detect_code():
    """Your connect code, from the account Slippi Launcher is logged into."""
    try:
        with open(os.path.join(LAUNCHER_DIR, "netplay", "User", "Slippi", "user.json"), encoding="utf-8") as f:
            return json.load(f)["connectCode"]   # only this field; the file also holds your login key
    except (OSError, ValueError, KeyError):
        sys.exit("Couldn't find your connect code. Log in to Slippi Launcher, or set MY_CODE in upset.py.")


def detect_replay_dir():
    """Slippi Launcher's replay folder setting, or its default (Documents\\Slippi)."""
    try:
        with open(os.path.join(LAUNCHER_DIR, "Settings"), encoding="utf-8") as f:
            path = json.load(f).get("settings", {}).get("rootSlpPath")
        if path:
            return path
    except (OSError, ValueError):
        pass
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # 5 = My Documents (follows OneDrive redirection)
    return os.path.join(buf.value, "Slippi")

API = "https://internal.slippi.gg/graphql"
QUERY = """query U($cc: String) { getUser(connectCode: $cc) {
  rankedNetplayProfile { ratingOrdinal ratingUpdateCount }
  rankedNetplayProfileHistory { ratingOrdinal ratingUpdateCount season { name } } } }"""
HEADER = b"{U\x03raw[$U#l"


# ------------------------------------------------------------- ratings ----
def fetch_ratings(code):
    """Returns (current, peak), either one may be None. current is None if unranked this season."""
    body = json.dumps({"query": QUERY, "variables": {"cc": code}}).encode()
    req = urllib.request.Request(API, body, {"Content-Type": "application/json",
                                             "User-Agent": "slippi-upset-alert"})
    with urllib.request.urlopen(req, timeout=10) as r:
        user = json.load(r)["data"]["getUser"]
    if not user:
        return None, None
    cur = user["rankedNetplayProfile"]
    current = cur["ratingOrdinal"] if cur and cur["ratingUpdateCount"] else None
    past = [s["ratingOrdinal"] for s in user["rankedNetplayProfileHistory"] or [] if s["ratingUpdateCount"]]
    ratings = past + ([current] if current is not None else [])
    return current, (max(ratings) if ratings else None)


# -------------------------------------------------------------- replays ----
def ubjson(buf, i):
    """Minimal UBJSON decoder (just what Slippi metadata uses). Returns (value, next_index)."""
    t = buf[i:i + 1]; i += 1
    ints = {b"i": ">b", b"U": ">B", b"I": ">h", b"l": ">i", b"L": ">q", b"d": ">f", b"D": ">d"}
    if t in ints:
        fmt = ints[t]; n = struct.calcsize(fmt)
        return struct.unpack(fmt, buf[i:i + n])[0], i + n
    if t == b"S":
        n, i = ubjson(buf, i)
        return buf[i:i + n].decode("utf-8", "replace"), i + n
    if t in (b"T", b"F", b"Z"):
        return {b"T": True, b"F": False, b"Z": None}[t], i
    if t == b"{":
        d = {}
        while buf[i:i + 1] != b"}":
            n, i = ubjson(buf, i)                  # keys are a length int + bytes, no 'S'
            key = buf[i:i + n].decode("utf-8", "replace"); i += n
            d[key], i = ubjson(buf, i)
        return d, i + 1
    if t == b"[":
        a = []
        while buf[i:i + 1] != b"]":
            v, i = ubjson(buf, i); a.append(v)
        return a, i + 1
    raise ValueError(f"unsupported UBJSON type {t!r} at {i - 1}")


def raw_length(path):
    """0 while the game is still being written; Slippi fills it in when the game ends."""
    with open(path, "rb") as f:
        head = f.read(15)
    if len(head) < 15 or not head.startswith(HEADER):
        return 0
    return int.from_bytes(head[11:15], "big")


def parse_game(path):
    """Returns (codes_by_port, winner_port or None, quitter_port or None)."""
    data = open(path, "rb").read()
    n = int.from_bytes(data[11:15], "big")
    raw = data[15:15 + n]

    # metadata -> connect codes per port
    meta, _ = ubjson(data, 15 + n + len(b"U\x08metadata"))
    codes = {int(p): v.get("names", {}).get("code") for p, v in meta.get("players", {}).items()}

    # event stream -> stocks and game-end info
    sizes = {}
    pos = 0
    if raw[0] == 0x35:
        blen = raw[1]
        for j in range(2, 1 + blen, 3):
            sizes[raw[j]] = int.from_bytes(raw[j + 1:j + 3], "big")
        pos = 1 + blen
    stocks, percent, end = {}, {}, None
    while pos < len(raw):
        cmd = raw[pos]
        size = sizes.get(cmd)
        if size is None:
            break
        if cmd == 0x38 and raw[pos + 6] == 0:      # post-frame, non-follower (ignore Nana)
            port = raw[pos + 5]
            percent[port] = struct.unpack(">f", raw[pos + 0x16:pos + 0x1A])[0]
            stocks[port] = raw[pos + 0x21]
        elif cmd == 0x39:
            end = raw[pos + 1:pos + 1 + size]
        pos += 1 + size

    if end is None or len(stocks) != 2:
        return codes, None, None                   # crashed/doubles/etc.
    quitter = struct.unpack(">b", end[1:2])[0] if len(end) >= 2 else -1
    if quitter != -1:
        return codes, None, quitter                # someone quit (LRAS): no winner
    if len(end) >= 6:                              # newer replays store placements directly
        places = struct.unpack(">4b", end[2:6])
        for port in stocks:
            if places[port] == 0:
                return codes, port, None
    a, b = stocks
    if stocks[a] != stocks[b]:
        return codes, max(stocks, key=lambda p: stocks[p]), None
    if percent[a] != percent[b]:                   # timeout with equal stocks
        return codes, min(percent, key=lambda p: percent[p]), None
    return codes, None, None


# ----------------------------------------------------------------- main ----
def fmt(x):
    return f"{x:.1f}" if x is not None else "unranked"


def handle(path):
    codes, winner, quitter = parse_game(path)
    me = next((p for p, c in codes.items() if c and c.upper() == MY_CODE.upper()), None)
    opp = next((c for p, c in codes.items() if p != me and c), None)
    name = os.path.basename(path)
    if me is None or opp is None:
        print(f"{name}: not a 1v1 netplay game with you in it, skipping")
        return
    if quitter is not None and quitter != me:
        print(f"{name}: vs {opp}: they quit  >>> NO CONTEST")
        play(SOUND_QUIT)
        return
    if winner != me:
        print(f"{name}: vs {opp}: {'loss' if winner is not None else 'you quit' if quitter == me else 'no result'}")
        return

    my_cur, my_peak = fetch_ratings(MY_CODE)
    op_cur, op_peak = fetch_ratings(opp)
    record = load_record()
    new_record = op_cur is not None and op_cur > record["rating"]
    beat_peak = op_peak is not None and my_peak is not None and op_peak > my_peak
    beat_cur = op_cur is not None and my_cur is not None and op_cur > my_cur
    if new_record:
        save_record({"rating": op_cur, "code": opp, "date": time.strftime("%Y-%m-%d %H:%M")})
        sound, tag = SOUND_RECORD, f"NEW RECORD! (was {record['rating']:.1f})"
    elif beat_peak:
        sound, tag = SOUND_PEAK, "beat a higher peak!"
    elif beat_cur:
        sound, tag = SOUND_CURRENT, "UPSET!"
    else:
        sound, tag = SOUND_WIN, ""
    print(f"{name}: WIN vs {opp}  them {fmt(op_cur)} (peak {fmt(op_peak)})  "
          f"you {fmt(my_cur)} (peak {fmt(my_peak)})" + (f"  >>> {tag}" if tag else ""))
    play(sound)


def load_record():
    """Highest current rating of any opponent you've beaten (starts at 0)."""
    try:
        with open(RECORD_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"rating": 0, "code": None, "date": None}


def save_record(record):
    with open(RECORD_FILE, "w") as f:
        json.dump(record, f, indent=2)


def play(sound):
    if sound and os.path.exists(sound):
        winsound.PlaySound(sound, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def is_higher(mine, theirs):
    """Same rule as the win sounds: their current rating beats yours, or their best season beats yours."""
    (my_cur, my_peak), (op_cur, op_peak) = mine, theirs
    return ((op_cur is not None and my_cur is not None and op_cur > my_cur)
            or (op_peak is not None and my_peak is not None and op_peak > my_peak))


def announce_opponent(opp):
    try:
        mine, theirs = fetch_ratings(MY_CODE), fetch_ratings(opp)
    except Exception as ex:
        print(f"New opponent: {opp}  (rating lookup failed: {ex})")
        return
    higher = is_higher(mine, theirs)
    print(f"New opponent: {opp}  {fmt(theirs[0])} (peak {fmt(theirs[1])})"
          + ("  >>> CHALLENGER APPROACHING" if higher else ""))
    play(SOUND_CHALLENGER if higher else SOUND_CONNECT)


def start_codes(path):
    """Connect codes by port from the Game Start event, which Slippi writes as soon as the
    game begins. Returns None if it isn't on disk yet."""
    with open(path, "rb") as f:
        raw = f.read(2048)[15:]
    if len(raw) < 2 or raw[0] != 0x35:
        return None
    blen = raw[1]
    sizes = {raw[j]: int.from_bytes(raw[j + 1:j + 3], "big") for j in range(2, 1 + blen, 3)}
    gs = raw[1 + blen:1 + blen + 1 + sizes.get(0x36, 0)]
    if len(gs) < 0x221 + 0xA * 4 or gs[0] != 0x36:
        return None
    codes = {}
    for port in range(4):
        code = gs[0x221 + 0xA * port:0x22B + 0xA * port].split(b"\0")[0]
        if code:
            codes[port] = code.decode("shift_jis", "replace").replace("＃", "#")  # fullwidth '#'
    return codes


def replay_dirs():
    """The root folder plus the two newest YYYY-MM month folders. Other subfolders
    (Spectate, anything the user made) are ignored so they can't crowd out the current month."""
    months = sorted(e.path for e in os.scandir(REPLAY_DIR)
                    if e.is_dir() and re.fullmatch(r"\d{4}-\d{2}", e.name))
    return [REPLAY_DIR] + months[-2:]


def watch():
    # Below-normal priority so the OS always favors Dolphin.
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    started = time.time()
    done, seen = set(), set()
    last_opp = None
    missing = [os.path.basename(s) for s in (SOUND_RECORD, SOUND_PEAK, SOUND_CURRENT, SOUND_WIN,
                                             SOUND_CHALLENGER, SOUND_CONNECT, SOUND_QUIT) if s and not os.path.exists(s)]
    if missing:
        print(f"Missing sounds: {', '.join(missing)}. Run `python get_sounds.py` first.")
    print(f"Watching {REPLAY_DIR} for new games as {MY_CODE}... (Ctrl+C to stop)")
    while True:
        try:
            for d in replay_dirs():
                for e in os.scandir(d):
                    if not e.name.endswith(".slp") or e.stat().st_mtime <= started:
                        continue
                    if e.path not in seen:                 # game just started
                        codes = start_codes(e.path)
                        if codes is not None:
                            seen.add(e.path)
                            opps = [c for c in codes.values() if c.upper() != MY_CODE.upper()]
                            if len(codes) == 2 and len(opps) == 1 and opps[0] != last_opp:
                                last_opp = opps[0]
                                announce_opponent(last_opp)
                    if e.path not in done and raw_length(e.path):   # game just ended
                        done.add(e.path)
                        try:
                            handle(e.path)
                        except Exception as ex:
                            print(f"{e.name}: error: {ex}")
        except OSError as ex:
            print(f"folder scan error: {ex}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    MY_CODE = MY_CODE or detect_code()
    REPLAY_DIR = REPLAY_DIR or detect_replay_dir()
    if len(sys.argv) == 3 and sys.argv[1] == "--test":
        handle(sys.argv[2])
        time.sleep(3)  # let the async sound finish
    else:
        try:
            watch()
        except KeyboardInterrupt:
            pass
