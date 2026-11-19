# VERSION: 1.0
# AUTHORS: Umash
# SETTING: username | text required | Username | Your online-fix.me account. Download links are only shown to signed-in members. | https://online-fix.me/
# SETTING: password | secret required | Password
#
# Online-Fix (online-fix.me): multiplayer fixes for PC games. Searching is open,
# but game pages only show the download link to signed-in members, so results
# need an account. The older plugin read a list from hydralinks.cloud, which
# now answers every plugin with a Cloudflare check.

import html
import http.cookiejar
import os
import re
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from helpers import _headers
from novaprinter import prettyPrinter


class umash_onlinefix(object):
    url = "https://online-fix.me"
    name = "Online-Fix"
    supported_categories = {"all": "0", "games": "0"}

    card = re.compile(r'class="big-link" href="(https://online-fix\.me/games/[^"]+)".*?alt="([^"]*)"', re.S)
    upload = re.compile(r'href="(https://uploads\.online-fix\.me:2053/torrents/[^"]+)"')
    timeout = 20

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def fetch(self, url, data=None, referer=None):
        headers = dict(_headers)
        headers["Referer"] = referer or self.url + "/"
        request = urllib.request.Request(url, data=data, headers=headers)
        with self.opener.open(request, timeout=self.timeout) as response:
            return response.read()

    def text(self, url, data=None, referer=None):
        return self.fetch(url, data, referer).decode("cp1251", "replace")

    def login(self):
        username = os.environ.get("UMASH_SETTING_USERNAME", "").strip()
        password = os.environ.get("UMASH_SETTING_PASSWORD", "")
        if not username or not password:
            raise RuntimeError("Online-Fix needs your account: add your username and password in the plugin's Settings")
        form = {"login_name": username, "login_password": password, "login": "submit"}
        page = self.text(self.url + "/", urllib.parse.urlencode(form, encoding="cp1251", errors="replace").encode("ascii"))
        if 'name="login_password"' in page:
            raise RuntimeError("Online-Fix refused the username or password in the plugin's Settings")

    def torrent(self, page):
        """The .torrent address of a game: its page links a folder holding the file."""
        folder = self.upload.search(self.text(page))
        if not folder:
            return ""
        folder = html.unescape(folder.group(1))
        if not folder.endswith("/"):
            folder += "/"
        files = re.findall(r'href="([^"]+\.torrent)"', self.text(folder, referer=page))
        return urllib.parse.urljoin(folder, html.unescape(files[0])) if files else ""

    def show(self, item):
        page, title = item
        try:
            link = self.torrent(page)
        except OSError:
            return
        if link:
            prettyPrinter({
                "link": link,
                "name": html.unescape(title).replace(" по сети", ""),
                "size": "-1",
                "seeds": -1,
                "leech": -1,
                "engine_url": self.url,
                "desc_link": page,
            })

    def search(self, what, cat="all"):
        self.login()
        story = urllib.parse.quote(urllib.parse.unquote(what), encoding="cp1251", errors="replace")
        cards = dict(self.card.findall(self.text(f"{self.url}/index.php?do=search&subaction=search&story={story}")))
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(self.show, cards.items()))

    def download_torrent(self, info):
        """The upload host only serves signed-in members arriving from the site."""
        self.login()
        data = self.fetch(info)
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
