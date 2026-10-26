# TagBee

A small music tag editor in the spirit of Mp3tag, styled to match the MacBee music player
(formerly called TagForge). Drag files or folders onto the window,
select one or many tracks, edit, and press **⌘S** - changes are written straight into the files
(no backups, no exported copies).

Formats: FLAC, M4A/MP4/M4B, MP3, Ogg Vorbis, Opus, WAV, AIFF.

## Run (Mac)
1. Install Python 3 from python.org if you don't have it (`python3 --version` in Terminal to check).
2. Double-click **run.command**. First launch creates a private environment and installs
   PySide6 + mutagen (needs internet once). If macOS blocks it: right-click → Open.
   Or in Terminal: `cd` into this folder, then `./run.command`.

## Install as a normal Mac app (once)
Double-click **Install TagBee.command**. It builds TagBee.app (with its icon), copies it to your
**Applications** folder (or ~/Applications if that isn't writable), checks that it starts, and opens it.
If the old TagForge.app is in Applications, the installer moves it to the Trash. Afterwards launch it from Launchpad / Spotlight / Applications, keep it in the Dock, and drop audio
files or folders onto its Dock icon. Everything it does is logged to
`~/Library/Logs/TagBee-install.log`; if anything goes wrong, that's the file to send.
To update later, run the installer again.

## Updating (and setting up another Mac)
After the first setup, just open **Update TagBee** in Applications: it pulls the newest version from
GitHub, rebuilds TagBee.app and reopens it (or says it's already up to date). Log: `~/Library/Logs/TagBee-update.log`.

First time on a Mac, paste this in Terminal (needs Python 3; macOS offers to install it if missing):

    git clone https://github.com/troyhome/TagBee ~/Projects/TagBee && ~/Projects/TagBee/Tools/tagbee.sh setup

That installs TagBee.app and makes the Update TagBee app. From Terminal: `Tools/tagbee.sh update`.

To publish a version: `Tools/tagbee.sh release` (raises the version, puts `TagBee-<version>.dmg` on the
Desktop and posts it as a GitHub Release).

## Remove Duplicates and Find Lyrics
**Tools ▸ Remove Duplicates…** finds songs loaded more than once (same artist and title, lengths within 3 s),
keeps the best-quality copy (lossless, then bit depth / sample rate, then bitrate) and moves the ticked extra
copies to the Trash. **Tools ▸ Find Lyrics…** (⇧⌘L) looks up lyrics on LRCLIB for the selected songs (or all);
they're added to the songs and written on Commit to File, and time-synced lyrics are also saved as a `.lrc` file
next to each song (renames move it along).

## Identify Songs (like MusicBrainz Picard)
**Tools ▸ Identify Songs…** (⇧⌘I, or the sidebar) recognises songs by their sound, so it works for files with no
tags or a name like "Track 07.flac". Chromaprint's `fpcalc` (bundled in `bin/`, version 1.6.2 from
github.com/acoustid/chromaprint, LGPL) makes an audio fingerprint, AcoustID says which MusicBrainz recording it is,
and MusicBrainz gives the title, artist, album, album artist, year, track and disc. When a song is on several
albums (album, single, compilation) you pick one; songs in one folder are pre-set to the album they share. Songs
80% sure or more are ticked. Apply, then Commit to File. With no songs selected it identifies those missing a
title, artist or album. Fix All offers to identify those first.

It needs a free AcoustID app key, once per Mac: sign in at https://acoustid.org (with a MusicBrainz account),
open **Your applications ▸ Register a new application** (name TagBee, version 1.2, website
https://github.com/troyhome/TagBee), copy the **API key** and paste it in the Identify Songs window.

## Fix All
**Tools ▸ Fix All…** (⇧⌘W, or the sidebar) does everything in one go for every loaded track: it finds covers
online for each album and lets you pick one per album, can move duplicates to the Trash and find lyrics, (a match is pre-picked only when the title agrees; None
leaves an album alone), renames files to the default style (Title - Artist - Track) where they differ, and
commits all changes to the files.

## Making a compilation
Select the tracks → **Tools ▸ Make Compilation…** (⌘K).
Each track keeps its own **Artist**; **Album Artist** becomes "Various Artists" (editable) and the
**Compilation** flag is set (`cpil` in M4A, `TCMP` in MP3, `COMPILATION=1` in FLAC/Ogg/Opus).
Players then show one album instead of one album per artist. Optionally sets the album name and
numbers the tracks. Then ⌘S.

## Layout
Left: **Add Files** (pick files, folders, or both) / **Add Folder** and tools (**Make Compilation, Auto-number, Rename Files**). The button at the top
collapses it to a strip of icons (⌃⌘S). Middle: a drop area when empty, then the track list; drop files or
folders on it any time. **Right-click the column headings** to show more columns (Album Artist, Year, Genre,
Format, Time). Right: the tag panel, laid out like Mp3tag's (Title, Artist, Album, Year/Track/Genre, Comment,
Album Artist, Composer, Disc Number + Compilation, **More fields** for the rest, then the cover last). Bottom: Mp3tag-style totals, `Selected: 3 (11:32 | 89.3 MB)`.

## Editing: Apply → Commit to File
1. **Edit** fields in the tag panel (the edited field gets an accent outline).
2. **Apply** (Return or ⌘↩) puts the edits on the selected tracks; their rows turn amber/bold. Selecting other
   tracks also applies them, so nothing typed is lost.
3. **Commit to File** (⌘S) writes every changed track into its file. No backups; files are changed in place.

**Revert** (⌘R) throws away edits you haven't applied; with none, it undoes the selected tracks' unsaved changes.

**Preferences** (⌘,): theme, accent colour and sidebar width (the same settings as MacBee), plus text size.

- Multi-select edits many files at once. **< keep >** (orange dashed outline) means the tracks differ: type to
  replace it on all of them. Each field's **▾** menu offers < keep >, < blank > (clear it on all) or any value the
  selected tracks already have, like Mp3tag.
- Fields: Title, Artist, Album, Album Artist, Compilation, Year/Date, Genre, Track & total,
  Disc & total, Composer, Comment, BPM, Copyright, Grouping, Lyrics, and sort names
  (tick "Sort names" in the panel).
- Cover art: shows the current cover; **Replace cover…** or drop an image file on the window
  with tracks selected; **Remove** deletes it.
  **Find** (or Tools ▸ Find Cover Online…, ⇧⌘F) searches Apple Music and MusicBrainz for the album's cover
  (with several albums selected, it shows a list of choices per album);
  double-click one to use it, then Apply and Commit to File.
- **View ▸ Theme**, **View ▸ Accent Color** and **View ▸ Larger / Smaller Text** (⌘+ / ⌘- / ⌘0) are also in
  Preferences. All are remembered.
- Right-click a track for the tools, Show in Finder, Revert and Remove.
- The Format column shows a quality badge (e.g. FLAC 24/96); hi-res files use the accent colour.
- Tools: **Auto-number…**, **Rename Files…** (presets: Title - Artist - Track (default), Track - Artist - Title,
  Artist - Title; or type your own with %track% %artist% %title% %album% …, with preview).
- Only fields you change are written; other tags (ReplayGain, MusicBrainz IDs, multi-value artists…)
  are left exactly as they were.

## Files
- `tagbee.py` - the app window
- `theme.py` - every colour (MacBee's theme tokens: background, surface, accent…) and the stylesheet
- `lyrics.py` - online lyrics (LRCLIB) and duplicate finding
- `identify.py` - Identify Songs (Chromaprint fingerprint → AcoustID → MusicBrainz)
- `bin/fpcalc` - Chromaprint's fingerprint tool (macOS universal)
- `covers.py` - online cover search (Apple Music / iTunes and MusicBrainz Cover Art Archive)
- `version.py` - the version number (shown in TagBee ▸ About TagBee; `release` raises it)
- `tagio.py` - reading/writing tags for each format (no GUI)
- `widgets.py` - MacBee-style controls: sidebar rows, flat icon buttons, capsules, Yes/No switch
- `make_icon.py` - draws `icon.png` (Bee Tag: amber tag with MacBee's bee, matching MacBee's Vinyl Bee icon)
- `make_symbols.swift` - saves the SF Symbols (the same icons MacBee uses) into `icons/`: `swift make_symbols.swift`
- Folders ending in `.nosync` (libraries and build output) are skipped by iCloud, so they don't upload
- `test_tagio.py` - round-trip tests: `python3 test_tagio.py <folder of sample audio>`

Built on the starter project's field list and Mutagen approach.
