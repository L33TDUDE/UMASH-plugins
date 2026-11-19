# VERSION: 1.0
# AUTHORS: Umash
#
# TorrentDownload (torrentdownload.info), a general index, best-seeded first.
#
# The site is erratic: a request can hang for 60 seconds and end in "504 Gateway
# Timeout", and the same request a moment later answers in under a second. The
# older plugins waited the full minute and never asked again, so a search could
# sit at "running" with one result. This one gives each request 15 seconds, asks
# up to 3 times, and fetches its pages at once: 3 pages of 50 for All, 5 for a
# category (the site has no category search, so rows are kept by the category
# the site shows on each).
#
# Dates: the search page only says "1 Year+", so exact dates come from the
# site's RSS feed, which covers the first ~50 results. Others show no date.
#
# Results are magnet links built from the info hash with public trackers;
# nothing is fetched when you download one.

import email.utils
import html
import re
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_torrentdownload(object):
    url = "https://www.torrentdownload.info"
    name = "TorrentDownload"
    supported_categories = {"all": "", "anime": "anime", "books": "books", "games": "games",
                            "movies": "movies", "music": "music", "software": "software", "tv": "tv"}
    pages = 3
    category_pages = 5
    wait = 15
    tries = 3

    row = re.compile(
        r'<div class="tt-name"><a href="/(?P<hash>[0-9A-Fa-f]{40})/(?P<slug>[^"]*)">(?P<name>.*?)</a>'
        r'(?:\s*<span class="smallish">\s*(?:&raquo;|»)\s*(?P<cat>[^<]*)</span>)?'
        r'.*?<td class="tdnormal">[^<]*</td>'
        r'\s*<td class="tdnormal">(?P<size>[^<]*)</td>'
        r'\s*<td class="tdseed">(?P<seeds>[^<]*)</td>'
        r'\s*<td class="tdleech">(?P<leech>[^<]*)</td>',
        re.S)
    item = re.compile(r"<item>(.*?)</item>", re.S)
    item_title = re.compile(r"<title>(.*?)</title>", re.S)
    item_hash = re.compile(r"/([0-9A-Fa-f]{40})</link>")
    item_date = re.compile(r"<pubDate>(.*?)</pubDate>", re.S)
    # The site's own labels, checked in this order ("Adult / Porn > DVD" fits none).
    category_rules = (
        ("anime", ("anime",)),
        ("books", ("book",)),
        ("tv", ("tv", "television")),
        ("movies", ("movie",)),
        ("music", ("music", "audio", "lossless", "mp3")),
        ("games", ("game",)),
        ("software", ("applic", "software", "mac", "windows", "unix", "linux")),
    )
    trackers = ("udp://tracker.opentrackr.org:1337/announce",
                "udp://tracker.torrent.eu.org:451/announce",
                "udp://open.stealth.si:80/announce",
                "udp://open.demonii.com:1337/announce",
                "udp://exodus.desync.com:6969/announce",
                "udp://explodie.org:6969/announce")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[a-f0-9]{40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address):
        """The page as text, or "" after every try failed."""
        for _ in range(self.tries):
            request = urllib.request.Request(address, headers=dict(_headers))
            try:
                with urllib.request.urlopen(request, timeout=self.wait) as response:
                    return response.read().decode("utf-8", "replace")
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
                continue
        return ""

    @staticmethod
    def text(raw):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", "", raw)).split())

    @staticmethod
    def count(raw):
        raw = raw.replace(",", "").strip()
        return int(raw) if raw.isdigit() else -1

    def kind(self, label):
        label = (label or "").lower()
        for name, words in self.category_rules:
            if any(word in label for word in words):
                return name
        return ""

    def feed(self, text):
        """{info hash: (full title, unix time)} from the RSS feed."""
        found = {}
        for item in self.item.findall(text):
            info_hash = self.item_hash.search(item)
            if not info_hash:
                continue
            title = self.item_title.search(item)
            day = self.item_date.search(item)
            stamp = -1
            if day:
                parsed = email.utils.parsedate_tz(day.group(1).strip())
                if parsed:
                    stamp = email.utils.mktime_tz(parsed)
            found[info_hash.group(1).lower()] = (self.text(title.group(1)) if title else "", stamp)
        return found

    def magnet(self, info_hash, name):
        parts = [f"xt=urn:btih:{info_hash}", "dn=" + urllib.parse.quote(name, safe="")]
        parts += ["tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers]
        return "magnet:?" + "&".join(parts)

    def rows(self, text, extra, cat):
        found = []
        for match in self.row.finditer(text):
            if cat != "all" and self.kind(match.group("cat")) != cat:
                continue
            info_hash = match.group("hash").lower()
            title, stamp = extra.get(info_hash, ("", -1))
            name = self.text(match.group("name"))
            # Long names are cut to "...-BE.."; the feed or the link has them whole.
            if name.endswith(".."):
                name = title or " ".join(urllib.parse.unquote(match.group("slug")).replace("+", " ").split())
            found.append((info_hash, {
                "link": self.magnet(info_hash, name),
                "name": name,
                "size": match.group("size").replace(",", "").strip() or "-1",
                "seeds": self.count(match.group("seeds")),
                "leech": self.count(match.group("leech")),
                "engine_url": self.url,
                "desc_link": f"{self.url}/{match.group('hash')}/{match.group('slug')}",
                "pub_date": stamp,
            }))
        return found

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        count = self.pages if cat == "all" else self.category_pages
        addresses = {number: f"{self.url}/search?q={query}&p={number}" for number in range(1, count + 1)}
        addresses["feed"] = f"{self.url}/feed?q={query}"
        texts = {}

        def get(key):
            texts[key] = self.fetch(addresses[key])

        threads = [threading.Thread(target=get, args=(key,)) for key in addresses]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        if not texts.get(1):
            print("TorrentDownload didn't answer after 3 tries; try again in a minute.", file=sys.stderr)
            raise SystemExit(1)
        extra = self.feed(texts.get("feed", ""))
        seen = set()
        for number in range(1, count + 1):
            for info_hash, row in self.rows(texts.get(number, ""), extra, cat):
                if info_hash not in seen:
                    seen.add(info_hash)
                    prettyPrinter(row)

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a TorrentDownload magnet")
        print(link + " " + link)
