# VERSION: 1.0
# AUTHORS: Umash
#
# SubsPlease (subsplease.org): English-subtitled episodes of the current
# season's anime, released within an hour of airing, in 480p, 720p and 1080p.
#
# The site's own search API answers 30 episodes a page, newest first, each with
# a magnet link per resolution. This reads up to 3 pages (up to 270 results: every
# episode in three resolutions; Umash's "load more" asks for the next ones) and shows each as its own row,
# with the size from the magnet and the day the episode was released. The site
# gives no seed counts. SubsPlease only releases anime, so "all" and "anime" are
# the same search.

import calendar
import email.utils
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_subsplease(object):
    url = "https://subsplease.org"
    name = "SubsPlease"
    supported_categories = {"all": "", "anime": ""}
    api = "https://subsplease.org/api/"
    pages = 3
    page_size = 30
    timeout = 25
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")
    resolutions = ("1080", "720", "540", "480")

    def fetch(self, query, page):
        params = {"f": "search", "tz": "UTC", "s": query}
        if page:
            params["p"] = page
        request = urllib.request.Request(self.api + "?" + urllib.parse.urlencode(params), headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        # An empty search is [] rather than an object.
        return data if isinstance(data, dict) else {}

    @staticmethod
    def date(text):
        parsed = email.utils.parsedate_tz(str(text))
        return email.utils.mktime_tz(parsed) if parsed else -1

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def search(self, what, cat="all"):
        query = urllib.parse.unquote(what).strip()
        if not query:
            return
        first = self.setting("UMASH_START_PAGE", 1)
        seen = set()
        for number in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                episodes = self.fetch(query, number - 1)
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as error:
                if number > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise RuntimeError(f"SubsPlease didn't answer: {error}")
            for episode in episodes.values():
                if not isinstance(episode, dict):
                    continue
                released = self.date(episode.get("release_date", ""))
                show = episode.get("show", "")
                slug = episode.get("page", "")
                desc = f"{self.url}/shows/{slug}/" if re.fullmatch(r"[a-z0-9-]+", str(slug)) else self.url
                for download in episode.get("downloads") or []:
                    magnet = html.unescape(str(download.get("magnet", "")))
                    if not self.safe_magnet.fullmatch(magnet) or magnet in seen:
                        continue
                    seen.add(magnet)
                    name = re.search(r"[?&]dn=([^&]+)", magnet)
                    size = re.search(r"[?&]xl=(\d+)", magnet)
                    prettyPrinter({
                        "link": magnet,
                        "name": urllib.parse.unquote_plus(name.group(1)) if name else f"[SubsPlease] {show} - {episode.get('episode', '')} ({download.get('res', '')}p)",
                        "size": int(size.group(1)) if size else -1,
                        "seeds": -1,
                        "leech": -1,
                        "engine_url": self.url,
                        "desc_link": desc,
                        "pub_date": released,
                    })
            has_more = len(episodes) >= self.page_size
            self.more(number + 1 if has_more else 0)
            if not has_more:
                return

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a SubsPlease magnet")
        print(link + " " + link)
