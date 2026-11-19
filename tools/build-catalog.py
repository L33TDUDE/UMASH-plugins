#!/usr/bin/env python3
"""Writes catalog/plugins.json, the list Umash reads.

    python3 -I tools/build-catalog.py

Inputs: plugins/*.py and catalog/metadata.json (hand-edited: name, site, notes, list, flags,
platforms for each plugin id; a "hidden" note keeps a plugin in the repo but out of the list).
For each plugin it takes the version from the file's
`# VERSION:` line and the sha256 of the file's bytes. Writes nothing and exits with an
error if a plugin has no metadata, metadata has no plugin, a version line is missing, or
a field is wrong. The list's date changes only when its content does.
"""
import datetime
import hashlib
import json
import pathlib
import re
import sys

FORMAT = 1
ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = re.compile(r"^#\s*VERSION:\s*(\S+)", re.I | re.M)
LISTS = ("official", "public", "private")
FLAGS = {"needsLogin", "needsKey", "adult", "readNotes"}
PLATFORMS = {"all", "macos", "linux", "win11"}
ID = re.compile(r"[a-z0-9_]{1,64}")


def main():
    metadata = json.loads((ROOT / "catalog" / "metadata.json").read_text("utf-8"))["plugins"]
    files = {p.stem: p for p in sorted((ROOT / "plugins").glob("*.py"))}
    problems, plugins = [], []
    for plugin_id in sorted(set(files) | set(metadata)):
        if plugin_id not in files:
            problems.append(f"{plugin_id}: in metadata.json but plugins/{plugin_id}.py doesn't exist")
            continue
        if plugin_id not in metadata:
            problems.append(f"{plugin_id}: has a file but no entry in metadata.json")
            continue
        meta, data = metadata[plugin_id], files[plugin_id].read_bytes()
        hidden = bool(meta.get("hidden"))
        found = VERSION.search(data[:600].decode("utf-8", "replace"))
        if not ID.fullmatch(plugin_id):
            problems.append(f"{plugin_id}: not a valid id")
        if not found:
            problems.append(f"{plugin_id}: no '# VERSION:' line in its first lines")
        if meta.get("list") not in LISTS:
            problems.append(f"{plugin_id}: list must be one of {LISTS}")
        if not meta.get("name"):
            problems.append(f"{plugin_id}: no name")
        if not set(meta.get("flags", [])) <= FLAGS:
            problems.append(f"{plugin_id}: unknown flag in {meta.get('flags')}")
        if not meta.get("platforms") or not set(meta["platforms"]) <= PLATFORMS:
            problems.append(f"{plugin_id}: platforms must be a non-empty subset of {sorted(PLATFORMS)}")
        if hidden:
            continue
        plugins.append({
            "id": plugin_id, "name": meta.get("name", ""), "site": meta.get("site", ""), "file": f"plugins/{plugin_id}.py",
            "version": found.group(1) if found else "", "sha256": hashlib.sha256(data).hexdigest(),
            "author": meta.get("author", "Umash"), "notes": meta.get("notes", ""), "list": meta.get("list", ""),
            "flags": sorted(meta.get("flags", [])), "platforms": meta.get("platforms", []),
        })
    if problems:
        sys.exit("Not written:\n  " + "\n  ".join(problems))

    target = ROOT / "catalog" / "plugins.json"
    updated = datetime.date.today().isoformat()
    if target.is_file():
        try:
            old = json.loads(target.read_text("utf-8"))
            if old.get("format") == FORMAT and old.get("plugins") == plugins:
                updated = old.get("updated", updated)
        except ValueError:
            pass
    target.write_text(json.dumps({"format": FORMAT, "updated": updated, "plugins": plugins}, indent=2, ensure_ascii=False) + "\n", "utf-8")
    counts = {name: sum(p["list"] == name for p in plugins) for name in LISTS}
    print(f"{len(plugins)} plugins listed ({counts['official']} official, {counts['public']} public, {counts['private']} private), dated {updated}")


if __name__ == "__main__":
    main()
