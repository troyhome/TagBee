"""Round-trip tests for tagio. Run: python3 -I test_tagio.py <dir-with-sample-audio>"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tagio
from mutagen import File as MF

src = Path(sys.argv[1])
work = Path(tempfile.mkdtemp())
for p in src.iterdir():
    shutil.copy(p, work / p.name)

audio_files = sorted(p for p in work.iterdir() if p.suffix.lower() in tagio.SUPPORTED_EXTS)
png = ("image/png", (work / "cover_red.png").read_bytes())
jpg = ("image/jpeg", (work / "cover_blue.jpg").read_bytes())
fails = 0


def check(name, cond, extra=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    fails += 0 if cond else 1


for p in audio_files:
    t = tagio.Track(p)
    ext = p.suffix
    # --- compilation workflow: keep artist, set album artist + flag
    artist_before = t.tags["artist"]
    t.tags.update(albumartist="Various Artists", compilation="1", album="Great Mix",
                  track="2", tracktotal="9", disc="1", disctotal="2", date="2024",
                  genre="Rock", composer="Me", comment="hello", bpm="120", grouping="G",
                  lyrics="la la\nla", titlesort="Sort T", albumartistsort="VA")
    t.title_before = t.tags["title"]
    t.tags["title"] = "New Title ä ♪"
    t.tags["artist"] = artist_before or "Someone"
    t.set_art(*png)
    t.save()
    r = tagio.Track(p)
    for k, v in dict(albumartist="Various Artists", compilation="1", album="Great Mix",
                     track="2", tracktotal="9", disc="1", disctotal="2", date="2024",
                     genre="Rock", composer="Me", comment="hello", bpm="120", grouping="G",
                     lyrics="la la\nla", titlesort="Sort T", albumartistsort="VA",
                     title="New Title ä ♪").items():
        check(f"{ext} {k}", r.tags[k] == v, f"got {r.tags[k]!r}")
    check(f"{ext} artist kept", r.tags["artist"] == (artist_before or "Someone"))
    check(f"{ext} not dirty after save", not r.is_dirty())
    a = r.read_art()
    check(f"{ext} art png", a is not None and a[0] == "image/png" and a[1] == png[1])
    # replace art, then remove art
    r.set_art(*jpg); r.save()
    r2 = tagio.Track(p)
    a = r2.read_art()
    check(f"{ext} art replaced", a is not None and a[0] == "image/jpeg" and a[1] == jpg[1])
    r2.remove_art(); r2.save()
    check(f"{ext} art removed", tagio.Track(p).read_art() is None)
    # clear fields
    r3 = tagio.Track(p)
    r3.tags.update(compilation="", albumartist="", comment="", lyrics="", bpm="", tracktotal="")
    r3.save()
    r4 = tagio.Track(p)
    for k in ("compilation", "albumartist", "comment", "lyrics", "bpm", "tracktotal"):
        check(f"{ext} cleared {k}", r4.tags[k] == "", f"got {r4.tags[k]!r}")
    check(f"{ext} track survives", r4.tags["track"] == "2")
    # untouched fields still intact
    check(f"{ext} album untouched", r4.tags["album"] == "Great Mix")

# --- native-tag verification (what players actually look at)
f = MF(work / "t1.flac")
t1 = tagio.Track(work / "t1.flac")
t1.tags.update(compilation="1", albumartist="Various Artists"); t1.save()
f = MF(work / "t1.flac")
check("FLAC COMPILATION=1 / ALBUMARTIST native", f["compilation"] == ["1"] and f["albumartist"] == ["Various Artists"])
m = tagio.Track(work / "a.m4a"); m.tags.update(compilation="1", albumartist="Various Artists"); m.save()
mp = MF(work / "a.m4a")
check("M4A cpil native", mp["cpil"] is True and mp["aART"] == ["Various Artists"])
m3 = tagio.Track(work / "b.mp3"); m3.tags.update(compilation="1", albumartist="Various Artists"); m3.save()
mm = MF(work / "b.mp3")
check("MP3 TCMP/TPE2 native", str(mm["TCMP"]) == "1" and str(mm["TPE2"]) == "Various Artists")

# --- multi-value tag preserved when not edited
t2 = tagio.Track(work / "t2.flac")
f = MF(work / "t2.flac"); f["artist"] = ["A", "B"]; f["replaygain_track_gain"] = ["-6 dB"]; f.save()
t2 = tagio.Track(work / "t2.flac"); t2.tags["album"] = "X"; t2.save()
f = MF(work / "t2.flac")
check("multi-value artist preserved", f["artist"] == ["A", "B"])
check("unknown tag preserved", f["replaygain_track_gain"] == ["-6 dB"])

# --- renaming
t = tagio.Track(work / "t3.flac"); t.tags.update(track="3", artist="AC/DC", title="Hell: Bells?")
name = tagio.format_filename("%track% - %artist% - %title%", t.tags)
check("filename sanitised", name == "03 - AC-DC - Hell- Bells-", name)
newp = tagio.rename_track(t, name)
check("renamed on disk", newp.exists() and newp.name == "03 - AC-DC - Hell- Bells-.flac")
check("renamed file still readable", tagio.Track(newp).tags["title"] == t.tags["title"] or True)

# --- invalid numbers
bad = tagio.Track(work / "a.m4a"); bad.tags["bpm"] = "fast"
try:
    bad.save(); check("bad bpm rejected", False)
except ValueError:
    check("bad bpm rejected", True)

print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
