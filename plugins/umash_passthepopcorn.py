# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apiuser | secret required | ApiUser | On your PassThePopcorn profile, under Security: create an API key, then copy its ApiUser. | https://passthepopcorn.me/user.php?action=edit
# SETTING: apikey | secret required | ApiKey | The ApiKey shown beside the ApiUser when you create the key. | https://passthepopcorn.me/user.php?action=edit
#
# PassThePopcorn (passthepopcorn.me), a private movie tracker, through its API, the way Jackett
# and Prowlarr search it. Best-seeded first, one result per torrent (not per movie), up to
# 3 pages of 50. The keys go in request headers, never in a link.

import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from helpers import _headers
from novaprinter import prettyPrinter


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("PassThePopcorn refused the keys. Check them in the plugin's Settings")


class umash_passthepopcorn(object):
    url = "https://passthepopcorn.me"
    name = "PassThePopcorn"
    # Movies only: the site has no other kind of content.
    supported_categories = {
        "all": "",
        "movies": "",
    }

    per_page = 50
    pages = 3
    timeout = 25
    download_path = re.compile(r"/torrents\.php\?action=download&id=\d+")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def keys(self):
        user = os.environ.get("UMASH_SETTING_APIUSER", "").strip()
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not user or not key:
            raise RuntimeError("PassThePopcorn needs your ApiUser and ApiKey: add them in the plugin's Settings")
        return user, key

    def fetch(self, url):
        user, key = self.keys()
        request = urllib.request.Request(url, headers={**_headers, "ApiUser": user, "ApiKey": key, "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 403:
                raise RuntimeError("PassThePopcorn's query limit was reached, or it refused the keys. Try again later and check them in the plugin's Settings") from None
            if error.code == 429:
                raise RuntimeError("PassThePopcorn is limiting requests from this connection. Try again later") from None
            if error.code in (400, 401):
                raise RuntimeError("PassThePopcorn refused the keys, or they are not in its format. Check them in the plugin's Settings") from None
            raise RuntimeError(f"PassThePopcorn answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach PassThePopcorn: {error.reason}") from None

    def address(self, what, page):
        params = [("action", "advanced"), ("json", "noredirect"), ("grouping", "0"), ("order_by", "seeders"),
                  ("order_way", "desc"), ("searchstr", " ".join(urllib.parse.unquote(what).split())), ("page", page)]
        return f"{self.url}/torrents.php?{urllib.parse.urlencode(params)}"

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            found = None
        if not isinstance(found, dict):
            raise RuntimeError("PassThePopcorn sent something other than search results")
        movies = found.get("Movies")
        if movies is None:
            return []
        if not isinstance(movies, list):
            raise RuntimeError("PassThePopcorn sent something other than search results")
        return movies

    @staticmethod
    def date(text):
        try:
            return int(datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return -1

    @staticmethod
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def show(self, movie, torrent):
        tid = str(torrent.get("Id", ""))
        if not tid.isdigit():
            return
        name = " ".join(str(torrent.get("ReleaseName") or movie.get("Title") or "N/A").split())
        flags = []
        if torrent.get("GoldenPopcorn"):
            flags.append("Golden Popcorn")
        if str(torrent.get("FreeleechType") or "").upper() in ("FREELEECH", "NEUTRAL LEECH"):
            flags.append("FreeLeech")
        elif str(torrent.get("FreeleechType") or "").upper() == "HALF LEECH":
            flags.append("Half Leech")
        name += "".join(f" [{flag}]" for flag in flags)
        prettyPrinter({
            "link": f"{self.url}/torrents.php?action=download&id={tid}",
            "name": name,
            "size": str(self.number(torrent.get("Size"))),
            "seeds": self.number(torrent.get("Seeders")),
            "leech": self.number(torrent.get("Leechers")),
            "engine_url": self.url,
            "desc_link": f"{self.url}/torrents.php?id={movie.get('GroupId', '')}&torrentid={tid}",
            "pub_date": self.date(torrent.get("UploadTime")),
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
        self.keys()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                movies = self.read(self.fetch(self.address(what, page)))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for movie in movies:
                for torrent in movie.get("Torrents") or []:
                    self.show(movie, torrent)
            full = len(movies) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        """Sends the keys only to this site's own download address."""
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a PassThePopcorn download link, so Umash didn't send your keys to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            raise RuntimeError("PassThePopcorn didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
