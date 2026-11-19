# VERSION: 1.0
# AUTHORS: Umash
#
# FitGirl Repacks (fitgirl-repacks.site): compressed PC game repacks, from tiny
# indie games to 100 GB+ blockbusters, each with its updates, DLC and bonus
# content. The magnet is the repack itself; installing is a separate step, as
# the site's own pages explain. Repacks are executables: only download them
# from the real site, which this plugin reads.
#
# A search asks the site's own WordPress API for posts whose TITLE contains
# your words, newest first, and takes each post's repack magnet from the
# post itself, so it never loads the site's pages, ads or download-host links.
# The API gives 40 repacks a page, up to 2 pages (80 results) per search;
# "load more" asks for the next ones. The posts that list the day's updated
# games, blog posts, off-topic files and anything without a torrent are left out. The size
# shown is the repack size on the site: for repacks with optional parts
# ("Selective Download") that is the smallest download, as the site's own
# titles say ("from 49.5 GB"). The date is the day the repack was posted or
# last updated. The site shows no seed counts.
#
# FitGirl posts games only, so "all" and "games" are the same search; adult
# games are left out when Umash's setting to hide adult results is on.

import calendar
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_fitgirl(object):
    url = "https://fitgirl-repacks.site"
    name = "FitGirl Repacks"
    supported_categories = {"all": "", "games": ""}
    api = "https://fitgirl-repacks.site/wp-json/wp/v2/posts"
    per_page = 40
    pages = 2
    timeout = 40
    # The site's own category and tag numbers: "Updates Digest" (daily lists of
    # updated games), "Russian Movies", and the "Adult" tag.
    digest_category = 46
    movies_category = 41
    adult_tag = 141
    uncategorized = 1

    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")
    mirrors = re.compile(r"Download Mirrors \(Torrent\)", re.I)
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[^"]+)"')
    # "Repack Size: 2.4 GB", "from 49.5 GB [Selective Download]" or "324/585 MB" (smallest first).
    size_line = re.compile(r"Repack Size:\s*(?:<[^>]+>\s*)*([^<\n]{1,60})", re.I)
    size_number = re.compile(r"([\d][\d.,]*)\s*(?:[/~-]\s*[\d.,]+\s*)?([KMGT]B)", re.I)

    @staticmethod
    def setting(name, default):
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def fetch(self, query, page):
        params = [
            ("search", query), ("search_columns", "post_title"), ("orderby", "date"), ("order", "desc"),
            ("per_page", self.per_page), ("page", page),
            ("categories_exclude", f"{self.digest_category},{self.movies_category}"),
            ("_fields", "id,date_gmt,link,title,content,categories"),
        ]
        if os.environ.get("UMASH_HIDE_ADULT") == "1":
            params.append(("tags_exclude", self.adult_tag))
        headers = dict(_headers)
        headers["Accept"] = "application/json"
        request = urllib.request.Request(self.api + "?" + urllib.parse.urlencode(params), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            if error.code == 400:
                return []  # WordPress answers 400 for a page past the last one.
            raise RuntimeError(f"FitGirl Repacks answered HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as error:
            raise RuntimeError(f"FitGirl Repacks didn't answer: {error}")

    @staticmethod
    def date(text):
        try:
            return calendar.timegm(time.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            return -1

    def show(self, post):
        # A post filed only under "Uncategorized" is a blog post or an off-topic file, not a repack.
        if set(post.get("categories") or [1]) <= {self.uncategorized}:
            return False
        content = ((post.get("content") or {}).get("rendered")) or ""
        link_page = str(post.get("link", ""))
        start = self.mirrors.search(content)
        found = self.magnet.search(content, start.end() if start else 0)
        if not found:
            return False
        link = html.unescape(found.group(1))
        if not self.safe_magnet.fullmatch(link) or not link.startswith("magnet:?xt=urn:btih:"):
            return False
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", "", (post.get("title") or {}).get("rendered", ""))).split())
        named = re.search(r"[?&]dn=([^&]+)", link)
        name = " ".join(urllib.parse.unquote_plus(named.group(1)).split()) if named else ""
        line = self.size_line.search(content)
        number = self.size_number.search(line.group(1)) if line else None
        prettyPrinter({
            "link": link,
            "name": name or title,
            "size": number.group(1).replace(",", "") + " " + number.group(2) if number else -1,
            "seeds": -1,
            "leech": -1,
            "engine_url": self.url,
            "desc_link": link_page if link_page.startswith(self.url + "/") else self.url,
            "pub_date": self.date(post.get("date_gmt")),
        })
        return True

    def search(self, what, cat="all"):
        query = " ".join(urllib.parse.unquote(what).split())
        if not query:
            return
        first = self.setting("UMASH_START_PAGE", 1)
        last = first + self.setting("UMASH_MAX_PAGES", self.pages)
        seen = set()
        for page in range(first, last):
            try:
                posts = self.fetch(query, page)
            except RuntimeError:
                if page > first:
                    return  # Keep what the earlier pages found. Load More picks up from here.
                raise
            if not isinstance(posts, list):
                posts = []
            for post in posts:
                if isinstance(post, dict) and post.get("id") not in seen:
                    seen.add(post.get("id"))
                    self.show(post)
            has_more = len(posts) >= self.per_page
            self.more(page + 1 if has_more else 0)
            if not has_more:
                return

    def download_torrent(self, link):
        if not self.safe_magnet.fullmatch(link):
            raise ValueError("not a FitGirl Repacks magnet")
        print(link + " " + link)
