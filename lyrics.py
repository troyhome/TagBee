"""lyrics.py - find song lyrics online (LRCLIB, free, no account) and find duplicate tracks.

Lyrics come back as plain text (for the lyrics tag) and, when available, time-synced LRC text (saved as a
.lrc file next to the song on Commit). Requests run one at a time inside a local event loop, so the window
keeps drawing while a progress dialog is up.
"""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QEventLoop, QTimer, QUrl, QUrlQuery
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

USER_AGENT = b"TagBee/1.1 ( https://github.com/troyhome/TagBee )"
LOSSLESS = {"FLAC", "ALAC", "WAV", "AIFF"}
COPY_SUFFIX = re.compile(r"(\s*\(\d+\)|\s+copy(\s+\d+)?|\s*-\s*copy)$", re.I)   # " (2)", " copy", " copy 3"


class LyricsFinder:
    def __init__(self):
        self.net = QNetworkAccessManager()

    def _get(self, url: QUrl, timeout_ms: int = 15000):
        """(status, body) for a GET, retrying when the server says it's busy."""
        for attempt in range(3):
            req = QNetworkRequest(url)
            req.setRawHeader(b"User-Agent", USER_AGENT)
            req.setTransferTimeout(timeout_ms)
            reply = self.net.get(req)
            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            loop.exec()
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
            body = bytes(reply.readAll())
            reply.deleteLater()
            if status in (429, 503) and attempt < 2:
                wait = QEventLoop()
                QTimer.singleShot(1500 * (attempt + 1), wait.quit)
                wait.exec()
                continue
            return status, body
        return 0, b""

    def find(self, artist: str, title: str, album: str = "", duration: float = 0):
        """(plain, synced) lyrics, either may be "", or None when nothing was found."""
        artist, title = artist.strip(), clean_title(title)
        if not artist or not title:
            return None
        tries = []
        if album and duration:
            tries.append({"album_name": album, "duration": str(int(round(duration)))})
        tries.append({})
        for extra in tries:
            url = QUrl("https://lrclib.net/api/get")
            q = QUrlQuery(); q.addQueryItem("artist_name", artist); q.addQueryItem("track_name", title)
            for k, v in extra.items():
                q.addQueryItem(k, v)
            url.setQuery(q)
            status, body = self._get(url)
            if status == 200:
                try:
                    d = json.loads(body)
                except ValueError:
                    continue
                if d.get("instrumental"):
                    return "[Instrumental]", ""
                plain, synced = d.get("plainLyrics") or "", d.get("syncedLyrics") or ""
                if not plain and synced:
                    plain = re.sub(r"^\[[^\]]*\]\s?", "", synced, flags=re.M)
                if plain or synced:
                    return plain.strip(), synced.strip()
        return None


def clean_title(title: str) -> str:
    """Drop " (Remastered 2011)", "[Live]", "- Radio Edit" style extras that stop a lyrics match."""
    t = re.sub(r"\s*[\(\[][^)\]]*(remaster|live|edit|version|mono|stereo|demo|bonus|deluxe|mix)[^)\]]*[\)\]]",
               "", title, flags=re.I)
    t = re.sub(r"\s+-\s+.*(remaster|live|edit|version|mono|stereo).*$", "", t, flags=re.I)
    return t.strip()


# --------------------------------------------------------------------------- duplicates

def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def quality_score(t) -> tuple:
    """Higher is better: lossless first, then bit depth / sample rate, then bitrate, then file size."""
    return (t.format in LOSSLESS, t.bits, t.sample_rate, t.bitrate, getattr(t, "size", 0))


def find_duplicates(tracks) -> list[list]:
    """Groups of tracks that are the same song (same artist and title, lengths within 3 s), best copy first."""
    by_key: dict[tuple, list] = {}
    for t in tracks:
        artist, title = _norm(t.tags["artist"] or t.tags["albumartist"]), _norm(clean_title(t.tags["title"]))
        if artist and title:
            key = ("tags", artist, title)
        else:
            # no tags to go on: "Hosanna - Eric Nordhoff - 08 (2).m4a" is a copy of "... - 08.m4a"
            key = ("name", _norm(COPY_SUFFIX.sub("", t.path.stem)))
        by_key.setdefault(key, []).append(t)
    groups = []
    for same in by_key.values():
        same.sort(key=lambda t: t.length)
        cluster = [same[0]]
        for t in same[1:]:
            if abs(t.length - cluster[-1].length) <= 3:
                cluster.append(t)
            else:
                if len(cluster) > 1:
                    groups.append(cluster)
                cluster = [t]
        if len(cluster) > 1:
            groups.append(cluster)
    for g in groups:
        # best quality first; between equal copies keep the one without "(2)" / "copy" in its name
        g.sort(key=lambda t: (quality_score(t), not COPY_SUFFIX.search(t.path.stem)), reverse=True)
    return groups
