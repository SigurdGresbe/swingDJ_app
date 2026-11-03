# swingDJ_app

A separate, modern PySide6 and Qt Quick desktop application for viewing, filtering,
coloring, merging, and exporting music lists, plus practical Spotify workflows.

The app reads existing files from `C:\VS_code\SpareTime`, but it does not modify
that folder. New outputs default to `%LOCALAPPDATA%\SpareTimeStudio\generated`,
and the controller blocks output paths inside the original SpareTime folder.

## Credentials and local data

Enter your own Spotify and Last.fm credentials in the app settings. Settings are
stored locally under `%LOCALAPPDATA%\SpareTimeStudio`, outside this repository.
Spotify can also read `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, and
`SPOTIPY_REDIRECT_URI` from your environment. Existing local SpareTime credentials
may be imported automatically when that project is present.

Token caches, `.env` files, local settings, error reports, and generated files are
excluded by `.gitignore`. Never commit API secrets or OAuth tokens.

## Launch

Double-click `run_sparetime_qt.bat`. It starts the app with `pythonw.exe` from
the selected Python installation, then closes the launcher console. Dependency
installation errors remain visible. No PowerShell window is needed while the app
runs. For visible terminal output while troubleshooting, run:

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Main features

- Virtualized, editable table view for XLSX, XLS, CSV, TSV, JSON, JSONL, and NDJSON.
- Clickable column sorting, contains filtering, hidden columns, and row density.
- Style and Theme tag checklists can hide matching songs, including multi-tag rows.
- Color-coded dance style and difficulty columns with a live legend.
- Export of the current filtered and sorted view in multiple formats.
- Safe merge preview, merge output, and folder-to-master building.
- Spotify OAuth, capability diagnostics, search, playlists, devices, playback,
  volume, playlist drill-down, track queueing, and playlist export.
- Direct Queue actions in LargeList prefer an explicit Spotify URI, then the
  row's matching Spotify playlist and configured playlists, then catalog search.
- **Update from Spotify** in the library (or **Update tagged list** in Spotify)
  imports every song from `Stil:`, `Event:`, and `Tema:` playlists,
  deduplicates by Spotify URI, aggregates Style, Event, and Theme tags, and adds half-tempo
  `KOD` values from curated SpareTime data or the ReccoBeats audio-features API.
- Paper and Night themes, four accent palettes, and a settings drawer.

Spotify playback controls depend on Spotify's current Web API restrictions and
the capabilities of the signed-in account. Use **Capability check** in the app to
see what the current app registration and account can access.

## Build a Windows executable

Run `build_windows.bat`. Qt's deployment tool creates a distributable build while
keeping this source folder independent from the two existing SpareTime projects.
The build excludes `tests`, and runtime data stays in `%LOCALAPPDATA%`, so exports
and API credentials are not packaged into the executable.

To refresh the full tagged list, connect your account on the Spotify page, then
click **Update from Spotify** in the library. Playlist prefixes are case-insensitive.
The update rereads all matching playlists and all their tracks, saves
`Spotify_Style_Theme_Tags.xlsx` in the generated folder, and opens it in the library.
It rebuilds the generated list, replacing manual edits in that file; export a copy
first if you want to keep those edits.

## History, tempo plan, and counted corrections

Open **History / Queue** in the library. Use **Queue** next to a song to add it
in order, then use the up/down controls to arrange it. The plot switches between
BPM and KOD; unknown tempos leave gaps. KOD is half BPM in this app.
Enter your counted value beside a song and click **Correct**. You can also edit
BPM or KOD cells in the library. Corrections persist locally, synchronize both
values, and override imported tempos after refreshes.

Choose **Played history**, then **Refresh history from Spotify** to import the
latest 50 played tracks with UTC timestamps. Repeated plays remain separate;
refreshing does not duplicate the same track/timestamp. History accumulates locally
across refreshes, but plays outside Spotify's returned window may be missed.
Enter a name and click **Create Spotify playlist** to export the displayed history
or plan to a new private playlist, preserving order and repeats. Every song must
have a Spotify track URI. Playlist creation failures report any partial playlist.

Local lists, saved history, plans, corrections, and file exports work offline.
Spotify playback control, Spotify imports/history refresh, playlist creation,
Last.fm discovery, and uncached online tempo lookup need internet access.
The app does not play local audio or Spotify downloads itself.

## Playback bar and shared queue

The bottom playback bar remains visible on every tab. Play/Pause is one toggle
and resumes playback without restarting the displayed track. Playback refreshes
from one Spotify state response every five seconds when an account cache exists;
failed refreshes clear the song display and report playback as unavailable.

**History / Queue** opens history and the shared queue plot. Use the
library **Queue** action to save a song in this list and queue it in Spotify
when connected. Failed queue requests leave the song as a local plan entry.
**Send local songs to Spotify queue** appends entries not already marked queued.
**Copy Spotify queue locally** replaces the local list with Spotify's
upcoming songs (excluding the currently playing track). Local reordering/removal
does not reorder or remove songs in Spotify's existing queue. Export the arranged
plan as a named playlist to preserve its chosen order in Spotify.

## Robustness checks

Run `python tests/verify_robustness.py` for isolated failure-path checks, alongside
`tests/verify_backend.py`, `tests/verify_listening.py`, `tests/verify_errors.py`,
and `tests/smoke_qml.py`.

Last.fm and Spotify authentication requests have finite network timeouts. Spotify
requests do not automatically retry, avoiding duplicate queue entries or playlists
when the server accepted a write but its response was lost. Retry failed actions
manually after checking Spotify. Playback polling backs off after errors, up to
60 seconds, and returns to five seconds after recovery.

Table exports and settings commit through a temporary file so a failed write
preserves the previous file. Invalid listening JSON is backed up as
`listening.corrupt.json` (with a unique name for additional backups) before
starting with an empty history and plan. Worker completion errors are reported
through the app's diagnostics.

## Using the app during Spotify updates

The tagged Spotify import has its own background worker. Playback, search,
queue actions, filtering, opening lists, and exporting remain available while it
runs. Other foreground tasks remain serialized to protect playback and local
state. A second import and exports targeting its workbook are blocked until it
finishes. Exports capture the selected view before starting their worker.
If the current table changes during import, the result is saved without replacing
the current table; open `Spotify_Style_Theme_Tags.xlsx` to view it.

The progress bar reports counts within the current stage (playlists, tempo
batches, or song searches). It resets when the stage changes; it is not an
estimated overall percentage or ETA. Stages with an unknown total show activity.

Select **Missing tempo** in the library to show songs with no positive, finite
BPM or KOD value. The count covers the loaded list; other filters still apply.
Use **Find tempo** beside a song, choose **Look up BPM online**, then enter your
checked/counted BPM or KOD and click **Save**. The correction persists locally,
applies to future Spotify refreshes, and removes the song from this view.
The online lookup opens a browser search; it does not automatically assign an
unverified tempo. This filter works offline.

Additional checks: `python tests/verify_concurrency.py` and
`python tests/verify_missing_tempo.py`.

## Live Spotify queue

Open **History / Queue**, then select **Live Spotify queue**. This is the default
queue view. It reads Spotify immediately and refreshes every five seconds while
visible. **Refresh now** requests a new snapshot without overlapping an in-flight
request. The currently playing song appears separately above upcoming songs;
upcoming songs retain Spotify order and duplicates.

Connection errors retain the last received queue and mark it stale. Automatic
refresh backs off up to 60 seconds, returning to five seconds after recovery.
Closing the dialog or choosing history/local queue stops queue polling. Polling
runs independently from Spotify tagged imports and does not change playback.

**Local queue** keeps the saved editable arrangement. Live refresh does not
change it. **Copy Spotify queue locally** explicitly replaces it when requested.
Local reordering/removal cannot change Spotify's queue through the public API.
Existing saved queue data remains compatible.

Run `python tests/verify_live_queue.py` for isolated queue-refresh checks.

The queue now opens in a non-modal drawer sliding in from the right. Main-page
controls remain available while it is open. Close it with **Close**, Escape, or a
swipe toward the right edge. Select **Tempo graph** to show the graph when needed.
Each song has **Play** and **Correct tempo** actions. **Play** starts the selected
Spotify URI; it does not remove or reorder entries in Spotify's existing queue.
The live view refreshes after playback changes.

## Editing lists and saved field overrides

**Edit lists** contains bulk tempo editing alongside Merge and Build. Open a list,
filter it in Library if needed, then choose BPM or KOD and a multiplier (default
2). Leave row numbers blank for the filtered rows, or enter ranges such as
`1-10, 15`. **Only below 60** is enabled by default. Preview shows all affected
rows, including repeated copies of matching songs. Apply saves the corrections;
**Undo last bulk edit** restores the previous tempos unless they have since been
edited again. Export creates a new edited list file.

Tempo input accepts multiplication such as `30*2` and `30.5*2`; the correction
dialog shows the numeric result before saving. Input is parsed as numbers and
multiplication, never executed as code.

Edited cells have an accent-colored dot. Text edits and tempo corrections persist
locally. Spotify track URIs link saved edits across imports, even if track order
changes. Spotify URI cells are protected because they identify the song. Local
rows without Spotify URIs are linked to their source file and row number.

Click an edited cell's dot to review its saved value and latest imported value.
Restoring requires checking **I want to discard this saved correction**, then
clicking **Restore imported value**. Restoring BPM or KOD clears both linked tempo
corrections. Future tagged Spotify imports update original values while retaining
saved overrides. For tempo, the original is the import pipeline's value, which
can come from local lists or a cache; historical raw API BPM was not retained.

The Night theme now applies to standard input controls, dialogs, the queue drawer,
and the tempo graph. Queue buttons have visible borders and keyboard-focus outlines.
Run `python tests/verify_editing.py` for arithmetic, bulk editing, reset, and
persistence checks.

Future tagged imports include **API BPM** and **Tempo source** columns for auditing
new online tempo results. Cached values from earlier versions cannot recover their
original API BPM, and are identified as such. No low values are automatically doubled.

## Style and Theme dropdowns and playlist additions

Editing Style or Theme opens a tag editor restricted to the predefined tags
already present in the loaded list and its saved source values. Type a prefix
and press **Tab** to complete the first matching suggestion, or select from the
dropdown. Multiple tags use semicolons. Tags normalize to their defined spelling,
and duplicates are removed. Blank input clears the field. Edits remain local
until you explicitly send playlist additions to Spotify.

In **Edit lists**, use **Preview playlist additions** under **Add edited tags to
Spotify lists**. It reviews saved tag additions on Spotify songs and matches
Style tags to `Stil:` playlists and Theme tags to `Tema:` playlists. After reviewing
the destinations, click **Add matched songs**. Matching uses exact tag names,
ignoring case and surrounding spaces. The app never guesses between duplicate
playlist names or creates missing playlists. Issues appear in the preview.

Only owned or collaborative playlists are eligible. Existing membership is checked
in the preview and again before writing, so already-present songs are skipped.
Partial failures report confirmed additions; preview again before retrying.
Removing a local tag does not remove a song from Spotify. Original playlists are
not renamed or cleared. Tag editing while a foreground task runs and playlist
updates during the tagged import are blocked to avoid conflicting requests.

Run `python tests/verify_tag_editing.py` and
`python tests/verify_tag_playlist_sync.py` for validation and mocked playlist-write
checks. These checks do not change live Spotify playlists.
