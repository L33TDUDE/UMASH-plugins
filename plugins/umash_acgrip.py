# VERSION: 1.0
# AUTHORS: Umash
#
# ACG.RIP (acg.rip): a Chinese index of anime fansub releases, Japanese drama
# and variety shows, music and everything else the fansub groups post. Titles
# are mostly in Chinese and Japanese with the English name after a slash, so
# search by the English or romaji name.
#
# The site's RSS feed gives 30 results a page, newest first, each with the
# .torrent file, the exact size and the date it was added. This reads up to
# 3 pages one after another, as the site refuses quick repeats (up to 90
# results; for "tv", up to 90 from each of the site's two TV sections), and
# Umash's "load more" asks for the next pages. The site shows no seed counts.
# Categories are the site's own:
#   anime = Anime (动画), tv = Japanese drama (日剧) and variety shows (综艺),
#   music = Music (音乐). "all" also includes Other (其它).

import email.utils
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from helpers import _headers, download_file
from novaprinter import prettyPrinter


class umash_acgrip(object):
    url = "https://acg.rip"
    name = "ACG.RIP"
    # Section numbers on the site: 1 anime, 2 Japanese drama, 3 variety, 4 music, 9 other.
    supported_categories = {"all": "", "anime": "1", "tv": "2,3", "music": "4"}
    pages = 3
    page_size = 30
    timeout = 25
    torrent_link = re.compile(r"https://acg\.rip/t/\d+\.torrent")
    page_link = re.compile(r"https://acg\.rip/t/\d+")

    def fetch(self, section, query, page):
        address = f"{self.url}/{section}.xml?term={urllib.parse.quote(query)}"
        if page > 1:
            address += f"&page={page}"
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            text = response.read().decode("utf-8", "replace")
        # Real feeds have no DOCTYPE. Refusing one rules out XML entity tricks.
        if "<!doctype" in text.lower():
            raise ValueError("feed has a DOCTYPE, refusing to read it")
        return ET.fromstring(text)

    @staticmethod
    def date(text):
        parsed = email.utils.parsedate_tz(text or "")
        return email.utils.mktime_tz(parsed) if parsed else -1

    def load(self, section, query, page):
        """One feed page. The site answers 429 to quick repeats, so it waits and tries once more."""
        for attempt in (0, 1):
            try:
                return self.fetch(section, query, page)
            except urllib.error.HTTPError as error:
                if error.code != 429 or attempt:
                    raise
                time.sleep(2.5)

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
        sections = self.supported_categories.get(cat, "").split(",")
        first = self.setting("UMASH_START_PAGE", 1)
        seen = set()
        answered = False
        failure = ""
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            full = False
            for section in sections:
                try:
                    feed = self.load(section, query, page)
                except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, ET.ParseError) as error:
                    failure = str(error)
                    continue
                answered = True
                items = list(feed.iter("item"))
                full = len(items) >= self.page_size or full
                for item in items:
                    enclosure = item.find("enclosure")
                    link = enclosure.get("url", "") if enclosure is not None else ""
                    if not self.torrent_link.fullmatch(link) or link in seen:
                        continue
                    seen.add(link)
                    size = item.findtext("{http://xmlns.ezrss.it/0.1/}contentLength") or ""
                    desc = (item.findtext("link") or "").strip()
                    prettyPrinter({
                        "link": link,
                        "name": " ".join((item.findtext("title") or "").split()),
                        "size": int(size) if size.isdigit() else -1,
                        "seeds": -1,
                        "leech": -1,
                        "engine_url": self.url,
                        "desc_link": desc if self.page_link.fullmatch(desc) else self.url,
                        "pub_date": self.date(item.findtext("pubDate")),
                    })
                time.sleep(0.6)
            if not answered:
                raise RuntimeError("ACG.RIP didn't answer: " + (failure or "no reply"))
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, link):
        if not self.torrent_link.fullmatch(link):
            raise ValueError("not an ACG.RIP torrent link")
        print(download_file(link))
