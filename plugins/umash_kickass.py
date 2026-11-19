# VERSION: 1.2
# AUTHORS: Umash
#
# Kickass Torrents (kickasstorrents.to), best-seeded first. Search pages list
# titles with seeds and sizes; the magnet is on each title's own page, so it is
# fetched only when you download one. The site gives only an age such as
# "3 years", so published dates are approximate.

import html
import re
import time
import urllib.parse

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_kickass(object):
    url = "https://kickasstorrents.to"
    name = "Kickass Torrents"
    # The site has no books or pictures category.
    supported_categories = {"all": "", "anime": "anime", "games": "games", "movies": "movies",
                            "music": "music", "software": "apps", "tv": "tv"}
    pages = 3
    per_page = 20

    row = re.compile(r'<tr class="(?:odd|even)"\s*>(.*?)</tr>', re.S)
    title = re.compile(r'<a href="(/[^"\s]+-t\d+\.html)"\s+class="cellMainLink">(.*?)</a>', re.S)
    size = re.compile(r'<td class="nobr center">\s*([^<]+?)\s*</td>')
    seeds = re.compile(r'<td class="green center">\s*(\d+)')
    leech = re.compile(r'<td class="red lasttd center">\s*(\d+)')
    age = re.compile(r'<td class="center" title="(\d+)<br/>([a-z]+)"')
    seconds = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "day": 86400,
               "week": 604800, "month": 2592000, "year": 31536000}
    row_category = re.compile(r'<strong>\s*<a href="/([a-z]+)/"')
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[^"\s]+)"')
    # Checked after unescaping, which can turn &#10; into a line break: this line
    # is Umash's only instruction about what to open.
    safe_magnet = re.compile(r'magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?')

    @staticmethod
    def count(pattern, text):
        found = pattern.search(text)
        return int(found.group(1)) if found else -1

    def published(self, row):
        found = self.age.search(row)
        if not found:
            return -1
        unit = self.seconds.get(found.group(2).rstrip("s"))
        return int(time.time()) - int(found.group(1)) * unit if unit else -1

    def read_page(self, text, wanted=""):
        rows = 0
        for row in self.row.findall(text):
            title = self.title.search(row)
            size = self.size.search(row)
            if not title:
                continue
            rows += 1
            category = self.row_category.search(row)
            if wanted and not (category and category.group(1) == wanted):
                continue
            page = self.url + title.group(1)
            prettyPrinter({
                "link": page,
                "name": " ".join(html.unescape(re.sub(r"<[^>]+>", "", title.group(2))).split()),
                "size": size.group(1) if size else "-1",
                "seeds": self.count(self.seeds, row),
                "leech": self.count(self.leech, row),
                "engine_url": self.url,
                "desc_link": page,
                "pub_date": self.published(row),
            })
        return rows

    def search(self, what, cat="all"):
        query = urllib.parse.quote(urllib.parse.unquote(what).replace("/", " "), safe="")
        wanted = self.supported_categories.get(cat, "")
        options = (f"category={wanted}&" if wanted else "") + "sortby=seeders&sort=desc"
        for number in range(1, self.pages + 1):
            part = "" if number == 1 else f"{number}/"
            try:
                text = retrieve_url(f"{self.url}/usearch/{query}/{part}?{options}")
            except Exception:
                # The site limits quick requests: keep what the first pages found.
                if number == 1:
                    raise
                break
            if self.read_page(text, wanted) < self.per_page:
                break

    def download_torrent(self, page):
        if not page.startswith(self.url + "/"):
            raise ValueError("not a Kickass Torrents page")
        found = self.magnet.search(retrieve_url(page))
        if not found:
            raise ValueError("no magnet on this page")
        magnet = html.unescape(found.group(1))
        if not self.safe_magnet.fullmatch(magnet):
            raise ValueError("the magnet on this page looks wrong")
        print(magnet + " " + page)
