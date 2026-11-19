# VERSION: 1.0
# AUTHORS: Umash
# SETTING: apikey | secret required | API key | Create one on your GazelleGames settings page, with the User and Torrents permissions. | https://gazellegames.net/user.php?action=edit
#
# GazelleGames (gazellegames.net), a private games tracker, through its API, the way
# Jackett and Prowlarr search it. Result links carry no passkey: the site is asked for
# it only when downloading, and it is sent only there.

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
        raise RuntimeError(f"GazelleGames answered with a redirect (HTTP {code}), so Umash stopped")


class umash_gazellegames(object):
    url = "https://gazellegames.net"
    name = "GazelleGames"
    # Everything on this site is games or close to it.
    supported_categories = {"all": "", "games": ""}

    pages = 3
    pause = 2  # The API allows few requests a minute.
    timeout = 25
    download_path = re.compile(r"/torrents\.php\?action=download&id=(\d+)")
    has_year = re.compile(r"\((19|20)\d\d\)")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def key(self):
        key = os.environ.get("UMASH_SETTING_APIKEY", "").strip()
        if not key:
            raise RuntimeError("GazelleGames needs your API key: add it in the plugin's Settings")
        return key

    def fetch(self, url, headers):
        request = urllib.request.Request(url, headers={**_headers, **headers})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("GazelleGames refused the API key. Check it and its permissions in the plugin's Settings") from None
            if error.code == 429:
                raise RuntimeError("GazelleGames is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"GazelleGames answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach GazelleGames: {error.reason}") from None

    def api(self, params):
        body = self.fetch(f"{self.url}/api.php?{urllib.parse.urlencode(params)}", {"X-API-Key": self.key(), "Accept": "application/json"})
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            found = None
        if not isinstance(found, dict) or found.get("status") != "success":
            raise RuntimeError("GazelleGames sent something other than search results")
        return found.get("response")

    def show(self, gid, group, tid, torrent):
        if str(torrent.get("TorrentType", "")).upper() != "TORRENT" or not str(tid).isdigit():
            return
        title = html.unescape(str(torrent.get("ReleaseTitle") or group.get("Name") or "N/A"))
        if group.get("Year") and not self.has_year.search(title):
            title += f" ({group['Year']})"
        flags = [f"{torrent.get('Format') or ''} {torrent.get('Encoding') or ''}".strip()]
        flags += [artist.get("Name", "") for artist in group.get("Artists") or []]
        flags += [torrent.get("Language") or "", torrent.get("Region") or ""]
        flags = [flag for flag in flags if flag]
        if flags:
            title += f" [{' / '.join(flags)}]"
        if str(torrent.get("FreeTorrent")) in ("1", "2", "3", "FreeLeech", "Neutral", "Either") or torrent.get("PersonalFL"):
            title += " [FreeLeech]"
        prettyPrinter({
            "link": f"{self.url}/torrents.php?action=download&id={tid}",
            "name": " ".join(title.split()),
            "size": str(torrent.get("Size", -1)),
            "seeds": torrent.get("Seeders", -1),
            "leech": torrent.get("Leechers", -1),
            "engine_url": self.url,
            "desc_link": f"{self.url}/torrents.php?id={gid}&torrentid={tid}",
            "pub_date": self.date(torrent.get("Time")),
        })

    @staticmethod
    def date(text):
        try:
            return int(datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
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
            params = {"request": "search", "search_type": "torrents", "empty_groups": "filled", "order_by": "time",
                      "order_way": "desc", "searchstr": urllib.parse.unquote(what).replace(".", " "), "page": page}
            try:
                found = self.api(params)
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            groups = found if isinstance(found, dict) else {}  # An empty search is an empty list.
            for gid, group in groups.items():
                torrents = group.get("Torrents")
                if isinstance(torrents, dict) and str(gid).isdigit():
                    for tid, torrent in torrents.items():
                        self.show(gid, group, tid, torrent)
            self.more(page + 1 if groups else 0)
            if not groups:
                return

    def download_torrent(self, info):
        """Adds the passkey here, and only for this site's own download address."""
        match = self.download_path.fullmatch(info[len(self.url):]) if info.startswith(self.url + "/") else None
        if not match:
            raise RuntimeError("That isn't a GazelleGames download link, so Umash didn't send your passkey to it")
        user = self.api({"request": "quick_user"})
        passkey = user.get("passkey") or user.get("PassKey") if isinstance(user, dict) else None
        if not passkey:
            raise RuntimeError("GazelleGames didn't give your passkey. The API key needs the User permission")
        query = urllib.parse.urlencode({"action": "download", "id": match.group(1), "authkey": "umash", "torrent_pass": passkey})
        data = self.fetch(f"{self.url}/torrents.php?{query}", {})
        if not data.startswith(b"d"):
            raise RuntimeError("GazelleGames didn't send a torrent file for this result")
        self.save_torrent(data, info)
