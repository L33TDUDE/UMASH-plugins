# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API token | Create one on your SpeedApp profile page, then paste it here. | https://speedapp.io/profile
#
# SpeedApp (speedapp.io), a Romanian private tracker, through its API, the way Jackett
# and Prowlarr search it. The token goes in a request header, never in a link.

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
        raise RuntimeError(f"SpeedApp answered with a redirect (HTTP {code}), so Umash stopped")


class umash_speedapp(object):
    url = "https://speedapp.io"
    name = "SpeedApp"
    # The site's category numbers, from Jackett's SpeedApp indexer. "all" sends none.
    supported_categories = {
        "all": "",
        "anime": "3",
        "books": "6",
        "games": "11,52",
        "movies": "38,10,35,8,29,7,2,17,24,59,57,61",
        "music": "5,64,68",
        "software": "1,14,37,19",
        "tv": "41,66,45,46,43,44,60,62,22,58,9,63",
    }
    adult_categories = {"15", "47", "48", "49", "50", "51"}

    per_page = 100
    pages = 5
    timeout = 25
    download_path = re.compile(r"/api/torrent/\d+/download")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("SpeedApp needs your API token: add it in the plugin's Settings")
        return key

    def fetch(self, url):
        request = urllib.request.Request(url, headers={**_headers, "Authorization": "Bearer " + self.key(), "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("SpeedApp refused the API token. Check it in the plugin's Settings") from None
            if error.code == 429:
                raise RuntimeError("SpeedApp is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"SpeedApp answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach SpeedApp: {error.reason}") from None

    def address(self, what, cat, page):
        params = [("itemsPerPage", self.per_page), ("sort", "torrent.createdAt"), ("direction", "desc"),
                  ("search", urllib.parse.unquote(what)), ("page", page)]
        wanted = self.supported_categories.get(cat, "")
        if not wanted and os.environ.get("UMASH_HIDE_ADULT") == "1":
            wanted = ",".join(value for value in self.supported_categories.values() if value)
        params += [("categories[]", number) for number in wanted.split(",") if number]
        return f"{self.url}/api/torrent?{urllib.parse.urlencode(params)}"

    def read_rows(self, body):
        try:
            rows = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            rows = None
        if not isinstance(rows, list):
            raise RuntimeError("SpeedApp sent something other than search results")
        return rows

    def show(self, row):
        tid = row.get("id")
        if not isinstance(tid, int):
            return
        category = str((row.get("category") or {}).get("id", ""))
        if os.environ.get("UMASH_HIDE_ADULT") == "1" and category in self.adult_categories:
            return
        title = re.sub(r"\[REQUEST(ED)?\]", "", str(row.get("name") or "N/A"), flags=re.I).strip(" .")
        if row.get("download_volume_factor") == 0:
            title += " [FreeLeech]"
        prettyPrinter({
            "link": f"{self.url}/api/torrent/{tid}/download",
            "name": " ".join(title.split()),
            "size": str(row.get("size", -1)),
            "seeds": row.get("seeders", -1),
            "leech": row.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": row.get("url") or f"{self.url}/browse/{tid}",
            "pub_date": self.date(row.get("created_at")),
        })

    @staticmethod
    def date(text):
        try:
            when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            return -1
        return int(when.replace(tzinfo=when.tzinfo or timezone.utc).timestamp())

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    @staticmethod
    def save_torrent(data, info):
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)

    def search(self, what, cat="all"):
        self.key()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                rows = self.read_rows(self.fetch(self.address(what, cat, page)))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for row in rows:
                self.show(row)
            full = len(rows) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        """Sends the token only to this site's own download address."""
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a SpeedApp download link, so Umash didn't send your token to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            raise RuntimeError("SpeedApp didn't send a torrent file for this result")
        self.save_torrent(data, info)
