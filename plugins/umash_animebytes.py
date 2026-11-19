# VERSION: 1.0
# AUTHORS: Umash
# SETTING: username | text required | Username | Your AnimeBytes username.
# SETTING: passkey | secret required | Passkey | Not your password. On your AnimeBytes profile, under Settings and Access, copy the Torrent Passkey. | https://animebytes.tv/user.php?action=edit
#
# AnimeBytes (animebytes.tv), a private anime, manga, game and music tracker, through its
# scrape API, the way Jackett and Prowlarr search it. One result per torrent, named Title
# Year/Edition [properties], newest first as the site sorts them. Up to 50 series or albums a
# search. The passkey is sent to the API and is never part of a result's link: it is added
# only when downloading.

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

KEY_MARK = "UMASH_KEY"


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Requests carry the passkey: never follow them to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"AnimeBytes answered with a redirect (HTTP {code}), so Umash stopped")


class umash_animebytes(object):
    url = "https://animebytes.tv"
    name = "AnimeBytes"
    # "type|switches": the API's type, then the category switches that narrow it.
    supported_categories = {
        "all": "anime|;music|",  # two searches, the way Jackett and Prowlarr do
        "anime": "anime|anime[tv_series],anime[tv_special],anime[ova],anime[ona],anime[dvd_special],anime[bd_special]",
        "books": "anime|printedtype[manga],printedtype[oneshot],printedtype[anthology],printedtype[manhwa],printedtype[light_novel],printedtype[artbook]",
        "games": "anime|gamec[game],gamec[visual_novel]",
        "movies": "anime|anime[movie]",
        "music": "music|",
        "tv": "anime|anime[tv_series],anime[tv_special],anime[ova],anime[ona],anime[dvd_special],anime[bd_special]",
    }
    per_search = 50
    timeout = 25
    download_path = re.compile(r"/torrent/\d+/download[/?][\w./?=&%-]*" + KEY_MARK + r"[\w./?=&%-]*")

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirects)

    def login(self):
        username = os.environ.get("UMASH_SETTING_USERNAME", "").strip()
        passkey = os.environ.get("UMASH_SETTING_PASSKEY", "").strip()
        if not username or not passkey:
            raise RuntimeError("AnimeBytes needs your username and passkey: add them in the plugin's Settings")
        return username, passkey

    def refused(self, code):
        if code in (401, 403, 404):  # The scrape address answers "not found" to a login it doesn't know.
            return "AnimeBytes refused the username or passkey. Check them in the plugin's Settings"
        if code == 429:
            return "AnimeBytes is limiting requests from this connection. Try again later"
        return f"AnimeBytes answered with HTTP {code}"

    def fetch(self, url):
        request = urllib.request.Request(url, headers={**_headers, "Accept": "application/json, */*"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise RuntimeError(self.refused(error.code)) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach AnimeBytes: {error.reason}") from None

    def address(self, what, spec):
        username, passkey = self.login()
        kind, _, switches = spec.partition("|")
        params = [("username", username), ("torrent_pass", passkey), ("sort", "grouptime"), ("way", "desc"),
                  ("type", kind), ("searchstr", " ".join(urllib.parse.unquote(what).split())),
                  ("limit", self.per_search)]
        params += [(switch, "1") for switch in switches.split(",") if switch]
        if kind == "anime" and os.environ.get("UMASH_HIDE_ADULT") == "1":
            params.append(("hentai", "0"))
        return f"{self.url}/scrape.php?{urllib.parse.urlencode(params)}"

    def read(self, body):
        try:
            found = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError("AnimeBytes sent something other than search results") from None
        if not isinstance(found, dict):
            raise RuntimeError("AnimeBytes sent something other than search results")
        if found.get("error"):
            text = " ".join(str(found["error"]).split())[:200]
            if "passkey" in text.lower() or "username" in text.lower() or "authentic" in text.lower() or "invalid" in text.lower():
                raise RuntimeError(self.refused(401))
            raise RuntimeError(f"AnimeBytes said: {text}")
        groups = found.get("Groups")
        return groups if isinstance(groups, list) else []

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

    def link(self, torrent, passkey):
        """The download address with the passkey replaced by a placeholder."""
        given = str(torrent.get("Link") or "")
        if given.startswith(self.url + "/") and passkey in given:
            return given.replace(passkey, KEY_MARK)
        return f"{self.url}/torrent/{torrent.get('ID')}/download/{KEY_MARK}"

    @staticmethod
    def properties(torrent):
        parts = re.split(r" \| | / ", unescape(str(torrent.get("Property") or "")))
        return [part.strip() for part in parts if part.strip() and "freeleech" not in part.lower()]

    def show(self, group, torrent, passkey):
        if not str(torrent.get("ID", "")).isdigit():
            return
        title = unescape(str(group.get("SeriesName") or group.get("FullName") or group.get("GroupName") or "N/A"))
        year = group.get("Year")
        edition = torrent.get("EditionData") or {}
        edition = unescape(str(edition.get("EditionTitle") or "")) if isinstance(edition, dict) else ""
        name = title
        if group.get("GroupName") in ("Movie", "Live Action Movie") and year:
            name += f" {year}"
        if edition:
            name += f" {edition}"
        name += "".join(f" [{prop}]" for prop in self.properties(torrent))
        if torrent.get("RawDownMultiplier") == 0:
            name += " [FreeLeech]"
        prettyPrinter({
            "link": self.link(torrent, passkey),
            "name": " ".join(name.split()),
            "size": str(self.number(torrent.get("Size"))),
            "seeds": self.number(torrent.get("Seeders")),
            "leech": self.number(torrent.get("Leechers")),
            "engine_url": self.url,
            "desc_link": f"{self.url}/torrent/{torrent.get('ID')}/group",
            "pub_date": self.date(torrent.get("UploadTime")),
        })

    @staticmethod
    def more(page):
        print(f"UMASH_MORE: {page}", file=sys.stderr, flush=True)

    def search(self, what, cat="all"):
        _, passkey = self.login()
        for index, spec in enumerate(self.supported_categories.get(cat, self.supported_categories["all"]).split(";")):
            try:
                groups = self.read(self.fetch(self.address(what, spec)))
            except RuntimeError:
                if index:
                    break  # Keep what the first search found.
                raise
            for group in groups:
                for torrent in group.get("Torrents") or []:
                    self.show(group, torrent, passkey)
        self.more(0)

    def download_torrent(self, info):
        """Adds the passkey here, and only to this site's own download address."""
        _, passkey = self.login()
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't an AnimeBytes download link, so Umash didn't send your passkey to it")
        data = self.fetch(info.replace(KEY_MARK, urllib.parse.quote(passkey, safe="")))
        if not data.startswith(b"d"):
            raise RuntimeError("AnimeBytes didn't send a torrent file for this result. Check your passkey in the plugin's Settings")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
