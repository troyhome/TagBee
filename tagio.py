"""tagio.py - the file-format layer for TagForge.

No GUI code lives here. It reads and writes tags (and cover art) for FLAC, M4A/MP4,
MP3, Ogg Vorbis, Opus, WAV and AIFF through one uniform set of fields, and only
touches the fields that were actually changed, so anything it doesn't know about
(multi-value tags, ReplayGain, MusicBrainz IDs, ...) is left alone.
"""
from __future__ import annotations

import hashlib
import base64
import re
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import id3
from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4Tags
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

SUPPORTED_EXTS = {
    ".flac", ".m4a", ".m4b", ".mp4", ".mp3",
    ".ogg", ".opus", ".wav", ".aif", ".aiff",
}

# (key, label) in the order they appear in the editor.
FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("compilation", "Compilation"),
    ("date", "Year / Date"),
    ("genre", "Genre"),
    ("track", "Track"),
    ("tracktotal", "Track total"),
    ("disc", "Disc"),
    ("disctotal", "Disc total"),
    ("composer", "Composer"),
    ("comment", "Comment"),
    ("bpm", "BPM"),
    ("copyright", "Copyright"),
    ("grouping", "Grouping"),
    ("lyrics", "Lyrics"),
    ("titlesort", "Title sort"),
    ("artistsort", "Artist sort"),
    ("albumsort", "Album sort"),
    ("albumartistsort", "Album artist sort"),
]
FIELD_KEYS = [k for k, _ in FIELDS]
LABELS = dict(FIELDS)

# --------------------------------------------------------------------------- helpers


def _blank() -> dict:
    return {k: "" for k in FIELD_KEYS}


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _split_pair(raw: str):
    raw = (raw or "").strip()
    if "/" in raw:
        a, b = raw.split("/", 1)
        return a.strip(), b.strip()
    return raw, ""


def _int(value, label="value") -> int:
    s = str(value or "").strip()
    if not s:
        return 0
    s = s.split("/", 1)[0].strip()
    try:
        return int(s)
    except ValueError:
        raise ValueError(f"{label} must be a whole number (got '{value}')")


def sniff_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _kind(audio) -> str:
    if isinstance(audio, MP4):
        return "mp4"
    if isinstance(audio, (FLAC, OggVorbis, OggOpus)):
        return "vorbis"
    if isinstance(audio, (MP3, WAVE, AIFF)):
        return "id3"
    raise ValueError("Unsupported audio format")


def _codec(audio) -> str:
    if isinstance(audio, MP4):
        return "ALAC" if "alac" in str(getattr(audio.info, "codec", "")).lower() else "AAC"
    return {
        FLAC: "FLAC", MP3: "MP3", OggVorbis: "Vorbis", OggOpus: "Opus", WAVE: "WAV", AIFF: "AIFF",
    }.get(type(audio), type(audio).__name__)


def _delete(tags, key):
    if key in tags:
        del tags[key]


# --------------------------------------------------------------------------- Vorbis (FLAC / Ogg / Opus)

VORBIS_READ = {
    "title": ["title"], "artist": ["artist"], "album": ["album"],
    "albumartist": ["albumartist", "album artist"],
    "date": ["date", "year"], "genre": ["genre"],
    "track": ["tracknumber"], "tracktotal": ["tracktotal", "totaltracks"],
    "disc": ["discnumber"], "disctotal": ["disctotal", "totaldiscs"],
    "composer": ["composer"], "comment": ["comment", "description"],
    "bpm": ["bpm"], "copyright": ["copyright"], "grouping": ["grouping", "contentgroup"],
    "lyrics": ["lyrics", "unsyncedlyrics"], "compilation": ["compilation"],
    "titlesort": ["titlesort"], "artistsort": ["artistsort"],
    "albumsort": ["albumsort"], "albumartistsort": ["albumartistsort"],
}


def _vjoin(tags, keys) -> str:
    for k in keys:
        if k in tags:
            vals = [str(v) for v in tags[k] if str(v)]
            if vals:
                return "; ".join(vals)
    return ""


def _read_vorbis(audio) -> dict:
    out = _blank()
    t = audio.tags
    if t is None:
        return out
    for field, keys in VORBIS_READ.items():
        out[field] = _vjoin(t, keys)
    if "/" in out["track"]:
        out["track"], total = _split_pair(out["track"])
        out["tracktotal"] = out["tracktotal"] or total
    if "/" in out["disc"]:
        out["disc"], total = _split_pair(out["disc"])
        out["disctotal"] = out["disctotal"] or total
    out["compilation"] = "1" if _truthy(out["compilation"]) else ""
    return out


def _write_vorbis(audio, tags: dict, changed: set):
    if audio.tags is None:
        audio.add_tags()
    t = audio.tags

    def setkey(key, value, aliases=()):
        for k in (key, *aliases):
            _delete(t, k)
        if value:
            t[key] = [value]

    simple = {
        "title": ("title", ()), "artist": ("artist", ()), "album": ("album", ()),
        "albumartist": ("albumartist", ("album artist",)),
        "date": ("date", ("year",)), "genre": ("genre", ()),
        "composer": ("composer", ()), "comment": ("comment", ("description",)),
        "bpm": ("bpm", ()), "copyright": ("copyright", ()),
        "grouping": ("grouping", ("contentgroup",)),
        "lyrics": ("lyrics", ("unsyncedlyrics",)),
        "titlesort": ("titlesort", ()), "artistsort": ("artistsort", ()),
        "albumsort": ("albumsort", ()), "albumartistsort": ("albumartistsort", ()),
    }
    for field, (key, aliases) in simple.items():
        if field in changed:
            setkey(key, tags[field], aliases)
    if changed & {"track", "tracktotal"}:
        setkey("tracknumber", tags["track"].strip())
        setkey("tracktotal", tags["tracktotal"].strip(), ("totaltracks",))
    if changed & {"disc", "disctotal"}:
        setkey("discnumber", tags["disc"].strip())
        setkey("disctotal", tags["disctotal"].strip(), ("totaldiscs",))
    if "compilation" in changed:
        setkey("compilation", "1" if tags["compilation"] else "")


def _vorbis_pictures(audio):
    if isinstance(audio, FLAC):
        return list(audio.pictures)
    pics = []
    for enc in (audio.tags or {}).get("metadata_block_picture", []):
        try:
            pics.append(Picture(base64.b64decode(enc)))
        except Exception:
            pass
    return pics


def _read_art_vorbis(audio):
    pics = _vorbis_pictures(audio)
    if not pics:
        return None
    pic = next((p for p in pics if p.type == 3), pics[0])
    return (pic.mime or sniff_mime(pic.data), bytes(pic.data))


def _write_art_vorbis(audio, art):
    if audio.tags is None:
        audio.add_tags()
    pic = None
    if art:
        mime, data = art
        pic = Picture()
        pic.type, pic.mime, pic.desc, pic.data = 3, mime, "Cover", data
    if isinstance(audio, FLAC):
        audio.clear_pictures()
        if pic:
            audio.add_picture(pic)
    else:
        _delete(audio.tags, "metadata_block_picture")
        if pic:
            audio.tags["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]


# --------------------------------------------------------------------------- MP4 / M4A

MP4_TEXT = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART",
    "date": "\xa9day", "genre": "\xa9gen", "composer": "\xa9wrt", "comment": "\xa9cmt",
    "copyright": "cprt", "grouping": "\xa9grp", "lyrics": "\xa9lyr",
    "titlesort": "sonm", "artistsort": "soar", "albumsort": "soal", "albumartistsort": "soaa",
}


def _read_mp4(audio) -> dict:
    out = _blank()
    t = audio.tags
    if t is None:
        return out
    for field, key in MP4_TEXT.items():
        vals = t.get(key) or []
        out[field] = "; ".join(str(v) for v in vals if str(v))
    if not out["genre"] and t.get("gnre"):
        try:
            out["genre"] = id3.GENRES[t["gnre"][0] - 1]
        except Exception:
            pass
    trkn = (t.get("trkn") or [(0, 0)])[0]
    disk = (t.get("disk") or [(0, 0)])[0]
    out["track"], out["tracktotal"] = (str(x) if x else "" for x in (list(trkn) + [0, 0])[:2])
    out["disc"], out["disctotal"] = (str(x) if x else "" for x in (list(disk) + [0, 0])[:2])
    cpil = t.get("cpil")
    if isinstance(cpil, (list, tuple)):
        cpil = cpil[0] if cpil else False
    out["compilation"] = "1" if cpil else ""
    out["bpm"] = str(t["tmpo"][0]) if t.get("tmpo") else ""
    return out


def _write_mp4(audio, tags: dict, changed: set):
    if audio.tags is None:
        audio.tags = MP4Tags()
    t = audio.tags
    for field, key in MP4_TEXT.items():
        if field in changed:
            if tags[field]:
                t[key] = [tags[field]]
            else:
                _delete(t, key)
            if field == "genre":
                _delete(t, "gnre")
    if changed & {"track", "tracktotal"}:
        n, tot = _int(tags["track"], "Track"), _int(tags["tracktotal"], "Track total")
        if n or tot:
            t["trkn"] = [(n, tot)]
        else:
            _delete(t, "trkn")
    if changed & {"disc", "disctotal"}:
        n, tot = _int(tags["disc"], "Disc"), _int(tags["disctotal"], "Disc total")
        if n or tot:
            t["disk"] = [(n, tot)]
        else:
            _delete(t, "disk")
    if "compilation" in changed:
        if tags["compilation"]:
            t["cpil"] = True
        else:
            _delete(t, "cpil")
    if "bpm" in changed:
        bpm = _int(tags["bpm"], "BPM")
        if bpm:
            t["tmpo"] = [bpm]
        else:
            _delete(t, "tmpo")


def _read_art_mp4(audio):
    covers = (audio.tags or {}).get("covr")
    if not covers:
        return None
    c = covers[0]
    mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
    return (mime, bytes(c))


def _write_art_mp4(audio, art):
    if audio.tags is None:
        audio.tags = MP4Tags()
    _delete(audio.tags, "covr")
    if art:
        mime, data = art
        fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio.tags["covr"] = [MP4Cover(data, imageformat=fmt)]


# --------------------------------------------------------------------------- ID3 (MP3 / WAV / AIFF)

ID3_TEXT = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
    "genre": "TCON", "composer": "TCOM", "bpm": "TBPM", "copyright": "TCOP",
    "titlesort": "TSOT", "artistsort": "TSOP", "albumsort": "TSOA", "albumartistsort": "TSO2",
}


def _frame_text(frame) -> str:
    if frame is None:
        return ""
    return "; ".join(str(x) for x in frame.text if str(x))


def _pick_comm(tags):
    frames = tags.getall("COMM")
    for f in frames:
        if f.desc == "":
            return f
    for f in frames:
        if not f.desc.lower().startswith(("itun", "id3v1")):
            return f
    return None


def _read_id3(audio) -> dict:
    out = _blank()
    t = audio.tags
    if t is None:
        return out

    def first(*ids):
        for i in ids:
            s = _frame_text(t.get(i))
            if s:
                return s
        return ""

    for field, fid in ID3_TEXT.items():
        out[field] = first(fid)
    if t.get("TCON"):
        out["genre"] = "; ".join(t["TCON"].genres)
    out["date"] = first("TDRC", "TYER")
    out["track"], out["tracktotal"] = _split_pair(first("TRCK"))
    out["disc"], out["disctotal"] = _split_pair(first("TPOS"))
    out["grouping"] = first("GRP1", "TIT1")
    out["compilation"] = "1" if _truthy(first("TCMP")) else ""
    c = _pick_comm(t)
    out["comment"] = _frame_text(c)
    lyr = t.getall("USLT")
    out["lyrics"] = lyr[0].text if lyr else ""
    return out


def _write_id3(audio, tags: dict, changed: set):
    if audio.tags is None:
        audio.add_tags()
    t = audio.tags

    def put(fid, value):
        t.delall(fid)
        if value:
            t.add(getattr(id3, fid)(encoding=3, text=[value]))

    for field, fid in ID3_TEXT.items():
        if field in changed:
            put(fid, tags[field])
    if "date" in changed:
        t.delall("TYER")
        put("TDRC", tags["date"])
    if changed & {"track", "tracktotal"}:
        n, tot = tags["track"].strip(), tags["tracktotal"].strip()
        put("TRCK", f"{n}/{tot}" if n and tot else (n or (f"0/{tot}" if tot else "")))
    if changed & {"disc", "disctotal"}:
        n, tot = tags["disc"].strip(), tags["disctotal"].strip()
        put("TPOS", f"{n}/{tot}" if n and tot else (n or (f"0/{tot}" if tot else "")))
    if "grouping" in changed:
        put("GRP1", tags["grouping"])
        put("TIT1", tags["grouping"])
    if "compilation" in changed:
        put("TCMP", "1" if tags["compilation"] else "")
    if "comment" in changed:
        old = _pick_comm(t)
        lang, desc = (old.lang, old.desc) if old else ("eng", "")
        if old is not None:
            t.pop(old.HashKey, None)
        if tags["comment"]:
            t.add(id3.COMM(encoding=3, lang=lang, desc=desc, text=[tags["comment"]]))
    if "lyrics" in changed:
        t.delall("USLT")
        if tags["lyrics"]:
            t.add(id3.USLT(encoding=3, lang="eng", desc="", text=tags["lyrics"]))


def _read_art_id3(audio):
    if audio.tags is None:
        return None
    pics = audio.tags.getall("APIC")
    if not pics:
        return None
    p = next((x for x in pics if x.type == 3), pics[0])
    return (p.mime or sniff_mime(p.data), bytes(p.data))


def _write_art_id3(audio, art):
    if audio.tags is None:
        audio.add_tags()
    audio.tags.delall("APIC")
    if art:
        mime, data = art
        audio.tags.add(id3.APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))


_READERS = {"vorbis": _read_vorbis, "mp4": _read_mp4, "id3": _read_id3}
_WRITERS = {"vorbis": _write_vorbis, "mp4": _write_mp4, "id3": _write_id3}
_ART_READERS = {"vorbis": _read_art_vorbis, "mp4": _read_art_mp4, "id3": _read_art_id3}
_ART_WRITERS = {"vorbis": _write_art_vorbis, "mp4": _write_art_mp4, "id3": _write_art_id3}


def _open(path):
    audio = MutagenFile(str(path))
    if audio is None:
        raise ValueError("Not a recognised audio file")
    return audio, _kind(audio)


# --------------------------------------------------------------------------- Track

class Track:
    """One audio file plus its pending (unsaved) edits."""

    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def reload(self):
        audio, kind = _open(self.path)
        self.kind = kind
        self.format = _codec(audio)
        info = audio.info
        self.length = float(getattr(info, "length", 0) or 0)
        self.bitrate = int(getattr(info, "bitrate", 0) or 0)
        self.orig = _READERS[kind](audio)
        self.tags = dict(self.orig)
        art = _ART_READERS[kind](audio)
        self._file_art_digest = _digest(art[1]) if art else ""
        self.art_op = None  # None | ("set", mime, data) | ("remove",)

    # -- state
    def changed_fields(self) -> set:
        return {k for k in FIELD_KEYS if self.tags[k] != self.orig[k]}

    def is_dirty(self) -> bool:
        return bool(self.changed_fields()) or self.art_op is not None

    def revert(self):
        self.tags = dict(self.orig)
        self.art_op = None

    # -- artwork
    def art_digest(self) -> str:
        if self.art_op:
            return _digest(self.art_op[2]) if self.art_op[0] == "set" else ""
        return self._file_art_digest

    def read_art(self):
        """Current artwork as (mime, bytes) or None, including a pending change."""
        if self.art_op:
            return (self.art_op[1], self.art_op[2]) if self.art_op[0] == "set" else None
        if not self._file_art_digest:
            return None
        audio, kind = _open(self.path)
        return _ART_READERS[kind](audio)

    def set_art(self, mime: str, data: bytes):
        self.art_op = ("set", mime, data)

    def remove_art(self):
        self.art_op = ("remove",)

    # -- saving
    def save(self):
        changed = self.changed_fields()
        if not changed and self.art_op is None:
            return
        audio, kind = _open(self.path)
        _WRITERS[kind](audio, self.tags, changed)
        if self.art_op is not None:
            art = (self.art_op[1], self.art_op[2]) if self.art_op[0] == "set" else None
            _ART_WRITERS[kind](audio, art)
        audio.save()
        self.reload()


# --------------------------------------------------------------------------- renaming

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    name = _ILLEGAL.sub("-", name).strip().strip(".")
    return re.sub(r"\s+", " ", name)


def format_filename(pattern: str, tags: dict) -> str:
    """Expand %field% tokens. %track% and %disc% are zero-padded to 2 digits."""
    def repl(m):
        key = m.group(1).lower()
        val = tags.get(key, "")
        if key in ("track", "disc") and val.strip().isdigit():
            val = val.strip().zfill(2)
        return val
    return sanitize_filename(re.sub(r"%(\w+)%", repl, pattern))


def rename_track(track: Track, new_stem: str) -> Path:
    """Rename the file on disk (keeps extension, avoids overwriting)."""
    if not new_stem:
        return track.path
    ext = track.path.suffix
    target = track.path.with_name(new_stem + ext)
    n = 2
    while target.exists() and not _same_file(target, track.path):
        target = track.path.with_name(f"{new_stem} ({n}){ext}")
        n += 1
    if target != track.path:
        track.path.rename(target)  # also handles case-only renames on macOS
        track.path = target
    return target


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False
