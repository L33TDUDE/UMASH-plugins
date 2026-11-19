# VERSION: 1.0
# AUTHORS: Umash, after qBittorrent's piratebay.py
#
# The Pirate Bay, through its open API (apibay.org), with the date each
# torrent was added.
#
# The API sends at most 100 results a request and filters by one Pirate Bay
# category code at a time. qBittorrent's plugin used the top-level codes, so
# Movies (200, "Video") also brought in TV shows, and it had no TV or books.
# This one asks for each code that belongs to the chosen category, at once, and
# merges them. The codes are the ones Jackett's Pirate Bay definition uses:
#   movies     201 Movies, 202 DVDR, 207 HD, 209 3D, 210 CAM/TS, 211 UHD/4k
#   tv         205 TV shows, 208 HD, 212 UHD/4k
#   music      101 Music, 104 FLAC, 203 Music videos
#   books      601 E-books, 602 Comics, 102 Audio books
#   games      400 (every platform)
#   software   300 (every system)
#   pictures   603 Pictures
#   all        100 Audio, 200 Video, 300 Applications, 400 Games, 600 Other,
#              and 500 Porn unless adult results are hidden in Settings
# The site has no anime category.
#
# Each name ends with the site's own category, like "(HD - Movies)".
#
# Based on qBittorrent's piratebay.py, GPL-2.0-or-later:
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version. This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

import json
import os
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_piratebay(object):
    url = "https://thepiratebay.org"
    api = "https://apibay.org/q.php"
    name = "The Pirate Bay"
    supported_categories = {"all": "0", "books": "601", "games": "400", "movies": "201",
                            "music": "101", "pictures": "603", "software": "300", "tv": "205"}
    codes = {
        "all": ["100", "200", "300", "400", "500", "600"],
        "movies": ["201", "202", "207", "209", "210", "211"],
        "tv": ["205", "208", "212"],
        "music": ["101", "104", "203"],
        "books": ["601", "602", "102"],
        "games": ["400"],
        "software": ["300"],
        "pictures": ["603"],
    }
    names = {
        "100": "Audio", "101": "Music", "102": "Audio books", "103": "Sound clips", "104": "FLAC", "199": "Audio other",
        "200": "Video", "201": "Movies", "202": "Movies DVDR", "203": "Music videos", "204": "Movie clips",
        "205": "TV shows", "206": "Handheld", "207": "HD - Movies", "208": "HD - TV shows", "209": "3D",
        "210": "CAM/TS", "211": "UHD/4k - Movies", "212": "UHD/4k - TV shows", "299": "Video other",
        "300": "Applications", "301": "Windows", "302": "Mac", "303": "UNIX", "304": "Handheld",
        "305": "iOS", "306": "Android", "399": "Other OS",
        "400": "Games", "401": "PC games", "402": "Mac games", "403": "PlayStation", "404": "Xbox",
        "405": "Wii", "406": "Handheld games", "407": "iOS games", "408": "Android games", "499": "Games other",
        "500": "Porn", "501": "Porn", "502": "Porn DVDR", "503": "Porn pictures", "504": "Porn games",
        "505": "Porn HD", "506": "Porn clips", "507": "Porn UHD/4k", "599": "Porn other",
        "600": "Other", "601": "E-books", "602": "Comics", "603": "Pictures", "604": "Covers",
        "605": "Physibles", "699": "Other",
    }
    trackers = ("udp://tracker.opentrackr.org:1337/announce",
                "udp://open.stealth.si:80/announce",
                "udp://tracker.torrent.eu.org:451/announce",
                "udp://exodus.desync.com:6969/announce",
                "udp://open.demonii.com:1337/announce",
                "udp://explodie.org:6969/announce")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, query, code):
        address = f"{self.api}?{urllib.parse.urlencode({'q': query, 'cat': code})}"
        request = urllib.request.Request(address, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                answer = json.loads(response.read().decode("utf-8", "replace"))
                return answer if isinstance(answer, list) else []
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError):
            return None

    @staticmethod
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def search(self, what, cat="all"):
        query = urllib.parse.unquote(what)
        codes = list(self.codes.get(cat, self.codes["all"]))
        hide_adult = os.environ.get("UMASH_HIDE_ADULT") == "1"
        if hide_adult:
            codes = [code for code in codes if not code.startswith("5")]
        answers = {}

        def get(code):
            answers[code] = self.fetch(query, code)

        threads = [threading.Thread(target=get, args=(code,)) for code in codes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if all(answers.get(code) is None for code in codes):
            raise RuntimeError("The Pirate Bay's API (apibay.org) didn't answer")

        seen = set()
        for code in codes:
            for item in answers.get(code) or []:
                info_hash = str(item.get("info_hash", "")).lower()
                if not re.fullmatch(r"[0-9a-f]{40}", info_hash) or info_hash == "0" * 40 or info_hash in seen:
                    continue
                category = str(item.get("category", ""))
                if hide_adult and category.startswith("5"):
                    continue
                seen.add(info_hash)
                name = " ".join(str(item.get("name", "")).split())
                parts = [f"xt=urn:btih:{info_hash}", "dn=" + urllib.parse.quote(name, safe="")]
                parts += ["tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers]
                label = self.names.get(category)
                prettyPrinter({
                    "link": "magnet:?" + "&".join(parts),
                    "name": f"{name} ({label})" if label else name,
                    "size": str(self.number(item.get("size"))),
                    "seeds": self.number(item.get("seeders")),
                    "leech": self.number(item.get("leechers")),
                    "engine_url": self.url,
                    "desc_link": f"{self.url}/description.php?id={self.number(item.get('id'))}",
                    "pub_date": self.number(item.get("added")),
                })

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a Pirate Bay magnet")
        print(link + " " + link)
