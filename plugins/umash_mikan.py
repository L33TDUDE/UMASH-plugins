# VERSION: 1.0
# AUTHORS: Umash
#
# Mikan Project (mikanani.me), a Chinese anime index of fansub releases.
#
# The site's search page lists every match (often 1,000 rows) with its magnet,
# size and date, in one request. The two older plugins for this site read the
# same pages but passed on neither the date nor a magnet. The site has no seed
# counts. Dates are in China time (UTC+8).

import calendar
import html
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_mikan(object):
    url = "https://mikanani.me"
    name = "Mikan Project"
    supported_categories = {"all": "", "anime": ""}

    row = re.compile(r'<tr class="js-search-results-row"(.*?)</tr>', re.S)
    magnet = re.compile(r'data-magnet="(magnet:\?xt=urn:btih:[^"]+)"')
    title = re.compile(r'<a href="(/Home/Episode/[0-9a-fA-F]{40})"[^>]*class="magnet-link-wrap">(.*?)</a>', re.S)
    cells = re.compile(r"<td>\s*([^<]*?)\s*</td>\s*<td>\s*(\d{4}/\d\d/\d\d \d\d:\d\d)\s*</td>")
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8", "replace")

    @staticmethod
    def published(text):
        """'2026/10/17 23:42' in China time (UTC+8), as unix time."""
        try:
            return calendar.timegm(time.strptime(text, "%Y/%m/%d %H:%M")) - 8 * 3600
        except ValueError:
            return -1

    def search(self, what, cat="all"):
        query = urllib.parse.quote(urllib.parse.unquote(what))
        page = self.fetch(f"{self.url}/Home/Search?searchstr={query}")
        for found in self.row.finditer(page):
            row = found.group(1)
            magnet, title = self.magnet.search(row), self.title.search(row)
            if not magnet or not title:
                continue
            link = html.unescape(magnet.group(1))
            if not self.safe_magnet.fullmatch(link):
                continue
            name = " ".join(html.unescape(re.sub(r"<[^>]+>", "", title.group(2))).split())
            cells = self.cells.search(row)
            prettyPrinter({
                "link": link + "&dn=" + urllib.parse.quote(name, safe=""),
                "name": name,
                "size": cells.group(1) if cells else "-1",
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": self.url + title.group(1),
                "pub_date": self.published(cells.group(2)) if cells else -1,
            })

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a Mikan Project magnet")
        print(link + " " + link)
