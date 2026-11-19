# VERSION: 2.0
# AUTHORS: Umash
#
# My Porn Club (myporn.club): adult videos and picture sets shared by the site's
# members. Adult content only; check that your country and age allow it.
#
# Searches the site's keyword pages (one word each, so several words are joined,
# as in its hashtags: "big tits" looks up "bigtits"), best-seeded first, 40 to a
# page: the name
# (the member's title without its hashtags), when it was added (the site gives
# "9 minutes ago" style times, so the date is approximate), size, seeds and
# leechers. Up to 3 pages (120 results), one after another; Umash's "load more"
# asks for the next. The magnet is on each torrent's own page, so it is read only
# when you download one. The site has no categories, so only "all" is offered.

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


class umash_mypornclub(object):
    url = "https://myporn.club"
    name = "My Porn Club"
    supported_categories = {"all": ""}
    pages = 3
    page_size = 40
    timeout = 30

    unit_seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800,
                    "month": 2592000, "year": 31536000}
    element = re.compile(r"<div class='torrent_element'>(.*?)(?=<div class='torrent_element'>|<div class='pagination_div'>|$)", re.S)
    topic = re.compile(r"<a href='(/t/[A-Za-z0-9]+)[^']*' class='tdn' title='([^']*)'")
    added = re.compile(r"class='tdn linkadd'>([^<]*)</a>")
    size = re.compile(r"\[size\]:</span><span class='teiv'>([^<]*)</span>")
    seeds = re.compile(r"teiv_seeders'>(\d+)<")
    leech = re.compile(r"teiv_leechers'>(\d+)<")
    detail_page = re.compile(r"https://myporn\.club/t/[A-Za-z0-9]+")
    magnet = re.compile(r"""href=['"](magnet:\?xt=urn:btih:[^'"]+)['"]""")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", "replace")

    def address(self, query, page):
        # The site's keyword pages are single words, written as its hashtags are
        # ("bigtits"), so several words are joined.
        return f"{self.url}/s/{urllib.parse.quote(''.join(query.split()), safe='')}/seeders/{page}"

    def when(self, text):
        found = re.match(r"(\d+|an?)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text.strip(), re.I)
        if not found:
            return -1
        count = 1 if found.group(1).lower() in ("a", "an") else int(found.group(1))
        return int(time.time()) - count * self.unit_seconds[found.group(2).lower()]

    @staticmethod
    def clean_name(title):
        # Members pack hashtags and links into the title; the name is what comes before them.
        text = " ".join(html.unescape(title).split())
        text = re.split(r"\s#|\s->|\shttps?://", text, maxsplit=1)[0].strip()
        return (text or " ".join(html.unescape(title).split()))[:200]

    @staticmethod
    def number(text):
        return int(text) if text.isdigit() and int(text) < 2**31 else -1

    def read(self, page_text):
        count = 0
        for found in self.element.finditer(page_text):
            element = found.group(1)
            topic = self.topic.search(element)
            if not topic:
                continue
            count += 1
            page = self.url + topic.group(1)
            added, size, seeds, leech = (pattern.search(element) for pattern in (self.added, self.size, self.seeds, self.leech))
            prettyPrinter({
                "link": page,
                "name": self.clean_name(topic.group(2)),
                "size": re.sub(r"(?i)\s*([kmgt])b$", lambda m: " " + m.group(1).upper() + "B", size.group(1).strip()) if size else -1,
                "seeds": self.number(seeds.group(1)) if seeds else -1,
                "leech": self.number(leech.group(1)) if leech else -1,
                "engine_url": self.url,
                "desc_link": page,
                "pub_date": self.when(added.group(1)) if added else -1,
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
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                text = self.fetch(self.address(query, page))
            except urllib.error.HTTPError as error:
                if error.code == 404:  # no keyword page: nothing matches
                    return
                raise RuntimeError(f"My Porn Club answered HTTP {error.code}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                raise RuntimeError("My Porn Club didn't answer: " + str(error))
            full = self.read(text) >= self.page_size
            self.more(page + 1 if full else 0)
            if not full:
                return
            time.sleep(0.6)

    def download_torrent(self, info):
        """Reads the magnet from the torrent's own page, on this site only."""
        if not self.detail_page.fullmatch(info):
            raise ValueError("that isn't a torrent page on My Porn Club")
        found = self.magnet.search(self.fetch(info))
        magnet = html.unescape(found.group(1)) if found else ""
        if not self.safe_magnet.fullmatch(magnet):
            raise RuntimeError("My Porn Club's page has no magnet, or one that looks wrong")
        print(magnet + " " + info)
