# VERSION: 1.0
# AUTHORS: Umash
# LOGIN: https://rutracker.org/forum/login.php | bb_session | cf_clearance, bb_guid, bb_ssl
#
# RuTracker (rutracker.org), read from the site's own search pages with the login you
# get by signing in from Umash. The site's sign-in page shows programs a Cloudflare
# check and sometimes a CAPTCHA, which the sign-in window handles the way a browser
# does. The login is sent only to this site, and result links carry none of it.
#
# The search follows Jackett's and Prowlarr's RuTracker indexers: Windows-1251 search
# words with wildcards between them, and their lists of forums for each category.

import gzip
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


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follows the site's own redirects. Nothing else is followed, so the login can't
    reach another address."""

    def __init__(self, site):
        super().__init__()
        self.site = urllib.parse.urlsplit(site)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "login.php" in newurl.lower():
            signed_out()
        target = urllib.parse.urlsplit(newurl)
        if (target.scheme, target.netloc) != (self.site.scheme, self.site.netloc):
            raise RuntimeError("RuTracker sent Umash to another site instead of answering, so the site may have changed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ResultsPage(HTMLParser):
    """Reads the torrent rows the way a browser does, so left-out closing tags don't matter."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found_table = False
        self.rows = []
        self.depth = 0
        self.row = None
        self.cell = None
        self.in_name = False

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        classes = attributes.get("class", "").split()
        if tag == "table":
            if self.depth:
                self.depth += 1
            elif attributes.get("id") == "tor-tbl":
                self.found_table = True
                self.depth = 1
            return
        if not self.depth:
            return
        if self.depth == 1 and tag == "tr":
            self.finish_row()
            self.row = {"cells": [], "id": None, "name": "", "download": False}
            self.cell = None
        elif self.row is None:
            return
        elif self.depth == 1 and tag == "td":
            self.row["cells"].append({"text": "", "sort": attributes.get("data-ts_text", ""), "size": "tor-size" in classes})
            self.cell = self.row["cells"][-1]
        elif tag == "a":
            self.read_link(attributes, classes)

    def read_link(self, attributes, classes):
        if "tr-dl" in classes:
            self.row["download"] = True
        elif "tLink" in classes and not self.row["id"]:
            query = urllib.parse.urlsplit(attributes.get("href", "")).query
            topic = attributes.get("data-topic_id") or urllib.parse.parse_qs(query).get("t", [""])[0]
            if topic.isdigit():
                self.row["id"] = topic
                self.in_name = True

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.finish_row()
        elif self.depth and tag == "a":
            self.in_name = False
        elif self.depth == 1 and tag == "td":
            self.cell = None

    def handle_data(self, data):
        if self.row is None:
            return
        if self.in_name:
            self.row["name"] += data
        if self.cell is not None:
            self.cell["text"] += data

    def finish_row(self):
        # A torrent still waiting for moderation has no download link yet.
        if self.row and self.row["id"] and self.row["download"] and self.row["name"].strip() and len(self.row["cells"]) >= 10:
            self.rows.append(self.row)
        self.row = None
        self.cell = None
        self.in_name = False


class umash_rutracker(object):
    url = "https://rutracker.org"
    name = "RuTracker"
    # The site's forums for each category, from Jackett's RuTracker indexer. "all" sends none.
    supported_categories = {
        "all": "",
        "anime": "33,1106,1105,599,1389,1391,2491,2544,1642,1390,404,1277,2484,1386,1387",
        "books": "1411,21,2157,765,2019,31,1427,2422,2195,2521,2223,2447,39,2086,1101,745,1689,2336,2337,1353,1400,1415,2046,1802,2189,2190,2443,1477,669,2196,2056,1436,2191,2477,1680,1684,2446,2524,2525,995,2022,2471,2375,764,1685,1688,2472,1687,2020,1349,1967,1341,2049,1681,2319,2434,1683,2444,2427,2452,2445,2435,667,2436,1335,2453,2320,1801,2023,2024,2026,2192,2027,295,2028,2029,1325,2386,2031,2030,2526,2527,2254,2376,2054,770,2476,2494,1528,2032,919,944,980,946,977,2074,2349,768,2099,2021,2437,1337,1447,2468,2469,2470,1686,2215,2216,2546,2217,2218,2252,2543,767,2515,2516,2517,2518,2519,2520,1696,2253,2033,1412,1446,753,2037,2224,2194,2418,1410,2034,2433,1961,2432,565,1523,1575,1520,2424,769,2038,2043,2042,2041,2044,2039,2045,2080,2047,2193,1037,1418,1422,1423,1424,1445,1425,1426,1428,1429,1430,1431,1433,1432,2202,862,2461,2462,2463,2464,2473,281,2465,2458,2048,1238,2055,754,2114,2438,2439,2440,2441,2442,2125,2133,2130,2313,2528,2129,2141,2314,2132,2131,2362,1265,1266,1267,1358,2363,734,1268,1673,1269,1270,1275,2364,1276,2094,1274,1264,2358,2359,2360,2361,2057,2355,2474,2356,2357,2413,1501,1580,525,610,1568,1542,2335,1544,1546,1549,1597,1552,1550,1553,1554,617,1555,2017,1257,1258,2208,677,1255,1479,1261,614,1583,1259,2065,1254,1260,2209,2210,1547,1548,2211,1596,2135,2140,2136,2138,615,1581,1590,1587,1594,1591,1588,1585,1586,2078,1929,1593,1592,1595,1556,2539,1560,1991,1561,1653,1570,1654,1655,1656,1930,1931,1932,1562,1563,1626,1564,1545,1565,1559,1566,1573,1567,2326,574,1036,400,2389,2388,2387,661,2348,2327,695,399,402,467,490,499,2137,2127,2324,2325,2342,530,2152,2328,1350,403,1279,716,2165,401,1964,1973,1974,1975,1976,1977,1203,1978,1979,1980,1981,1970,334,1909,147",
        "games": "5,635,127,2203,647,646,50,53,1008,900,128,2204,278,52,54,51,2226,2118,1310,2410,2205,2225,2206,1007,2228,139,2478,2480,2481,2142,2060,2145,2146,2143,2012,899,1992,2059,548,908,357,886,973,546,1352,1116,595,887,510,773,774,1605,968,129,2185,2487,2182,2181,2180,2179,2186,700,1926,2420",
        "movies": "22,941,1666,376,106,7,187,2090,2221,2091,2092,2093,2200,1950,252,2540,934,505,212,2459,1235,166,124,1543,709,1577,93,905,101,100,877,1576,572,2220,1670,2198,2199,313,312,1247,2201,2339,140,194,718,775,1457,1940,272,271,352,549,1213,2109,514,2097,4,84,2343,930,2365,1900,2258,521,208,539,2183,209,484,822,181,847",
        "music": "185,809,409,560,794,556,2307,557,2308,558,793,1395,436,2309,2310,2311,969,1125,1130,1131,1132,1133,2084,1128,1129,1856,2430,1283,2085,1282,1284,1285,1138,1136,1137,1849,1126,1127,1134,1135,2018,855,408,441,1173,1486,1172,446,909,1665,1760,1764,1767,1769,1765,1771,1770,1768,1774,1772,2233,416,2377,468,691,469,786,785,1631,1499,715,1388,282,796,784,783,2331,2431,880,1215,1220,1221,1334,1216,1223,1224,1225,1226,782,577,1842,1648,134,965,2495,424,1361,425,1635,1634,2497,428,1362,429,735,1753,2232,714,1331,1330,1219,1452,2275,2270,1351,2499,2503,2504,2502,2501,2505,2500,2267,2277,2278,2279,2280,2281,2282,2353,2284,2285,2283,2286,2287,2268,2293,2292,2290,2289,2288,2269,2297,2295,2296,2298,1698,1702,1703,1704,1705,1706,1707,2329,2330,1708,1709,1710,1711,1712,1713,731,1799,1714,1715,1716,1796,1797,1719,1778,1779,1780,1720,798,1724,1725,1730,1731,1726,1727,1815,1816,1728,1729,2230,2231,1732,1736,1737,1738,1739,1740,1741,1773,202,172,236,1742,1743,1744,1745,1746,1747,1748,1749,2175,2174,722,737,738,464,463,739,740,951,952,1821,1844,1822,1894,1895,460,1818,1819,1847,1824,1807,1829,1830,1831,1857,1859,1858,840,1860,1825,1826,1827,1828,1808,797,1805,1832,1833,1834,1836,1837,1839,454,1838,1840,1841,2229,1809,1861,1862,1947,1946,1945,1944,1810,1864,1865,1871,1867,1869,1873,1811,1868,1875,1877,1878,1907,1880,1881,466,465,1866,406,1299,1163,1164,1884,1885,2513,1755,1757,1890,1396,2302,2346,2303,2345,1893,1397,2512,2219,1660,506,1835,1625,1217,974,1444,2401,239,450,2301,123,1756,1758,1766,1754,860,453,1170,1759,1852,413,445,702,1990,1793,1141,1775,1227,475,1121,431,2378,1039,2383,2305,1782,1787,1789,1791,1912,1189,2403,984,983,2352,2384,1142,1107,1228,988,1122,986,2379,1038,2088,2304,1783,1788,1790,1792,1886,2509,2507,2263,2511,2264,2262,2261,1887,2531,2400,1812,655,1777,2530,2529,1781,2508,2426,2351,1340,2306,1795,2271,1913,1784,1892,2266,518,2236,1927,2240,2248,2244,148",
        "software": "960,537,637,650,2149,1004,1002,1012,2489,2523,2153,1019,1021,1025,1376,1379,1381,1473,1013,1028,1029,1030,1031,1032,1033,1034,1066,1035,1536,1051,1040,1041,1636,1042,1014,2134,1060,1061,1062,1067,1086,1068,1063,1087,1192,1088,1193,1071,1073,1052,1053,1054,1055,1056,2077,1057,1018,1058,1016,1195,1079,1080,1081,1082,1083,1084,1085,1089,1090,1065,1064,1092,1204,1027,1199,1091,285,2154,1005,289,290,288,292,291,957,287,286,1366,1368,1383,1394,1370,2237,1372,1373,1375,1371,1374,1933,1935,1003,1937,2235,1908,864,863,2535,2534,2238,1936,315,1363,2082,2241",
        "tv": "511,1493,921,815,816,1460,498,9,812,81,920,80,1535,188,91,990,1408,175,79,104,189,842,235,242,819,1531,721,1102,1120,1214,489,387,1359,184,1417,1449,504,372,110,121,507,536,1144,195,2366,1803,266,193,1690,1459,1463,825,1248,1288,265,2404,2405,2370,2396,2398,1498,119,1171,1669,2393,625,1949,173,273,911,325,534,594,1301,607,1574,1539,694,781,704,1537,2100,820,915,1242,717,1939,2412,2102,19,670,1475,2107,1453,294,46,103,671,2177,656,2538,2159,251,98,97,851,2178,821,2076,56,2123,876,2139,2380,1467,1469,672,249,552,500,2112,1327,1468,1280,752,1114,2168,2160,2176,314,2323,1278,1281,2110,979,2169,2166,2164,2163,85,24,1959,939,1481,113,115,882,1482,393,1569,373,1186,137,2537,532,827,1484,1485,114,1332,1495,926,1311,2171,2455,1434,1339,922,918,1315,1336,2350,1472,2068,2016,1346,2493,2103,2485,2479,2089,2338,927,1392,2475,2113,2482,2522,2486,1794,255,256,1986,660,1551,626,262,1326,978,1287,1188,1667,1675,257,875,263,2073,550,2124,1470,528,486,854,2079,260,1319,1608,2294,2545,2147,1693,136,2532,592,1229,2533,1952,1621,1668,2075,1613,1614,1623,1615,1630,2425,2514,1616,2014,1491,1442,1987,1617,1620,1998,1343,751,497,1697,2004,2001,2002,283,1997,2003,2009,2010,2006,2007,2005,259,2008,126,845,343,2111,1527,2069,1323,1202,1985,1982,2151,1983,1984,807,1167",
    }

    per_page = 50
    pages = 10  # The site stops at 500 results for one search.
    forums_at_once = 200  # Jackett's limit: larger categories are searched in parts.
    pause = 0.3
    timeout = 20
    download_path = re.compile(r"/forum/dl\.php\?t=\d+")
    separators = re.compile(r"[^a-zA-Zа-яА-ЯёЁ0-9]+")
    signed_in = ('id="logged-in-username"', "log-out-icon")
    total = re.compile(r"Результатов\s+поиска:\s*(\d+)")
    no_results = re.compile(r"Не\s+найдено|Результатов\s+поиска:\s*0\b", re.I)
    changed = "RuTracker's results page has changed, so Umash can't read it"

    def __init__(self):
        self.opener = urllib.request.build_opener(SameSiteRedirects(self.url))

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
                raise RuntimeError(f"RuTracker refused the request (HTTP {error.code}). If this keeps happening, try signing in again") from None
            if error.code == 429:
                raise RuntimeError("RuTracker is limiting requests from this connection. Try again later") from None
            raise RuntimeError(f"RuTracker answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach RuTracker: {error.reason}") from None
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data

    def page(self, url):
        text = self.fetch(url).decode("cp1251", "replace")
        if "<html" not in text[:4000].lower() and "<!doctype" not in text[:4000].lower():
            raise RuntimeError("RuTracker sent something other than a web page, so the site may have changed")
        # Only a signed-in page has these. A Cloudflare check doesn't either.
        if not any(mark in text for mark in self.signed_in):
            signed_out()
        return text

    def words(self, what):
        """The site's search takes Windows-1251, with % as a wildcard between words."""
        return self.separators.sub("%", urllib.parse.unquote(what)).strip("%")

    def parts(self, cat):
        """The forums of a category, in groups small enough for one address."""
        forums = self.supported_categories.get(cat, "")
        if not forums:
            return [""]
        forums = forums.split(",")
        return [",".join(forums[i:i + self.forums_at_once]) for i in range(0, len(forums), self.forums_at_once)]

    def address(self, words, forums, inner):
        query = "nm=" + urllib.parse.quote(words.encode("cp1251", "ignore"), safe="")
        if forums:
            query += "&f=" + forums
        query += "&o=10&s=2"  # Best-seeded first.
        if inner > 1:
            query += f"&start={(inner - 1) * self.per_page}"
        return f"{self.url}/forum/tracker.php?{query}"

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
        if not page.rows and "dl.php?t=" in text:
            raise RuntimeError(self.changed)
        return [self.result(row) for row in page.rows]

    def result(self, row):
        cells = row["cells"]
        return {
            "id": row["id"],
            "link": f"{self.url}/forum/dl.php?t={row['id']}",
            "name": " ".join(row["name"].split()),
            "size": self.bytes_of(cells),
            "seeds": self.seeds(cells[6]),
            "leech": self.number(cells[7]["text"]),
            "engine_url": self.url,
            "desc_link": f"{self.url}/forum/viewtopic.php?t={row['id']}",
            "pub_date": int(cells[9]["sort"]) if cells[9]["sort"].isdigit() else -1,
        }

    @staticmethod
    def bytes_of(cells):
        sizes = [cell["sort"] for cell in cells if cell["size"]]
        return sizes[0] if sizes and sizes[0].isdigit() else "-1"

    @classmethod
    def seeds(cls, cell):
        # A torrent nobody seeds shows days since one did, as a negative or "дн".
        if cell["sort"].startswith("-") or "дн" in cell["text"]:
            return 0
        return max(cls.number(cell["sort"] or cell["text"]), 0)

    @staticmethod
    def number(text):
        digits = re.sub(r"\D", "", text)
        return int(digits) if digits else -1

    def has_more(self, text, inner, count):
        if inner >= self.pages or not count:
            return False
        found = self.total.search(text)
        if found:
            return (inner - 1) * self.per_page + count < int(found.group(1))
        return count >= self.per_page

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
        words = self.words(what)
        if not words:
            self.more(0)
            return
        parts = self.parts(cat)
        # A page number holds both: 1 to 10 are the first group's pages, 11 to 20 the second's.
        current = self.setting("UMASH_START_PAGE", 1)
        seen = set()
        for done in range(self.setting("UMASH_MAX_PAGES", self.pages)):
            group, inner = (current - 1) // self.pages, (current - 1) % self.pages + 1
            if group >= len(parts):
                self.more(0)
                return
            if done:
                time.sleep(self.pause)
            try:
                text = self.page(self.address(words, parts[group], inner))
            except RuntimeError:
                # Keep what the earlier pages found. Load More picks up from here.
                if done:
                    return
                raise
            rows = self.read_rows(text)
            fresh = [row for row in rows if row["id"] not in seen]
            seen.update(row["id"] for row in fresh)
            for row in fresh:
                prettyPrinter({key: value for key, value in row.items() if key != "id"})
            if fresh and self.has_more(text, inner, len(rows)):
                current += 1
            else:
                current = (group + 1) * self.pages + 1
            if (current - 1) // self.pages >= len(parts):
                self.more(0)
                return
            self.more(current)

    def download_torrent(self, info):
        """Sends the login only to this site's own download address."""
        self.headers()
        if not info.startswith(self.url + "/") or not self.download_path.fullmatch(info[len(self.url):]):
            raise RuntimeError("That isn't a RuTracker download link, so Umash didn't send your login to it")
        data = self.fetch(info)
        if not data.startswith(b"d"):
            text = data.decode("cp1251", "replace")
            if not any(mark in text for mark in self.signed_in):
                signed_out()
            raise RuntimeError("RuTracker didn't send a torrent file for this result")
        handle, path = tempfile.mkstemp(suffix=".torrent")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        print(path + " " + info)
