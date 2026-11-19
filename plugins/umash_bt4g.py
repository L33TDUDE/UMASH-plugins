# VERSION: 1.1
# AUTHORS: Umash
#
# BT4G (bt4gprx.com), a DHT search engine. Its web pages show Cloudflare's
# browser check to every plugin, but it publishes each search as an RSS feed,
# which is open: one quick request, with magnets. Feeds have no seed counts.

import email.utils
import re
import urllib.parse
import xml.etree.ElementTree as ET

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_bt4g(object):
    url = "https://bt4gprx.com"
    name = "BT4G"
    # The feed has no category filter.
    supported_categories = {"all": ""}

    @staticmethod
    def date(text):
        try:
            return int(email.utils.parsedate_to_datetime(text).timestamp())
        except (TypeError, ValueError):
            return -1

    def search(self, what, cat="all"):
        query = urllib.parse.quote_plus(urllib.parse.unquote(what))
        feed = retrieve_url(f"{self.url}/search?q={query}&page=rss", unescape_html_entities=False)
        # Real feeds have no DOCTYPE. Refusing one rules out XML entity tricks.
        if "<!doctype" in feed.lower():
            raise ValueError("feed has a DOCTYPE, refusing to read it")
        for item in ET.fromstring(feed).iter("item"):
            link = (item.findtext("link") or "").strip()
            if not link.startswith("magnet:"):
                continue
            size = re.search(r"([\d.]+\s*[KMGT]i?B)", item.findtext("description") or "", re.I)
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
