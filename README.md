# slippi-upset

Melee announcer callouts for Slippi netplay. Run it in the background while you
play, and it reacts to who you're playing and whether you beat them:

| When | Sound |
|---|---|
| Game 1 starts against someone rated higher than you | *Challenger Approaching* jingle |
| You beat the highest-rated opponent you've ever beaten | "A new record!" |
| You beat someone whose best season beats your best season | "Wow! Incredible!" |
| You beat someone whose current rating beats yours | "Congratulations!" |
| Any other win | "Complete!" |

Only the first matching win sound plays. Losses, quits and doubles are silent.
Ratings come from slippi.gg, so it works for ranked and unranked games alike.

## Setup

Requires **Windows**, **Python 3.9+**, and Slippi Launcher (logged in).

```
git clone https://github.com/diegoaranas/slippi-upset
cd slippi-upset
python get_sounds.py
```

The announcer clips are Nintendo's, so they aren't in this repo. `get_sounds.py`
downloads the community rips from [The Sounds Resource](https://sounds.spriters-resource.com/gamecube/ssbm/)
and saves the six clips to `sounds/` at half volume (`--volume 1` for full).

## Usage

Start it before you play and leave the terminal open:

```
python upset.py
```

```
Watching C:\Users\you\Documents\Slippi for new games as ABCD#123... (Ctrl+C to stop)
New opponent: EFGH#456  2210.4 (peak 2301.7)  >>> CHALLENGER APPROACHING
Game_20260923T221106.slp: WIN vs EFGH#456  them 2210.4 (peak 2301.7)  you 2146.6 (peak 2146.6)  >>> NEW RECORD! (was 1950.3)
```

To check it on a game you've already played:

```
python upset.py --test "C:\path\to\Game_20260923T221106.slp"
```

## Configuration

Everything is at the top of `upset.py`:

- `MY_CODE` / `REPLAY_DIR`: detected from Slippi Launcher. Set them only if detection fails or you keep replays somewhere unusual.
- `SOUND_*`: any `.wav` file works. `SOUND_CONNECT` plays for every *other* new opponent; it's off by default (try `sounds/versus.wav`).

Your record is kept in `record.json` next to the script. It starts at 0, so
your first win sets it. Delete the file to reset.

## How it works

Slippi writes a replay file as each game is played. The script checks the
replay folder once a second:

- **Game starts:** reads the first 2 KB of the new file to get the connect codes.
- **Game ends:** Slippi fills in the replay's length header. The script then reads the replay once to find the winner and looks up both players' ratings.

It makes no network requests during a game and runs at below-normal CPU
priority, so it doesn't affect Dolphin. It uses only the Python standard library.

Ratings come from the same API the slippi.gg profile pages use. It's not an
official public API, so it could change without notice.

## License

MIT for the code in this repo. The announcer clips belong to Nintendo and
aren't covered by this license.
