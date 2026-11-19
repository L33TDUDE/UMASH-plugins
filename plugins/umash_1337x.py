# VERSION: 1.0
# AUTHORS: Umash
# LOGIN: https://1337x.to/ | cf_clearance
#
# 1337x (1337x.to), a large public torrent site, read from the site's own search pages. The
# site shows every program a Cloudflare check, which the sign-in window passes the way a
# browser does: open the plugin's sign-in, wait for the site to load, and Umash keeps the
# Cloudflare pass (no account exists or is needed). Best-seeded first, up to 5 pages of 20.
# The magnet is on each torrent's own page, so it is fetched only when you download one.
# The search follows Jackett's and Prowlarr's 1337x indexers.

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
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from novaprinter import prettyPrinter

SIGNED_OUT = 4  # Umash's "this plugin needs signing in again".


def signed_out():
    sys.exit(SIGNED_OUT)


def on_site(link, domain):
    """An HTTPS address on the site or one of its subdomains."""
    parts = urllib.parse.urlsplit(link)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == domain or host.endswith("." + domain))


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follows the site's own redirects. Nothing else is followed, so the login can't
    reach another address. Being sent to the sign-in page means signed out."""

    def __init__(self, site):
        super().__init__()
        self.site = site

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if self.site.sign_in_page.search(urllib.parse.urlsplit(target).path):
            signed_out()
        if not on_site(target, self.site.domain):
            raise RuntimeError(f"{self.site.name} sent Umash to another site instead of answering, so the site may have changed")
        return super().redirect_request(req, fp, code, msg, headers, target)


class Node(object):
    """One element of a page, with what is inside it."""

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.children = []
        self.parent = parent

    def get(self, name):
        return self.attrs.get(name) or ""

    def has_class(self, name):
        return name in self.get("class").split()

    def elements(self):
        """Every element inside this one, in page order."""
        stack = [child for child in reversed(self.children) if isinstance(child, Node)]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(child for child in reversed(node.children) if isinstance(child, Node))

    def find_all(self, tag=None, cls=None, test=None):
        return [node for node in self.elements()
                if (tag is None or node.tag == tag) and (cls is None or node.has_class(cls)) and (test is None or test(node))]

    def find(self, tag=None, cls=None, test=None):
        found = self.find_all(tag, cls, test)
        return found[0] if found else None

    def text(self):
        parts = []
        stack = [self]
        while stack:
            item = stack.pop()
            if isinstance(item, Node):
                stack.extend(reversed(item.children))
            else:
                parts.append(item)
        return " ".join("".join(parts).split())

    def cells(self):
        return [child for child in self.children if isinstance(child, Node) and child.tag in ("td", "th")]


class Page(HTMLParser):
    """Reads a page the way a browser does, closing what the server leaves open,
    such as </td> and </tr>."""

    empty = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    # A new one of these ends the one still open, up to the boundary.
    ends = {"td": ({"td", "th"}, {"tr", "table"}), "th": ({"td", "th"}, {"tr", "table"}),
            "tr": ({"tr"}, {"table"}), "tbody": ({"tbody", "thead", "tfoot"}, {"table"}),
            "thead": ({"tbody", "thead", "tfoot"}, {"table"}), "option": ({"option"}, {"select"}),
            "li": ({"li"}, {"ul", "ol"})}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("#page", {}, None)
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in self.ends:
            closing, boundary = self.ends[tag]
            for index in range(len(self.stack) - 1, 0, -1):
                name = self.stack[index].tag
                if name in boundary:
                    break
                if name in closing:
                    del self.stack[index:]
                    break
        node = Node(tag, {name: value or "" for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.empty:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.empty and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            name = self.stack[index].tag
            if name == tag:
                del self.stack[index:]
                return
            # A stray end tag doesn't reach out of a table.
            if name == "table":
                return

    def handle_data(self, data):
        if self.stack[-1].tag not in ("script", "style"):
            self.stack[-1].children.append(data)


class SignInSite(object):
    """What every site Umash signs in to shares: the login goes only to the site,
    errors never include it, and a page without the signed-in mark means signing in again."""

    url = ""
    name = ""
    domain = ""
    charset = "utf-8"
    timeout = 20
    pages = 10
    per_page = 50
    pause = 0.3
    signed_in = ()  # Text only a signed-in page has.
    sign_in_page = re.compile(r"/login(?:\.php)?/?$", re.I)
    extra_cookie = ""
    units = {"b": 1, "б": 1, "k": 1024, "к": 1024, "m": 1024 ** 2, "м": 1024 ** 2, "g": 1024 ** 3, "г": 1024 ** 3, "t": 1024 ** 4, "т": 1024 ** 4}

    def __init__(self):
        if not self.domain:
            host = urllib.parse.urlsplit(self.url).hostname or ""
            self.domain = host[4:] if host.startswith("www.") else host
        self.opener = urllib.request.build_opener(SameSiteRedirects(self))

    def headers(self):
        cookie = os.environ.get("UMASH_LOGIN_COOKIE", "").strip()
        if not cookie:
            signed_out()
        if self.extra_cookie:
            cookie += "; " + self.extra_cookie
        headers = {"Cookie": cookie, "Accept": "text/html,application/xhtml+xml,*/*", "Accept-Encoding": "gzip"}
        agent = os.environ.get("UMASH_LOGIN_USER_AGENT", "")
        if agent:
            headers["User-Agent"] = agent
        return headers

    def fetch(self, url, data=None, extra=None):
        """Sends the login only to the site itself. Errors never include it."""
        if not on_site(url, self.domain):
            raise RuntimeError(f"That isn't a {self.name} address, so Umash didn't send your login to it")
        request = urllib.request.Request(url, data=data, headers={**self.headers(), **(extra or {})})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            # A Cloudflare check: signing in again in the window passes it.
            if error.headers.get("cf-mitigated") == "challenge":
                signed_out()
            if error.code in (401, 403):
                raise RuntimeError(f"{self.name} refused the request (HTTP {error.code}). If this keeps happening, try signing in again") from None
            if error.code == 429:
                raise RuntimeError(f"{self.name} is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"{self.name} answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach {self.name}: {error.reason}") from None
        return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body

    def page(self, url, data=None, extra=None):
        """A signed-in page, read into elements."""
        text = self.fetch(url, data, extra).decode(self.charset, "replace")
        if not self.is_signed_in(text):
            signed_out()
        return text, Page(text).root

    def is_signed_in(self, text):
        return any(mark in text for mark in self.signed_in)

    def changed(self):
        return RuntimeError(f"{self.name}'s results page has changed, so Umash can't read it")

    def link(self, href):
        """An address on the page, made whole."""
        return urllib.parse.urljoin(self.url + "/", href.strip())

    def encode(self, words):
        return urllib.parse.quote(words.encode(self.charset, "ignore"), safe="")

    @staticmethod
    def number(text):
        digits = re.sub(r"\D", "", text or "")
        return int(digits) if digits else -1

    def size(self, text):
        """Bytes, from "1.37 GB", "700 МБ", "1,4 ГБ" or plain bytes."""
        text = (text or "").replace("\xa0", " ").strip()
        if text.isdigit():
            return text
        found = re.search(r"(\d+(?:[.,]\d+)?)\s*([KkMmGgTtКкМмГгТт]?)(?:i?[BbБб]|$)", text)
        if not found:
            return "-1"
        unit = found.group(2).lower() or "b"
        return str(int(float(found.group(1).replace(",", ".")) * self.units[unit]))

    site_zone = timezone.utc
    today = ("сегодня", "сьогодні", "today", "hoy")
    yesterday = ("вчера", "вчора", "yesterday", "ayer")
    months = {name: number for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
    # In order: "годин" is Ukrainian for hours, "год" Russian for a year.
    ages = ((r"min|мин|хв", 60), (r"hour|hora|час|годин", 3600), (r"day|día|dia|дн|ден", 86400),
            (r"week|semana|недел|тиж", 604800), (r"month|mes|месяц|місяц", 2629800), (r"year|año|ano|год|лет|рік|рок", 31557600))

    def date(self, text):
        """A Unix time from the ways sites show dates, in the site's own time zone."""
        text = " ".join((text or "").lower().split())
        clock = re.search(r"(\d{1,2}):(\d\d)(?::(\d\d))?", text)
        hour, minute, second = (int(clock.group(1)), int(clock.group(2)), int(clock.group(3) or 0)) if clock else (0, 0, 0)
        now = datetime.now(self.site_zone)
        found = re.search(r"(\d{4})-(\d\d)-(\d\d)", text)
        named = re.search(r"\b(\d{1,2}) ([a-z]{3})[a-z]* '?(\d{2,4})\b", text)
        if found:
            year, month, day = (int(part) for part in found.groups())
        elif re.search(r"\d\d\.\d\d\.\d{2,4}", text):
            day, month, year = (int(part) for part in re.search(r"(\d\d)\.(\d\d)\.(\d{2,4})", text).groups())
        elif named and named.group(2) in self.months:
            day, month, year = int(named.group(1)), self.months[named.group(2)], int(named.group(3))
        elif any(word in text for word in self.today + self.yesterday):
            when = now - timedelta(days=1) if any(word in text for word in self.yesterday) else now
            year, month, day = when.year, when.month, when.day
        else:
            return self.age(text)
        if year < 100:
            year += 2000
        try:
            return int(datetime(year, month, day, hour, minute, second, tzinfo=self.site_zone).timestamp())
        except ValueError:
            return -1

    def age(self, text):
        """An approximate date from "3 days ago", "hace 2 semanas" and the like."""
        found = re.search(r"(\d+(?:[.,]\d+)?)\s*([^\d\s]+)", text)
        if not found:
            return -1
        for pattern, seconds in self.ages:
            if re.match(pattern, found.group(2)):
                return int(time.time() - float(found.group(1).replace(",", ".")) * seconds)
        return -1

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
        words = " ".join(urllib.parse.unquote(what).split())
        first = self.setting("UMASH_START_PAGE", 1)
        hiding = os.environ.get("UMASH_HIDE_ADULT") == "1"
        seen = set()
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            if page > first:
                time.sleep(self.pause)
            try:
                rows, more = self.results(words, cat, page)
            except RuntimeError:
                # Keep what the earlier pages found. Load More picks up from here.
                if page > first:
                    return
                raise
            fresh = [row for row in rows if row["link"] not in seen]
            seen.update(row["link"] for row in fresh)
            for row in fresh:
                adult = row.pop("adult", False)
                if not (hiding and adult):
                    prettyPrinter(dict(row, engine_url=self.url))
            if not fresh or not more or page >= self.pages:
                self.more(0)
                return
            self.more(page + 1)

    def download_torrent(self, info):
        """Sends the login only to this site's own download addresses."""
        self.headers()
        if not on_site(info, self.domain) or not self.download_link.fullmatch(info):
            raise RuntimeError(f"That isn't a {self.name} download link, so Umash didn't send your login to it")
        data = self.torrent(info)
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)

    def torrent(self, info):
        return self.checked(self.fetch(info))

    def checked(self, data):
        if not data.startswith(b"d"):
            if not self.is_signed_in(data[:400000].decode(self.charset, "replace")):
                signed_out()
            raise RuntimeError(f"{self.name} didn't send a torrent file for this result")
        return data


class umash_1337x(SignInSite):
    url = "https://1337x.to"
    name = "1337x"
    pages = 5
    per_page = 20
    pause = 1.0  # The site limits quick requests.
    # The site's own category names. "books" is part of its Other group and is narrowed below.
    supported_categories = {
        "all": "",
        "anime": "Anime",
        "books": "Other",
        "games": "Games",
        "movies": "Movies",
        "music": "Music",
        "software": "Apps",
        "tv": "TV",
    }
    adult_subs = {"48", "49", "50", "51", "67"}
    book_subs = {"34", "36", "39", "52"}
    torrent_page = re.compile(r"https://1337x\.to/torrent/\d+/[^/\s?#]*/?")
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[^"\s]+)"')
    # Checked after unescaping, which can turn &#10; into a line break: this line
    # is Umash's only instruction about what to open.
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")
    months = {name: number for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}

    def is_signed_in(self, text):
        """There is no account: a page that is the site's own, not Cloudflare's check, is enough."""
        head = text[:6000].lower()
        return "1337x" in head and "just a moment" not in head and "cf-chl" not in text[:20000].lower()

    @staticmethod
    def title_from(link, shown):
        """The listing shortens long names with an ellipsis; the address holds the whole one."""
        if "..." not in shown and "\u2026" not in shown:
            return shown
        slug = urllib.parse.unquote(link.rstrip("/").rsplit("/", 1)[-1])
        slug = re.sub(r"-([\w\[\]()]+)$", r"~\1", slug).replace("-", " ")
        return re.sub(r"~([\w\[\]()]+)$", r"-\1", slug).strip() or shown

    def published(self, text):
        """"12:25am" (today), "7am Sep. 14th" (this year) or "Apr. 18th '11" (an older year)."""
        text = " ".join((text or "").lower().replace("\xa0", " ").split())
        now = datetime.now(timezone.utc)
        clock = re.search(r"(\d{1,2})(?::(\d\d))?\s*([ap])m", text)
        hour, minute = 0, 0
        if clock:
            hour, minute = int(clock.group(1)) % 12 + (12 if clock.group(3) == "p" else 0), int(clock.group(2) or 0)
        day = re.search(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+'(\d\d))?", text)
        try:
            if day and day.group(1) in self.months:
                year = 2000 + int(day.group(3)) if day.group(3) else now.year
                return int(datetime(year, self.months[day.group(1)], int(day.group(2)), hour, minute, tzinfo=timezone.utc).timestamp())
            if clock:
                return int(now.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp())
        except ValueError:
            return -1
        return -1

    def results(self, words, cat, page):
        category = self.supported_categories.get(cat, "")
        query = urllib.parse.quote(words, safe="")
        if category:
            path = f"/sort-category-search/{query}/{category}/seeders/desc/{page}/"
        else:
            path = f"/sort-search/{query}/seeders/desc/{page}/"
        text, root = self.page(self.url + path)
        hiding = os.environ.get("UMASH_HIDE_ADULT") == "1"
        rows = []
        for row in root.find_all("tr", test=lambda node: node.find("a", test=lambda a: a.get("href").startswith("/torrent/")) is not None):
            first = next((cell for cell in row.cells() if cell.has_class("coll-1")), None)
            if first is None:
                continue
            link = first.find("a", test=lambda a: a.get("href").startswith("/torrent/"))
            sub = first.find("a", test=lambda a: a.get("href").startswith("/sub/"))
            sub_id = sub.get("href").strip("/").split("/")[1] if sub is not None and sub.get("href").count("/") >= 2 else ""
            if cat == "books" and sub_id and sub_id not in self.book_subs:
                continue
            by_class = {name: next((cell for cell in row.cells() if cell.has_class(name)), None)
                        for name in ("coll-2", "coll-3", "coll-4", "coll-date")}
            if not link or not all(by_class.values()):
                continue
            href = self.link(link.get("href"))
            if not self.torrent_page.fullmatch(href):
                continue
            rows.append({
                "link": href,
                "name": " ".join(self.title_from(href, link.text()).split()),
                "size": self.size(by_class["coll-4"].text()),
                "seeds": max(self.number(by_class["coll-2"].text()), 0),
                "leech": max(self.number(by_class["coll-3"].text()), 0),
                "desc_link": href,
                "pub_date": self.published(by_class["coll-date"].text()),
                "adult": sub_id in self.adult_subs,
            })
        if not rows and "/torrent/" in text:
            raise self.changed()
        return rows, len(rows) >= self.per_page

    def download_torrent(self, info):
        """Reads the magnet from the torrent's own page, on this site only."""
        self.headers()
        if not self.torrent_page.fullmatch(info):
            raise RuntimeError("That isn't a 1337x torrent page, so Umash didn't send the Cloudflare pass to it")
        text = self.fetch(info).decode(self.charset, "replace")
        if not self.is_signed_in(text):
            signed_out()
        found = self.magnet.search(text)
        magnet = html.unescape(found.group(1)) if found else ""
        if not self.safe_magnet.fullmatch(magnet):
            raise RuntimeError("1337x's page has no magnet, or one that looks wrong")
        print(magnet + " " + info)
