"""covers.py - find album covers online (Apple Music / iTunes and MusicBrainz's Cover Art Archive).

Both are free and need no account. Everything is asynchronous (QtNetwork), so the window never freezes.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QSize, Qt, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

USER_AGENT = b"TagBee/1.0 ( https://github.com/troyhome/TagBee )"   # MusicBrainz asks apps to say who they are
THUMB = 160


class CoverSearch(QObject):
    """Runs one search at a time; emits each result as it arrives."""
    found = Signal(dict)          # {"source", "album", "artist", "thumb", "full", "size"}
    thumb_ready = Signal(dict, QImage)
    finished = Signal(int)        # number of results

    def __init__(self, parent=None):
        super().__init__(parent)
        self.net = QNetworkAccessManager(self)
        self._gen = 0
        self._pending = 0
        self._count = 0

    def _get(self, url: QUrl, handler, gen: int):
        req = QNetworkRequest(url)
        req.setRawHeader(b"User-Agent", USER_AGENT)
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        req.setTransferTimeout(15000)
        reply = self.net.get(req)
        self._pending += 1

        def done():
            self._pending -= 1
            try:
                if gen == self._gen and reply.error() == QNetworkReply.NoError:
                    handler(bytes(reply.readAll()))
            finally:
                reply.deleteLater()
                if gen == self._gen and self._pending == 0:
                    self.finished.emit(self._count)
        reply.finished.connect(done)

    def search(self, text: str):
        self._gen += 1
        self._count = 0
        gen = self._gen
        text = text.strip()
        if not text:
            self.finished.emit(0)
            return
        # Apple Music / iTunes: big, clean covers; the URL can ask for any size up to the original
        url = QUrl("https://itunes.apple.com/search")
        q = QUrlQuery(); q.addQueryItem("term", text); q.addQueryItem("entity", "album"); q.addQueryItem("limit", "24")
        url.setQuery(q)
        self._get(url, lambda data: self._itunes(data, gen), gen)
        # MusicBrainz release groups -> Cover Art Archive front covers
        url = QUrl("https://musicbrainz.org/ws/2/release-group/")
        q = QUrlQuery(); q.addQueryItem("query", text); q.addQueryItem("fmt", "json"); q.addQueryItem("limit", "12")
        url.setQuery(q)
        self._get(url, lambda data: self._musicbrainz(data, gen), gen)

    def _emit(self, r: dict, gen: int):
        def got(data):
            img = QImage.fromData(data)
            if not img.isNull():
                self._count += 1
                self.found.emit(r)
                self.thumb_ready.emit(r, img)
        self._get(QUrl(r["thumb"]), got, gen)

    def _itunes(self, data: bytes, gen: int):
        for it in json.loads(data).get("results", []):
            art = it.get("artworkUrl100")
            if not art:
                continue
            self._emit({"source": "Apple Music", "album": it.get("collectionName", ""),
                        "artist": it.get("artistName", ""), "year": (it.get("releaseDate") or "")[:4],
                        "thumb": art.replace("100x100bb", f"{THUMB * 2}x{THUMB * 2}bb"),
                        "full": art.replace("100x100bb", "1400x1400bb")}, gen)

    def _musicbrainz(self, data: bytes, gen: int):
        for rg in json.loads(data).get("release-groups", []):
            artist = " ".join(c.get("name", "") + c.get("joinphrase", "") for c in rg.get("artist-credit", []))
            base = f"https://coverartarchive.org/release-group/{rg['id']}/front"
            self._emit({"source": "MusicBrainz", "album": rg.get("title", ""), "artist": artist.strip(),
                        "year": (rg.get("first-release-date") or "")[:4],
                        "thumb": base + "-250", "full": base + "-1200"}, gen)

    def download(self, url: str, callback):
        """Fetch a full-size cover; callback(bytes or None)."""
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", USER_AGENT)
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        req.setTransferTimeout(30000)
        reply = self.net.get(req)

        def done():
            ok = reply.error() == QNetworkReply.NoError
            data = bytes(reply.readAll()) if ok else None
            reply.deleteLater()
            callback(data)
        reply.finished.connect(done)


class CoverSearchDialog(QDialog):
    """Search box + a grid of covers. Double-click one (or Use Cover) to pick it."""

    def __init__(self, parent, query: str):
        super().__init__(parent)
        self.setWindowTitle("Find Cover Online")
        self.resize(760, 560)
        self.result: bytes | None = None
        self.search = CoverSearch(self)
        self.search.thumb_ready.connect(self.add_result)
        self.search.finished.connect(self.on_finished)

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit(query); self.query.setPlaceholderText("Artist and album")
        self.query.returnPressed.connect(self.run)
        go = QPushButton("Search"); go.setAutoDefault(False); go.clicked.connect(self.run)
        row.addWidget(self.query, 1); row.addWidget(go)
        lay.addLayout(row)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 30, THUMB + 58))
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.itemDoubleClicked.connect(lambda _: self.choose())
        lay.addWidget(self.grid, 1)
        self.status = QLabel(); self.status.setObjectName("faint")
        lay.addWidget(self.status)
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.use = box.addButton("Use Cover", QDialogButtonBox.AcceptRole)
        self.use.setEnabled(False)
        self.grid.itemSelectionChanged.connect(lambda: self.use.setEnabled(bool(self.grid.selectedItems())))
        box.accepted.connect(self.choose); box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.run()

    def run(self):
        self.grid.clear()
        self.use.setEnabled(False)
        self.status.setText("Searching Apple Music and MusicBrainz…")
        self.search.search(self.query.text())

    def add_result(self, r: dict, img: QImage):
        pix = QPixmap.fromImage(img.scaled(THUMB * 2, THUMB * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        pix.setDevicePixelRatio(2.0)
        year = f" ({r['year']})" if r.get("year") else ""
        it = QListWidgetItem(QIcon(pix), f"{r['album']}{year}\n{r['artist']}")
        it.setToolTip(f"{r['album']}{year}\n{r['artist']}\nfrom {r['source']}")
        it.setData(Qt.UserRole, r)
        it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.grid.addItem(it)

    def on_finished(self, n: int):
        if n:
            self.status.setText(f"{n} cover{'s' if n != 1 else ''} found. Double-click one to use it.")
        else:
            self.status.setText("No covers found. Try fewer words, or check your internet connection.")

    def choose(self):
        items = self.grid.selectedItems()
        if not items:
            return
        r = items[0].data(Qt.UserRole)
        self.status.setText("Downloading the full-size cover…")
        self.use.setEnabled(False)
        self.search.download(r["full"], self.downloaded)

    def downloaded(self, data):
        if data and not QImage.fromData(data).isNull():
            self.result = data
            self.accept()
        else:
            self.status.setText("That cover couldn't be downloaded. Try another one.")
            self.use.setEnabled(True)
