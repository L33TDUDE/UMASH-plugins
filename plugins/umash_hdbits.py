# VERSION: 1.0
# AUTHORS: Umash
# SETTING: username | text required | Username | Your HDBits username.
# SETTING: passkey | secret required | Passkey | Not your password. On your HDBits profile page, copy the value labelled Passkey. | https://hdbits.org/my.php
#
# HDBits (hdbits.org), a private HD movie and TV tracker, through its API, the way Jackett
# and Prowlarr search it. Results are newest-first as the site returns them, up to 3 pages
# of 100. The passkey is sent to the API in the request body and is never part of a result's
# link: it is added only when downloading.

import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter

KEY_MARK = "UMASH_KEY"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry the passkey: never follow them to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"HDBits answered with a redirect (HTTP {code}), so Umash stopped")


class umash_hdbits(object):
    url = "https://hdbits.org"
    name = "HDBits"
    # The site's category numbers: 1 movie, 2 TV, 3 documentary, 4 music, 5 sport,
    # 6 audio track, 7 XXX, 8 misc. "all" sends none.
    supported_categories = {
        "all": "",
        "movies": "1",
        "music": "4,6",
        "tv": "2,3,5",
    }
    adult_categories = {"7"}

    per_page = 100
    pages = 3
    timeout = 25
    download_path = re.compile(r"/download\.php\?id=\d+&passkey=" + KEY_MARK)
    # status codes the API answers with in its body: 4 and 5 are about the login.
    refused_codes = {4, 5}

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def login(self):
        username = os.environ.get("UMASH_SETTING_USERNAME", "").strip()
        passkey = os.environ.get("UMASH_SETTING_PASSKEY", "").strip()
        if not username or not passkey:
            raise RuntimeError("HDBits needs your username and passkey: add them in the plugin's Settings")
        return username, passkey

    def refused(self, code):
        if code in (401, 403):
            return "HDBits refused the username or passkey. Check them in the plugin's Settings"
        if code == 429:
            return "HDBits is limiting requests from this connection. Try again later"
        return f"HDBits answered with HTTP {code}"

    def fetch(self, url, body=None):
        headers = {**_headers, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code)) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach HDBits: {error.reason}") from None

    def query(self, what, cat, page):
        username, passkey = self.login()
        body = {"username": username, "passkey": passkey, "limit": self.per_page, "page": page - 1}
        words = " ".join(urllib.parse.unquote(what).split())
        if words:
            body["search"] = re.sub(r"[\W_]+", " ", words).strip()
        wanted = self.supported_categories.get(cat, "")
        if not wanted and os.environ.get("UMASH_HIDE_ADULT") == "1":
            wanted = ",".join(str(number) for number in (1, 2, 3, 4, 5, 6, 8))
        if wanted:
            body["category"] = [int(number) for number in wanted.split(",")]
        return json.dumps(body).encode()

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            found = None
        if not isinstance(found, dict) or not isinstance(found.get("status"), int):
            raise RuntimeError("HDBits sent something other than search results")
        if found["status"] in self.refused_codes:
            raise RuntimeError(self.refused(401))
        if found["status"] != 0:
            message = " ".join(str(found.get("message", "")).split())[:200]
            raise RuntimeError(f"HDBits said: {message}" if message else "HDBits could not run that search")
        rows = found.get("data")
        if not isinstance(rows, list):
            raise RuntimeError("HDBits sent something other than search results")
        return rows

    @staticmethod
    def title(row):
        """The scene-style file name, as Jackett and Prowlarr use, except for XXX and full discs."""
        name = str(row.get("name") or "N/A")
        filename = str(row.get("filename") or "")
        if row.get("type_category") != 7 and row.get("type_medium") != 1 and filename:
            name = re.sub(r"\.torrent$", "", filename, flags=re.I)
        return " ".join(name.split())

    def show(self, row):
        tid = str(row.get("id", ""))
        if not tid.isdigit():
            return
        if os.environ.get("UMASH_HIDE_ADULT") == "1" and str(row.get("type_category")) in self.adult_categories:
            return
        name = self.title(row)
        if row.get("freeleech") == "yes":
            name += " [FreeLeech]"
        elif row.get("type_category") == 7:
            name += " [Neutral]"
        prettyPrinter({
            "link": f"{self.url}/download.php?id={tid}&passkey={KEY_MARK}",
            "name": name,
            "size": str(row.get("size", -1)),
            "seeds": row.get("seeders", -1),
            "leech": row.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": f"{self.url}/details.php?id={tid}",
            "pub_date": row.get("utadded") if isinstance(row.get("utadded"), int) else -1,
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
        self.login()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                rows = self.read(self.fetch(f"{self.url}/api/torrents", self.query(what, cat, page)))
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
        """Adds the passkey here, and only to this site's own download address."""
        _, passkey = self.login()
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't an HDBits download link, so Umash didn't send your passkey to it")
        data = self.fetch(info.replace(KEY_MARK, urllib.parse.quote(passkey, safe="")))
        if not data.startswith(b"d"):
            raise RuntimeError("HDBits didn't send a torrent file for this result. Check your passkey in the plugin's Settings")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
