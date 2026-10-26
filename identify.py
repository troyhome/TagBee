"""identify.py - recognise songs by their sound, like MusicBrainz Picard.

1. Chromaprint's `fpcalc` (bundled in bin/) listens to the file and makes an audio fingerprint.
2. AcoustID (free; needs an app key, see README) says which MusicBrainz recordings have that fingerprint.
3. MusicBrainz gives each recording's title and artist, and the albums it's on (with track and disc numbers).

The window shows one row per song with its best match; when a song is on several albums (single, album,
compilation) you pick one. Nothing changes until Apply; then Commit to File saves, like every other edit.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QByteArray, QEventLoop, QProcess, QTimer, Qt, QUrl, QUrlQuery
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

USER_AGENT = b"TagBee/1.1 ( https://github.com/troyhome/TagBee )"
ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
MB_URL = "https://musicbrainz.org/ws/2/recording/"
MIN_SCORE = 0.5            # AcoustID's confidence; below this the match is a guess
VARIOUS = "Various Artists"
FILLED = ["title", "artist", "album", "albumartist", "date", "track", "tracktotal", "disc", "compilation"]


# ---- what a song is missing

PLACEHOLDER = re.compile(r"^(track\s*\d+|unknown.*|untitled.*|audio\s*track.*|\d+)$", re.I)


def needs_identifying(t) -> bool:
    """No title, artist or album, or a title that's only a placeholder ("Track 07", "Unknown", the file name)."""
    title = t.tags["title"].strip()
    if not title or not t.tags["artist"].strip() or not t.tags["album"].strip():
        return True
    return bool(PLACEHOLDER.match(title)) or title == t.path.stem


# ---- matches

@dataclass
class Album:
    """One album (MusicBrainz release group) a recording is on, with this song's place on it."""
    album: str
    albumartist: str
    year: str
    track: str
    tracktotal: str
    disc: str
    kind: str               # "Album", "Single", "Compilation", "Live" ...
    compilation: bool
    group_id: str

    def label(self) -> str:
        bits = [b for b in (self.year, self.kind) if b]
        return f"{self.album}" + (f"  ({', '.join(bits)})" if bits else "")


@dataclass
class Match:
    score: float
    title: str
    artist: str
    albums: list[Album] = field(default_factory=list)


# ---- the fingerprint tool

def fpcalc_path() -> str | None:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / "bin" / "fpcalc", base.parent / "Resources" / "bin" / "fpcalc",
                 Path(__file__).resolve().parent / "bin" / "fpcalc"):
        if cand.exists():
            return str(cand)
    return shutil.which("fpcalc")


def fingerprint(path: Path, timeout_ms: int = 120000):
    """(duration seconds, fingerprint) or None. Runs fpcalc without freezing the window."""
    exe = fpcalc_path()
    if not exe:
        return None
    proc = QProcess()
    proc.start(exe, ["-json", str(path)])
    loop = QEventLoop()
    proc.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    if proc.state() != QProcess.NotRunning:
        loop.exec()
    if proc.state() != QProcess.NotRunning:
        proc.kill(); proc.waitForFinished(2000)
        return None
    try:
        d = json.loads(bytes(proc.readAllStandardOutput()))
        return float(d["duration"]), str(d["fingerprint"])
    except (ValueError, KeyError):
        return None


# ---- online lookups

class KeyProblem(Exception):
    pass


class Identifier:
    def __init__(self, key: str):
        from covers import shared_net
        self.net = shared_net()
        self.key = key.strip()
        self._recordings: dict[str, dict | None] = {}

    def _wait(self, ms: int):
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

    def _send(self, url: QUrl, body: bytes | None = None, timeout_ms: int = 20000):
        """(status, body), retrying when the server says it's busy."""
        for attempt in range(3):
            req = QNetworkRequest(url)
            req.setRawHeader(b"User-Agent", USER_AGENT)
            req.setTransferTimeout(timeout_ms)
            if body is None:
                reply = self.net.get(req)
            else:
                req.setHeader(QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded")
                reply = self.net.post(req, QByteArray(body))
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            loop.exec()
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
            data = bytes(reply.readAll())
            reply.deleteLater()
            if status in (429, 503) and attempt < 2:
                self._wait(1500 * (attempt + 1))
                continue
            return status, data
        return 0, b""

    def acoustid(self, duration: float, fp: str) -> list[tuple[float, str]]:
        """[(score, MusicBrainz recording id)], best first."""
        q = QUrlQuery()
        for k, v in (("format", "json"), ("client", self.key), ("duration", str(int(round(duration)))),
                     ("fingerprint", fp), ("meta", "recordingids")):
            q.addQueryItem(k, v)
        body = q.query(QUrl.FullyEncoded).encode()
        status, data = self._send(QUrl(ACOUSTID_URL), body)
        try:
            d = json.loads(data)
        except ValueError:
            d = {}
        if d.get("status") != "ok":
            err = (d.get("error") or {})
            if err.get("code") in (4, 5) or "client" in str(err.get("message", "")).lower():
                raise KeyProblem("AcoustID didn't accept the app key. Check it in Identify Songs ▸ AcoustID key.")
            raise ConnectionError(err.get("message") or f"AcoustID didn't answer (status {status}).")
        out = []
        for r in d.get("results", []):
            for rec in r.get("recordings", []) or []:
                if rec.get("id"):
                    out.append((float(r.get("score", 0)), rec["id"]))
        seen, best = set(), []
        for score, rid in sorted(out, key=lambda x: -x[0]):
            if rid not in seen:
                seen.add(rid); best.append((score, rid))
        return best

    def recording(self, rid: str) -> dict | None:
        """MusicBrainz details (cached). Waits a second between calls, as MusicBrainz asks."""
        if rid in self._recordings:
            return self._recordings[rid]
        url = QUrl(MB_URL + rid)
        q = QUrlQuery(); q.addQueryItem("inc", "releases+media+artist-credits+release-groups"); q.addQueryItem("fmt", "json")
        url.setQuery(q)
        self._wait(1000)
        status, data = self._send(url)
        try:
            d = json.loads(data) if status == 200 else None
        except ValueError:
            d = None
        self._recordings[rid] = d
        return d

    def identify(self, path: Path) -> list[Match]:
        """Every likely recording for this file, best first ([] when unknown)."""
        fp = fingerprint(path)
        if not fp:
            raise RuntimeError("couldn't read the audio")
        matches = []
        for score, rid in self.acoustid(*fp)[:3]:
            if score < MIN_SCORE:
                continue
            rec = self.recording(rid)
            if rec:
                matches.append(to_match(score, rec))
        return [m for m in matches if m.albums] or matches


def credit(ac: list) -> str:
    return "".join((a.get("name") or a.get("artist", {}).get("name", "")) + (a.get("joinphrase") or "") for a in ac or []).strip()


def to_match(score: float, rec: dict) -> Match:
    m = Match(score=score, title=rec.get("title", ""), artist=credit(rec.get("artist-credit")))
    groups: dict[str, list[tuple[dict, dict, dict]]] = {}
    for rel in rec.get("releases", []) or []:
        rg = rel.get("release-group") or {}
        for medium in rel.get("media", []) or []:
            for tr in medium.get("tracks", []) or []:
                groups.setdefault(rg.get("id") or rel.get("id"), []).append((rel, rg, medium | {"_track": tr}))
    for gid, items in groups.items():
        def rank(item):           # official first, then the earliest
            rel = item[0]
            return (rel.get("status") != "Official", rel.get("date") or "9999")
        rel, rg, medium = sorted(items, key=rank)[0]
        aa = credit(rg.get("artist-credit") or rel.get("artist-credit")) or m.artist
        secondary = rg.get("secondary-types") or []
        various = aa.lower() in ("various artists", "various")
        kind = "Compilation" if (various or "Compilation" in secondary) else \
            (secondary[0] if secondary else rg.get("primary-type") or "")
        year = (rg.get("first-release-date") or rel.get("date") or "")[:4]
        tr = medium["_track"]
        m.albums.append(Album(
            album=rel.get("title") or rg.get("title", ""), albumartist=VARIOUS if various else aa, year=year,
            track=str(tr.get("position") or tr.get("number") or ""), tracktotal=str(medium.get("track-count") or ""),
            disc=str(medium.get("position") or ""), kind=kind, compilation=various, group_id=gid))
    m.albums.sort(key=album_rank)
    return m


def album_rank(a: Album):
    """Plain studio albums first, then EPs/singles, then compilations and live; older first."""
    order = {"Album": 0, "EP": 1, "Single": 2, "Soundtrack": 3, "Compilation": 4, "Live": 5}
    return (order.get(a.kind, 6), a.year or "9999")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# ---- the window

class IdentifyDialog(QDialog):
    """One row per song: what it is now, the match found, and which album to use."""

    def __init__(self, parent, tracks, settings):
        super().__init__(parent)
        self.setWindowTitle("Identify Songs")
        self.resize(1080, 620)
        self.tracks, self.settings = tracks, settings
        self.results: dict[int, list[Match]] = {}
        self.touched: set[int] = set()          # rows where you picked a match yourself
        self.applied = []
        lay = QVBoxLayout(self)
        head = QLabel(f"Listening to {len(tracks)} song{'s' if len(tracks) != 1 else ''} and looking them up on "
                      "AcoustID and MusicBrainz. Untick songs you don't want changed, pick the album where a song is "
                      "on several, then click Apply. Commit to File saves the changes.")
        head.setWordWrap(True); lay.addWidget(head)

        keyrow = QHBoxLayout()
        keyrow.addWidget(QLabel("AcoustID key:"))
        self.key = QLineEdit(str(settings.value("acoustidKey", "")))
        self.key.setPlaceholderText("Paste your free app key from acoustid.org (see README)")
        self.key.setEchoMode(QLineEdit.Normal)
        keyrow.addWidget(self.key, 1)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start)
        keyrow.addWidget(self.start_btn)
        lay.addLayout(keyrow)

        self.table = QTableWidget(len(tracks), 5)
        self.table.setHorizontalHeaderLabels(["USE", "NOW", "FOUND", "ALBUM", "SURE"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.checks: list[QCheckBox] = []
        self.combos: list[QComboBox] = []
        for i, t in enumerate(tracks):
            c = QCheckBox(); c.setEnabled(False); self.checks.append(c)
            self.table.setCellWidget(i, 0, c)
            now = " - ".join(x for x in (t.tags["artist"], t.tags["title"]) if x.strip()) or t.path.name
            item = QTableWidgetItem(now); item.setToolTip(str(t.path)); self.table.setItem(i, 1, item)
            self.table.setItem(i, 2, QTableWidgetItem("Waiting…"))
            combo = QComboBox(); combo.setEnabled(False); self.combos.append(combo)
            combo.activated.connect(lambda _=0, i=i: self.picked(i))
            self.table.setCellWidget(i, 3, combo)
            self.table.setItem(i, 4, QTableWidgetItem(""))
        lay.addWidget(self.table, 1)

        self.keep = QCheckBox("Keep fields that already have something in them (only fill the empty ones)")
        self.keep.setChecked(settings.value("identifyKeep", False, type=bool))
        lay.addWidget(self.keep)
        self.status = QLabel(); self.status.setObjectName("faint"); self.status.setWordWrap(True)
        self.bar = QProgressBar(); self.bar.setRange(0, max(1, len(tracks))); self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        lay.addWidget(self.status); lay.addWidget(self.bar)
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply_btn = box.addButton("Apply", QDialogButtonBox.AcceptRole)
        self.apply_btn.setEnabled(False)
        box.accepted.connect(self.apply); box.rejected.connect(self.stop_and_close)
        lay.addWidget(box)
        self._next, self._stopped = 0, False
        if self.key.text().strip():
            QTimer.singleShot(0, self.start)
        else:
            self.status.setText("TagBee needs a free AcoustID app key once. Paste it above, then click Start.")

    # ---- running
    def start(self):
        key = self.key.text().strip()
        if not key:
            self.status.setText("Paste your AcoustID app key first.")
            return
        self.settings.setValue("acoustidKey", key)
        if not fpcalc_path():
            self.status.setText("The fingerprint tool (fpcalc) is missing from TagBee. Reinstall TagBee.")
            return
        self.key.setEnabled(False); self.start_btn.setEnabled(False)
        self.finder = Identifier(key)
        QTimer.singleShot(0, self.identify_next)

    def identify_next(self):
        self.bar.setValue(self._next)
        if self._stopped:
            return
        if self._next >= len(self.tracks):
            self.finish()
            return
        i = self._next
        t = self.tracks[i]
        self.status.setText(f"Identifying {i + 1} of {len(self.tracks)}: {t.path.name}")
        self.table.item(i, 2).setText("Listening…")
        self.table.scrollToItem(self.table.item(i, 2))
        try:
            matches = self.finder.identify(t.path)
        except KeyProblem as exc:
            self.status.setText(str(exc))
            self.key.setEnabled(True); self.start_btn.setEnabled(True)
            self.table.item(i, 2).setText("Waiting…")
            return
        except Exception as exc:
            matches = None
            self.table.item(i, 2).setText(f"Not checked ({exc})")
        if matches is not None:
            self.show_matches(i, matches)
        self._next += 1
        QTimer.singleShot(0, self.identify_next)

    def show_matches(self, i, matches: list[Match]):
        self.results[i] = matches
        combo = self.combos[i]
        combo.clear()
        if not matches:
            self.table.item(i, 2).setText("Not recognised")
            return
        for mi, m in enumerate(matches):
            for ai, a in enumerate(m.albums or [None]):
                text = f"{m.artist} - {m.title}" + (f"   ·   {a.label()}" if a else "   ·   (no album)")
                combo.addItem(text, (mi, ai))
        best = matches[0]
        self.table.item(i, 2).setText(f"{best.artist} - {best.title}")
        self.table.item(i, 4).setText(f"{round(best.score * 100)}%")
        combo.setEnabled(combo.count() > 1)
        combo.setCurrentIndex(self.default_choice(i))
        self.checks[i].setEnabled(True)
        self.checks[i].setChecked(best.score >= 0.8)
        self.apply_btn.setEnabled(True)

    def default_choice(self, i, folder_groups: Counter | None = None) -> int:
        """The album already in the tags if it's one of them, else the one most songs in this folder share,
        else the first (plain studio album before singles and compilations)."""
        t, combo = self.tracks[i], self.combos[i]
        now = norm(t.tags["album"])
        best, best_rank = 0, None
        for n in range(combo.count()):
            mi, ai = combo.itemData(n)
            m = self.results[i][mi]
            a = m.albums[ai] if m.albums else None
            rank = (mi,                                                     # better fingerprint match first
                    0 if a and now and norm(a.album) == now else 1,
                    -(folder_groups or Counter())[a.group_id] if a else 0)
            if best_rank is None or rank < best_rank:
                best, best_rank = n, rank
        return best

    def finish(self):
        """Songs in one folder usually come from one album: re-pick the rows you haven't touched to agree."""
        by_folder: dict[Path, Counter] = {}
        for i, matches in self.results.items():
            if matches and matches[0].albums:
                groups = {a.group_id for a in matches[0].albums}
                by_folder.setdefault(self.tracks[i].path.parent, Counter()).update(groups)
        for i in self.results:
            if self.results[i] and i not in self.touched:
                self.combos[i].setCurrentIndex(self.default_choice(i, by_folder.get(self.tracks[i].path.parent)))
        found = sum(1 for m in self.results.values() if m)
        self.status.setText(f"Done: {found} of {len(self.tracks)} song{'s' if len(self.tracks) != 1 else ''} recognised. "
                            "Ticked songs (80% sure or more) change when you click Apply.")
        self.bar.setValue(len(self.tracks))

    def picked(self, i):
        self.touched.add(i)
        self.checks[i].setChecked(True)

    def stop_and_close(self):
        self._stopped = True
        self.reject()

    # ---- applying
    def apply(self):
        self._stopped = True
        self.settings.setValue("identifyKeep", self.keep.isChecked())
        keep = self.keep.isChecked()
        for i, t in enumerate(self.tracks):
            if not self.checks[i].isChecked() or not self.results.get(i):
                continue
            mi, ai = self.combos[i].currentData()
            m = self.results[i][mi]
            a = m.albums[ai] if m.albums else None
            new = {"title": m.title, "artist": m.artist}
            if a:
                new.update(album=a.album, albumartist=a.albumartist, date=a.year, track=a.track,
                           tracktotal=a.tracktotal, disc=a.disc, compilation="1" if a.compilation else "")
            for k, v in new.items():
                if keep and t.tags[k].strip():
                    continue
                if v or k == "compilation":
                    t.tags[k] = v
            self.applied.append(t)
        self.accept()
