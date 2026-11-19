# VERSION: 1.0
# AUTHORS: Umash
#
# Sukebei (sukebei.nyaa.si), Nyaa's adult sister site.
#
# Best-seeded first, up to 4 pages of 75 with the date each was added. The
# older plugin read up to 14 pages and passed on no date; this one stops at 4
# and waits half a second between pages, as the site asks for slow crawling.

import html
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_sukebei(object):
    url = "https://sukebei.nyaa.si"
    name = "Sukebei (Nyaa)"
    # Anime = Art - Anime, books = Art - Doujinshi, games = Art - Games,
    # pictures = Real Life - Photobooks and Pictures, movies = Real Life - Videos.
    supported_categories = {"all": "0_0", "anime": "1_1", "books": "1_2", "games": "1_3",
                            "pictures": "2_1", "movies": "2_2"}
    pages = 4
    per_page = 75

    row = re.compile(r'<tr class="(?:default|success|danger)">(.*?)</tr>', re.S)
    title = re.compile(r'<a href="(/view/\d+)" title="([^"]*)">')
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[^"]+)"')
    numbers = re.compile(
        r'<td class="text-center">([^<]*)</td>\s*'
        r'<td class="text-center" data-timestamp="(\d+)">[^<]*</td>\s*'
        r'<td class="text-center">(\d+)</td>\s*'
        r'<td class="text-center">(\d+)</td>', re.S)
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            return ""

    def read(self, page):
        count = 0
        for found in self.row.finditer(page):
            row = found.group(1)
            title, magnet, numbers = self.title.search(row), self.magnet.search(row), self.numbers.search(row)
            if not title or not magnet or not numbers:
                continue
            link = html.unescape(magnet.group(1))
            if not self.safe_magnet.fullmatch(link):
                continue
            count += 1
            prettyPrinter({
                "link": link,
                "name": html.unescape(title.group(2)),
                "size": numbers.group(1).strip(),
                "seeds": int(numbers.group(3)),
                "leech": int(numbers.group(4)),
                "engine_url": self.url,
                "desc_link": self.url + title.group(1),
                "pub_date": int(numbers.group(2)),
            })
        return count

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        category = self.supported_categories.get(cat, "0_0")
        for number in range(1, self.pages + 1):
            page = self.fetch(f"{self.url}/?f=0&c={category}&q={query}&s=seeders&o=desc&p={number}")
            if not page and number == 1:
                raise RuntimeError("Sukebei didn't answer")
            if self.read(page) < self.per_page:
                break
            time.sleep(0.5)

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a Sukebei magnet")
        print(link + " " + link)
