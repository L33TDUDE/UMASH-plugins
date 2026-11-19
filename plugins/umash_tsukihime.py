# VERSION: 1.0
# AUTHORS: Umash, after dominc8's tsukihime.py
#
# TsukiHime (tsukihime.org), an anime index with an open JSON API.
#
# One search gives up to 100 releases with name, size, date and info hash.
# Seed counts are on each release's own record, so those are fetched 8 at a
# time. The older plugin fetched them one by one and stopped with an error
# (KeyError 'trackers') at the first release without tracker data, so a
# search ended early. It also added up the counts from every tracker, which
# counts the same people several times; this one takes the largest.
#
# Based on dominc8's plugin, MIT licence:
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import json
import queue
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_tsukihime(object):
    url = "https://tsukihime.org"
    api = "https://api.tsukihime.org/v1"
    name = "TsukiHime"
    supported_categories = {"all": "", "anime": ""}
    limit = 100
    workers = 8
    trackers = ("udp://tracker.opentrackr.org:1337/announce",
                "udp://open.stealth.si:80/announce",
                "udp://tracker.torrent.eu.org:451/announce",
                "udp://exodus.desync.com:6969/announce")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def get_json(self, address):
        request = urllib.request.Request(address, headers={**_headers, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError):
            return None

    @staticmethod
    def number(value):
        return value if isinstance(value, int) and value >= 0 else -1

    def peers(self, record):
        """(seeds, leechers): the largest any tracker reports, or -1 when none do."""
        trackers = [tracker for tracker in (record or {}).get("trackers") or [] if isinstance(tracker, dict)]
        seeds = max((self.number(tracker.get("seeders")) for tracker in trackers), default=-1)
        leech = max((self.number(tracker.get("leechers")) for tracker in trackers), default=-1)
        urls = [tracker.get("url") for tracker in trackers if isinstance(tracker.get("url"), str)]
        return seeds, leech, urls

    def search(self, what, cat="all"):
        query = urllib.parse.quote(urllib.parse.unquote(what))
        answer = self.get_json(f"{self.api}/search/torrents?q={query}&limit={self.limit}")
        if answer is None:
            raise RuntimeError("TsukiHime didn't answer")
        releases = [item for item in answer.get("results") or []
                    if isinstance(item, dict) and re.fullmatch(r"[0-9a-fA-F]{40}", str(item.get("btih", "")))]

        records = {}
        waiting = queue.Queue()
        for item in releases:
            waiting.put(item["id"])

        def work():
            while True:
                try:
                    number = waiting.get_nowait()
                except queue.Empty:
                    return
                records[number] = self.get_json(f"{self.api}/torrents/{int(number)}")

        threads = [threading.Thread(target=work) for _ in range(min(self.workers, len(releases)))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        for item in releases:
            name = str(item.get("name") or "")
            seeds, leech, urls = self.peers(records.get(item["id"]))
            parts = [f"xt=urn:btih:{item['btih'].lower()}", "dn=" + urllib.parse.quote(name, safe="")]
            parts += ["tr=" + urllib.parse.quote(url, safe="") for url in (urls or self.trackers)]
            size = item.get("totalsize")
            date = item.get("source_date") or item.get("added_date")
            prettyPrinter({
                "link": "magnet:?" + "&".join(parts),
                "name": name,
                "size": str(size) if isinstance(size, int) else "-1",
                "seeds": seeds,
                "leech": leech,
                "engine_url": self.url,
                "desc_link": f"{self.url}/view/{int(item['id'])}",
                "pub_date": date if isinstance(date, int) else -1,
            })

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a TsukiHime magnet")
        print(link + " " + link)
