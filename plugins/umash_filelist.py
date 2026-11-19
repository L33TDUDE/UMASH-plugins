# VERSION: 1.0
# AUTHORS: Umash
# SETTING: username | text required | Username | Your FileList username.
# SETTING: passkey | secret required | Passkey | Not your site password. Open your FileList profile and copy the value labelled Passkey. | https://filelist.io/my.php
#
# FileList (filelist.io), a private tracker, through its API. The community
# plugin hid every API error, so a wrong passkey looked like "no results". It
# also encoded searches twice and filtered with a parameter the API does not
# read. Result links here carry no passkey: it is added only when downloading.

import base64
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from helpers import _headers
from novaprinter import prettyPrinter


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry the login: never follow them to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"FileList answered with a redirect (HTTP {code}), so Umash stopped")


class umash_filelist(object):
    url = "https://filelist.io"
    name = "FileList"
    # The API's category numbers. "all" sends no filter.
    supported_categories = {
        "all": "",
        "anime": "24",
        "books": "16,29",
        "games": "9,10",
        "movies": "1,2,3,4,6,19,20,25,26",
        "music": "5,11",
        "software": "8,17,22",
        "tv": "15,21,23,27,31",
    }

    api_url = url + "/api.php"
    download_url = url + "/download.php"
    timeout = 20
    # The API gives dates in Romanian time, without a zone.
    site_zone = timezone(timedelta(hours=2))

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def login(self):
        username = os.environ.get("UMASH_SETTING_USERNAME", "").strip()
        passkey = os.environ.get("UMASH_SETTING_PASSKEY", "").strip()
        if not username or not passkey:
            raise RuntimeError("FileList needs your username and passkey: add them in the plugin's Settings")
        return username, passkey

    def refused(self, code, text):
        """A sentence for the user. Never includes a request's address, which can hold the passkey."""
        lower = text.lower()
        if code in (401, 403) or "passkey" in lower or "username" in lower:
            return "FileList refused the username or passkey. The passkey is not your site password: copy it from your FileList profile"
        if code == 429 or "too many" in lower:
            return "FileList is limiting requests from this connection. Try again later"
        return f"FileList answered with HTTP {code}"

    def fetch(self, url, headers=None):
        request = urllib.request.Request(url, headers={**_headers, **(headers or {})})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            text = error.read(2000).decode("utf-8", "replace")
            raise RuntimeError(self.refused(error.code, text)) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach FileList: {error.reason}") from None

    def search(self, what, cat="all"):
        username, passkey = self.login()
        params = {"action": "search-torrents", "type": "name", "query": urllib.parse.unquote(what)}
        category = self.supported_categories.get(cat, "")
        if category:
            params["category"] = category
        login = base64.b64encode(f"{username}:{passkey}".encode()).decode()
        body = self.fetch(f"{self.api_url}?{urllib.parse.urlencode(params)}", {"Authorization": "Basic " + login})
        try:
            rows = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError("FileList sent something other than search results") from None
        if isinstance(rows, dict):
            raise RuntimeError(self.refused(200, str(rows.get("error", ""))))
        for row in rows:
            self.show(row)

    def show(self, row):
        tid = row.get("id")
        if not isinstance(tid, int):
            return
        title = row.get("name") or "N/A"
        if row.get("freeleech"):
            title += " [FreeLeech]"
        if row.get("doubleup"):
            title += " [2x]"
        prettyPrinter({
            "link": f"{self.download_url}?id={tid}",
            "name": title,
            "size": str(row.get("size", -1)),
            "seeds": row.get("seeders", -1),
            "leech": row.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": f"{self.url}/details.php?id={tid}",
            "pub_date": self.date(row.get("upload_date")),
        })

    def date(self, text):
        try:
            when = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return -1
        return int(when.replace(tzinfo=self.site_zone).timestamp())

    def download_torrent(self, info):
        """Adds the passkey here, and only for this site's own download address."""
        _, passkey = self.login()
        match = re.fullmatch(re.escape(self.download_url) + r"\?id=(\d+)", info)
        if not match:
            raise RuntimeError("That isn't a FileList download link, so Umash didn't send your passkey to it")
        query = urllib.parse.urlencode({"id": match.group(1), "passkey": passkey})
        data = self.fetch(f"{self.download_url}?{query}")
        if not data.startswith(b"d"):
            raise RuntimeError(self.refused(200, data[:2000].decode("utf-8", "replace")))
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
