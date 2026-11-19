# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API token | Create one on your Orpheus profile settings, under Access Settings (API tokens), with the Torrents permission. | https://orpheus.network/user.php?action=edit
#
# Orpheus (orpheus.network), a private music tracker, through
# its API, the way Jackett and Prowlarr search it. The key goes in a request header,
# never in a link. Downloads use no freeleech tokens.

import html
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


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Orpheus refused the API key. Check it in the plugin's Settings")


class umash_orpheus(object):
    url = "https://orpheus.network"
    name = "Orpheus"
    # The site's category numbers. "all" sends none.
    supported_categories = {
        "all": "",
        "books": "3,4,7",
        "music": "1",
        "software": "2",
    }

    pages = 3
    pause = 1.1  # The API allows ten requests in ten seconds.
    timeout = 25
    download_path = re.compile(r"/ajax\.php\?action=download&id=\d+")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("Orpheus needs your API key: add it in the plugin's Settings")
        return key

    def fetch(self, url):
        request = urllib.request.Request(url, headers={**_headers, "Authorization": "token " + self.key(), "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("Orpheus refused the API key. Check it in the plugin's Settings") from None
            if error.code == 429:
                raise RuntimeError("Orpheus is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"Orpheus answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach Orpheus: {error.reason}") from None

    def address(self, what, cat, page):
        params = [("action", "browse"), ("searchstr", urllib.parse.unquote(what)), ("order_by", "seeders"),
                  ("order_way", "desc"), ("page", page)]
        wanted = self.supported_categories.get(cat, "")
        params += [(f"filter_cat[{number}]", "1") for number in wanted.split(",") if number]
        return f"{self.url}/ajax.php?{urllib.parse.urlencode(params)}"

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            found = None
        if isinstance(found, dict) and found.get("status") == "failure" and re.search(r"token|auth|key|permission", str(found.get("error", "")), re.I):
            raise RuntimeError("Orpheus refused the API token. Check it in the plugin's Settings")
        if not isinstance(found, dict) or found.get("status") != "success" or not isinstance(found.get("response"), dict):
            raise RuntimeError("Orpheus sent something other than search results")
        return found["response"]

    @staticmethod
    def album(group, torrent):
        """Artist - Album (Year) [Type] [Edition] [Format Quality / Media]"""
        title = f"{group.get('artist', '')} - {group.get('groupName', '')} ({group.get('groupYear', '')})"
        if group.get("releaseType") and group["releaseType"] != "Unknown":
            title += f" [{group['releaseType']}]"
        if torrent.get("remasterTitle"):
            title += f" [{torrent['remasterTitle']} {torrent.get('remasterYear') or ''}".rstrip() + "]"
        flags = [f"{torrent.get('format', '')} {torrent.get('encoding', '')}".strip(), str(torrent.get("media", ""))]
        if torrent.get("hasLog"):
            flags.append(f"Log ({torrent.get('logScore', 0)}%)")
        if torrent.get("hasCue"):
            flags.append("Cue")
        return f"{title} [{' / '.join(flag for flag in flags if flag)}]"

    def show(self, group, torrent, title):
        tid = torrent.get("torrentId")
        if not isinstance(tid, int):
            return
        name = " ".join(html.unescape(title).split())
        if torrent.get("isFreeleech") or torrent.get("isNeutralLeech") or torrent.get("isFreeload") or torrent.get("isPersonalFreeleech"):
            name += " [FreeLeech]"
        prettyPrinter({
            "link": f"{self.url}/ajax.php?action=download&id={tid}",
            "name": name,
            "size": str(torrent.get("size", -1)),
            "seeds": torrent.get("seeders", -1),
            "leech": torrent.get("leechers", -1),
            "engine_url": self.url,
            "desc_link": f"{self.url}/torrents.php?id={group.get('groupId', '')}&torrentid={tid}",
            "pub_date": self.date(torrent.get("time") or group.get("groupTime")),
        })

    @staticmethod
    def date(value):
        if str(value).isdigit():
            return int(value)
        try:
            return int(datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
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

    @staticmethod
    def save_torrent(data, info):
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)

    def search(self, what, cat="all"):
        self.key()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            if page > first:
                time.sleep(self.pause)
            try:
                found = self.read(self.fetch(self.address(what, cat, page)))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for group in found.get("results") or []:
                torrents = group.get("torrents")
                if torrents:
                    for torrent in torrents:
                        self.show(group, torrent, self.album(group, torrent))
                else:  # Anything but music has one torrent to a group.
                    self.show(group, group, str(group.get("groupName", "N/A")))
            has_more = page < int(found.get("pages") or 1)
            self.more(page + 1 if has_more else 0)
            if not has_more:
                return

    def download_torrent(self, info):
        """Sends the key only to this site's own download address."""
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a Orpheus download link, so Umash didn't send your key to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            raise RuntimeError("Orpheus didn't send a torrent file for this result")
        self.save_torrent(data, info)
