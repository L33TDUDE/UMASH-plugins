# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | On your BroadcasTheNet profile, under Security: the API Key. | https://broadcasthe.net/user.php?action=edit
#
# BroadcasTheNet (broadcasthe.net), a private TV tracker, through its JSON-RPC API, the way
# Jackett and Prowlarr search it. Newest first, as the API returns them, up to 3 pages of
# 100 (the API allows 150 calls an hour). Download links hold your key, so results link to
# the torrent's number instead, and the real link is asked for only when downloading.

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


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"BroadcasTheNet answered with a redirect (HTTP {code}), so Umash stopped")


class umash_broadcasthenet(object):
    url = "https://broadcasthe.net"
    api = "https://api.broadcasthe.net/"
    domain = "broadcasthe.net"
    name = "BroadcasTheNet"
    # TV only: the site has no other kind of content.
    supported_categories = {
        "all": "",
        "tv": "",
    }

    per_page = 100
    pages = 3
    timeout = 25
    result_link = re.compile(r"https://api\.broadcasthe\.net/torrent/\d+")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("BroadcasTheNet needs your API key: add it in the plugin's Settings")
        return key

    def refused(self, code):
        if code in (401, 403):
            return "BroadcasTheNet refused the API key. Check it in the plugin's Settings"
        if code == 429:
            return "BroadcasTheNet is limiting requests from this connection. Try again later"
        return f"BroadcasTheNet answered with HTTP {code}"

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
            raise RuntimeError(f"Couldn't reach BroadcasTheNet: {error.reason}") from None

    def call(self, query, results, offset):
        body = json.dumps({"jsonrpc": "2.0", "id": "umash", "method": "getTorrents",
                           "params": [self.key(), query, results, offset]}).encode()
        try:
            found = json.loads(self.fetch(self.api, body).decode("utf-8", "replace"))
        except ValueError:
            found = None
        if not isinstance(found, dict):
            raise RuntimeError("BroadcasTheNet sent something other than search results")
        error = found.get("error")
        if error:
            text = " ".join(str(error.get("message", "") if isinstance(error, dict) else error).split())[:200]
            if "call limit" in text.lower() or "limit" in text.lower():
                raise RuntimeError("BroadcasTheNet's hourly call limit was reached. Try again later")
            if "invalid" in text.lower() or "key" in text.lower() or "auth" in text.lower():
                raise RuntimeError(self.refused(401))
            raise RuntimeError(f"BroadcasTheNet said: {text}" if text else "BroadcasTheNet could not run that search")
        result = found.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("BroadcasTheNet sent something other than search results")
        torrents = result.get("torrents")
        # An empty answer is a list, not an object.
        return [row for row in (torrents.values() if isinstance(torrents, dict) else []) if isinstance(row, dict)]

    @staticmethod
    def title(row):
        name = str(row.get("ReleaseName") or row.get("GroupName") or "N/A").replace("\\", "")
        if str(row.get("Container", "")).upper() in ("M2TS", "ISO"):
            name = re.sub(r"\bH\.?265\b", "HEVC", name)
            name = re.sub(r"\bH\.?264\b", "AVC", name)
        return " ".join(name.split())

    @staticmethod
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def show(self, row):
        tid = str(row.get("TorrentID", ""))
        if not tid.isdigit():
            return
        # Downloads on BTN are freeleech (no download counted), as Prowlarr marks them.
        prettyPrinter({
            "link": f"{self.api}torrent/{tid}",
            "name": self.title(row),
            "size": str(self.number(row.get("Size"))),
            "seeds": self.number(row.get("Seeders")),
            "leech": self.number(row.get("Leechers")),
            "engine_url": self.url,
            "desc_link": f"{self.url}/torrents.php?id={row.get('GroupID', '')}&torrentid={tid}",
            "pub_date": self.number(row.get("Time")),
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
        self.key()
        words = " ".join(urllib.parse.unquote(what).split())
        query = {"search": words.replace(" ", "%")} if words else {}
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                rows = self.call(query, self.per_page, (page - 1) * self.per_page)
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for row in sorted(rows, key=lambda item: -self.number(item.get("Time"))):
                self.show(row)
            full = len(rows) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        """Asks the API for the real link, and fetches it only from this site."""
        if not self.result_link.fullmatch(info):
            raise RuntimeError("That isn't a BroadcasTheNet link, so Umash didn't send your key to it")
        rows = self.call({"id": info.rsplit("/", 1)[1]}, 1, 0)
        link = rows[0].get("DownloadURL") if rows else None
        parts = urllib.parse.urlsplit(link) if isinstance(link, str) else None
        host = (parts.hostname or "").lower() if parts else ""
        if not parts or parts.scheme != "https" or not (host == self.domain or host.endswith("." + self.domain)):
            raise RuntimeError("BroadcasTheNet didn't give a download link for this result")
        data = self.fetch(link)
        if not data.startswith(b"d"):
            raise RuntimeError("BroadcasTheNet didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
