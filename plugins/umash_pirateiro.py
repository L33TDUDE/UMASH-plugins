# VERSION: 1.0
# AUTHORS: Umash, after LightDestory's pirateiro.py
#
# Pirateiro (pirateiro.io), a general index.
#
# The site writes large counts short, like "8.4k" seeds. The older plugin read
# only plain digits, so it skipped exactly the best-seeded results. This one
# reads "8.4k" as 8400 (the site gives no more precision) and fetches 3 pages
# at once (about 40 rows each).
#
# The search page has no size or date, and a torrent's own page takes up to a
# minute to load and says only "3 years ago", so size and date are left empty.
# The magnet is read from the torrent's page when you download.

import html
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_pirateiro(object):
    url = "https://pirateiro.io"
    name = "Pirateiro"
    supported_categories = {"all": "0", "anime": "2", "games": "3", "movies": "1",
                            "music": "4", "software": "6", "tv": "5"}
    pages = 3

    # Each result is shown twice (a table and a phone list); only table rows count.
    row = re.compile(
        r'<tr[^>]*>\s*<td>(?P<cat>[^<]*)</td>\s*<td\s*>\s*<a href="(?P<link>https://pirateiro\.io/torrent/(?P<id>\d+))">'
        r'\s*<h6[^>]*>(?P<name>.*?)</h6>\s*</a>.*?'
        r'btn-seed-home[^>]*>(?P<seeds>[^<]*)</span>.*?'
        r'btn-leech-home[^>]*>(?P<leech>[^<]*)</span>',
        re.S)
    magnet = re.compile(r'"(magnet:\?xt=urn:btih:[^"\s]+)"')
    page_link = re.compile(r"^https://pirateiro\.io/torrent/\d+$")
    # Checked after unescaping: Umash opens only what passes this.
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address, wait):
        request = urllib.request.Request(address, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=wait) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            return ""

    @staticmethod
    def count(raw):
        """'361' -> 361, '8.4k' -> 8400, '1.2m' -> 1200000; -1 when unreadable."""
        found = re.fullmatch(r"([\d.,]+)\s*([km]?)", (raw or "").strip().lower())
        if not found:
            return -1
        try:
            number = float(found.group(1).replace(",", ""))
        except ValueError:
            return -1
        return int(round(number * {"": 1, "k": 1_000, "m": 1_000_000}[found.group(2)]))

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        category = self.supported_categories.get(cat, "0")
        extra = "" if category == "0" else f"&category={category}"
        texts = {}

        def get(number):
            texts[number] = self.fetch(f"{self.url}/search?query={query}&page={number}{extra}", 30)

        threads = [threading.Thread(target=get, args=(number,)) for number in range(1, self.pages + 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        seen = set()
        for number in range(1, self.pages + 1):
            for match in self.row.finditer(texts.get(number, "")):
                if match.group("id") in seen:
                    continue
                seen.add(match.group("id"))
                name = " ".join(html.unescape(re.sub(r"<[^>]+>", "", match.group("name"))).split())
                prettyPrinter({
                    "link": match.group("link"),
                    "name": name,
                    "size": "-1",
                    "seeds": self.count(match.group("seeds")),
                    "leech": self.count(match.group("leech")),
                    "engine_url": self.url,
                    "desc_link": match.group("link"),
                    "pub_date": -1,
                })

    def download_torrent(self, page):
        if not self.page_link.fullmatch(page):
            raise ValueError("not a Pirateiro torrent page")
        # The site's torrent pages can take most of a minute.
        found = self.magnet.search(self.fetch(page, 55))
        if not found:
            raise ValueError("Pirateiro didn't send the torrent's page; try again")
        magnet = html.unescape(found.group(1))
        if not self.safe_magnet.fullmatch(magnet):
            raise ValueError("the magnet on this page looks wrong")
        print(magnet + " " + page)
