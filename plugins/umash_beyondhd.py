# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | On your Beyond-HD profile, under My Security. | https://beyond-hd.me/
# SETTING: rsskey | secret required | RSS key | On your Beyond-HD profile, under My Security. | https://beyond-hd.me/
#
# Beyond-HD (beyond-hd.me), a private tracker for movies and TV, through its API, the
# way Jackett and Prowlarr search it. Result links carry no key: it is added only when
# downloading. One page a search, as the API allows few requests: Load More gets the next.

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

KEY_MARK = "UMASH_KEY"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"Beyond-HD answered with a redirect (HTTP {code}), so Umash stopped")


class umash_beyondhd(object):
    url = "https://beyond-hd.me"
    name = "Beyond-HD"
    supported_categories = {"all": "", "movies": "1", "tv": "2"}

    timeout = 25

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def keys(self):
        api = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        rss = os.environ.get("UMASH_SETTING_RSSKEY", "").strip()
        if not api or not rss:
            raise RuntimeError("Beyond-HD needs your API key and RSS key: add them in the plugin's Settings")
        return api, rss

    def fetch(self, url, data=None):
        headers = {**_headers, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("Beyond-HD refused the API key. Check it in the plugin's Settings") from None
            if error.code == 429:
                raise RuntimeError("Beyond-HD is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"Beyond-HD answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach Beyond-HD: {error.reason}") from None

    def request_body(self, what, cat, page, rss):
        body = {"action": "search", "rsskey": rss, "search": urllib.parse.unquote(what), "page": page}
        wanted = self.supported_categories.get(cat, "")
        if wanted:
            body["categories"] = [int(wanted)]
        return json.dumps(body).encode()

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            found = None
        if not isinstance(found, dict):
            raise RuntimeError("Beyond-HD sent something other than search results")
        if found.get("status_code") == 0 or found.get("success") is False:
            message = str(found.get("status_message", ""))
            if "key" in message.lower():
                raise RuntimeError("Beyond-HD refused the API key or RSS key. Check them in the plugin's Settings")
            raise RuntimeError("Beyond-HD couldn't run this search")
        return found

    def show(self, row, rss):
        link = row.get("download_url")
        if not isinstance(link, str) or not link.startswith(self.url + "/"):
            return
        title = " ".join(str(row.get("name") or "N/A").split())
        if row.get("freeleech") or row.get("limited"):
            title += " [FreeLeech]"
        prettyPrinter({
            "link": link.replace(rss, KEY_MARK),
            "name": title,
            "size": str(row.get("size", -1)),
            "seeds": row.get("seeders", -1),
            "leech": row.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": row.get("url") or self.url,
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
        api, rss = self.keys()
        page = self.setting("UMASH_START_PAGE", 1)
        found = self.read(self.fetch(f"{self.url}/api/torrents/{api}", self.request_body(what, cat, page, rss)))
        rows = found.get("results") or []
        for row in rows:
            self.show(row, rss)
        self.more(page + 1 if rows and page < int(found.get("total_pages") or 1) else 0)

    def download_torrent(self, info):
        """Adds the key here, and only for this site's own addresses."""
        _, rss = self.keys()
        if not info.startswith(self.url + "/") or KEY_MARK not in info:
            raise RuntimeError("That isn't a Beyond-HD download link, so Umash didn't send your key to it")
        data = self.fetch(info.replace(KEY_MARK, urllib.parse.quote(rss, safe="")))
        if not data.startswith(b"d"):
            raise RuntimeError("Beyond-HD didn't send a torrent file for this result")
        self.save_torrent(data, info)
