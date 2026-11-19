# VERSION: 2.0
# AUTHORS: Umash, after Ashalda's sktorrent.py (https://github.com/Ashalda/sktorrent-qbt)
# LOGIN: https://sktorrent.eu/torrent/login.php | *
#
# SkTorrent (sktorrent.eu), a Czech and Slovak site, mostly films and series
# with CZ/SK dubbing. The site no longer lists torrents to visitors who aren't
# signed in (it answers them "Bad ID!"), so this reads the site's search pages with
# the login you get by signing in from Umash: the free account the site offers, with
# no password or cookie to copy. The login is sent only to this site, and result
# links carry none of it.
#
# The site takes 3 to 9 seconds a page and shows 24 results a page, so this
# reads the page count from the first page and fetches up to 4 more at once
# (120 results). The older plugin fetched every page in turn until one came back
# empty: minutes for a common word.
#
# Magnets carry the site's own UDP tracker and public ones. The older plugin
# also added an announce address with its author's personal ID (pid=...), which
# would report your downloads to the site under that account; this one doesn't.

import calendar
import gzip
import html
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from novaprinter import prettyPrinter

SIGNED_OUT = 4  # Umash's "this plugin needs signing in again".


class SignedOut(Exception):
    """The site answered as it does for a visitor who isn't signed in."""


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """The login goes with every request, so only the site's own redirects are followed.
    A redirect to its sign-in page means the login has ended."""

    def __init__(self, site):
        super().__init__()
        self.site = urllib.parse.urlsplit(site)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if "login" in target.path.lower():
            raise SignedOut()
        if (target.scheme, target.netloc) != (self.site.scheme, self.site.netloc):
            raise RuntimeError("SkTorrent sent Umash to another site instead of answering, so Umash stopped")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class umash_sktorrent(object):
    url = "https://sktorrent.eu"
    name = "SkTorrent"
    supported_categories = {"all": ""}
    pages = 5
    timeout = 40

    row = re.compile(
        r'details\.php\?name=[^"&]*&id=(?P<id>[a-fA-F0-9]{40})"[^>]*>.*?<br>(?P<name>[^<]*)</A>\s*'
        r'<br>Velkost (?P<size>[^|<]+)\| Pridany (?P<date>\d{2}/\d{2}/\d{4})<br>\s*'
        r'Odosielaju : (?P<seeds>\d+)<br>\s*'
        r'Stahuju : (?P<leech>\d+)',
        re.S | re.I)
    pager = re.compile(r"[?&]page=(\d+)")
    # The site ends titles with the film's rating on ČSFD, the Czech and Slovak
    # film database: "... [1080p] = CSFD 72%". Not part of the release name.
    rating = re.compile(r"\s*=\s*CSFD\b[^=]*$", re.I)
    trackers = ("udp://ipv4announce.sktorrent.eu:6969/announce",
                "udp://tracker.opentrackr.org:1337/announce",
                "udp://tracker.torrent.eu.org:451/announce",
                "udp://open.stealth.si:80/announce",
                "udp://open.demonii.com:1337/announce")

    def __init__(self):
        self.opener = urllib.request.build_opener(SameSiteRedirects(self.url))

    def headers(self):
        cookie = os.environ.get("UMASH_LOGIN_COOKIE", "").strip()
        if not cookie:
            raise SignedOut()
        headers = {"Cookie": cookie, "Accept": "text/html,*/*", "Accept-Language": "sk,cs;q=0.9,en;q=0.8",
                   "Accept-Encoding": "gzip"}
        agent = os.environ.get("UMASH_LOGIN_USER_AGENT", "")
        if agent:
            headers["User-Agent"] = agent
        return headers

    @staticmethod
    def visitor_page(text):
        """What the site shows anyone who isn't signed in: its sign-in form, or "Bad ID!"."""
        lower = text[:60000].lower()
        return "bad id!" in lower or 'action="login.php"' in lower or 'name="pwd"' in lower

    def fetch(self, url):
        """The page as text. Errors never include the login."""
        request = urllib.request.Request(url, headers=self.headers())
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            # The site answers a visitor with HTTP 404 and a page saying "Bad ID!".
            text = self.text(error.read(60000))
            if self.visitor_page(text):
                raise SignedOut() from None
            if error.code == 429:
                raise RuntimeError("SkTorrent is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"SkTorrent answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (SignedOut, RuntimeError)):
                raise error.reason from None
            raise RuntimeError(f"Couldn't reach SkTorrent: {error.reason}") from None
        text = self.text(data)
        if self.visitor_page(text):
            raise SignedOut()
        return text

    @staticmethod
    def text(data):
        if data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError):
                pass
        return data.decode("utf-8", "replace")

    def page_url(self, query, number):
        return f"{self.url}/torrent/torrents_v2.php?search={query}&category=0&zaner=&jazyk=&active=0&page={number}"

    @staticmethod
    def published(day):
        """The day it was added (06/09/2025, day first), at midnight UTC."""
        try:
            return calendar.timegm(time.strptime(day, "%d/%m/%Y"))
        except ValueError:
            return -1

    def magnet(self, info_hash, name):
        parts = [f"xt=urn:btih:{info_hash}", "dn=" + urllib.parse.quote(name, safe="")]
        parts += ["tr=" + urllib.parse.quote(tracker, safe="") for tracker in self.trackers]
        return "magnet:?" + "&".join(parts)

    def rows(self, text):
        found = []
        for match in self.row.finditer(text):
            name = self.rating.sub("", " ".join(html.unescape(match.group("name")).split()))
            info_hash = match.group("id").lower()
            found.append({
                "link": self.magnet(info_hash, name),
                "name": name,
                "size": match.group("size").strip(),
                "seeds": int(match.group("seeds")),
                "leech": int(match.group("leech")),
                "engine_url": self.url,
                "desc_link": f"{self.url}/torrent/details.php?id={info_hash}",
                "pub_date": self.published(match.group("date")),
            })
        return found

    def search(self, what, cat="all"):
        try:
            self.run(what)
        except SignedOut:
            sys.exit(SIGNED_OUT)

    def run(self, what):
        query = urllib.parse.quote(urllib.parse.unquote(what), safe="")
        first = self.fetch(self.page_url(query, 0))
        seen = set()
        for row in self.rows(first):
            seen.add(row["desc_link"])
            prettyPrinter(row)
        last = max((int(number) for number in self.pager.findall(first)), default=0)
        numbers = range(1, min(last, self.pages - 1) + 1)
        if not numbers:
            return
        # The rest at once, printed in page order. A page that fails is skipped:
        # the first page already showed the search works.
        texts = {}

        def fetch(number):
            try:
                texts[number] = self.fetch(self.page_url(query, number))
            except (SignedOut, RuntimeError):
                pass

        threads = [threading.Thread(target=fetch, args=(number,)) for number in numbers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for number in numbers:
            for row in self.rows(texts.get(number, "")):
                if row["desc_link"] not in seen:
                    seen.add(row["desc_link"])
                    prettyPrinter(row)
