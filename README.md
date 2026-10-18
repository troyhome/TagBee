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

## Making a compilation
Select the tracks → **Tools ▸ Make Compilation…** (⌘K).
Each track keeps its own **Artist**; **Album Artist** becomes "Various Artists" (editable) and the
**Compilation** flag is set (`cpil` in M4A, `TCMP` in MP3, `COMPILATION=1` in FLAC/Ogg/Opus).
Players then show one album instead of one album per artist. Optionally sets the album name and
numbers the tracks. Then ⌘S.

## Layout
Left: **Add Files / Add Folder** and tools (**Make Compilation, Auto-number, Rename Files**). The button at the top
collapses it to a strip of icons (⌃⌘S). Drop files or folders anywhere on the window.
Middle: the track list (File, #, Title, Artist, Album, Comp.). **Right-click the column headings** to show
more columns (Album Artist, Year, Genre, Format, Time); your choice is remembered. Right: the tag panel, laid out
like Mp3tag's (one column, cover at the bottom). Bottom: Mp3tag-style totals, `Selected: 3 (11:32 | 89.3 MB)`.

## Editing: edit → Save
Select tracks and type in the tag panel. Changes go onto the selected tracks right away (rows turn amber/bold),
then **Save** (⌘S) writes every changed track into its file. **Revert** (⌘R) undoes unsaved changes on the
selected tracks. No backups are made; files are changed in place.

- Multi-select edits many files at once. **< keep >** (orange dashed outline) means the tracks differ: type to
  replace it on all of them. Each field's **▾** menu offers < keep >, < blank > (clear it on all) or any value the
  selected tracks already have, like Mp3tag.
- Fields: Title, Artist, Album, Album Artist, Compilation, Year/Date, Genre, Track & total,
  Disc & total, Composer, Comment, BPM, Copyright, Grouping, Lyrics, and sort names
  (tick "Sort names" in the panel).
- Cover art: shows the current cover; **Replace cover…** or drop an image file on the window
  with tracks selected; **Remove** deletes it.
- **View ▸ Theme** (Dark / Medium Gray / Light / Match System), **View ▸ Accent Color** (Cyan, Violet, Orange,
  Green, Pink or Custom…) and **View ▸ Larger / Smaller Text** (⌘+ / ⌘- / ⌘0). All are remembered.
- Right-click a track for the tools, Show in Finder, Revert and Remove.
- The Format column shows a quality badge (e.g. FLAC 24/96); hi-res files use the accent colour.
- Tools: **Auto-number…**, **Rename Files…** (pattern like `%track% - %artist% - %title%`, with preview).
- Only fields you change are written; other tags (ReplayGain, MusicBrainz IDs, multi-value artists…)
  are left exactly as they were.

## Files
- `tagbee.py` - the app window
- `theme.py` - every colour (MacBee's theme tokens: background, surface, accent…) and the stylesheet
- `tagio.py` - reading/writing tags for each format (no GUI)
- `widgets.py` - MacBee-style controls: sidebar rows, flat icon buttons, capsules, Yes/No switch
- `make_icon.py` - draws `icon.png` in MacBee's icon style
- `make_symbols.swift` - saves the SF Symbols (the same icons MacBee uses) into `icons/`: `swift make_symbols.swift`
- Folders ending in `.nosync` (libraries and build output) are skipped by iCloud, so they don't upload
- `test_tagio.py` - round-trip tests: `python3 test_tagio.py <folder of sample audio>`

Built on the starter project's field list and Mutagen approach.
