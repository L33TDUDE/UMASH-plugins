# VERSION: 2.0
# AUTHORS: Umash
#
# Elitetorrent (elitetorrent.com): a Spanish-language index of movies and TV
# episodes, mostly in Castilian Spanish, with some Latin American and subtitled
# English releases. Search with Spanish titles or the original name.
#
# The site's search pages list each release's name, quality, language and (for
# movies) size, 30 to a page, but not seeds or leechers (shown as unknown). Up to
# 3 pages (90 results), one after another; Umash's "load more" asks for the next.
# The magnet is on each release's own page, so it is read only when you download
# one. The site searches movies and series together; the movies and tv
# categories keep one or the other.

import base64
import binascii
import codecs
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


class umash_elitetorrent(object):
    url = "https://www.elitetorrent.com"
    name = "Elitetorrent"
    supported_categories = {"all": "", "movies": "peliculas", "tv": "series"}
    pages = 3
    page_size = 30
    timeout = 30

    item = re.compile(r"<li>\s*<div class=imagen>(.*?)</li>", re.S)
    link = re.compile(r'<a class=nombre href="(https://www\.elitetorrent\.com/(?:peliculas|series)/[^"]+)"[^>]*>(.*?)</a>', re.S)
    quality = re.compile(r'<span class="marca estreno" style="[^"]*"><i>([^<]*)</i></span>')
    size = re.compile(r"<span class=dig1>([^<]*)</span>")
    language = re.compile(r"id=idiomacio>.*?/images/([a-z]+)\.png", re.S)
    languages = {"espanol": "ES", "latino": "LAT", "vose": "VOSE", "ingles": "EN", "vo": "VO"}
    detail_page = re.compile(r"https://www\.elitetorrent\.com/(?:peliculas|series)/[A-Za-z0-9_%-]+/?")
    button = re.compile(r'<a href="https://acortame-esto\.com/s\.php\?i=([A-Za-z0-9+/=_-]+)[^"]*"[^>]*'
                        r'class="enlace_torrent[^"]*"[^>]*>([^<]*)</a>')
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", "replace")

    def address(self, query, page):
        return f"{self.url}/" + (f"page/{page}/" if page > 1 else "") + "?s=" + urllib.parse.quote_plus(query)

    @staticmethod
    def text(markup):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", "", markup)).split())

    def title_of(self, item):
        title = self.link.search(item)
        name = self.text(title.group(2)) if title else ""
        tags = []
        found = self.quality.search(item)
        if found and re.search(r"[A-Za-z0-9]", found.group(1)):
            tags.append(self.text(found.group(1)))
        icon = self.language.search(item)
        if icon and icon.group(1) in self.languages:
            tags.append(self.languages[icon.group(1)])
        return title, (f"{name} [{', '.join(tags)}]" if tags else name)

    def read(self, page_text, section):
        for found in self.item.finditer(page_text):
            item = found.group(1)
            title, name = self.title_of(item)
            if not title:
                continue
            page = html.unescape(title.group(1))
            if (section and "/" + section + "/" not in page) or not self.detail_page.fullmatch(page):
                continue
            size = self.size.search(item)
            prettyPrinter({
                "link": page,
                "name": name,
                "size": self.text(size.group(1)).replace("GBs", "GB").replace("MBs", "MB") if size and size.group(1).strip() else -1,
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": page,
                "pub_date": -1,
            })

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
                text = self.fetch(self.address(query, page))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                raise RuntimeError("Elitetorrent didn't answer: " + str(error))
            self.read(text, section)
            full = len(self.item.findall(text)) >= self.page_size
            self.more(page + 1 if full else 0)
            if not full:
                return
            time.sleep(0.6)

    @staticmethod
    def unwrap(value):
        """The site keeps each address as text wrapped in several layers of base64,
        then ROT13. Peels the layers; anything that isn't text stops the loop."""
        data = value.encode()
        for _ in range(10):
            try:
                step = base64.b64decode(data + b"=" * (-len(data) % 4), validate=True)
            except (binascii.Error, ValueError):
                break
            if not step.isascii():
                break
            data = step
        return codecs.decode(data.decode("ascii", "replace"), "rot13")

    def download_torrent(self, info):
        """Reads the magnet from the release's own page, on this site only."""
        if not self.detail_page.fullmatch(info):
            raise ValueError("that isn't a release page on Elitetorrent")
        for value, label in self.button.findall(self.fetch(info)):
            if "magnet" not in label.lower():
                continue
            magnet = self.unwrap(value)
            if self.safe_magnet.fullmatch(magnet):
                print(magnet + " " + info)
                return
        raise RuntimeError("Elitetorrent's page has no magnet, or one that looks wrong")
