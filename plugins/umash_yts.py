# VERSION: 1.0
# AUTHORS: Umash
#
# YTS (yts.mx), small-size movie releases, through the site's public JSON API. No account
# needed. Best-seeded first, one result per quality (720p, 1080p, 2160p...), up to 3 pages of
# 50 movies. The API gives the info hash, so the magnet is built here with the trackers YTS's
# own magnet links use. YTS moved its API to movies-api.accel.li; the older yts.mx and yts.bz
# addresses are tried when that one doesn't answer.

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_yts(object):
    url = "https://yts.mx"
    name = "YTS"
    # Movies only: the site has no other kind of content.
    supported_categories = {
        "all": "",
        "movies": "",
    }

    # Tried in order. Only these hosts are ever asked.
    api_hosts = ("https://movies-api.accel.li", "https://yts.mx", "https://yts.bz")
    per_page = 50
    pages = 3
    timeout = 20
    trackers = (
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.demonii.com:1337/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://open.stealth.si:80/announce",
        "udp://exodus.desync.com:6969/announce",
        "udp://tracker.openbittorrent.com:80/announce",
        "udp://explodie.org:6969/announce",
        "udp://tracker.tiny-vps.com:6969/announce",
    )

    def fetch(self, path, params):
        """Asks each API host in turn, and returns the first answer that is search results."""
        last = "YTS didn't answer"
        for host in self.api_hosts:
            request = urllib.request.Request(f"{host}{path}?{urllib.parse.urlencode(params)}",
                                             headers={**_headers, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    found = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as error:
                last = "YTS is limiting requests from this connection. Try again later" if error.code == 429 \
                    else f"YTS answered with HTTP {error.code}"
                continue
            except urllib.error.URLError as error:
                last = f"Couldn't reach YTS: {error.reason}"
                continue
            except ValueError:
                last = "YTS sent something other than search results"
                continue
            if isinstance(found, dict) and found.get("status") == "ok" and isinstance(found.get("data"), dict):
                return found["data"]
            last = "YTS sent something other than search results"
        raise RuntimeError(last)

    def magnet(self, infohash, title):
        return ("magnet:?xt=urn:btih:" + infohash + "&dn=" + urllib.parse.quote(title)
                + "".join("&tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers))

    @staticmethod
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def show(self, movie, torrent):
        infohash = str(torrent.get("hash") or "")
        if not re.fullmatch(r"[0-9A-Fa-f]{40}", infohash):
            return
        title = " ".join(str(movie.get("title_long") or movie.get("title") or "N/A").split())
        details = [str(torrent.get(key)) for key in ("quality", "type", "video_codec") if torrent.get(key)]
        name = title + "".join(f" [{detail}]" for detail in details) + " [YTS]"
        prettyPrinter({
            "link": self.magnet(infohash.upper(), name),
            "name": name,
            "size": str(self.number(torrent.get("size_bytes"))),
            "seeds": self.number(torrent.get("seeds")),
            "leech": self.number(torrent.get("peers")),
            "engine_url": self.url,
            "desc_link": str(movie.get("url") or self.url),
            "pub_date": self.number(torrent.get("date_uploaded_unix")),
        })

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    def search(self, what, cat="all"):
        words = " ".join(urllib.parse.unquote(what).split())
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                data = self.fetch("/api/v2/list_movies.json", [("query_term", words), ("limit", self.per_page),
                                                               ("page", page), ("sort_by", "seeds"), ("order_by", "desc")])
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            movies = data.get("movies") if isinstance(data.get("movies"), list) else []
            for movie in movies:
                for torrent in movie.get("torrents") or []:
                    self.show(movie, torrent)
            total = self.number(data.get("movie_count"))
            has_more = bool(movies) and page * self.per_page < total
            self.more(page + 1 if has_more else 0)
            if not has_more:
                return
