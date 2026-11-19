# VERSION: 3.0
# AUTHORS: Umash
#
# The RarBg (therarbg.com): a general index of movies, TV, games, music, anime,
# software and books, best-seeded first. Search pages list each torrent's name,
# category, date added, size, seeds and leechers, 50 to a page; the magnet lives
# on the torrent's own page, so it is read only when you download one. Up to 3
# pages (150 results), one after another; Umash's "load more" asks for the next.
# Categories are the site's own sections; "all" searches every one.

import calendar
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_therarbg(object):
    url = "https://therarbg.com"
    name = "The RarBg"
    supported_categories = {"all": "", "anime": "Anime", "books": "Books", "games": "Games",
                            "movies": "Movies", "music": "Music", "software": "Apps", "tv": "TV"}
    pages = 3
    page_size = 50
    timeout = 30

    row = re.compile(r'<tr class="list-entry">(.*?)</tr>', re.S)
    title = re.compile(r'<td class="n">\s*<a href="(/post-detail/[^"]+)"[^>]*>(.*?)</a>', re.S)
    cell = r'<td class="{0}">(.*?)</td>'
    stamp = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[^"]+)"')
    detail_page = re.compile(r"https://therarbg\.com/post-detail/[A-Za-z0-9]+/[A-Za-z0-9._~%-]*/?")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", "replace")

    def address(self, query, section, page):
        # The site filters inside the path: keywords:<words>[:category:<section>].
        path = "keywords:" + urllib.parse.quote(query.replace(":", " "), safe="")
        if section:
            path += ":category:" + section
        return f"{self.url}/get-posts/{path}/" + (f"?page={page}" if page > 1 else "")

    @staticmethod
    def text(markup):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", "", markup)).split())

    def date(self, text):
        found = self.stamp.search(text)
        if not found:
            return -1
        year, month, day = map(int, found.groups())
        return calendar.timegm((year, month, day, 0, 0, 0))

    @staticmethod
    def number(text):
        text = text.strip()
        return int(text) if text.isdigit() and int(text) < 2**31 else -1

    def read(self, page_text):
        count = 0
        for found in self.row.finditer(page_text):
            row = found.group(1)
            title = self.title.search(row)
            cells = {key: re.search(self.cell.format(key), row, re.S) for key in ("d", "s", "se", "le")}
            if not title or not all(cells.values()):
                continue
            count += 1
            page = self.url + html.unescape(title.group(1))
            if not self.detail_page.fullmatch(page):
                continue
            prettyPrinter({
                "link": page,
                "name": self.text(title.group(2)),
                "size": self.text(cells["s"].group(1)) or -1,
                "seeds": self.number(self.text(cells["se"].group(1))),
                "leech": self.number(self.text(cells["le"].group(1))),
                "engine_url": self.url,
                "desc_link": page,
                "pub_date": self.date(self.text(cells["d"].group(1))),
            })
        return count

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
        query = urllib.parse.unquote(what).strip()
        section = self.supported_categories.get(cat, "")
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                text = self.fetch(self.address(query, section, page))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                raise RuntimeError("The RarBg didn't answer: " + str(error))
            full = self.read(text) >= self.page_size
            self.more(page + 1 if full else 0)
            if not full:
                return
            time.sleep(0.6)

    def download_torrent(self, info):
        """Reads the magnet from the torrent's own page, on this site only."""
        if not self.detail_page.fullmatch(info):
            raise ValueError("that isn't a torrent page on The RarBg")
        found = self.magnet.search(self.fetch(info))
        magnet = html.unescape(found.group(1)) if found else ""
        if not self.safe_magnet.fullmatch(magnet):
            raise RuntimeError("The RarBg's page has no magnet, or one that looks wrong")
        print(magnet + " " + info)
