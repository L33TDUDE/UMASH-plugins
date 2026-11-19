# VERSION: 1.2
# AUTHORS: Umash
# SETTING: api_key | secret | API key | Optional. Without a key: 200 searches a day. A free Bitsearch account's key allows 1,000. | https://bitsearch.eu/api
#
# Bitsearch (bitsearch.eu) through its public API: https://bitsearch.eu/api
# One request per search, up to 100 results.
#
# Free use needs no account: 200 searches a day per IP address. A free
# Bitsearch account gives an API key and 1,000 a day: add it in Umash under
# Plugins > Bitsearch > Settings. It is kept in the Keychain.
#
# Search results carry the info hash but no magnet link; the magnet is built
# here with the trackers Bitsearch's own magnet links use.
#
# Dates: search results include createdAt for only a few torrents. Every
# result's id is a MongoDB ObjectId, whose first 8 hex digits are the second
# the record was created: the same moment as createdAt for everything added
# since 2019. Torrents from Bitsearch's January 2019 import show that import
# date instead of their older real one.

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import helpers
from novaprinter import prettyPrinter


class umash_bitsearch(object):
    url = "https://bitsearch.eu"
    name = "Bitsearch"
    # qBittorrent category -> Bitsearch category id (see bitsearch.eu/api).
    supported_categories = {
        "all": "",
        "movies": "2",
        "tv": "3",
        "anime": "4",
        "software": "5",
        "games": "6",
        "music": "7",
        "books": "9",
    }

    api = "https://bitsearch.eu/api/v1/search"
    limit = 100
    timeout = 20
    trackers = (
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://tracker.qu.ax:6969/announce",
        "udp://tracker.tryhackx.org:6969/announce",
        "udp://tracker.bitsearch.to:1337/announce",
    )

    @staticmethod
    def api_key():
        return os.environ.get("UMASH_SETTING_API_KEY", "").strip()

    def fetch(self, params):
        headers = dict(helpers._headers)
        headers["Accept"] = "application/json"
        key = self.api_key()
        if key:
            headers["x-api-key"] = key
        request = urllib.request.Request(self.api + "?" + urllib.parse.urlencode(params), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 429:
                limit = "1,000 a day with your key" if key else \
                    "200 a day without a key; a free Bitsearch account's key allows 1,000 (add it in the plugin's Settings)"
                raise RuntimeError("Bitsearch daily search limit reached: " + limit)
            if error.code == 401:
                raise RuntimeError("Bitsearch refused the API key in the plugin's Settings")
            raise RuntimeError(f"Bitsearch answered HTTP {error.code}")
        except urllib.error.URLError as error:
            raise RuntimeError(f"Bitsearch did not answer: {error.reason}")
        except ValueError:
            raise RuntimeError("Bitsearch did not return JSON")

    def magnet(self, infohash, title):
        quote = lambda text: urllib.parse.quote(text, safe="")
        return ("magnet:?xt=urn:btih:" + infohash + "&dn=" + quote(title)
                + "".join("&tr=" + quote(t) for t in self.trackers))

    @staticmethod
    def count(value):
        """Seeds or leechers; -1 (unknown) for Bitsearch's broken counters, which
        arrive as negative numbers sent unsigned (4294967231 for -65)."""
        try:
            number = int(value or 0)
        except (TypeError, ValueError):
            return -1
        return number if 0 <= number < 2 ** 31 else -1

    @staticmethod
    def unix_time(stamp):
        try:
            return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp())
        except ValueError:
            return -1

    @classmethod
    def added(cls, row):
        """When Bitsearch added the torrent: createdAt, else the time inside its id."""
        if row.get("createdAt"):
            stamp = cls.unix_time(row["createdAt"])
            if stamp > 0:
                return stamp
        object_id = str(row.get("id") or "")
        if len(object_id) == 24:
            try:
                return int(object_id[:8], 16)
            except ValueError:
                pass
        return -1

    def search(self, what, cat="all"):
        params = {"q": urllib.parse.unquote(what), "limit": self.limit}
        category = self.supported_categories.get(cat, "")
        if category:
            params["category"] = category
        data = self.fetch(params)
        if not data.get("success", True):
            raise RuntimeError("Bitsearch: " + str(data.get("error") or data.get("message") or "search failed"))
        for row in data.get("results") or []:
            infohash = str(row.get("infohash") or "").strip()
            title = str(row.get("title") or "").strip()
            if len(infohash) not in (32, 40) or not title:
                continue
            prettyPrinter({
                "link": self.magnet(infohash, title),
                "name": title,
                "size": int(row.get("size") or -1),
                "seeds": self.count(row.get("seeders")),
                "leech": self.count(row.get("leechers")),
                "engine_url": self.url,
                "desc_link": f"{self.url}/torrent/{row.get('id')}",
                # Not updatedAt: that is when Bitsearch last checked the swarm.
                "pub_date": self.added(row),
            })
