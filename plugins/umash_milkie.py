# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | Find or generate it on your Milkie security settings page. | https://milkie.cc/settings/security
#
# Milkie (milkie.cc), a private tracker, through its API, the way Jackett and Prowlarr
# search it. Result links carry no key: it is added only when downloading.

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
        raise RuntimeError(f"Milkie answered with a redirect (HTTP {code}), so Umash stopped")


class umash_milkie(object):
    url = "https://milkie.cc"
    name = "Milkie"
    # The API's category numbers. "all" sends none.
    supported_categories = {
        "all": "",
        "books": "5",
        "games": "4",
        "movies": "1",
        "music": "3",
        "software": "6",
        "tv": "2",
    }
    adult_category = 7

    per_page = 100
    timeout = 25
    download_path = re.compile(r"/api/v1/torrents/([\w-]+)/torrent")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("Milkie needs your API key: add it in the plugin's Settings")
        return key

    def fetch(self, url):
        request = urllib.request.Request(url, headers={**_headers, "x-milkie-auth": self.key(), "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("Milkie refused the API key. Check it in the plugin's Settings") from None
            if error.code == 429:
                raise RuntimeError("Milkie is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"Milkie answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach Milkie: {error.reason}") from None

    def address(self, what, cat):
        params = {"ps": self.per_page, "query": urllib.parse.unquote(what)}
        wanted = self.supported_categories.get(cat, "")
        if not wanted and os.environ.get("UMASH_HIDE_ADULT") == "1":
            wanted = ",".join(value for value in self.supported_categories.values() if value)
        if wanted:
            params["categories"] = wanted
        return f"{self.url}/api/v1/torrents?{urllib.parse.urlencode(params)}"

    def read_rows(self, body):
        try:
            rows = json.loads(body.decode("utf-8", "replace")).get("torrents")
        except (AttributeError, ValueError):
            rows = None
        if not isinstance(rows, list):
            raise RuntimeError("Milkie sent something other than search results")
        return rows

    def show(self, row):
        tid = str(row.get("id", ""))
        if not re.fullmatch(r"[\w-]+", tid):
            return
        if os.environ.get("UMASH_HIDE_ADULT") == "1" and row.get("category") == self.adult_category:
            return
        prettyPrinter({
            "link": f"{self.url}/api/v1/torrents/{tid}/torrent",
            "name": " ".join(str(row.get("releaseName") or "N/A").split()),
            "size": str(row.get("size", -1)),
            "seeds": row.get("seeders", -1),
            "leech": row.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": f"{self.url}/browse/{tid}",
            "pub_date": self.date(row.get("createdAt")),
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
    def save_torrent(data, info):
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)

    def search(self, what, cat="all"):
        self.key()
        # One page of the best matches, as Jackett reads: Umash couldn't check how the API pages.
        for row in self.read_rows(self.fetch(self.address(what, cat))):
            self.show(row)
        self.more(0)

    def download_torrent(self, info):
        """Adds the key here, and only for this site's own download address."""
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a Milkie download link, so Umash didn't send your key to it")
        data = self.fetch(f"{info}?{urllib.parse.urlencode({'key': self.key()})}")
        if not data.startswith(b"d"):
            raise RuntimeError("Milkie didn't send a torrent file for this result")
        self.save_torrent(data, info)
