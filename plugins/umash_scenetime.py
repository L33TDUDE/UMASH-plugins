# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | On the SceneTime RSS page, scroll to the Torznab API section and copy the API Key. | https://www.scenetime.com/rss.php
#
# SceneTime (scenetime.com), a private movie, TV and general tracker, through its Torznab-style RSS API, the
# way Jackett and Prowlarr search it. Up to 100 results a search (the API has no further pages). Result links carry no key: it is added only
# when downloading. 

import email.utils
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

from helpers import _headers
from novaprinter import prettyPrinter

TORZNAB = "{http://torznab.com/schemas/2015/feed}attr"
KEY_MARK = "UMASH_KEY"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry the key: never follow them to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"SceneTime answered with a redirect (HTTP {code}), so Umash stopped")


class umash_scenetime(object):
    url = "https://www.scenetime.com"
    name = "SceneTime"
    # The API's category numbers. "all" sends none.
    supported_categories = {
        "all": "",
        "anime": "100001",
        "books": "100007,100065",
        "games": "100006,100015,100055,100012,100051,100048",
        "movies": "100047,100064,100082,100059,100057,100016",
        "music": "100004,100116",
        "software": "100053,100052,100024",
        "tv": "100001,100009,100043,100077,100002",
    }
    adult_categories = {"100010", "6000"}

    api_url = "https://www.scenetime.com/rss.php"
    # Downloads may come from this domain or its subdomains, nowhere else.
    domain = "scenetime.com"
    per_page = 100
    pages = 1
    timeout = 25

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("SceneTime needs your API key: add it in the plugin's Settings")
        return key

    def refused(self, code, text):
        """A sentence for the user. Never includes a request's address, which holds the key."""
        lower = text.lower()
        if code in (401, 403) or "api key" in lower or "apikey" in lower:
            return "SceneTime refused the API key. Check it in the plugin's Settings"
        if code == 429 or "too many" in lower or "limit" in lower:
            return "SceneTime is limiting requests from this connection. Try again later"
        return f"SceneTime answered with HTTP {code}"

    def fetch(self, url):
        request = urllib.request.Request(url, headers=dict(_headers))
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code, error.read(2000).decode("utf-8", "replace"))) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach SceneTime: {error.reason}") from None

    def categories(self, cat):
        wanted = self.supported_categories.get(cat, "")
        if not wanted and os.environ.get("UMASH_HIDE_ADULT") == "1":
            return ",".join(value for value in self.supported_categories.values() if value)
        return wanted

    def address(self, what, cat, page):
        params = {"t": "search", "q": urllib.parse.unquote(what), "limit": self.per_page, "apikey": self.key()}
        wanted = self.categories(cat)
        if wanted:
            params["cat"] = wanted
        return f"{self.api_url}?{urllib.parse.urlencode(params)}"

    def read_items(self, body):
        if b"<!DOCTYPE" in body[:2000].upper():
            raise RuntimeError("SceneTime sent a web page instead of search results")
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            raise RuntimeError("SceneTime sent something other than search results") from None
        if root.tag == "error":
            # Torznab's codes 100 to 102 are about the key: wrong, suspended, or not allowed.
            if root.get("code") in ("100", "101", "102"):
                raise RuntimeError(self.refused(401, ""))
            message = " ".join(root.get("description", "").split())[:200]
            raise RuntimeError(f"SceneTime said: {message}" if message else self.refused(200, ""))
        return root.findall("./channel/item")

    def show(self, item, key):
        attrs = {}
        for attr in item.findall(TORZNAB):
            attrs.setdefault(attr.get("name", ""), attr.get("value", ""))
        categories = {attr.get("value") for attr in item.findall(TORZNAB) if attr.get("name") == "category"}
        if os.environ.get("UMASH_HIDE_ADULT") == "1" and categories & self.adult_categories:
            return
        enclosure = item.find("enclosure")
        link = enclosure.get("url", "") if enclosure is not None else item.findtext("link", "")
        if not link:
            return
        title = " ".join((item.findtext("title") or "N/A").split())
        if attrs.get("downloadvolumefactor") in ("0", "0.0"):
            title += " [FreeLeech]"
        prettyPrinter({
            "link": link.replace(key, KEY_MARK),
            "name": title,
            "size": item.findtext("size") or attrs.get("size") or "-1",
            "seeds": self.number(attrs.get("seeders")),
            "leech": self.number(attrs.get("leechers", attrs.get("peers"))),
            "engine_url": self.url,
            "desc_link": (item.findtext("comments") or item.findtext("guid") or self.url).replace(key, KEY_MARK),
            "pub_date": self.date(item.findtext("pubDate")),
        })

    @staticmethod
    def number(text):
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def date(text):
        try:
            return int(email.utils.parsedate_to_datetime(text).timestamp())
        except (TypeError, ValueError):
            return -1

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def search(self, what, cat="all"):
        key = self.key()
        # The API has one page of up to 100 results, so there is nothing more to load.
        for item in self.read_items(self.fetch(self.address(what, cat, 1))):
            self.show(item, key)
        self.more(0)

    def download_torrent(self, info):
        """Adds the key here, and only for this site's own addresses."""
        key = self.key()
        host = urllib.parse.urlsplit(info).hostname or ""
        if not info.startswith("https://") or not (host == self.domain or host.endswith("." + self.domain)):
            raise RuntimeError("That isn't a SceneTime download link, so Umash didn't send your key to it")
        data = self.fetch(info.replace(KEY_MARK, urllib.parse.quote(key, safe="")))
        if not data.startswith(b"d"):
            raise RuntimeError(self.refused(200, data[:2000].decode("utf-8", "replace")))
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
