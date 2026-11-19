# VERSION: 1.0
# AUTHORS: Umash
# SETTING: mamid | secret required | Session ID (mam_id) | On myanonamouse.net open Preferences, then Security, and fill in Create session: leave your current IP in the IP box, choose ASN if your IP changes (a home connection), leave the dynamic seedbox option on No, and click Submit changes. The page then shows the new session's ID, a long string of letters and numbers: copy all of it and paste it here. | https://www.myanonamouse.net/preferences/index.php?view=security
#
# MyAnonamouse (myanonamouse.net), a private audiobook and ebook tracker, through the same
# JSON search its site page uses, the way Jackett and Prowlarr search it. Names read
# Title by Author [Language / Format]. Up to 3 pages of 100. The session ID goes in a request
# header, never in a link. Downloads use no freeleech wedges. A session ID belongs to the IP (or the
# provider, if you made it ASN-locked) it was made for: if the site refuses it, create a new session.

import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape

from helpers import _headers
from novaprinter import prettyPrinter


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry the session: only the site's own redirects are followed."""

    def __init__(self, site):
        super().__init__()
        self.site = urllib.parse.urlsplit(site)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if "/login" in target.path or "/lostPw" in target.path:
            raise RuntimeError("MyAnonamouse refused the session ID. Make a new one in the plugin's Settings")
        if (target.scheme, target.netloc) != (self.site.scheme, self.site.netloc):
            raise RuntimeError("MyAnonamouse sent Umash to another site instead of answering, so Umash stopped")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class umash_myanonamouse(object):
    url = "https://www.myanonamouse.net"
    name = "MyAnonamouse"
    # The site's main categories: 13 audiobooks, 14 ebooks, 15 musicology (music and sheet music), 16 radio.
    supported_categories = {
        "all": "",
        "books": "13,14",
        "music": "15,16",
    }

    per_page = 100
    pages = 3
    timeout = 25
    download_path = re.compile(r"/tor/download\.php\?tid=\d+")
    units = {"b": 1, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4,
             "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4}

    def __init__(self):
        self.opener = urllib.request.build_opener(SameSiteRedirects(self.url))

    def session(self):
        value = os.environ.get("UMASH_SETTING_MAMID", "").strip()
        if not value:
            raise RuntimeError("MyAnonamouse needs your session ID: add it in the plugin's Settings")
        if not re.fullmatch(r"[A-Za-z0-9%+/=_.\-]+", value):
            raise RuntimeError("That session ID has characters MyAnonamouse's never use. Copy it again in the plugin's Settings")
        return value

    def refused(self, code):
        if code in (401, 403):
            return "MyAnonamouse refused the session ID. Make a new one for your current IP in the plugin's Settings"
        if code == 429:
            return "MyAnonamouse is limiting requests from this connection. Try again later"
        return f"MyAnonamouse answered with HTTP {code}"

    def fetch(self, url):
        headers = {**_headers, "Cookie": "mam_id=" + self.session(), "Accept": "application/json, */*"}
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code)) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach MyAnonamouse: {error.reason}") from None

    def address(self, what, cat, page):
        params = [("tor[text]", " ".join(urllib.parse.unquote(what).split())), ("tor[searchType]", "all"),
                  ("tor[srchIn][title]", "true"), ("tor[srchIn][author]", "true"), ("tor[srchIn][narrator]", "true"),
                  ("tor[searchIn]", "torrents"), ("tor[sortType]", "seedersDesc"),
                  ("tor[startNumber]", (page - 1) * self.per_page), ("perpage", self.per_page)]
        wanted = [number for number in self.supported_categories.get(cat, "").split(",") if number]
        if wanted:
            # Main categories go in main_cat. The cat parameter holds sub-category ids, so 13-16 there match nothing.
            params += [(f"tor[main_cat][{index}]", number) for index, number in enumerate(wanted)]
        else:
            params.append(("tor[cat][]", "0"))
        return f"{self.url}/tor/js/loadSearchJSONbasic.php?{urllib.parse.urlencode(params)}"

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError("MyAnonamouse sent something other than search results. If it keeps happening, make a new session ID") from None
        if not isinstance(found, dict):
            raise RuntimeError("MyAnonamouse sent something other than search results")
        error = str(found.get("error") or "")
        if error.startswith("Nothing returned"):
            return []
        if not isinstance(found.get("data"), list):
            if "parked" in error.lower():
                raise RuntimeError("MyAnonamouse says your account is parked, so it won't search. Unpark it on the site (Preferences, then Account), then try again")
            if error and "session" not in error.lower() and "login" not in error.lower():
                raise RuntimeError("MyAnonamouse said: " + " ".join(error.split())[:200])
            raise RuntimeError(self.refused(401) if error else "MyAnonamouse sent something other than search results")
        return found["data"]

    def size(self, text):
        found = re.fullmatch(r"\s*([\d.,]+)\s*([A-Za-z]*)\s*", str(text or ""))
        if not found:
            return "-1"
        unit = self.units.get(found.group(2).lower() or "b")
        if not unit:
            return "-1"
        try:
            return str(int(float(found.group(1).replace(",", "")) * unit))
        except ValueError:
            return "-1"

    @staticmethod
    def people(text, limit=5):
        try:
            found = json.loads(text) if text else {}
        except ValueError:
            return ""
        return ", ".join(unescape(str(name)) for name in list(found.values())[:limit]) if isinstance(found, dict) else ""

    @staticmethod
    def date(text):
        try:
            return int(datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            return -1

    @staticmethod
    def number(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def show(self, row):
        tid = str(row.get("id", ""))
        if not tid.isdigit():
            return
        name = " ".join(unescape(str(row.get("title") or "N/A")).split())
        author = self.people(row.get("author_info"))
        if author:
            name += f" by {author}"
        flags = [flag for flag in (str(row.get("lang_code") or ""), str(row.get("filetype") or "").upper()) if flag]
        if flags:
            name += " [" + " / ".join(flags) + "]"
        if row.get("vip"):
            name += " [VIP]"
        if row.get("free") or row.get("personal_freeleech"):
            name += " [FreeLeech]"
        prettyPrinter({
            "link": f"{self.url}/tor/download.php?tid={tid}",
            "name": name,
            "size": self.size(row.get("size")),
            "seeds": self.number(row.get("seeders")),
            "leech": self.number(row.get("leechers")),
            "engine_url": self.url,
            "desc_link": f"{self.url}/t/{tid}",
            "pub_date": self.date(row.get("added")),
        })

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
        self.session()
        first = self.setting("UMASH_START_PAGE", 1)
        for page in range(first, first + self.setting("UMASH_MAX_PAGES", self.pages)):
            try:
                rows = self.read(self.fetch(self.address(what, cat, page)))
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            for row in rows:
                self.show(row)
            full = len(rows) >= self.per_page
            self.more(page + 1 if full else 0)
            if not full:
                return

    def download_torrent(self, info):
        """Sends the session only to this site's own download address."""
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a MyAnonamouse download link, so Umash didn't send your session to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            raise RuntimeError("MyAnonamouse didn't send a torrent file for this result. Your session ID may be for another IP")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
