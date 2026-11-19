# VERSION: 1.0
# AUTHORS: Umash
#
# Zamunda.LIFE (zamunda.life), which replaced zamunda.rip: a public search of magnets
# from the Bulgarian trackers Zamunda, ArenaBG and Zelka. It needs no account. It gives
# no seed counts or dates, and shows 20 results at a time.

import json
import re
import sys
import os
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_zamunda(object):
    url = "https://zamunda.life"
    name = "Zamunda.LIFE"
    supported_categories = {"all": ""}

    pages = 10
    per_page = 20
    timeout = 20
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[0-9A-Fa-f]{40}[^\s\"'<>]*")
    size = re.compile(r"([\d.,]+)\s*([KMGT]?B)", re.I)

    def fetch(self, offset, what):
        query = urllib.parse.urlencode({"q": urllib.parse.unquote(what), "bg_audio": "false", "bg_movies": "false",
                                        "bg_arena": "false", "zelka": "false", "offset": offset})
        request = urllib.request.Request(f"{self.url}/api/torrents?{query}", headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Zamunda.LIFE answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach Zamunda.LIFE: {error.reason}") from None

    def read_rows(self, body):
        try:
            rows = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError("Zamunda.LIFE sent something other than search results") from None
        if not isinstance(rows, list):
            raise RuntimeError("Zamunda.LIFE sent something other than search results")
        return rows

    def show(self, row):
        magnet = row.get("link") or ""
        if not self.safe_magnet.fullmatch(magnet):  # The site marks lost torrents with no hash.
            return
        size = self.size.search(str(row.get("size") or ""))
        prettyPrinter({
            "link": magnet,
            "name": " ".join(str(row.get("title") or "N/A").split()),
            "size": f"{size.group(1).replace(',', '.')} {size.group(2).upper()}" if size else "-1",
            "seeds": -1,
            "leech": -1,
            "engine_url": self.url,
            "desc_link": self.url,
            "pub_date": -1,
        })

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    def search(self, what, cat="all"):
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                rows = self.read_rows(self.fetch((page - 1) * self.per_page, what))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found.
                raise
            for row in rows:
                self.show(row)
            full = len(rows) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        if not self.safe_magnet.fullmatch(info):
            raise RuntimeError("That isn't a magnet link")
        print(info + " " + info)
