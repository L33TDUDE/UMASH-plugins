# VERSION: 1.0
# AUTHORS: Umash
#
# Torrents-CSV (torrents-csv.com): an open database of torrents collected from
# the DHT, searched through the site's JSON API.
#
# The API gives 25 results a page and a cursor for the next page; this reads
# up to 6 pages (up to 150 results), one after another, and stops when the
# database has no further page. Results carry the info hash, size, seed and leech counts and
# the date the torrent was first seen. There is no magnet link, so one is built
# here with common public trackers. The database has no categories, so only
# "all" is offered.

import json
import urllib.error
import urllib.parse
import urllib.request

import helpers
from novaprinter import prettyPrinter


class umash_torrentscsv(object):
    url = "https://torrents-csv.com"
    name = "Torrents-CSV"
    supported_categories = {"all": ""}

    api = "https://torrents-csv.com/service/search"
    page_size = 25
    pages = 6
    timeout = 20
    trackers = (
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.stealth.si:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://exodus.desync.com:6969/announce",
    )

    def fetch(self, params):
        headers = dict(helpers._headers)
        headers["Accept"] = "application/json"
        request = urllib.request.Request(self.api + "?" + urllib.parse.urlencode(params), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Torrents-CSV answered HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as error:
            raise RuntimeError(f"Torrents-CSV didn't answer: {error}")

    def magnet(self, infohash, name):
        tail = "".join("&tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers)
        return f"magnet:?xt=urn:btih:{infohash}&dn={urllib.parse.quote(name, safe='')}{tail}"

    @staticmethod
    def number(value):
        return value if isinstance(value, int) and 0 <= value < 2**31 else -1

    def search(self, what, cat="all"):
        query = urllib.parse.unquote(what)
        after = None
        seen = set()
        for number in range(self.pages):
            params = {"q": query, "size": self.page_size}
            if after is not None:
                params["after"] = after
            data = self.fetch(params)
            torrents = data.get("torrents") or []
            for torrent in torrents:
                infohash = str(torrent.get("infohash", "")).lower()
                name = str(torrent.get("name", "")).strip()
                if len(infohash) != 40 or not all(c in "0123456789abcdef" for c in infohash) or not name:
                    continue
                if infohash in seen:
                    continue
                seen.add(infohash)
                prettyPrinter({
                    "link": self.magnet(infohash, name),
                    "name": name,
                    "size": self.number(torrent.get("size_bytes")),
                    "seeds": self.number(torrent.get("seeders")),
                    "leech": self.number(torrent.get("leechers")),
                    "engine_url": self.url,
                    "desc_link": "-1",
                    "pub_date": self.number(torrent.get("created_unix")),
                })
            after = data.get("next")
            if not torrents or after is None:
                break

    def download_torrent(self, link):
        print(link + " " + link)
