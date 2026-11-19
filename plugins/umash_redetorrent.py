# VERSION: 1.0
# AUTHORS: Umash
#
# Rede Torrents (redestorrents.com, formerly redetorrent.com): Brazilian movies
# and series. Search pages list titles; each title's page holds one magnet per
# quality, so every title costs one more request.

import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_redetorrent(object):
    url = "https://redestorrents.com"
    name = "Rede Torrents"
    supported_categories = {"all": "0"}

    card = re.compile(r'<a href="(https://redestorrents\.com/[^"]+)"\s+[^>]*?title="([^"]*)"', re.S)
    magnet = re.compile(r'<div class="download-name">(.*?)</div>\s*<a href="(magnet:[^"]+)"', re.S)

    def details(self, page, title):
        try:
            text = retrieve_url(page)
        except Exception:
            return
        for label, link in self.magnet.findall(text):
            label = html.unescape(re.sub(r"<[^>]+>", "", label)).replace("DOWNLOAD TORRENT", "").strip()
            prettyPrinter({
                "link": html.unescape(link),
                "name": f"{title} {label}".strip(),
                "size": "-1",
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": page,
            })

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        text = retrieve_url(f"{self.url}/index.php?busca={query}")
        start = text.find('class="custom-card"')
        titles = {}
        for page, title in self.card.findall(text[start:] if start >= 0 else ""):
            if "torrent" in page:
                title = html.unescape(title).replace("Torrent", "").replace("Download", "")
                titles.setdefault(page, " ".join(title.split()))
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda item: self.details(*item), titles.items()))
