# UMASH-plugins

Search plugins for Umash. Each plugin is one Python file that searches one site and prints its results in the nova3 format used by qBittorrent's search plugins.

## Layout

```
plugins/                One file per plugin, named umash_<site>.py. The file name is the plugin's ID.
catalog/metadata.json   Hand-edited: each plugin's name, site, notes, list, flags and platforms.
catalog/plugins.json    The list Umash reads. Generated: don't edit it by hand.
tools/build-catalog.py  Builds plugins.json from the two above.
```

Umash carries no plugins of its own. On first launch a person chooses Official, Public or Private (each includes the ones before it) and Umash downloads those plugins from here, checking every file against the sha256 in `plugins.json`.

After you add or change a plugin, or edit `metadata.json`, run:

```
python3 -I tools/build-catalog.py
```

and commit the result. The generator stops if a plugin has no metadata (or the reverse), has no `# VERSION:` line, or has a bad field. Don't edit `plugins.json` by hand: the hashes would stop matching and Umash would refuse the files. A `"hidden"` note in `metadata.json` keeps a plugin in this repository but out of the list.

## The list (format 1)

```
{ "format": 1, "updated": "2026-11-19", "plugins": [ { ... }, ... ] }
```

Each plugin entry has:

| Field | Meaning |
|---|---|
| `id` | Lowercase letters, digits and underscores. Same as the file name without `.py`. |
| `name`, `site`, `notes` | What Umash shows people. |
| `file` | Always `plugins/<id>.py`. |
| `version` | From the plugin's `# VERSION:` line. Umash offers an update only when this is higher than the installed version. |
| `sha256` | Hash of the file. Umash compares every download against it before showing the plugin for review. |
| `list` | `official`, `public` or `private`. A person who chooses Public gets official and public; Private gets all three. |
| `flags` | `needsLogin`, `needsKey`, `adult`, `readNotes`. |
| `platforms` | `all`, or any of `macos`, `linux`, `win11`. Plugins are plain Python, so everything is `all` today. |

An unknown `format` number is refused whole, so an older app never misreads a newer list.

## Rules for this repo

- Plugin file names are lowercase with underscores. Don't rename one: installed copies are matched by ID.
- No API keys, cookies, passwords or personal data in any file. Plugins read credentials from the user's own settings at run time.
- Plugins adapted from other authors keep their original attribution header.
- Raise `# VERSION:` when a plugin changes, or Umash won't offer the update.

This repository is in early testing and is not ready for general use.
