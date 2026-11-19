# VERSION: 1.0
# AUTHORS: Umash
#
# LimeTorrents (limetorrents.fun): a long-running general torrent index with
# movies, TV, music, games, software, anime and more.
#
# Best-seeded first, 40 results a page, 2 pages a search (80 results), then
# Umash's "load more". The site's search ignores its category choice, so a
# category search reads up to 4 pages and keeps the rows the site files under
# that category (the site names it on every row), so the result count is usually
# still near 40 or more. The site shows only a rough age ("4 days ago", "1 Year+"),
# so the date is approximate: exact for the last few days, nearer a year than a
# day for old ones. The magnet is built from the info hash with common public
# trackers, so nothing is fetched from the third-party torrent cache the site
# links to. The site's sponsored "Download" rows at the top of every search are left out.
#
# Categories are the site's own: anime, software (Applications), games, movies,
# music and tv (TV shows). "Other" is in All only.

import html
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import helpers
from helpers import _headers
from novaprinter import prettyPrinter


class umash_limetorrents(object):
    url = "https://www.limetorrents.fun"
    name = "LimeTorrents"
    # The site's own labels, as each result row prints them.
    supported_categories = {
        "all": "", "anime": "anime", "software": "applications", "games": "games",
        "movies": "movies", "music": "music", "tv": "tv shows",
    }
    # Tried in order: the site has moved between these before.
    hosts = ("https://www.limetorrents.fun", "https://www.limetorrents.lol", "https://www.limetorrents.info")
    per_page = 40
    timeout = 30
    trackers = (
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.stealth.si:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://exodus.desync.com:6969/announce",
        "udp://tracker.tiny-vps.com:6969/announce",
    )

    row = re.compile(
        r'<div class="tt-name"><a href="https?://itorrents\.[a-z]+/torrent/([0-9A-Fa-f]{40})\.torrent\?title=[^"]*"[^>]*></a>'
        r'<a href="([^"]+)">(.*?)</a></div>.*?'
        r'<td class="tdnormal">([^<]*)(?:</a>)?</td><td class="tdnormal">([^<]*)</td>'
        r'<td class="tdseed">([^<]*)</td><td class="tdleech">([^<]*)</td>', re.S)
    age = re.compile(r"(?:(\d+)\s+(minute|hour|day|week|month|year)s?|(yesterday))", re.I)
    seconds = {"minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def fetch(self, path):
        failure = "no reply"
        for host in self.hosts:
            request = urllib.request.Request(host + path, headers=dict(_headers))
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return helpers._unpacked(response.read()).decode("utf-8", "replace")
            except urllib.error.HTTPError as error:
                failure = f"HTTP {error.code}"
                if error.code == 404:
                    return ""  # a page past the last one
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as error:
                failure = str(error)
        raise RuntimeError("LimeTorrents didn't answer: " + failure)

    def date(self, text):
        found = self.age.search(text)
        if not found:
            return -1
        if found.group(3):
            return int(time.time()) - 86400
        return int(time.time()) - int(found.group(1)) * self.seconds[found.group(2).lower()]

    def magnet(self, infohash, name):
        tail = "".join("&tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers)
        return f"magnet:?xt=urn:btih:{infohash.lower()}&dn={urllib.parse.quote(name, safe='')}{tail}"

    def read(self, page, wanted):
        count = 0
        for found in self.row.finditer(page):
            infohash, path, title, added, size, seeds, leech = found.groups()
            count += 1
            label = added.rsplit(" in ", 1)[-1].strip().rstrip(".").lower()
            if wanted and label != wanted:
                continue
            name = " ".join(html.unescape(re.sub(r"<[^>]+>", "", title)).split())
            if not name:
                continue
            prettyPrinter({
                "link": self.magnet(infohash, name),
                "name": name,
                "size": size.strip() or -1,
                "seeds": int(seeds.replace(",", "")) if seeds.replace(",", "").isdigit() else -1,
                "leech": int(leech.replace(",", "")) if leech.replace(",", "").isdigit() else -1,
                "engine_url": self.url,
                "desc_link": self.url + html.unescape(path) if path.startswith("/") else self.url,
                "pub_date": self.date(added),
            })
        return count

    def search(self, what, cat="all"):
        query = urllib.parse.quote(" ".join(urllib.parse.unquote(what).split()), safe="")
        wanted = self.supported_categories.get(cat, "")
        first = self.setting("UMASH_START_PAGE", 1)
        for number in range(first, first + self.setting("UMASH_MAX_PAGES", 4 if wanted else 2)):
            try:
                text = self.fetch(f"/search/all/{query}/seeds/{number}/")
            except RuntimeError:
                if number > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            has_more = self.read(text, wanted) >= self.per_page  # counts every row on the page, shown or not
            self.more(number + 1 if has_more else 0)
            if not has_more:
                return
            time.sleep(0.5)

    def download_torrent(self, link):
        if not re.fullmatch(r"magnet:\?xt=urn:btih:[0-9a-f]{40}(&[^\s\x00-\x1f\x7f-\x9f]*)?", link):
            raise ValueError("not a LimeTorrents magnet")
        print(link + " " + link)
