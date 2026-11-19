# VERSION: 1.0
# AUTHORS: Umash
#
# DistroWatch (distrowatch.com) torrents: about 200 current Linux and BSD
# release images that DistroWatch seeds itself, from Debian, openSUSE and
# NetBSD to small projects. Everything here is legal to share.
#
# One request reads the site's whole torrent list, newest first, and keeps the
# ones whose project or file name matches every word you type. Each result is
# named "Project: file" with the date DistroWatch added it, and its description
# link opens the project's DistroWatch page. The list has no size or seed
# counts. Results are DistroWatch's own .torrent files, which Umash downloads
# only from distrowatch.com.

import calendar
import html
import re
import time
import urllib.parse
import urllib.request

from helpers import _headers, download_file
from novaprinter import prettyPrinter


class umash_distrowatch(object):
    url = "https://distrowatch.com"
    name = "DistroWatch"
    supported_categories = {"all": "", "software": ""}

    row = re.compile(
        r'<td class="torrent"[^>]*><a href="(?P<project_page>[a-z0-9_-]+)">.*?<br>(?P<project>[^<]*)</a></td>\s*'
        r'<td class="torrent"><a href="(?P<link>dwres/torrents/[^"]+\.torrent)">(?P<file>[^<]*)</a></td>\s*'
        r'<td class="torrentdate"[^>]*>(?P<date>\d{4}-\d\d-\d\d)</td>', re.S)
    torrent_link = re.compile(r"https://distrowatch\.com/dwres/torrents/[^\s\"'<>/]+\.torrent")

    def search(self, what, cat="all"):
        words = urllib.parse.unquote(what).lower().split()
        request = urllib.request.Request(f"{self.url}/dwres.php?resource=bittorrent&sortorder=date", headers=dict(_headers))
        with urllib.request.urlopen(request, timeout=30) as response:
            page = response.read().decode("utf-8", "replace")
        for match in self.row.finditer(page):
            project = html.unescape(match.group("project")).strip()
            file = html.unescape(match.group("file")).strip()
            if words and not all(word in f"{project} {file}".lower() for word in words):
                continue
            try:
                added = calendar.timegm(time.strptime(match.group("date"), "%Y-%m-%d"))
            except ValueError:
                added = -1
            prettyPrinter({
                "link": f"{self.url}/{match.group('link')}",
                "name": f"{project}: {re.sub(r'[.]torrent$', '', file)}",
                "size": "-1",
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": f"{self.url}/{match.group('project_page')}",
                "pub_date": added,
            })

    def download_torrent(self, link):
        if not self.torrent_link.fullmatch(link):
            raise ValueError("not a DistroWatch torrent link")
        print(download_file(link))
