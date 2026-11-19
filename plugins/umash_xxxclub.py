# VERSION: 1.0
# AUTHORS: Umash
#
# XXXClub (xxxclub.to). Search pages list torrents; the magnet is on each
# torrent's page, so the 30 best-seeded rows cost one more request each.

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_xxxclub(object):
    url = "https://xxxclub.to"
    name = "XXXClub"
    supported_categories = {"all": "all"}

    row = re.compile(
        r'<a href="(/torrents/details/[^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="adde[^"]*">([^<]*)</span>\s*<span class="siz[^"]*">([^<]*)</span>\s*'
        r'<span class="see[^"]*">(\d+)</span>\s*<span class="lee[^"]*">(\d+)</span>', re.S)
    limit = 30

    @staticmethod
    def date(text):
        try:
            return int(datetime.strptime(text.strip(), "%d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return -1

    def show(self, item):
        path, name, added, size, seeds, leech = item
        page = self.url + path
        try:
            match = re.search(r'href="(magnet:[^"]+)"', retrieve_url(page, unescape_html_entities=False))
        except Exception:
            return
        if match:
            prettyPrinter({
                "link": html.unescape(match.group(1)),
                "name": html.unescape(re.sub(r"<[^>]+>", "", name)).strip(),
                "size": size.strip(),
                "seeds": int(seeds),
                "leech": int(leech),
                "engine_url": self.url,
                "desc_link": page,
                "pub_date": self.date(added),
            })

    def search(self, what, cat="all"):
        text = retrieve_url(f"{self.url}/torrents/search/all/{what}", unescape_html_entities=False)
        rows = sorted(self.row.findall(text), key=lambda row: -int(row[4]))[:self.limit]
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(self.show, rows))
