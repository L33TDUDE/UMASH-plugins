# VERSION: 1.0
# AUTHORS: Umash
#
# Linux Tracker (linuxtracker.org): Linux and BSD images. The site was rebuilt;
# this reads its new /torrents/ pages. One page of results is 25 or so; three
# pages are read. Each row's address is the torrent's info hash, so the magnet
# is built without another request.

import html
import re
import urllib.parse
from datetime import datetime, timezone

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_linuxtracker(object):
    url = "https://linuxtracker.org"
    name = "Linux Tracker"
    supported_categories = {"all": "0", "software": "0"}

    row = re.compile(
        r'class="torrent-name" href="/torrents/([0-9a-f]{40})/">(.*?)</a>.*?'
        r'class="muted-cell">([^<]*)</td>\s*<td class="numeric muted-cell">([^<]*)</td>\s*'
        r'<td class="numeric seeds stat-stack">\s*<strong>(\d+)</strong>.*?'
        r'<td class="numeric leeches stat-stack">\s*<strong>(\d+)</strong>', re.S)
    pages = 3

    @staticmethod
    def date(text):
        try:
            return int(datetime.strptime(text.strip(), "%b %d, %Y").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return -1

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        for page in range(1, self.pages + 1):
            text = retrieve_url(f"{self.url}/torrents/?q={query}&page={page}", unescape_html_entities=False)
            rows = self.row.findall(text)
            for infohash, name, added, size, seeds, leech in rows:
                name = html.unescape(name)
                prettyPrinter({
                    "link": f"magnet:?xt=urn:btih:{infohash}&dn={urllib.parse.quote(name, safe='')}"
                            "&tr=" + urllib.parse.quote("http://linuxtracker.org:2710/announce", safe=""),
                    "name": name,
                    "size": size.strip(),
                    "seeds": int(seeds),
                    "leech": int(leech),
                    "engine_url": self.url,
                    "desc_link": f"{self.url}/torrents/{infohash}/",
                    "pub_date": self.date(added),
                })
            if ">Next<" not in text:
                break
