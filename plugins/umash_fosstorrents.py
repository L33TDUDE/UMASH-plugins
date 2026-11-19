# VERSION: 1.0
# AUTHORS: Umash
#
# FOSS Torrents (fosstorrents.com): official torrents of free and open-source
# software, such as Linux distributions, LibreOffice, Blender and 0 A.D.
# Everything here is legal to share.
#
# The site publishes one feed of all its torrents (about 1,100), so a search
# reads it once and keeps the ones that match every word you type, newest
# first. The site's sitemap, read at the same time, gives each project's page
# for the description link. The feed has the date each torrent was added but
# no size or seed counts. Results are the site's own .torrent files, which
# Umash downloads only from fosstorrents.com.

import email.utils
import threading
import html
import re
import urllib.parse
import urllib.request

from helpers import _headers, download_file
from novaprinter import prettyPrinter


class umash_fosstorrents(object):
    url = "https://fosstorrents.com"
    name = "FOSS Torrents"
    supported_categories = {"all": "", "software": ""}
    limit = 300

    item = re.compile(r"<item>(.*?)</item>", re.S)
    field = {name: re.compile(rf"<{name}>(.*?)</{name}>", re.S) for name in ("title", "description", "link", "pubDate")}
    torrent_link = re.compile(r"https://fosstorrents\.com/[^\s\"'<>]+\.torrent")
    project = re.compile(r"Torrent for ([a-z0-9/-]+) - ")
    page = re.compile(r"<loc>(https://fosstorrents\.com/(?:distributions|games|softwares)/([a-z0-9/-]+?)/?)</loc>")

    def fetch(self, address):
        request = urllib.request.Request(address, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except Exception:
            return ""

    def search(self, what, cat="all"):
        words = urllib.parse.unquote(what).lower().split()
        texts = {}
        threads = [threading.Thread(target=lambda key=key: texts.__setitem__(key, self.fetch(f"{self.url}/{key}")))
                   for key in ("feed/torrents.xml", "sitemap.xml")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        feed = texts.get("feed/torrents.xml", "")
        if "<item>" not in feed:
            raise RuntimeError("FOSS Torrents didn't send its torrent list")
        pages = {slug: address for address, slug in self.page.findall(texts.get("sitemap.xml", ""))}
        rows = []
        for item in self.item.findall(feed):
            get = {name: html.unescape((pattern.search(item).group(1) if pattern.search(item) else "").strip())
                   for name, pattern in self.field.items()}
            link = get["link"]
            if not self.torrent_link.fullmatch(link):
                continue
            name = " ".join(get["title"].split())
            haystack = f"{name} {get['description']} {link}".lower()
            if words and not all(word in haystack for word in words):
                continue
            parsed = email.utils.parsedate_tz(get["pubDate"])
            slug = self.project.match(get["description"])
            page = pages.get(slug.group(1)) if slug else None
            rows.append({
                "link": link,
                "name": name,
                "size": "-1",
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": page or f"{self.url}/search/?q=" + urllib.parse.quote(name.split(" - ")[0]),
                "pub_date": email.utils.mktime_tz(parsed) if parsed else -1,
            })
        rows.sort(key=lambda row: row["pub_date"], reverse=True)
        for row in rows[:self.limit]:
            prettyPrinter(row)

    def download_torrent(self, link):
        if not self.torrent_link.fullmatch(link):
            raise ValueError("not a FOSS Torrents link")
        print(download_file(link))
