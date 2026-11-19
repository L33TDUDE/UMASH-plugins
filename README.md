# UMASH-plugins

Search plugins for Umash. Each plugin is one Python file that searches one site and prints its results in the nova3 format used by qBittorrent's search plugins.

## Layout

```
plugins/                One file per plugin, named umash_<site>.py. The file name is the plugin's ID.
catalog/plugins.json    The list Umash reads: every plugin with its version, a sha256 of its file, and notes.
```

`catalog/plugins.json` is generated from the app by `tools/publish-plugins.sh`. Don't edit it by hand: the hashes would stop matching and Umash would refuse the files.

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
| `list` | `official`, `public` or `private`: where Umash lists the plugin. |
| `flags` | `needsLogin`, `needsKey`, `adult`, `readNotes`. |
| `platforms` | `all`, or any of `macos`, `linux`, `win11`. Plugins are plain Python, so everything is `all` today. |

An unknown `format` number is refused whole, so an older app never misreads a newer list.

## Rules for this repo

- Plugin file names are lowercase with underscores. Don't rename one: installed copies are matched by ID.
- No API keys, cookies, passwords or personal data in any file. Plugins read credentials from the user's own settings at run time.
- Plugins adapted from other authors keep their original attribution header.
- Raise `# VERSION:` when a plugin changes, or Umash won't offer the update.

This repository is in early testing and is not ready for general use.
