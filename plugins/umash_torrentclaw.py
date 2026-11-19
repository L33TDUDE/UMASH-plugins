# VERSION: 1.0
# AUTHORS: Umash, after Deivid Soto's torrentclaw.py
# SETTING: api_key | secret required | API key | Free: sign up at torrentclaw.com, then copy the key from your Settings page. Without one the site sends no magnets or info hashes. | https://torrentclaw.com/register
#
# TorrentClaw (torrentclaw.com) gathers torrents from other sites (YTS, EZTV,
# Knaben, Torrents.csv and more) under each film or show, with a quality score.
#
# The older plugin turned every problem into an empty list: a missing key, a
# key the site refused, a rate limit or a site error all looked like "no
# results". This one says which it was. Up to 3 pages are fetched at once.
# Names end with the site's quality score, like [TC-94].

import json
import os
import re
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from helpers import _headers
from novaprinter import prettyPrinter


class umash_torrentclaw(object):
    url = "https://torrentclaw.com"
    name = "TorrentClaw"
    supported_categories = {"all": None, "movies": "movie", "tv": "show"}
    pages = 3
    trackers = ("udp://tracker.opentrackr.org:1337/announce",
                "udp://open.tracker.cl:1337/announce",
                "udp://tracker.torrent.eu.org:451/announce",
                "udp://open.stealth.si:80/announce",
                "udp://exodus.desync.com:6969/announce",
                "udp://open.demonii.com:1337/announce")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    @staticmethod
    def stop(message):
        print(message, file=sys.stderr)
        raise SystemExit(1)

    def fetch(self, address, key):
        """(status, parsed JSON or None)."""
        headers = {**_headers, "Accept": "application/json", "Authorization": f"Bearer {key}"}
        try:
            with urllib.request.urlopen(urllib.request.Request(address, headers=headers), timeout=20) as response:
                return response.status, json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            return error.code, None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError):
            return 0, None

    @staticmethod
    def published(text):
        try:
            return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())
        except (ValueError, TypeError):
            return -1

    @staticmethod
    def count(value):
        return value if isinstance(value, int) and value >= 0 else -1

    def search(self, what, cat="all"):
        key = os.environ.get("UMASH_SETTING_API_KEY", "").strip()
        if not key:
            self.stop("TorrentClaw needs its free API key: add it in Plugins > TorrentClaw > Settings.")
        params = {"q": urllib.parse.unquote(what), "limit": "50"}
        kind = self.supported_categories.get(cat)
        if kind:
            params["type"] = kind
        answers = {}

        def get(number):
            answers[number] = self.fetch(f"{self.url}/api/v1/search?{urllib.parse.urlencode({**params, 'page': number})}", key)

        threads = [threading.Thread(target=get, args=(number,)) for number in range(1, self.pages + 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        status, first = answers[1]
        if status in (401, 403):
            self.stop(f"TorrentClaw refused the API key (HTTP {status}). Check it in Plugins > TorrentClaw > Settings.")
        if status == 429:
            self.stop("TorrentClaw says too many searches (HTTP 429). Wait a while and try again.")
        if first is None:
            self.stop(f"TorrentClaw didn't answer properly (HTTP {status or 'no connection'}).")

        printed, seen, withheld = 0, set(), False
        for number in range(1, self.pages + 1):
            _, answer = answers.get(number, (0, None))
            for content in (answer or {}).get("results") or []:
                url = content.get("contentUrl")
                for torrent in content.get("torrents") or []:
                    info_hash = str(torrent.get("infoHash") or "").lower()
                    if not re.fullmatch(r"[0-9a-f]{40}", info_hash):
                        withheld = True
                        continue
                    if info_hash in seen:
                        continue
                    seen.add(info_hash)
                    name = str(torrent.get("rawTitle") or content.get("title") or "")
                    if isinstance(torrent.get("qualityScore"), int):
                        name += f" [TC-{torrent['qualityScore']}]"
                    magnet = str(torrent.get("magnetUrl") or "")
                    if not self.safe_magnet.fullmatch(magnet):
                        parts = [f"xt=urn:btih:{info_hash}", "dn=" + urllib.parse.quote(name, safe="")]
                        magnet = "magnet:?" + "&".join(parts + ["tr=" + urllib.parse.quote(t, safe="") for t in self.trackers])
                    size = torrent.get("sizeBytes")
                    prettyPrinter({
                        "link": magnet,
                        "name": name,
                        "size": str(size) if isinstance(size, int) and size > 0 else "-1",
                        "seeds": self.count(torrent.get("seeders")),
                        "leech": self.count(torrent.get("leechers")),
                        "engine_url": self.url,
                        "desc_link": self.url + url if isinstance(url, str) and url.startswith("/") else self.url,
                        "pub_date": self.published(torrent.get("uploadedAt")),
                    })
                    printed += 1
        if not printed and (withheld or "api key" in str(first.get("_notice", "")).lower()):
            self.stop("TorrentClaw didn't accept the API key: it answered as if none was sent, "
                      "so it held back the magnets. Check the key in Plugins > TorrentClaw > Settings.")

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a TorrentClaw magnet")
        print(link + " " + link)
