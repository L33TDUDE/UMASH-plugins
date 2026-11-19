# VERSION: 1.2
# AUTHORS: Umash
#
# EZTV through its public JSON API (eztvx.to/api), which is not behind the
# Cloudflare check that blocks the site's search pages, and needs no login (the
# site's Login link is optional). The API is asked at eztvx.to first, then at the
# site's other addresses if that one doesn't answer, so a block on one doesn't end
# the search. A Cloudflare check or a rate limit is reported as such.
#
# The API has no text search, only "torrents for this IMDb id". So a search
# goes in two steps:
#   1. IMDb's public suggestion feed (the one imdb.com's search box uses)
#      turns the show name into IMDb ids. Only the show name is sent there.
#   2. The EZTV API lists each show's torrents.
# When no show matches (a release group like "MeGusta", a quality like "x265", a year),
# the newest 500 uploads are scanned for the words instead, 5 pages at once.
# "Severance S02E03", "severance s02" and "severance 2x03" narrow the results
# to that season or episode. The show name typed must be in a torrent's name:
# EZTV files some torrents under the wrong show (Breaking Brad under Breaking Bad).

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from helpers import _headers, retrieve_url
from novaprinter import prettyPrinter


class umash_eztv(object):
    url = "https://eztvx.to"
    name = "EZTV"
    supported_categories = {"all": "all", "tv": "tv"}

    # Tried in order. Only these addresses are ever asked for the list.
    api_hosts = ("https://eztvx.to", "https://eztv.wf", "https://eztv.tf", "https://eztv.yt")
    timeout = 25
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}(&[^\s\x00-\x1f\x7f-\x9f]*)?")
    host = None  # The address that last answered.
    suggest = "https://v2.sg.media-imdb.com/suggestion/{letter}/{query}.json"
    show_types = ("tvSeries", "tvMiniSeries")
    max_shows = 3
    page_size = 100
    # Pages per show: 3 without an episode filter (newest 300), up to 20 with one.
    pages_plain = 3
    pages_filtered = 20
    # When no show matches: how many pages of the newest uploads are scanned for the words.
    pages_recent = 5

    episode_patterns = (
        re.compile(r"\bs(\d{1,2})\s*e(\d{1,3})\b", re.I),
        re.compile(r"\b(\d{1,2})x(\d{1,3})\b", re.I),
        re.compile(r"\bs(\d{1,2})\b()", re.I),
        re.compile(r"\bseason\s*(\d{1,2})\b()", re.I),
    )

    @classmethod
    def split_query(cls, text):
        """'Severance S02E03' -> ('Severance', 2, 3). Season or episode may be None."""
        for pattern in cls.episode_patterns:
            match = pattern.search(text)
            if match:
                season = int(match.group(1))
                episode = int(match.group(2)) if match.group(2) else None
                show = (text[:match.start()] + " " + text[match.end():]).strip()
                return " ".join(show.split()), season, episode
        return " ".join(text.split()), None, None

    @staticmethod
    def get_json(url):
        text = retrieve_url(url, unescape_html_entities=False)
        if not text:
            raise RuntimeError("no answer from " + urllib.parse.urlsplit(url).netloc)
        try:
            return json.loads(text)
        except ValueError:
            raise RuntimeError(urllib.parse.urlsplit(url).netloc + " did not return JSON")

    def find_shows(self, show):
        """IMDb ids (digits only) of the TV shows that best match `show`."""
        cleaned = re.sub(r"[^\w\s'&-]", " ", show).strip().lower()
        if not cleaned:
            return []
        query = urllib.parse.quote(cleaned)
        data = self.get_json(self.suggest.format(letter=cleaned[0], query=query))
        ids = []
        for item in data.get("d", []):
            if item.get("qid") in self.show_types and str(item.get("id", "")).startswith("tt"):
                ids.append(item["id"][2:])
            if len(ids) == self.max_shows:
                break
        return ids

    def api_json(self, params):
        """EZTV's list for these parameters, from the first address that answers it."""
        last = "EZTV didn't answer"
        hosts = ([self.host] if self.host else []) + [h for h in self.api_hosts if h != self.host]
        for host in hosts:
            request = urllib.request.Request(f"{host}/api/get-torrents?{urllib.parse.urlencode(params)}",
                                             headers={**_headers, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    found = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as error:
                if error.headers.get("cf-mitigated") == "challenge":
                    last = "EZTV is asking this connection to pass Cloudflare's check, so its list can't be read right now"
                elif error.code == 429:
                    last = "EZTV is limiting requests from this connection. Try again later"
                else:
                    last = f"EZTV answered with HTTP {error.code}"
                continue
            except urllib.error.URLError as error:
                last = f"Couldn't reach EZTV: {error.reason}"
                continue
            except (OSError, ValueError):
                last = "EZTV sent something other than its list"
                continue
            if isinstance(found, dict) and ("torrents" in found or "torrents_count" in found):
                self.host = host
                return found
            last = "EZTV sent something other than its list"
        raise RuntimeError(last)

    def torrents(self, imdb_id, pages):
        first = self.api_json({"imdb_id": imdb_id, "limit": self.page_size, "page": 1})
        rows = list(first.get("torrents") or [])
        total = int(first.get("torrents_count") or 0)
        last = min(pages, -(-total // self.page_size))
        if last > 1:
            with ThreadPoolExecutor(4) as pool:
                for page in pool.map(lambda n: self.api_json({"imdb_id": imdb_id, "limit": self.page_size, "page": n}), range(2, last + 1)):
                    rows += page.get("torrents") or []
        return rows

    @staticmethod
    def words(text):
        return re.findall(r"[a-z0-9]+", text.lower().replace("'", ""))

    @classmethod
    def matches(cls, row, wanted, season, episode):
        name = " " + " ".join(cls.words(row.get("title") or row.get("filename") or "")) + " "
        if " " + wanted + " " not in name:
            return False
        if season is None:
            return True
        try:
            row_season, row_episode = int(row.get("season") or -1), int(row.get("episode") or 0)
        except ValueError:
            return False
        if row_season != season:
            return False
        # A season pack (episode 0) answers an episode search too.
        return episode is None or row_episode in (episode, 0)

    def show(self, row):
        prettyPrinter({
            "link": row.get("magnet_url"),
            "name": re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", row.get("title") or row.get("filename") or ""),
            "size": int(row.get("size_bytes") or -1),
            "seeds": int(row.get("seeds") or 0),
            "leech": int(row.get("peers") or 0),
            "engine_url": self.url,
            "desc_link": f"{self.url}/ep/{row.get('id')}/" if str(row.get("id", "")).isdigit() else "",
            "pub_date": int(row.get("date_released_unix") or -1),
        })

    def recent(self):
        """The newest uploads, pages_recent pages at once, newest first."""
        pages = [self.api_json({"limit": self.page_size, "page": 1})]
        total = int(pages[0].get("torrents_count") or 0)
        last = min(self.pages_recent, -(-total // self.page_size))
        if last > 1:
            with ThreadPoolExecutor(4) as pool:
                pages += list(pool.map(lambda n: self.api_json({"limit": self.page_size, "page": n}), range(2, last + 1)))
        return [row for page in pages for row in page.get("torrents") or []]

    def search(self, what, cat="all"):
        show, season, episode = self.split_query(urllib.parse.unquote(what))
        ids = self.find_shows(show)
        pages = self.pages_plain if season is None else self.pages_filtered
        seen = set()
        wanted = " ".join(self.words(show))
        shown = 0
        for imdb_id in ids:
            for row in self.torrents(imdb_id, pages):
                magnet = row.get("magnet_url") or ""
                if not self.safe_magnet.fullmatch(magnet) or row.get("hash") in seen or not self.matches(row, wanted, season, episode):
                    continue
                seen.add(row.get("hash"))
                self.show(row)
                shown += 1
        if shown or not wanted:
            return
        # No show by that name has torrents: the words may be in the newest uploads' names.
        for row in self.recent():
            magnet = row.get("magnet_url") or ""
            if not self.safe_magnet.fullmatch(magnet) or row.get("hash") in seen or not self.matches(row, wanted, season, episode):
                continue
            seen.add(row.get("hash"))
            self.show(row)
            shown += 1
        if not shown and not ids:
            print(f"EZTV: no TV show on IMDb matches '{show}'", file=sys.stderr)
