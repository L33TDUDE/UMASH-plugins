# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | Find or generate it on your C411 Integrations page. | https://c411.org/user/integrations
#
# C411 (c411.org), a French private tracker, through its Torznab API, the way Jackett and Prowlarr
# search it. Result links carry no key: it is added only when downloading.

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
        raise RuntimeError(f"C411 answered with a redirect (HTTP {code}), so Umash stopped")


class umash_c411(object):
    url = "https://c411.org"
    name = "C411"
    # The API's category numbers. "all" sends none.
    supported_categories = {
        "all": "",
        "anime": "5070",
        "books": "3030,7000,7010,7020,7030",
        "games": "1000,1030,1040,1080,1090",
        "movies": "2000,2010,2030,2050,2060,2070,2080,2090",
        "music": "3000,3010,3050",
        "software": "4000,4030,4040,4050,4060,4070",
        "tv": "5000,5060,5080",
    }
    adult_categories = {"6000", "6010", "6050", "6060", "6070", "6080"}

    api_url = "https://c411.org/api/torznab"
    # Downloads may come from this domain or its subdomains, nowhere else.
    domain = "c411.org"
    per_page = 100
    pages = 5
    timeout = 25

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("C411 needs your API key: add it in the plugin's Settings")
        return key

    def refused(self, code, text):
        """A sentence for the user. Never includes a request's address, which holds the key."""
        lower = text.lower()
        if code in (401, 403) or "api key" in lower or "apikey" in lower:
            return "C411 refused the API key. Check it in the plugin's Settings"
        if code == 429 or "too many" in lower or "limit" in lower:
            return "C411 is limiting requests from this connection. Try again later"
        return f"C411 answered with HTTP {code}"

    def fetch(self, url):
        request = urllib.request.Request(url, headers=dict(_headers))
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code, error.read(2000).decode("utf-8", "replace"))) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach C411: {error.reason}") from None

    def categories(self, cat):
        wanted = self.supported_categories.get(cat, "")
        if not wanted and os.environ.get("UMASH_HIDE_ADULT") == "1":
            return ",".join(value for value in self.supported_categories.values() if value)
        return wanted

    def address(self, what, cat, page):
        params = {"t": "search", "q": urllib.parse.unquote(what), "limit": self.per_page,
                  "offset": (page - 1) * self.per_page, "apikey": self.key()}
        wanted = self.categories(cat)
        if wanted:
            params["cat"] = wanted
        return f"{self.api_url}?{urllib.parse.urlencode(params)}"

    def read_items(self, body):
        if b"<!DOCTYPE" in body[:2000].upper():
            raise RuntimeError("C411 sent a web page instead of search results")
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            raise RuntimeError("C411 sent something other than search results") from None
        if root.tag == "error":
            # Torznab's codes 100 to 102 are about the key: wrong, suspended, or not allowed.
            if root.get("code") in ("100", "101", "102"):
                raise RuntimeError(self.refused(401, ""))
            message = " ".join(root.get("description", "").split())[:200]
            raise RuntimeError(f"C411 said: {message}" if message else self.refused(200, ""))
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

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    def search(self, what, cat="all"):
        key = self.key()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                items = self.read_items(self.fetch(self.address(what, cat, page)))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for item in items:
                self.show(item, key)
            full = len(items) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        """Adds the key here, and only for this site's own addresses."""
        key = self.key()
        host = urllib.parse.urlsplit(info).hostname or ""
        if not info.startswith("https://") or not (host == self.domain or host.endswith("." + self.domain)):
            raise RuntimeError("That isn't a C411 download link, so Umash didn't send your key to it")
        data = self.fetch(info.replace(KEY_MARK, urllib.parse.quote(key, safe="")))
        if not data.startswith(b"d"):
            raise RuntimeError(self.refused(200, data[:2000].decode("utf-8", "replace")))
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
