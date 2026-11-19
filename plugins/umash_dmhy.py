# VERSION: 1.0
# AUTHORS: Umash
#
# DMHY (share.dmhy.org, 動漫花園): one of the largest Chinese-language indexes of
# anime, manga, Japanese drama and music, with fansub releases from groups in
# Taiwan, Hong Kong and mainland China. Titles are mostly Chinese or Japanese
# with the English name in brackets, so search by whatever name the release uses.
#
# Reads the site's search pages, which carry what its RSS feed leaves out: the
# size and the seed and leech counts, best-matched newest first. Up to 2 pages
# of 80 (160 results), one after another; Umash's "load more" asks for the
# next pages. Categories are the site's own
# sections, and each includes its sub-sections:
#   anime = Anime (動畫, with the season collections 季度全集),
#   books = Manga (漫畫, with the Taiwan/Hong Kong and Japanese originals),
#   music = Music (音樂, with anime, doujin and pop music),
#   games = Games (遊戲, with PC, console, handheld and online games),
#   tv = Japanese drama (日劇) and Tokusatsu (特攝).
# "all" searches every section, including RAW and Other.

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


class umash_dmhy(object):
    url = "https://share.dmhy.org"
    name = "DMHY"
    # Section ids from the site's search form (sort_id).
    supported_categories = {"all": "0", "anime": "2", "books": "3", "music": "4", "games": "9", "tv": "6,12"}
    pages = 2
    page_size = 80
    timeout = 30

    row = re.compile(r'<tr class="(?:odd)?">(.*?)</tr>', re.S)
    stamp = re.compile(r"(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2})")
    topic = re.compile(r'<td class="title">.*?<a href="(/topics/view/[^"]+)"[^>]*>(.*?)</a>', re.S)
    magnet = re.compile(r'class="download-arrow arrow-magnet"[^>]*href="(magnet:\?xt=urn:btih:[^"]+)"')
    cells = re.compile(r'<td nowrap="nowrap" align="center">([^<]*)</td>\s*'
                       r'<td nowrap="nowrap" align="center"><span class="btl_1">([^<]*)</span></td>\s*'
                       r'<td nowrap="nowrap" align="center"><span class="bts_1">([^<]*)</span></td>', re.S)
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, section, query, page):
        path = "/topics/list" + (f"/page/{page}" if page > 1 else "")
        address = f"{self.url}{path}?keyword={urllib.parse.quote_plus(query)}"
        if section != "0":
            address += f"&sort_id={section}"
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", "replace")

    def date(self, text):
        # The site shows Taiwan time (UTC+8).
        found = self.stamp.search(text)
        if not found:
            return -1
        year, month, day, hour, minute = map(int, found.groups())
        return calendar.timegm((year, month, day, hour, minute, 0)) - 8 * 3600

    @staticmethod
    def number(text):
        text = text.strip()
        return int(text) if text.isdigit() and int(text) < 2**31 else -1

    def read(self, page_text):
        count = 0
        for found in self.row.finditer(page_text):
            row = found.group(1)
            topic, magnet, cells = self.topic.search(row), self.magnet.search(row), self.cells.search(row)
            if not topic or not magnet or not cells:
                continue
            count += 1
            title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", topic.group(2))).split())
            link = html.unescape(magnet.group(1))
            if not self.safe_magnet.fullmatch(link):
                continue
            # The site's magnets carry an empty name; give them the title.
            link = link.replace("&dn=&", "&dn=" + urllib.parse.quote(title, safe="") + "&", 1)
            prettyPrinter({
                "link": link,
                "name": title,
                "size": cells.group(1).strip() or -1,
                "seeds": self.number(cells.group(2)),
                "leech": self.number(cells.group(3)),
                "engine_url": self.url,
                "desc_link": self.url + html.unescape(topic.group(1)),
                "pub_date": self.date(row),
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
        sections = self.supported_categories.get(cat, "0").split(",")
        first = self.setting("UMASH_START_PAGE", 1)
        answered = False
        failure = ""
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            full = False
            for section in sections:
                try:
                    text = self.fetch(section, query, page)
                except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                    failure = str(error)
                    continue
                answered = True
                full = self.read(text) >= self.page_size or full
            if not answered:
                raise RuntimeError("DMHY didn't answer: " + (failure or "no reply"))
            self.more(page + 1 if full else 0)
            if not full:
                return
            time.sleep(0.6)

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a DMHY magnet")
        print(link + " " + link)
