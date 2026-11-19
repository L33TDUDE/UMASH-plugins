# VERSION: 1.0
# AUTHORS: Umash
# LOGIN: https://www.torrentday.com/login.php | uid, pass
#
# TorrentDay (torrentday.com), a private tracker, read from the site's own search
# list with the login you get by signing in from Umash (the sign-in page has a
# CAPTCHA, which you answer in the window). Exact sizes, upload times, seeds and
# leechers. The login is sent only to this site, and result links carry none of it.
# The search follows Jackett's and Prowlarr's TorrentDay indexers: one list per
# search, as the site sends it.

import gzip
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from novaprinter import prettyPrinter

SIGNED_OUT = 4  # Umash's "this plugin needs signing in again".


def signed_out():
    sys.exit(SIGNED_OUT)


class Redirected(RuntimeError):
    """The site answered with a redirect that isn't its sign-in page."""

    def __init__(self, target):
        super().__init__("TorrentDay sent Umash to another page instead of answering, so the site may have changed")
        self.target = target


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """The site sends anyone not signed in to its sign-in page. Nothing is followed,
    so the login can't reach another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "login" in newurl.lower():
            signed_out()
        raise Redirected(newurl)


class umash_torrentday(object):
    url = "https://www.torrentday.com"
    name = "TorrentDay"
    # The site's category numbers, from Jackett's TorrentDay indexer.
    supported_categories = {
        "all": "",
        "anime": "29",
        "books": "42;20;102",
        "games": "10;4;18;8;9",
        "movies": "25;96;11;5;103;3;21;22;13;44;48;1",
        "music": "17;27;23;41;16;45",
        "software": "47;43;28;12",
        "tv": "24;104;32;31;33;46;82;14;26;7;34;2;30;95",
    }
    adult_categories = "19;6;15"

    timeout = 20
    download_path = re.compile(r"/download\.php/(\d+)/\1\.torrent")
    changed = "TorrentDay's search list has changed, so Umash can't read it"

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def headers(self):
        cookie = os.environ.get("UMASH_LOGIN_COOKIE", "").strip()
        if not cookie:
            signed_out()
        headers = {"Cookie": cookie, "Accept": "application/json, */*", "Accept-Encoding": "gzip"}
        agent = os.environ.get("UMASH_LOGIN_USER_AGENT", "")
        if agent:
            headers["User-Agent"] = agent
        return headers

    def fetch(self, url):
        """Errors never include the login."""
        request = urllib.request.Request(url, headers=self.headers())
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            if error.headers.get("cf-mitigated") == "challenge":
                signed_out()
            if error.code in (401, 403):
                raise RuntimeError(f"TorrentDay refused the request (HTTP {error.code}). If this keeps happening, try signing in again") from None
            if error.code == 429:
                raise RuntimeError("TorrentDay is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"TorrentDay answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach TorrentDay: {error.reason}") from None
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data

    def address(self, what, cat):
        wanted = self.supported_categories.get(cat, "")
        if not wanted:
            # Everything, as Jackett asks: each category by number, XXX only when adult content is on.
            wanted = ";".join(value for value in self.supported_categories.values() if value)
            if os.environ.get("UMASH_HIDE_ADULT") != "1":
                wanted += ";" + self.adult_categories
        words = " ".join(urllib.parse.unquote(what).split())
        return f"{self.url}/t.json?{wanted};q=" + urllib.parse.quote(words, safe="")

    def read_rows(self, data):
        try:
            found = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            text = data[:20000].decode("utf-8", "replace").lower()
            # A sign-in page that came back without a redirect.
            if "do-login.php" in text or 'name="password"' in text:
                signed_out()
            raise RuntimeError(self.changed) from None
        if not isinstance(found, list):
            raise RuntimeError(self.changed)
        rows = []
        for item in found:
            if not isinstance(item, dict):
                raise RuntimeError(self.changed)
            tid = self.number(item.get("t"))
            name = " ".join(str(item.get("name") or "").split())
            if tid < 0 or not name:
                raise RuntimeError(self.changed)
            if self.multiplier(item) == 0:
                name += " [FreeLeech]"
            rows.append({
                "id": tid,
                "adult": str(item.get("c", "")) in self.adult_categories.split(";"),
                "link": f"{self.url}/download.php/{tid}/{tid}.torrent",
                "name": name,
                "size": max(self.number(item.get("size")), -1),  # Bytes.
                "seeds": self.number(item.get("seeders")),
                "leech": self.number(item.get("leechers")),
                "engine_url": self.url,
                "desc_link": f"{self.url}/details.php?id={tid}",
                "pub_date": self.number(item.get("ctime")),
            })
        return rows

    @staticmethod
    def number(value):
        """A whole number from the list, or -1."""
        if isinstance(value, bool):
            return -1
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value or "").strip()
        return int(text) if text.isdigit() else -1

    @staticmethod
    def multiplier(item):
        try:
            return float(item.get("download-multiplier", 1))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def more(page):
        """The site sends one list per search, so there's never a next page."""
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def search(self, what, cat="all"):
        self.headers()
        hiding = os.environ.get("UMASH_HIDE_ADULT") == "1"
        seen = set()
        for row in self.read_rows(self.fetch(self.address(what, cat))):
            if row["id"] in seen or (hiding and row["adult"]):
                continue
            seen.add(row["id"])
            prettyPrinter({key: value for key, value in row.items() if key not in ("id", "adult")})
        self.more(0)

    def download_torrent(self, info):
        """Sends the login only to this site's own download address."""
        self.headers()
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a TorrentDay download link, so Umash didn't send your login to it")
        try:
            data = self.fetch(info)
        except Redirected as moved:
            # Signed out, a download goes to the home page. One small search tells
            # that apart from a torrent the site no longer has.
            if urllib.parse.urlsplit(urllib.parse.urljoin(info, moved.target)).path not in ("", "/"):
                raise
            self.read_rows(self.fetch(f"{self.url}/t.json?{self.supported_categories['anime']};q=umash"))
            raise RuntimeError("TorrentDay didn't send a torrent file for this result") from None
        if not data.startswith(b"d"):
            text = data[:20000].decode("utf-8", "replace").lower()
            if "do-login.php" in text or 'name="password"' in text:
                signed_out()
            raise RuntimeError("TorrentDay didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
