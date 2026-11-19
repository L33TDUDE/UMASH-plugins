# VERSION: 1.2
# AUTHORS: Umash
# LOGIN: https://brokenstones.is/login.php | session | keeplogged
#
# BrokenStones (brokenstones.is), a private tracker for macOS and iOS apps and
# games, with the login you get by signing in from Umash. The login is sent only
# to this site, and result links carry none of it.
#
# The site runs Gazelle. Search uses its JSON API (ajax.php?action=browse) as
# Jackett's and Prowlarr's BrokenStones indexers do; if the site sends a web page
# instead, the search page is read the way Jackett reads Phoenix Project, which
# runs similar software. Newest first, 3 pages at a time, with Load More.
#
# The JSON API sends only the app's name, so each page of results also reads the
# same search page for every torrent's edition ("26.5.1 [Intel/Pre-K'ed AiO by
# Macked]", in div.torrent_info), matched by torrent id. Checked with a real
# account on 2026-11-09.

import gzip
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from helpers import _headers
from novaprinter import prettyPrinter

SIGNED_OUT = 4  # Umash's "this plugin needs signing in again".


def signed_out():
    sys.exit(SIGNED_OUT)


def clean_edition(text):
    """The edition text, without the site's own freeleech label ("... / Freeleech!"):
    Umash marks those rows [FreeLeech] itself."""
    text = " ".join(text.split())
    return re.sub(r"\s*/\s*(?:Personal\s+)?(?:Freeleech|Neutral\s*Leech)!?\s*$", "", text, flags=re.I)


def plain_size(text):
    """"1,378.21 MB" as "1378.21 MB": the runtime stops reading at a comma."""
    return re.sub(r"(?<=\d)[,\s](?=\d)", "", " ".join(text.split()))


def is_sign_in_page(data):
    text = data[:40000].decode("utf-8", "replace").lower()
    return 'id="loginform"' in text or "<title>login ::" in text


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """The site sends anyone not signed in to login.php. Nothing is followed, so
    the login can't reach another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "login" in newurl.lower():
            signed_out()
        raise RuntimeError(f"{self.site} sent Umash to another page instead of answering, so the site may have changed")


class Rows(HTMLParser):
    """The search page's results table (table.torrent_table, one tr.torrent per
    torrent), read from the server's own HTML. Fields follow Jackett's selectors."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.title = False
        self.depth = 0  # Tables inside the row's cells.
        self.info = 0  # Inside the edition box (div.torrent_info).

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        href = attrs.get("href") or ""
        if tag == "tr" and "torrent" in classes and self.row is None:
            self.row = {"title": "", "details": "", "id": "", "date": "", "size": "", "seeds": "", "leech": "",
                        "free": False, "info": "", "torrentid": ""}
            self.info = 0
            return
        if self.row is None:
            return
        if tag == "div" and (self.info or "torrent_info" in classes):
            self.info += 1  # The edition box, and any div inside it.
        if tag == "table":
            self.depth += 1
        elif tag == "td":
            self.cell = next((name for name in ("td_size", "td_seeders", "td_leechers") if name in classes), None)
        elif tag == "a":
            if href.startswith("torrents.php?id=") and not self.row["details"]:
                self.row["details"] = href
                self.title = True
                found = re.search(r"[?&]torrentid=(\d+)", href)
                self.row["torrentid"] = found.group(1) if found else ""
            match = re.match(r"torrents\.php\?action=download&(?:amp;)?id=(\d+)", href)
            if match and not self.row["id"]:
                self.row["id"] = match.group(1)
        elif tag == "span" and "time" in classes and attrs.get("title") and not self.row["date"]:
            self.row["date"] = attrs["title"]
        elif tag == "strong" and "tl_free" in classes:
            self.row["free"] = True

    def handle_endtag(self, tag):
        if self.row is None:
            return
        if tag == "div" and self.info:
            self.info -= 1
        if tag == "a":
            self.title = False
        elif tag == "td":
            self.cell = None
        elif tag == "table":
            self.depth -= 1
        elif tag == "tr" and self.depth <= 0:
            if self.row["id"] and self.row["title"].strip():
                self.rows.append(self.row)
            self.row = None
            self.depth = 0

    def handle_data(self, data):
        if self.row is None:
            return
        if self.title:
            self.row["title"] += data
        if self.info == 1:  # The box's own text, not a div inside it.
            self.row["info"] += data
        key = {"td_size": "size", "td_seeders": "seeds", "td_leechers": "leech"}.get(self.cell)
        if key:
            self.row[key] += data


class umash_brokenstones(object):
    url = "https://brokenstones.is"
    name = "BrokenStones"
    # The site's categories (Jackett): 1 macOS apps, 2 macOS games, 3 iOS apps,
    # 4 iOS games, 5 graphics, 6 audio, 7 tutorials, 8 other.
    supported_categories = {
        "all": "",
        "games": "2,4",
        "music": "6",
        "pictures": "5",
        "software": "1,3",
    }

    pages = 3
    api = True  # Whether to try the JSON API before the search page.
    editions = True  # Whether JSON results get their edition text from the search page.
    pause = 2.1  # Gazelle allows 5 API requests in 10 seconds.
    timeout = 25
    download_path = re.compile(r"/torrents\.php\?action=download&id=\d+")

    def __init__(self):
        NoRedirects.site = self.name
        self.opener = urllib.request.build_opener(NoRedirects)

    def headers(self):
        cookie = os.environ.get("UMASH_LOGIN_COOKIE", "").strip()
        if not cookie:
            signed_out()
        headers = {"Cookie": cookie, "Accept-Encoding": "gzip"}
        # The sign-in window's browser identity; both sites refuse Python's own.
        headers["User-Agent"] = os.environ.get("UMASH_LOGIN_USER_AGENT", "") or _headers["User-Agent"]
        return headers

    def fetch(self, address, missing_ok=False):
        """Errors never include the login. With missing_ok, a 404 gives b""."""
        request = urllib.request.Request(address, headers=self.headers())
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return b""
            if error.headers.get("cf-mitigated") == "challenge":
                signed_out()
            if error.code in (401, 403):
                raise RuntimeError(f"{self.name} refused the request (HTTP {error.code}). If this keeps happening, try signing in again") from None
            if error.code == 429:
                raise RuntimeError(f"{self.name} is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"{self.name} answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach {self.name}: {error.reason}") from None
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data

    def categories(self, cat):
        return [("filter_cat[" + number + "]", "1") for number in self.supported_categories.get(cat, "").split(",") if number]

    def api_address(self, words, cat, page):
        params = [("action", "browse"), ("searchstr", words), ("order_by", "time"), ("order_way", "desc"), ("page", page)]
        return f"{self.url}/ajax.php?" + urllib.parse.urlencode(params + self.categories(cat))

    def page_address(self, words, cat, page):
        params = [("searchstr", words), ("action", "advanced"), ("group_results", "0"), ("order", "time"),
                  ("sort", "desc"), ("searchsubmit", "1"), ("page", page)]
        return f"{self.url}/torrents.php?" + urllib.parse.urlencode(self.categories(cat) + params)

    # The JSON API

    @staticmethod
    def date(value):
        """Unix time, or "2026-01-31 12:00:00" in UTC, as Gazelle sends it."""
        text = str(value or "").strip()
        if text.isdigit():
            return int(text)
        try:
            return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return -1

    def api_rows(self, found):
        rows = []
        for group in found.get("results") or []:
            if not isinstance(group, dict):
                continue
            title = " ".join(html.unescape(str(group.get("groupName") or "")).split())
            year = str(group.get("groupYear") or "")
            if year and year != "0":
                title += f" [{year}]"
            for torrent in group.get("torrents") or [group]:
                if not isinstance(torrent, dict) or not str(torrent.get("torrentId", "")).isdigit():
                    continue
                name = title
                extra = " ".join(html.unescape(str(torrent.get("remasterTitle") or "")).split())
                if extra:
                    name += f" [{extra}]"
                if torrent.get("isFreeleech") or torrent.get("isNeutralLeech") or torrent.get("isPersonalFreeleech"):
                    name += " [FreeLeech]"
                rows.append(self.row(int(torrent["torrentId"]), name, torrent.get("size", -1),
                                     torrent.get("seeders", -1), torrent.get("leechers", -1),
                                     self.date(torrent.get("time") or group.get("groupTime")),
                                     group.get("groupId")))
        return rows

    # The search page

    @staticmethod
    def page_date(text):
        """"Nov 09 2026, 10:32", in GMT, from the time's tooltip."""
        try:
            return int(datetime.strptime(" ".join(text.split()), "%b %d %Y, %H:%M").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return -1

    @staticmethod
    def count(text):
        text = text.strip().replace(",", "")
        return int(text) if text.isdigit() else -1

    def page_rows(self, data):
        parser = Rows()
        parser.feed(data.decode("utf-8", "replace"))
        rows = []
        for found in parser.rows:
            name = " ".join(found["title"].split())
            edition = clean_edition(found["info"])
            if edition:
                name += " " + edition
            if found["free"]:
                name += " [FreeLeech]"
            group = re.search(r"[?&]id=(\d+)", html.unescape(found["details"]))
            rows.append(self.row(int(found["id"]), name, plain_size(found["size"]) or -1,
                                 self.count(found["seeds"]), self.count(found["leech"]),
                                 self.page_date(found["date"]), group.group(1) if group else None))
        return rows

    def row(self, tid, name, size, seeds, leech, date, group):
        details = f"{self.url}/torrents.php?" + (f"id={group}&" if str(group or "").isdigit() else "") + f"torrentid={tid}"
        return {
            "id": tid,
            "link": f"{self.url}/torrents.php?action=download&id={tid}",
            "name": name,
            "size": str(size),
            "seeds": seeds,
            "leech": leech,
            "engine_url": self.url,
            "desc_link": details,
            "pub_date": date,
        }

    def editions_on_page(self, words, cat, page):
        """Each torrent's edition text ("26.5.1 [Intel/Pre-K'ed AiO by Macked]"),
        by torrent id, from the search page. The JSON API doesn't send it."""
        data = self.fetch(self.page_address(words, cat, page))
        if is_sign_in_page(data):
            signed_out()
        parser = Rows()
        parser.feed(data.decode("utf-8", "replace"))
        return {found["torrentid"] or found["id"]: clean_edition(found["info"]) for found in parser.rows if clean_edition(found["info"])}

    def add_editions(self, rows, words, cat, page):
        time.sleep(self.pause)
        try:
            editions = self.editions_on_page(words, cat, page)
        except RuntimeError:
            return  # Names without editions beat no results.
        for row in rows:
            edition = editions.get(str(row["id"]))
            if edition:
                plain, free = row["name"], row["name"].endswith(" [FreeLeech]")
                if free:
                    plain = plain[: -len(" [FreeLeech]")]
                row["name"] = f"{plain} {edition}" + (" [FreeLeech]" if free else "")

    def results(self, words, cat, page):
        """One page of results, and whether there are more."""
        data = self.fetch(self.api_address(words, cat, page), missing_ok=True) if self.api else b""
        try:
            found = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            found = None
        if isinstance(found, dict):
            if found.get("status") != "success" or not isinstance(found.get("response"), dict):
                reason = str(found.get("error") or "an error")
                if "login" in reason.lower() or "logged" in reason.lower():
                    signed_out()
                raise RuntimeError(f"{self.name}'s search answered with {reason}")
            response = found["response"]
            pages = response.get("pages")
            rows = self.api_rows(response)
            if rows and self.editions:
                self.add_editions(rows, words, cat, page)
            return rows, str(pages).isdigit() and page < int(pages)
        if is_sign_in_page(data):
            signed_out()
        # No JSON API: the search page, as a browser sees it.
        data = self.fetch(self.page_address(words, cat, page))
        if is_sign_in_page(data):
            signed_out()
        text = data.decode("utf-8", "replace")
        rows = self.page_rows(data)
        # Download links but no rows it can read: the layout changed. No links: no results.
        if not rows and "action=download" in text:
            raise RuntimeError(f"{self.name}'s search page has changed, so Umash can't read it")
        return rows, f"page={page + 1}" in text

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    def search(self, what, cat="all"):
        self.headers()
        words = " ".join(urllib.parse.unquote(what).split())
        first = self.setting("UMASH_START_PAGE", 1)
        seen = set()
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            if page > first:
                time.sleep(self.pause)
            try:
                rows, has_more = self.results(words, cat, page)
            except RuntimeError:
                if page > first:
                    self.more(page)  # Keep what the earlier pages found. Load More picks up from here.
                    return
                raise
            for row in rows:
                if row["id"] not in seen:
                    seen.add(row["id"])
                    prettyPrinter({key: value for key, value in row.items() if key != "id"})
            self.more(page + 1 if has_more and rows else 0)
            if not (has_more and rows):
                return

    def download_torrent(self, info):
        """Sends the login only to this site's own download address."""
        self.headers()
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError(f"That isn't a {self.name} download link, so Umash didn't send your login to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            if is_sign_in_page(data):
                signed_out()
            # Some Gazelle sites want the link from the torrent's page, with its keys.
            tid = info.rsplit("=", 1)[1]
            page = self.fetch(f"{self.url}/torrents.php?torrentid={tid}")
            if is_sign_in_page(page):
                signed_out()
            found = re.search(r'href="(torrents\.php\?action=download&(?:amp;)?id=' + tid + r'(?:&(?:amp;)?[A-Za-z_]+=[A-Za-z0-9]+)*)"',
                              page.decode("utf-8", "replace"))
            if found:
                data = self.fetch(f"{self.url}/" + html.unescape(found.group(1)))
        if not data.startswith(b"d"):
            raise RuntimeError(f"{self.name} didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
