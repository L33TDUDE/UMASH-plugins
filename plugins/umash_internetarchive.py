# VERSION: 1.0
# AUTHORS: Umash
#
# Internet Archive (archive.org): films, TV, music, books, software, games and
# pictures that are free to download and share: public-domain and out-of-copyright
# works, open-source software, live-music recordings, and much that uploaders
# have placed there. Every item has an official .torrent file whose web
# seeds are archive.org's own servers, so downloads work with no peers.
#
# One request to the Archive's search API, up to 100 items, most-downloaded
# first; Umash's "load more" asks for the next 100. Every word you type has to appear in an item's title, creator or
# subject. Results show the item's total size and the date it was added. The
# Archive publishes no seed counts. Categories use the Archive's own media
# types and well-known collections:
#   movies = videos, tv = the Television, Classic TV and TV Archive collections,
#   anime = the Anime collection, music = audio and live-music recordings,
#   books = texts, games = DOS, Windows 3, console and arcade game collections,
#   software = software, pictures = images.

import calendar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers, download_file
from novaprinter import prettyPrinter


class umash_internetarchive(object):
    url = "https://archive.org"
    name = "Internet Archive"
    supported_categories = {
        "all": "",
        "movies": "mediatype:movies",
        "tv": "collection:(television OR classic_tv OR tvarchive)",
        "anime": "collection:anime",
        "music": "mediatype:(audio OR etree)",
        "books": "mediatype:texts",
        "games": "mediatype:software AND collection:(softwarelibrary_msdos_games OR softwarelibrary_win3_games OR consolelivingroom OR internetarcade)",
        "software": "mediatype:software",
        "pictures": "mediatype:image",
    }
    api = "https://archive.org/advancedsearch.php"
    limit = 100
    timeout = 40
    identifier = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}")
    torrent_link = re.compile(r"https://archive\.org/download/([A-Za-z0-9][A-Za-z0-9._-]{0,200})/\1_archive\.torrent")
    word = re.compile(r"[^\W_]+(?:['.][^\W_]+)*", re.U)

    def fetch(self, params):
        headers = dict(_headers)
        headers["Accept"] = "application/json"
        request = urllib.request.Request(self.api + "?" + urllib.parse.urlencode(params), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Internet Archive answered HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as error:
            raise RuntimeError(f"Internet Archive didn't answer: {error}")

    @staticmethod
    def date(text):
        try:
            return calendar.timegm(time.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            return -1

    def query(self, words, cat):
        # Each word must be in the title, creator or subject. Only items that have the
        # Archive's torrent file (all but a few) are kept.
        parts = ['format:"Archive BitTorrent"']
        for word in words:
            parts.append(f"(title:({word}) OR creator:({word}) OR subject:({word}))")
        extra = self.supported_categories.get(cat, "")
        if extra:
            parts.append("(" + extra + ")")
        return " AND ".join(parts)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def search(self, what, cat="all"):
        words = self.word.findall(urllib.parse.unquote(what))[:8]
        if not words:
            return
        first = self.setting("UMASH_START_PAGE", 1)
        for number in range(first, first + self.setting("UMASH_MAX_PAGES", 1)):
            params = [
                ("q", self.query(words, cat)), ("rows", self.limit), ("page", number), ("output", "json"),
                ("sort[]", "downloads desc"),
            ] + [("fl[]", field) for field in ("identifier", "title", "item_size", "publicdate")]
            try:
                docs = (self.fetch(params).get("response") or {}).get("docs") or []
            except RuntimeError:
                if number > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for doc in docs:
                identifier = str(doc.get("identifier", ""))
                title = doc.get("title")
                if isinstance(title, list):
                    title = title[0] if title else ""
                title = " ".join(str(title or identifier).split())
                if len(title) > 200:
                    title = title[:199] + "…"
                if not self.identifier.fullmatch(identifier):
                    continue
                size = doc.get("item_size")
                prettyPrinter({
                    "link": f"{self.url}/download/{identifier}/{identifier}_archive.torrent",
                    "name": title,
                    "size": size if isinstance(size, int) and size >= 0 else -1,
                    "seeds": -1,
                    "leech": -1,
                    "engine_url": self.url,
                    "desc_link": f"{self.url}/details/{identifier}",
                    "pub_date": self.date(doc.get("publicdate")),
                })
            has_more = len(docs) >= self.limit
            self.more(number + 1 if has_more else 0)
            if not has_more:
                return

    def download_torrent(self, link):
        if not self.torrent_link.fullmatch(link):
            raise ValueError("not an Internet Archive torrent link")
        print(download_file(link))
