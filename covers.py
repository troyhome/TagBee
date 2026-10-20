"""covers.py - find album covers online (Apple Music / iTunes and MusicBrainz's Cover Art Archive).

Both are free and need no account. Everything is asynchronous (QtNetwork), so the window never freezes.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget,
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

    def _get(self, url: QUrl, handler, gen: int, attempt: int = 0):
        req = QNetworkRequest(url)
        req.setRawHeader(b"User-Agent", USER_AGENT)
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        req.setTransferTimeout(15000)
        reply = self.net.get(req)
        self._pending += 1

        def done():
            self._pending -= 1
            try:
                status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if gen == self._gen and status in (429, 503) and attempt < 2:
                    # MusicBrainz asking us to slow down: wait a moment and try again
                    self._pending += 1
                    def again():
                        self._pending -= 1
                        self._get(url, handler, gen, attempt + 1)
                    QTimer.singleShot(1500 * (attempt + 1), again)
                elif gen == self._gen and reply.error() == QNetworkReply.NoError:
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


def norm(text: str) -> str:
    """Lowercase letters and digits only, for comparing album titles."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


class AlbumCoverRow(QWidget):
    """One album in the magic wand: its name on the left, a row of covers to choose from (or None)."""

    def __init__(self, title: str, artist: str, count: int, current: QPixmap | None):
        super().__init__()
        self.title, self.artist = title, artist
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 6, 0, 6); lay.setSpacing(12)
        info = QVBoxLayout(); info.setSpacing(2)
        cover = QLabel(); cover.setFixedSize(64, 64); cover.setObjectName("cover"); cover.setAlignment(Qt.AlignCenter)
        if current is not None:
            cover.setPixmap(current)
        else:
            cover.setText("No cover")
        name = QLabel(title or "(no album)"); name.setWordWrap(True)
        f = name.font(); f.setBold(True); name.setFont(f)
        sub = QLabel(f"{artist}\n{count} song{'s' if count != 1 else ''}"); sub.setObjectName("muted")
        self.state = QLabel("Waiting…"); self.state.setObjectName("faint")
        for w in (cover, name, sub, self.state):
            info.addWidget(w)
        info.addStretch(1)
        box = QWidget(); box.setFixedWidth(170); box.setLayout(info)
        lay.addWidget(box)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setFlow(QListWidget.LeftToRight)
        self.grid.setWrapping(False)
        self.grid.setIconSize(QSize(110, 110))
        self.grid.setGridSize(QSize(126, 158))
        self.grid.setFixedHeight(176)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        none = QListWidgetItem("None\n(leave as is)")
        none.setSizeHint(QSize(120, 150)); none.setTextAlignment(Qt.AlignCenter)
        none.setData(Qt.UserRole, None)
        self.grid.addItem(none)
        self.grid.setCurrentRow(0)
        lay.addWidget(self.grid, 1)
        self.picked_by_hand = False
        self.grid.itemClicked.connect(lambda _: setattr(self, "picked_by_hand", True))

    def add(self, r: dict, img: QImage):
        pix = QPixmap.fromImage(img.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        pix.setDevicePixelRatio(2.0)
        year = f" ({r['year']})" if r.get("year") else ""
        it = QListWidgetItem(QIcon(pix), f"{r['album']}{year}\n{r['source']}")
        it.setToolTip(f"{r['album']}{year}\n{r['artist']}\nfrom {r['source']}")
        it.setData(Qt.UserRole, r)
        it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.grid.addItem(it)
        # pre-pick the first cover whose album title matches; never a guess
        if not self.picked_by_hand and self.grid.currentRow() == 0 and norm(r["album"]) == norm(self.title) != "":
            self.grid.setCurrentItem(it)

    def choice(self) -> dict | None:
        it = self.grid.currentItem()
        return it.data(Qt.UserRole) if it else None


class MagicWandDialog(QDialog):
    """Magic wand: find a cover for every album (you choose), optionally rename, then save everything."""

    def __init__(self, parent, albums: list[dict], rename_count: int, rename_label: str):
        super().__init__(parent)
        self.setWindowTitle("Magic Wand")
        self.resize(900, 640)
        self.albums = albums
        self.covers: dict[int, bytes] = {}       # album index -> chosen cover bytes
        self.search = None
        lay = QVBoxLayout(self)
        head = QLabel(f"{len(albums)} album{'s' if len(albums) != 1 else ''}: pick a cover for each "
                      "(a match is pre-picked when the album title agrees), then click Do It All.")
        head.setWordWrap(True)
        lay.addWidget(head)
        holder = QWidget(); rows = QVBoxLayout(holder); rows.setSpacing(0)
        self.rows: list[AlbumCoverRow] = []
        for a in albums:
            row = AlbumCoverRow(a["album"], a["artist"], len(a["tracks"]), a.get("current"))
            self.rows.append(row); rows.addWidget(row)
            line = QFrame(); line.setObjectName("divider"); rows.addWidget(line)
        rows.addStretch(1)
        scroll = QScrollArea(); scroll.setWidget(holder); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        lay.addWidget(scroll, 1)
        self.do_covers = QCheckBox("Save the chosen covers")
        self.do_covers.setChecked(True)
        self.do_rename = QCheckBox(f"Rename {rename_count} file{'s' if rename_count != 1 else ''} to “{rename_label}”"
                                   if rename_count else f"Rename files to “{rename_label}” (all already match)")
        self.do_rename.setChecked(rename_count > 0); self.do_rename.setEnabled(rename_count > 0)
        lay.addWidget(self.do_covers); lay.addWidget(self.do_rename)
        note = QLabel("Do It All also commits every other unsaved change to the files. No backups are made.")
        note.setObjectName("faint"); lay.addWidget(note)
        self.status = QLabel(); self.status.setObjectName("faint")
        lay.addWidget(self.status)
        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = box.addButton("Do It All", QDialogButtonBox.AcceptRole)
        box.accepted.connect(self.start); box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._next = 0
        QTimer.singleShot(0, self.search_next)

    # one album at a time (MusicBrainz allows about one request a second)
    def search_next(self):
        if self._next >= len(self.rows):
            self.status.setText("Search finished.")
            return
        i = self._next
        row, a = self.rows[i], self.albums[i]
        row.state.setText("Searching…")
        self.status.setText(f"Searching {i + 1} of {len(self.rows)}: {a['album']}")
        self.search = CoverSearch(self)
        self.search.thumb_ready.connect(row.add)
        def finished(n, row=row):
            row.state.setText(f"{n} found" if n else "None found online")
            self._next += 1
            QTimer.singleShot(1000, self.search_next)
        self.search.finished.connect(finished)
        self.search.search(" ".join(x for x in (a["search_artist"], a["album"]) if x))

    def start(self):
        """Download the chosen covers, then close; the window does the saving."""
        self.go.setEnabled(False)
        self.todo = [(i, r.choice()) for i, r in enumerate(self.rows)
                     if self.do_covers.isChecked() and r.choice()]
        self.fetcher = CoverSearch(self)
        self.fetch_next()

    def fetch_next(self):
        if not self.todo:
            self.accept()
            return
        i, r = self.todo.pop(0)
        self.status.setText(f"Downloading cover for {self.albums[i]['album']}…")

        def got(data, i=i):
            if data and not QImage.fromData(data).isNull():
                self.covers[i] = data
                self.rows[i].state.setText("Cover downloaded")
            else:
                self.rows[i].state.setText("Couldn't download that cover")
            self.fetch_next()
        self.fetcher.download(r["full"], got)
