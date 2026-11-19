# VERSION: 1.0
# AUTHORS: Umash
#
# Snowfl (snowfl.com), an aggregator of other torrent sites. Its page script
# holds a key that every request needs and that changes from time to time, so
# it is read from the script on each search, the way the site itself does it.
# Results without a magnet are resolved through Snowfl's magnet endpoint.

import json
import random
import re
import string
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from helpers import retrieve_url
from novaprinter import prettyPrinter


class umash_snowfl(object):
    url = "https://snowfl.com"
    name = "Snowfl"
    supported_categories = {"all": "0"}

    def key(self):
        home = retrieve_url(self.url + "/")
        script = re.search(r'"(b\.min\.js[^"]*)"', home)
        if not script:
            raise RuntimeError("Snowfl: the page no longer links its script")
        match = re.search(r'var\s+\w+\s*=\s*"([A-Za-z0-9]{24,})"\s*;\s*\$\(', retrieve_url(self.url + "/" + script.group(1)))
        if not match:
            raise RuntimeError("Snowfl: the key is no longer in its script")
        return match.group(1)

    def magnet(self, key, item):
        if item.get("magnet"):
            return item["magnet"]
        try:
            target = urllib.parse.quote(item.get("url", ""), safe="")
            return json.loads(retrieve_url(f"{self.url}/{key}/{item.get('site', '')}/{target}")).get("url", "")
        except Exception:  # one bad result must not sink the search
            return ""

    def search(self, what, cat="all"):
        if len(urllib.parse.unquote(what)) < 3:
            raise RuntimeError("Snowfl needs at least 3 characters")
        key = self.key()
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        items = json.loads(retrieve_url(f"{self.url}/{key}/{what}/{nonce}/0/SEED/NONE/0?_={int(time.time() * 1000)}"))
        with ThreadPoolExecutor(8) as pool:
            links = list(pool.map(lambda item: self.magnet(key, item), items))
        for item, link in zip(items, links):
            if not link.startswith("magnet:"):
                continue
            site = item.get("site")
            prettyPrinter({
                "link": link,
                "name": f"{item.get('name', '')} [{site}]" if site else item.get("name", ""),
                "size": item.get("size", "-1"),
                "seeds": item.get("seeder", -1),
                "leech": item.get("leecher", -1),
                "engine_url": self.url,
                "desc_link": item.get("url", "-1"),
            })
