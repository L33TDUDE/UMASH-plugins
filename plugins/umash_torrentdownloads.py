# VERSION: 2.0
# AUTHORS: Umash
#
# Torrent Downloads (torrentdownloads.pro): a general index of movies, TV, music,
# games, anime, books and software.
#
# Reads the site's RSS search feed, which carries everything for each result:
# name, date added, size, seeds, leechers, category and info hash. The feed holds
# the best 50 matches for a search and has no further pages, so searching inside
# one category (anime, books and so on) reaches results that "all" leaves out.
# The magnet is built from the info hash, so downloading needs no second request.

import email.utils
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

from helpers import _headers
from novaprinter import prettyPrinter


class umash_torrentdownloads(object):
    url = "https://www.torrentdownloads.pro"
    name = "Torrent Downloads Pro"
    # The site's category ids (cid); 0 is every category.
    supported_categories = {"all": "0", "anime": "1", "books": "2", "games": "3", "movies": "4",
                            "music": "5", "software": "7", "tv": "8"}
    timeout = 30
    max_bytes = 4_000_000

    trackers = ("udp://tracker.opentrackr.org:1337/announce", "udp://open.stealth.si:80/announce",
                "udp://exodus.desync.com:6969/announce", "udp://tracker.torrent.eu.org:451/announce")
    info_hash = re.compile(r"[0-9A-Fa-f]{40}")
    torrent_path = re.compile(r"/torrent/[0-9]+/[A-Za-z0-9._~%-]*")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read(self.max_bytes)

    @staticmethod
    def parse(raw):
        """The feed's XML. The site's host adds a script after the closing tag, so the
        data is cut there. A feed that declares a DOCTYPE or entities is refused: a
        real one never does, and they are how XML parsers get attacked."""
        end = raw.find(b"</rss>")
        if end < 0 or re.search(rb"<!(?:DOCTYPE|ENTITY)", raw, re.I):
            raise RuntimeError("Torrent Downloads answered with something that isn't its feed")
        try:
            return ElementTree.fromstring(raw[:end + len(b"</rss>")])
        except ElementTree.ParseError:
            raise RuntimeError("Torrent Downloads answered with something that isn't its feed")

    @staticmethod
    def number(text):
        text = (text or "").strip()
        return int(text) if text.isdigit() and int(text) < 2**31 else -1

    @staticmethod
    def date(text):
        try:
            return int(email.utils.parsedate_to_datetime(text).timestamp())
        except (TypeError, ValueError):
            return -1

    def magnet(self, digest, name):
        parts = [f"magnet:?xt=urn:btih:{digest.lower()}", "dn=" + urllib.parse.quote(name, safe="")]
        parts += ["tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers]
        return "&".join(parts)

    def search(self, what, cat="all"):
        query = urllib.parse.unquote(what).strip()
        address = (f"{self.url}/rss.xml?type=search&cid={self.supported_categories.get(cat, '0')}"
                   f"&search={urllib.parse.quote_plus(query)}")
        try:
            feed = self.parse(self.fetch(address))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise RuntimeError("Torrent Downloads didn't answer: " + str(error))
        for item in feed.iter("item"):
            digest = (item.findtext("info_hash") or "").strip()
            name = " ".join((item.findtext("title") or "").split())
            if not self.info_hash.fullmatch(digest) or not name:
                continue
            path = (item.findtext("link") or "").strip()
            prettyPrinter({
                "link": self.magnet(digest, name),
                "name": name,
                "size": self.number(item.findtext("size")),
                "seeds": self.number(item.findtext("seeders")),
                "leech": self.number(item.findtext("leechers")),
                "engine_url": self.url,
                "desc_link": self.url + path if self.torrent_path.fullmatch(path) else "",
                "pub_date": self.date(item.findtext("pubDate")),
            })
