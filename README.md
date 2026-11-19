# UMASH-plugins

Search plugins for Umash. Each plugin is one Python file that searches one site and prints its results in the nova3 format used by qBittorrent's search plugins.

## Layout

```
plugins/    One file per plugin, named umash_<site>.py. The file name is the plugin's ID.
catalog/    The plugin list Umash reads (added in the next step).
```

Plugins are plain Python, so one copy serves every platform Umash runs on (macOS, Linux, Windows 11). If a plugin ever needs to be limited to one platform, its catalog entry will say so; the file stays the same.

## Rules for this repo

- Plugin file names are lowercase with underscores. Don't rename one: installed copies are matched by ID.
- No API keys, cookies, passwords or personal data in any file. Plugins read credentials from the user's own settings at run time.
- Plugins adapted from other authors keep their original attribution header.

This repository is in early testing and is not ready for general use.
