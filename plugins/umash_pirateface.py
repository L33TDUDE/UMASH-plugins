# VERSION: 1.0
# AUTHORS: Umash
#
# Pirate Face (pirateface.co), community torrents of open AI models (LLMs and others, mirrored
# from Hugging Face). No account needed. It uses the plain-text search the site documents for
# terminal use on its How it works page: pirateface.co/s/<words> answers one line per model that has
# a torrent: name, size, seeds, then the magnet. The site gives no leechers or dates, and no
# further pages. The date comes from each model's own page, where the site shows when it
# "Witnessed" the model (recorded its checksums). Those pages are big, so they are read a few at a
# time within a time limit and the dates are kept in a small cache file: a first search may show
# some results without a date, and the next search fills in the rest. Models whose license needs
# the downloader to accept terms first have no magnet in the list, so they don't show here. The size
# is the site's rounded figure. The magnets carry the site's own trackers and Hugging Face web seeds.

import calendar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

from novaprinter import prettyPrinter


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Only the site's own redirects are followed."""

    def __init__(self, site):
        super().__init__()
        self.site = urllib.parse.urlsplit(site)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if (target.scheme, target.netloc) != (self.site.scheme, self.site.netloc):
            raise RuntimeError("Pirate Face sent Umash to another site instead of answering, so Umash stopped")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class umash_pirateface(object):
    url = "https://pirateface.co"
    name = "Pirate Face"
    # Models are searched in one list: the site has no categories.
    supported_categories = {
        "all": "",
    }

    timeout = 25
    # The dates: pages read at once, the most pages read in a search, the time they may take in
    # all, and how long a date is kept. The page is read up to this many bytes.
    workers = 8
    most_pages = 40
    date_budget = 10
    keep_days = 14
    page_bytes = 700000
    cache_file = os.path.join(os.path.expanduser("~"), "Library", "Caches", "UMash", "pirateface-dates.json")
    witnessed = re.compile(r"<dt>Witnessed</dt><dd>(\d{1,2}) ([A-Za-z]{3,9}) (\d{4}), (\d{1,2}):(\d{2}) UTC</dd>")
    months = {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}
    # name, size, seeds, magnet, separated by spaces. Model names never hold a space.
    line = re.compile(r"^(\S+)\s+([\d.,]+)\s*([A-Za-z]+)\s+(\d+)\s+seeds?\s+(magnet:\?xt=urn:btih:([0-9A-Za-z]{32,40})(?:&\S*)?)$")
    units = {"b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
             "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}

    def __init__(self):
        self.opener = urllib.request.build_opener(SameSiteRedirects(self.url))

    def address(self, what):
        # A slash would make the site answer with a web page, so words are split on it.
        words = " ".join(urllib.parse.unquote(what).replace("/", " ").split())
        return f"{self.url}/s/{urllib.parse.quote_plus(words)}"

    def fetch(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "Umash", "Accept": "text/plain"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise RuntimeError("Pirate Face is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"Pirate Face answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach Pirate Face: {error.reason}") from None

    def size(self, number, unit):
        factor = self.units.get(unit.lower())
        if not factor:
            return "-1"
        try:
            return str(int(float(number.replace(",", "")) * factor))
        except ValueError:
            return "-1"

    def read(self, text):
        """The results in the site's list, or an error when it sent something else."""
        if re.match(r"\s*<(!doctype|html)", text[:200], re.I):
            raise RuntimeError("Pirate Face sent a web page instead of search results")
        found = []
        for raw in text.splitlines():
            match = self.line.match(raw.strip())
            if match:
                found.append(match)
        if not found and text.strip() and not text.lstrip().startswith("No torrents match"):
            raise RuntimeError("Pirate Face sent something other than search results")
        return found

    def date_in(self, page):
        """The "Witnessed" time on a model page as a Unix time, or -1."""
        match = self.witnessed.search(page)
        month = self.months.get(match.group(2)[:3].lower()) if match else None
        if not match or not month:
            return -1
        try:
            return calendar.timegm((int(match.group(3)), month, int(match.group(1)), int(match.group(4)), int(match.group(5)), 0))
        except (ValueError, OverflowError):
            return -1

    def date_of(self, repo):
        """One model's date from its page, or -1 when it can't be read."""
        try:
            request = urllib.request.Request(f"{self.url}/{urllib.parse.quote(repo)}", headers={"User-Agent": "Umash", "Accept": "text/html"})
            with self.opener.open(request, timeout=self.timeout) as response:
                return self.date_in(response.read(self.page_bytes).decode("utf-8", "replace"))
        except (RuntimeError, OSError, ValueError):
            return -1

    def load_cache(self):
        try:
            with open(self.cache_file, encoding="utf-8") as file:
                found = json.load(file)
            return found if isinstance(found, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_cache(self, cache):
        """Keeps the cache small and forgets nothing it can't write: a missing cache only costs time."""
        try:
            now = time.time()
            fresh = {repo: entry for repo, entry in cache.items()
                     if isinstance(entry, list) and len(entry) == 2 and now - entry[1] < self.keep_days * 86400}
            newest = dict(sorted(fresh.items(), key=lambda item: item[1][1], reverse=True)[:5000])
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            temporary = self.cache_file + f".{os.getpid()}"
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump(newest, file)
            os.replace(temporary, self.cache_file)
        except OSError:
            pass

    def dates_for(self, repos):
        """Date by model name. Known ones come from the cache, the rest are read within the limits."""
        cache = self.load_cache()
        now = time.time()
        dates = {}
        missing = []
        for repo in repos:
            entry = cache.get(repo)
            if isinstance(entry, list) and len(entry) == 2 and now - entry[1] < self.keep_days * 86400:
                dates[repo] = int(entry[0])
            else:
                missing.append(repo)
        missing = missing[:self.most_pages]
        if missing:
            pool = ThreadPoolExecutor(max_workers=self.workers)
            jobs = {pool.submit(self.date_of, repo): repo for repo in missing}
            done, _ = wait(jobs, timeout=self.date_budget)
            for job in done:
                value = job.result()
                if value > 0:
                    dates[jobs[job]] = value
                    cache[jobs[job]] = [value, now]
            pool.shutdown(wait=False, cancel_futures=True)
            self.save_cache(cache)
        return dates

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def search(self, what, cat="all"):
        seen = set()
        found = []
        for match in self.read(self.fetch(self.address(what))):
            if match.group(6).lower() not in seen:
                seen.add(match.group(6).lower())
                found.append(match)
        dates = self.dates_for([match.group(1) for match in found])
        for match in found:
            repo, number, unit, seeds, magnet, infohash = match.groups()
            prettyPrinter({
                "link": magnet,
                "name": repo,
                "size": self.size(number, unit),
                "seeds": int(seeds),
                "leech": -1,
                "engine_url": self.url,
                "desc_link": f"{self.url}/{urllib.parse.quote(repo)}",
                "pub_date": dates.get(repo, -1),
            })
        self.more(0)  # One list, no further pages.
