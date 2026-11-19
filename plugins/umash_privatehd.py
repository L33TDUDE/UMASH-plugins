# VERSION: 1.0
# AUTHORS: Umash
# SETTING: username | text required | Username | Your PrivateHD username.
# SETTING: password | secret required | Password | Your PrivateHD password. It is sent only to privatehd.to, to ask for a session. | https://privatehd.to/
# SETTING: pid | secret required | PID | On your PrivateHD profile page, the PID (your personal ID). | https://privatehd.to/profile
#
# PrivateHD (privatehd.to), a private HD movie and TV tracker, through
# the same API Jackett and Prowlarr use. Umash signs in for each search, asks for up to 2 pages
# of 50 (the site wants about 6 seconds between requests), and names each result by its file
# name. Download links hold your RSS key, so results carry a placeholder instead and the key is
# looked up only when downloading. Sister sites: AvistaZ, CinemaZ and ExoticaZ.

import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from helpers import _headers
from novaprinter import prettyPrinter

KEY_MARK = "UMASH_KEY"


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry a login: only the site's own redirects are followed."""

    def __init__(self, site):
        super().__init__()
        self.site = urllib.parse.urlsplit(site)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if (target.scheme, target.netloc) != (self.site.scheme, self.site.netloc):
            raise RuntimeError("PrivateHD sent Umash to another site instead of answering, so Umash stopped")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class umash_privatehd(object):
    url = "https://privatehd.to"
    name = "PrivateHD"
    domain = "privatehd.to"
    # The site's types: 1 movies, 2 TV. "all" sends 0.
    supported_categories = {
        "all": "0",
        "movies": "1",
        "tv": "2",
    }
    adult_site = False

    per_page = 50
    pages = 2
    pause = 6.1  # The API asks for about this long between requests.
    timeout = 30
    # /rss/download/<id>/<rss key>.torrent
    rss_link = re.compile(r"^(https://[^/]+/rss/download/\d+/)([^/?#]+?)(\.torrent)?$")
    safe_link = re.compile(r"https://[^/\s]+/rss/download/\d+/UMASH_KEY(?:\.torrent)?")

    def __init__(self):
        self.opener = urllib.request.build_opener(SameSiteRedirects(self.url))

    def secrets(self):
        username = os.environ.get("UMASH_SETTING_USERNAME", "").strip()
        password = os.environ.get("UMASH_SETTING_PASSWORD", "")
        pid = os.environ.get("UMASH_SETTING_PID", "").strip()
        if not username or not password.strip() or not pid:
            raise RuntimeError(f"{self.name} needs your username, password and PID: add them in the plugin's Settings")
        return username, password, pid

    def refused(self, code, text=""):
        if code in (401, 403, 422) or "unauthorized" in text.lower():
            return f"{self.name} refused the username, password or PID. Check them in the plugin's Settings"
        if code == 429:
            return f"{self.name} is limiting requests from this connection. Try again later"
        return f"{self.name} answered with HTTP {code}"

    def fetch(self, url, data=None, token=None):
        headers = {**_headers, "Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code, error.read(2000).decode("utf-8", "replace"))) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach {self.name}: {error.reason}") from None

    def sign_in(self):
        username, password, pid = self.secrets()
        form = urllib.parse.urlencode({"username": username, "password": password, "pid": pid}).encode()
        try:
            token = json.loads(self.fetch(f"{self.url}/api/v1/jackett/auth", form).decode("utf-8", "replace")).get("token")
        except (ValueError, AttributeError):
            token = None
        if not isinstance(token, str) or not token:
            raise RuntimeError(f"{self.name} didn't give a session. Check your username, password and PID in the plugin's Settings")
        return token

    def address(self, what, cat, page):
        params = [("in", "1"), ("type", self.supported_categories.get(cat, "0")), ("limit", self.per_page),
                  ("search", " ".join(urllib.parse.unquote(what).split())), ("page", page)]
        return f"{self.url}/api/v1/jackett/torrents?{urllib.parse.urlencode(params)}"

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            found = None
        rows = found.get("data") if isinstance(found, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"{self.name} sent something other than search results")
        return rows

    def mask(self, link):
        found = self.rss_link.match(link)
        if found and found.group(1).startswith(self.url + "/"):
            return f"{found.group(1)}{KEY_MARK}{found.group(3) or ''}"
        return None

    @staticmethod
    def date(text):
        try:
            return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
        except ValueError:
            return -1

    @staticmethod
    def number(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return -1

    def show(self, row):
        link = self.mask(str(row.get("download") or ""))
        if not link:
            return  # A link Umash can't keep the key out of is left out.
        name = " ".join(str(row.get("file_name") or row.get("release_title") or "N/A").split())
        name = re.sub(r"\.torrent$", "", name, flags=re.I)
        multiplier = row.get("download_multiply")
        if multiplier == 0:
            name += " [FreeLeech]"
        elif multiplier == 0.5:
            name += " [Half Leech]"
        prettyPrinter({
            "link": link,
            "name": name,
            "size": str(self.number(row.get("file_size"))),
            "seeds": self.number(row.get("seed")),
            "leech": self.number(row.get("leech")),
            "engine_url": self.url,
            "desc_link": str(row.get("url") or self.url),
            "pub_date": self.date(row.get("created_at_iso")),
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
        if self.adult_site and os.environ.get("UMASH_HIDE_ADULT") == "1":
            self.more(0)
            return
        token = self.sign_in()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            if page > first:
                time.sleep(self.pause)
            try:
                rows = self.read(self.fetch(self.address(what, cat, page), token=token))
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

    def rss_key(self, token):
        """Reads the RSS key from the newest result's own download link."""
        rows = self.read(self.fetch(f"{self.url}/api/v1/jackett/torrents?in=1&type=0&limit=1", token=token))
        for row in rows:
            found = self.rss_link.match(str(row.get("download") or ""))
            if found and found.group(1).startswith(self.url + "/"):
                return urllib.parse.unquote(found.group(2))
        raise RuntimeError(f"{self.name} didn't show your RSS key, so Umash can't build the download link")

    def download_torrent(self, info):
        """Adds the RSS key here, and only to this site's own download address."""
        if not self.safe_link.fullmatch(info) or not info.startswith(self.url + "/"):
            raise RuntimeError(f"That isn't an {self.name} download link, so Umash didn't send your key to it")
        token = self.sign_in()
        time.sleep(self.pause)
        key = self.rss_key(token)
        time.sleep(self.pause)
        data = self.fetch(info.replace(KEY_MARK, urllib.parse.quote(key, safe="")))
        if not data.startswith(b"d"):
            raise RuntimeError(f"{self.name} didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
