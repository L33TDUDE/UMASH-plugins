# VERSION: 1.0
# AUTHORS: Umash
#
# Nyaa (nyaa.si): the largest English-language home of anime releases, with
# fansub episodes and batches, raw releases, Japanese music, light novels and
# manga, and Japanese live-action shows.
#
# Best-seeded first, with the date each torrent was added, size, seeds and
# leeches, and a magnet on every row. A search reads 2 pages of 75 (150
# results); Umash's "load more" asks for the next pages. The older plugin read
# up to 14 pages with no pause and no date. This one asks the site for sorted
# results directly and waits 5 seconds between pages, as the site's
# robots.txt asks of crawlers.
#
# Categories use the site's own sections, each with its sub-sections:
#   anime = Anime (music videos, English-translated, non-English, raw),
#   music = Audio (lossless, lossy), books = Literature (light novels, manga),
#   tv and movies = Live Action (shows, films, idol videos: the site keeps them
#   in one section), pictures = Pictures (graphics, photos),
#   software = Software (applications, games), games = Software > Games.

import html
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import helpers
from helpers import _headers
from novaprinter import prettyPrinter


class umash_nyaa(object):
    url = "https://nyaa.si"
    name = "Nyaa"
    # Category ids from the site's own search form (c=<section>_<sub-section>, 0 = all of it).
    supported_categories = {
        "all": "0_0", "anime": "1_0", "music": "2_0", "books": "3_0", "tv": "4_0", "movies": "4_0",
        "pictures": "5_0", "software": "6_0", "games": "6_2",
    }
    pages = 2
    per_page = 75
    pause = 5

    row = re.compile(r'<tr class="(?:default|success|danger)">(.*?)</tr>', re.S)
    title = re.compile(r'<a href="(/view/\d+)" title="([^"]*)">')
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[^"]+)"')
    numbers = re.compile(
        r'<td class="text-center">([^<]*)</td>\s*'
        r'<td class="text-center" data-timestamp="(\d+)">[^<]*</td>\s*'
        r'<td class="text-center">(\d+)</td>\s*'
        r'<td class="text-center">(\d+)</td>', re.S)
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = helpers._unpacked(response.read())
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Nyaa answered HTTP {error.code}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as error:
            raise RuntimeError(f"Nyaa didn't answer: {error}")
        return data.decode("utf-8", "replace")

    def read(self, page):
        count = 0
        for found in self.row.finditer(page):
            row = found.group(1)
            title, magnet, numbers = self.title.search(row), self.magnet.search(row), self.numbers.search(row)
            if not title or not magnet or not numbers:
                continue
            count += 1
            link = html.unescape(magnet.group(1))
            if not self.safe_magnet.fullmatch(link):
                continue
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
        first = self.setting("UMASH_START_PAGE", 1)
        for number in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                page = self.fetch(f"{self.url}/?f=0&c={category}&q={query}&s=seeders&o=desc&p={number}")
            except RuntimeError:
                if number > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            has_more = self.read(page) >= self.per_page
            self.more(number + 1 if has_more else 0)
            if not has_more:
                return
            if number + 1 < first + self.setting("UMASH_MAX_PAGES", self.pages):
                time.sleep(self.pause)

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a Nyaa magnet")
        print(link + " " + link)
