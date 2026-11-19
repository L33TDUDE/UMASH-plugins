# VERSION: 1.0
# AUTHORS: Umash
#
# Academic Torrents (academictorrents.com): a community-run library of research
# data, scientific papers and university course videos, built to be shared:
# machine-learning datasets (ImageNet, COCO), genomes, Wikipedia dumps, open-access
# journals and lecture series. Everything here is shared by its authors or
# is free to share. Nothing here is a film, TV show or game.
#
# The site asks scrapers not to use its search page and to read its database
# file instead: one cached XML file (about 3 MB, about 3,000 torrents) that it
# refreshes once a day. A search reads that file and keeps the torrents whose
# title or description contain every word you type, with title matches
# first, then those where your words appear together as a phrase. The file lists
# the size but no date or seed counts. Results are the site's own .torrent files, which
# Umash downloads only from academictorrents.com.
#
# Categories are the site's own three types: books = Paper (scientific papers
# and books); "all" also includes Dataset and Course (university lectures).

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from helpers import _headers, download_file
from novaprinter import prettyPrinter


class umash_academictorrents(object):
    url = "https://academictorrents.com"
    name = "Academic Torrents"
    supported_categories = {"all": "", "books": "Paper"}
    database = "https://academictorrents.com/database.xml"
    limit = 200
    infohash = re.compile(r"[0-9a-f]{40}")
    torrent_link = re.compile(r"https://academictorrents\.com/download/[0-9a-f]{40}\.torrent")

    def fetch(self):
        request = urllib.request.Request(self.database, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Academic Torrents answered HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise RuntimeError(f"Academic Torrents didn't answer: {error}")
        # The real file has no DOCTYPE. Refusing one rules out XML entity tricks.
        if "<!doctype" in text.lower():
            raise RuntimeError("Academic Torrents sent a database with a DOCTYPE; not reading it")
        try:
            return ET.fromstring(text)
        except ET.ParseError as error:
            raise RuntimeError(f"Academic Torrents sent a database that can't be read: {error}")

    def search(self, what, cat="all"):
        words = urllib.parse.unquote(what).lower().split()
        wanted = self.supported_categories.get(cat, "")
        rows = []
        for item in self.fetch().iter("item"):
            infohash = (item.findtext("infohash") or "").strip().lower()
            title = " ".join((item.findtext("title") or "").split())
            if not self.infohash.fullmatch(infohash) or not title:
                continue
            if wanted and (item.findtext("category") or "") != wanted:
                continue
            name = title.lower()
            description = (item.findtext("description") or "").lower()
            if not all(word in name or word in description for word in words):
                continue
            # Best first: your words as a phrase in the title, then every word in the
            # title, then in the description only.
            phrase = " ".join(words)
            rank = 0 if phrase and phrase in name else 1 if all(word in name for word in words) else 2
            size = (item.findtext("size") or "").strip()
            rows.append((rank, {
                "link": f"{self.url}/download/{infohash}.torrent",
                "name": title,
                "size": int(size) if size.isdigit() else -1,
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": f"{self.url}/details/{infohash}",
                "pub_date": -1,
            }))
        rows.sort(key=lambda pair: pair[0])
        for _, row in rows[:self.limit]:
            prettyPrinter(row)

    def download_torrent(self, link):
        if not self.torrent_link.fullmatch(link):
            raise ValueError("not an Academic Torrents link")
        print(download_file(link))
