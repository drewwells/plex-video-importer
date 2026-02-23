# Dance Plex Organization Notes (Reusable Decisions)

This file records the conventions and decisions used to organize `/mnt/raid/dance` content into Plex-friendly TV Shows, including how we name folders, seasons, episodes, and how we force Plex to display episode titles.

## Core Goal

- Make "categories" show up as Plex Shows.
- Make files under each category show up as Episodes.
- Ensure Plex shows a real episode title (not "Episode 1"), using filenames as the source of truth and locking titles via Plex API when needed.

## Plex Library Assumptions

- Plex library type: `TV Shows`
- Library name used in this environment: `Dance`
- Plex section id observed for `Dance`: `13`
- Plex is running on this host; API calls were most reliable against `http://127.0.0.1:32400`.

## Folder Structure Conventions

### 1) Non-site / Personal Dance Videos

Library root:

- `/mnt/raid/dance/Shows`

Shows:

- Each category becomes a show directory under `/mnt/raid/dance/Shows`.
- If a category has both direct videos and subcategory folders with videos:
  - `<Category> - Misc` is used for the videos directly under the category root.
  - `<Category> - <Subcategory>` is used for each subcategory.

Seasons:

- Always `Season 01` (single season per category-show).

Episodes:

- Stored under `.../<Show>/Season 01/`.

Episode filename format:

- `<Show> - S01E## - <Title>.<ext>`

Episode numbering rules:

- If the filename already contains `SxxEyy`, use `yy`.
- Else if filename has a leading number like `01 - ...`, use that.
- Else assign sequential numbers in sorted-path order.

Episode title rules:

- Derived from filename.
- Strip leading show prefix if present.
- Strip `SxxEyy` prefix if present.
- Strip trailing ids like `[12345]` and `(cid 12345)` if present.

### 2) Uscreen Site As a Single Show (GarySusan)

Library root:

- `/mnt/raid/dance/garysusan`

Show folder:

- `/mnt/raid/dance/garysusan/GarySusan`

Season folder format (on disk):

- `Season NN - <Category> - <Collection>`

Episode file format (on disk):

- `GarySusan - SNNEXX - <Title>.mp4`

Important decision:

- Episode titles should not redundantly include the collection/season name.
- We removed collection prefixes like `Basics 1 -` / `Basics 1:` / `Basics 1:` from the episode filenames so the season name can carry that context.

Variants:

- Any `*.plex-appletv.mp4` variants are moved out of the indexed tree to avoid duplicate episodes:
  - `/mnt/raid/dance/garysusan/_variants/...`
  - If you decide you want the Apple TV transcodes to become the primary files (so Plex will stream them without transcoding),
    use `scripts/promote_plex_appletv_variants.py` to overwrite the originals with the variants.

### 3) JT Swing (Single Show: JTSwing)

Library root (folder added to Plex):

- `/mnt/raid/dance/jtswing.com`

Show folder:

- `/mnt/raid/dance/jtswing.com/JTSwing`

Seasons:

- Each JT category becomes a season directory:
  - `Season NN - <Category>`
  - Example: `Season 01 - Beginner`

Episodes:

- Stored under each season directory.

Episode filename format:

- `JTSwing - SNNEXX - <Title>.mp4`

Episode title rules:

- Derived from filename.
- Specifically, it is the final ` <Title>` part after ` - SNNEXX - `.
  - Example: `JTSwing - S03E36 - Fly By.mp4` -> Plex title `Fly By`

## Plex Metadata Strategy (Titles and Season Names)

Plex does not reliably infer episode titles from filenames for personal media TV content. The stable approach is:

- Set the Plex episode title from the filename and lock it.
- Set the Plex season title from the season folder name and lock it.

### Plex Token

Plex uses an auth token (`X-Plex-Token`), not an API key.

Ways to obtain it:

- From Plex Web: open DevTools -> Network while browsing/playing and look for `X-Plex-Token`.
- From Plex server `Preferences.xml` as `PlexOnlineToken="..."` (path depends on install).

## Scripts Added (Runbook)

### Rename GarySusan Episodes (Remove Season Prefix From Title)

- `/mnt/raid/dance/garysusan_rename_episode_files.py`

Dry run:

```sh
python3 /mnt/raid/dance/garysusan_rename_episode_files.py \
  --root /mnt/raid/dance/garysusan/GarySusan
```

Apply:

```sh
python3 /mnt/raid/dance/garysusan_rename_episode_files.py \
  --root /mnt/raid/dance/garysusan/GarySusan \
  --apply
```

### Set Plex Episode Titles From Filenames (And Lock)

- `/mnt/raid/dance/plex_title_from_filename.py`

Example (most reliable on this host):

```sh
PLEX_TOKEN='...token...' \
python3 /mnt/raid/dance/plex_title_from_filename.py \
  --server 'http://127.0.0.1:32400' \
  --library 'Dance' \
  --section-id 13 \
  --files-root '/mnt/raid/dance/Shows' \
  --refresh \
  --apply
```

Run again for GarySusan:

```sh
PLEX_TOKEN='...token...' \
python3 /mnt/raid/dance/plex_title_from_filename.py \
  --server 'http://127.0.0.1:32400' \
  --library 'Dance' \
  --section-id 13 \
  --files-root '/mnt/raid/dance/garysusan' \
  --refresh \
  --apply
```

### Set Plex Season Titles For GarySusan From On-Disk Season Folder Names

- `/mnt/raid/dance/plex_set_garysusan_season_titles.py`

Dry run:

```sh
PLEX_TOKEN='...token...' \
python3 /mnt/raid/dance/plex_set_garysusan_season_titles.py \
  --server 'http://127.0.0.1:32400' \
  --section-id 13 \
  --show-title GarySusan \
  --seasons-root /mnt/raid/dance/garysusan/GarySusan
```

Apply:

```sh
PLEX_TOKEN='...token...' \
python3 /mnt/raid/dance/plex_set_garysusan_season_titles.py \
  --server 'http://127.0.0.1:32400' \
  --section-id 13 \
  --show-title GarySusan \
  --seasons-root /mnt/raid/dance/garysusan/GarySusan \
  --apply
```

Note:

- The same script also works for shows whose season folders are just `Season NN - <Season Title>` (no collection segment), e.g. JTSwing.

### Promote Apple TV Variants (Overwrite Originals)

- `scripts/promote_plex_appletv_variants.py`

Dry run (prints plan):

```sh
python3 scripts/promote_plex_appletv_variants.py --root /mnt/raid/dance/garysusan
```

Apply and discard originals (replaces each canonical `.mp4` with its matching `.plex-appletv.mp4`):

```sh
python3 scripts/promote_plex_appletv_variants.py \
  --root /mnt/raid/dance/garysusan \
  --delete-originals \
  --apply
```

## Operational Notes

- Plex API calls from inside the sandbox were unreliable/blocked. Running against `http://127.0.0.1:32400` outside the sandbox worked reliably.
- After large filesystem moves, a Plex refresh (`/library/sections/<id>/refresh`) helps Plex re-index before title updates.
