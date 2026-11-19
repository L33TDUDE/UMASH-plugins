# VERSION: 2.1
# AUTHORS: Umash
# LOGIN: https://iptorrents.com/login.php | uid, pass | cf_clearance
#
# IPTorrents (iptorrents.com), a private tracker, read from the site's own search
# pages with the login you get by signing in from Umash. Everything the website
# shows: old results, seeds and leechers, best-seeded first. The login is sent only
# to this site, and result links carry none of it.

import gzip
import html
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from novaprinter import prettyPrinter

SIGNED_OUT = 4  # Umash's "this plugin needs signing in again".


def signed_out():
    sys.exit(SIGNED_OUT)


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """The site sends anyone not signed in to its sign-in page. Nothing is followed,
    so the login can't reach another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "login" in newurl.lower():
            signed_out()
        raise RuntimeError("IPTorrents sent Umash to another page instead of answering, so the site may have changed")


class ResultsPage(HTMLParser):
    """Reads the torrent rows the way a browser does. The server leaves out closing tags
    such as </td> and </th>, which a pattern match can't rely on."""

    details = re.compile(r"/t/(\d+)/?$")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found_table = False
        self.saw_download = False
        self.rows = []
        self.depth = 0
        self.row = None
        self.cell = None
        self.in_name = False
        self.in_sub = False
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        classes = attributes.get("class", "").split()
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif attributes.get("id") == "torrents":
                self.found_table = True
                self.depth = 1
            return
        if not self.depth:
            return
        if self.row is not None and "free" in classes:
            self.row["free"] = True
        if self.depth == 1 and tag == "tr":
            self.finish_row()
            self.row = {"cells": [], "id": None, "name": "", "download": None, "category": "", "free": False, "sub": ""}
            self.cell = None
        elif self.row is None:
            return
        elif self.depth == 1 and tag == "td":
            self.row["cells"].append("")
            self.cell = len(self.row["cells"]) - 1
        elif tag == "a":
            self.read_link(attributes.get("href", ""))
        elif tag == "img" and not self.row["category"]:
            self.row["category"] = attributes.get("alt", "")
        elif tag == "div":
            if self.skipping or "tTip" in classes:
                self.skipping += 1
            elif "sub" in classes:
                self.in_sub = True

    def read_link(self, href):
        parts = urllib.parse.urlsplit(href)
        if parts.path.startswith("/download.php/"):
            self.saw_download = True
            if not self.row["download"]:
                self.row["download"] = parts.path
            return
        # The bookmark and comment links go to the same page, with a query or fragment.
        found = self.details.fullmatch(parts.path)
        if found and not parts.query and not parts.fragment and not self.row["id"]:
            self.row["id"] = found.group(1)
            self.in_name = True

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.finish_row()
        elif not self.depth or self.row is None:
            return
        elif tag == "a":
            self.in_name = False
            self.skipping = 0
        elif tag == "div":
            if self.skipping:
                self.skipping -= 1
            else:
                self.in_sub = False
        elif tag == "td" and self.depth == 1:
            self.cell = None

    def handle_data(self, data):
        if self.row is None or self.skipping:
            return
        if self.in_name:
            self.row["name"] += data
        if self.in_sub:
            self.row["sub"] += data
        if self.cell is not None:
            self.row["cells"][self.cell] += data

    def finish_row(self):
        if self.row and self.row["id"] and self.row["download"] and len(self.row["cells"]) >= 4 and self.row["name"].strip():
            self.rows.append(self.row)
        self.row = None
        self.cell = None
        self.in_name = self.in_sub = False
        self.skipping = 0


class umash_iptorrents(object):
    url = "https://iptorrents.com"
    name = "IPTorrents"
    # The site's category numbers. "all" sends none, which is what the site calls everything.
    supported_categories = {
        "all": "",
        "anime": "60",
        "books": "35;94;95;92;64;102",
        "games": "43;47;45;71;50;2;44",
        "movies": "48;101;20;38;7;100;89;90;68;6;87;62;54;77;96",
        "music": "80;3;93;37;21",
        "pictures": "36",
        "software": "1;86;69;58",
        "tv": "22;99;4;65;78;66;5;23;26;55;25;79;82;83;24",
    }
    # With adult content off, "all" names everything except the XXX categories.
    other_categories = "98;76"

    pages = 10
    pause = 0.2
    timeout = 20
    download_path = re.compile(r"/download\.php/(\d+)/([^?#]+)")

    age = re.compile(r"([\d.]+)\s*(minute|hour|day|week|month|year)s?\s+ago", re.I)
    seconds = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2629800, "year": 31557600}
    no_results = re.compile(r"no torrents|nothing found|no results|not found", re.I)
    changed = "IPTorrents' results page has changed, so Umash can't read it"

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def headers(self):
        cookie = os.environ.get("UMASH_LOGIN_COOKIE", "").strip()
        if not cookie:
            signed_out()
        headers = {"Cookie": cookie, "Accept": "text/html,*/*", "Accept-Encoding": "gzip"}
        agent = os.environ.get("UMASH_LOGIN_USER_AGENT", "")
        if agent:
            headers["User-Agent"] = agent
        return headers

    def fetch(self, url):
        """Errors never include the login."""
        request = urllib.request.Request(url, headers=self.headers())
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            # A Cloudflare check: signing in again in the window passes it.
            if error.headers.get("cf-mitigated") == "challenge":
                signed_out()
            if error.code in (401, 403):
                raise RuntimeError(f"IPTorrents refused the request (HTTP {error.code}). If this keeps happening, try signing in again") from None
            if error.code == 429:
                raise RuntimeError("IPTorrents is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"IPTorrents answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach IPTorrents: {error.reason}") from None
        # The site compresses its pages whether or not it was asked to.
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data

    def page(self, url):
        text = self.fetch(url).decode("utf-8", "replace")
        if "<html" not in text[:4000].lower() and "<!doctype" not in text[:4000].lower():
            raise RuntimeError("IPTorrents sent something other than a web page, so the site may have changed")
        # Only a signed-in page has the sign-out link.
        if "/lout.php" not in text:
            signed_out()
        return text

    def address(self, what, cat, page):
        wanted = self.supported_categories.get(cat, "")
        hiding = os.environ.get("UMASH_HIDE_ADULT") == "1"
        if not wanted and hiding:
            wanted = ";".join(v for v in self.supported_categories.values() if v) + ";" + self.other_categories
        parts = [f"{number}=" for number in wanted.split(";") if number]
        parts += ["q=" + urllib.parse.quote(urllib.parse.unquote(what), safe=""), "o=seeders"]
        if page > 1:
            parts.append(f"p={page}")
        return f"{self.url}/t?{'&'.join(parts)}"

    def read_rows(self, text):
        """Every torrent on a search page. Raises when the page can't be read."""
        page = ResultsPage()
        page.feed(text)
        page.close()
        page.finish_row()
        if not page.found_table:
            if self.no_results.search(re.sub(r"<[^>]+>", " ", text)):
                return []
            raise RuntimeError(self.changed)
        if not page.rows and page.saw_download:
            raise RuntimeError(self.changed)
        return [self.result(row) for row in page.rows]

    def result(self, row):
        name = " ".join(row["name"].split())
        if row["free"]:
            name += " [FreeLeech]"
        cells = [cell.strip() for cell in row["cells"]]
        return {
            "id": row["id"],
            "adult": row["category"].upper().startswith("XXX"),
            "link": self.url + urllib.parse.quote(urllib.parse.unquote(row["download"]), safe="/"),
            "name": name,
            "size": cells[-4] or "-1",
            "seeds": self.number(cells[-2]),
            "leech": self.number(cells[-1]),
            "engine_url": self.url,
            "desc_link": f"{self.url}/t/{row['id']}",
            "pub_date": self.published(row["sub"]),
        }

    @staticmethod
    def number(text):
        digits = re.sub(r"\D", "", text)
        return int(digits) if digits else -1

    def published(self, text):
        """The site gives only an age, such as "8.7 years ago", so the date is approximate."""
        found = self.age.search(text)
        if not found:
            return -1
        return int(time.time() - float(found.group(1)) * self.seconds[found.group(2).lower()])

    @staticmethod
    def more(page):
        """Tells Umash which page comes next, or 0 at the end of the results."""
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    def search(self, what, cat="all"):
        self.headers()
        first = self.setting("UMASH_START_PAGE", 1)
        hiding = os.environ.get("UMASH_HIDE_ADULT") == "1"
        seen = set()
        widest = 0
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            if page > first:
                time.sleep(self.pause)
            try:
                text = self.page(self.address(what, cat, page))
            except RuntimeError:
                # Keep what the earlier pages found. Load More picks up from here.
                if page > first:
                    return
                raise
            rows = self.read_rows(text)
            fresh = [row for row in rows if row["id"] not in seen]
            if not fresh:
                self.more(0)
                return
            seen.update(row["id"] for row in fresh)
            for row in fresh:
                if not (hiding and row["adult"]):
                    prettyPrinter({key: value for key, value in row.items() if key not in ("id", "adult")})
            widest = max(widest, len(rows))
            self.more(0 if len(rows) < widest else page + 1)
            if len(rows) < widest:
                return

    def download_torrent(self, info):
        """Sends the login only to this site's own download address."""
        self.headers()
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't an IPTorrents download link, so Umash didn't send your login to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            if b"/lout.php" not in data:
                signed_out()
            raise RuntimeError("IPTorrents didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
