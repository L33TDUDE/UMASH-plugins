# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | On your Lat-Team account: My Settings, then the API Key tab. | https://lat-team.com/
#
# Lat-Team (lat-team.com), a Latin American private tracker, through its UNIT3D API, the way Jackett and Prowlarr
# search it. The site's own download links hold your RSS key, so results link to the
# torrent's API address instead, and the real link is asked for only when downloading.

import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone

from helpers import _headers
from novaprinter import prettyPrinter


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry the key: only the site's own redirects are followed."""

    def __init__(self, site):
        super().__init__()
        self.site = urllib.parse.urlsplit(site)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if "/login" in target.path:
            raise RuntimeError("Lat-Team refused the API key. Check it in the plugin's Settings")
        if (target.scheme, target.netloc) != (self.site.scheme, self.site.netloc):
            raise RuntimeError("Lat-Team sent Umash to another site instead of answering, so Umash stopped")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class umash_latteam(object):
    url = "https://lat-team.com"
    name = "Lat-Team"
    # The site's category numbers. "all" sends none.
    supported_categories = {
        "all": "",
        "anime": "5",
        "books": "18,11,29,30",
        "games": "4",
        "movies": "1",
        "music": "3,9",
        "software": "17",
        "tv": "2,20,8,16,22",
    }
    adult_categories = {"12"}

    per_page = 100
    pages = 5
    timeout = 25
    torrent_path = re.compile(r"/api/torrents/\d+")

    def __init__(self):
        self.opener = urllib.request.build_opener(SameSiteRedirects(self.url))

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("Lat-Team needs your API key: add it in the plugin's Settings")
        return key

    def refused(self, code):
        if code in (401, 403):
            return "Lat-Team refused the API key. Check it in the plugin's Settings"
        if code == 429:
            return "Lat-Team is limiting requests from this connection. Try again later"
        return f"Lat-Team answered with HTTP {code}"

    def fetch(self, url, authorized=True):
        headers = {**_headers, "Accept": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer " + self.key()
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code)) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach Lat-Team: {error.reason}") from None

    def document(self, body):
        try:
            return json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError("Lat-Team sent something other than search results") from None

    def address(self, what, cat, page):
        words = re.sub(r"\.", " ", urllib.parse.unquote(what))
        params = [("name", words), ("sortField", "seeders"), ("sortDirection", "desc"),
                  ("perPage", self.per_page), ("page", page)]
        wanted = self.supported_categories.get(cat, "")
        if not wanted and os.environ.get("UMASH_HIDE_ADULT") == "1":
            wanted = ",".join(value for value in self.supported_categories.values() if value)
        params += [("categories[]", number) for number in wanted.split(",") if number]
        return f"{self.url}/api/torrents/filter?{urllib.parse.urlencode(params)}"

    def show(self, row):
        attributes = row.get("attributes") or {}
        tid = str(row.get("id", ""))
        if not tid.isdigit() or not attributes:
            return
        if os.environ.get("UMASH_HIDE_ADULT") == "1" and str(attributes.get("category_id")) in self.adult_categories:
            return
        title = " ".join(str(attributes.get("name") or "N/A").split())
        if str(attributes.get("freeleech", "")).startswith("100") or attributes.get("featured"):
            title += " [FreeLeech]"
        prettyPrinter({
            "link": f"{self.url}/api/torrents/{tid}",
            "name": title,
            "size": str(attributes.get("size", -1)),
            "seeds": attributes.get("seeders", -1),
            "leech": attributes.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": attributes.get("details_link") or f"{self.url}/torrents/{tid}",
            "pub_date": self.date(attributes.get("created_at")),
        })

    @staticmethod
    def date(text):
        for style in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return int(datetime.strptime(str(text), style).replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
        return -1

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
        self.key()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                found = self.document(self.fetch(self.address(what, cat, page)))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            rows = found.get("data") if isinstance(found, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("Lat-Team sent something other than search results")
            for row in rows:
                self.show(row)
            full = len(rows) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        """Asks the site for the real link, and fetches it only from this site."""
        if not info.startswith(self.url + "/") or not self.torrent_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a Lat-Team link, so Umash didn't send your key to it")
        found = self.document(self.fetch(info))
        row = (found.get("data") or found) if isinstance(found, dict) else {}
        link = (row.get("attributes") or row).get("download_link") if isinstance(row, dict) else None
        if not isinstance(link, str) or not link.startswith(self.url + "/"):
            raise RuntimeError("Lat-Team didn't give a download link for this result")
        data = self.fetch(link, authorized=False)
        if not data.startswith(b"d"):
            raise RuntimeError("Lat-Team didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
