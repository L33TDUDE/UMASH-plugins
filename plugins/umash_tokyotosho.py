# VERSION: 1.2
# AUTHORS: Umash
#
# Tokyo Toshokan (tokyotosho.info): anime and Japanese media. Its search page
# shows Cloudflare's browser check to every plugin, but the same search is
# published as an open RSS feed: one quick request, with magnets and sizes.
# Feeds have no seed counts.

import email.utils
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_tokyotosho(object):
    url = "https://www.tokyotosho.info"
    name = "Tokyo Toshokan"
    # The start of each item's category. The feed ignores the site's type filter.
    supported_categories = {"all": "", "anime": "Anime", "music": "Music", "books": "Manga"}

    @staticmethod
    def date(text):
        try:
            return int(email.utils.parsedate_to_datetime(text).timestamp())
        except (TypeError, ValueError):
            return -1

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        wanted = self.supported_categories.get(cat, "")
        feed = retrieve_url(f"{self.url}/rss.php?terms={query}", unescape_html_entities=False)
        # Real feeds have no DOCTYPE. Refusing one rules out XML entity tricks.
        if "<!doctype" in feed.lower():
            raise ValueError("feed has a DOCTYPE, refusing to read it")
        hide_adult = os.environ.get("UMASH_HIDE_ADULT") == "1"
        for item in ET.fromstring(feed).iter("item"):
            category = item.findtext("category") or ""
            if not category.startswith(wanted):
                continue
            if hide_adult and category.lower().startswith(("hentai", "jav")):
                continue
            description = item.findtext("description") or ""
            magnet = re.search(r'href="(magnet:[^"]+)"', description)
            link = magnet.group(1) if magnet else (item.findtext("link") or "").strip()
            if not link:
                continue
            size = re.search(r"Size:\s*([\d.]+\s*[KMGT]i?B)", description, re.I)
            prettyPrinter({
                "link": link,
                "name": (item.findtext("title") or "").strip(),
                "size": size.group(1) if size else "-1",
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": (item.findtext("guid") or "-1").strip(),
                "pub_date": self.date(item.findtext("pubDate")),
            })
