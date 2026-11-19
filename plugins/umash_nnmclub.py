# VERSION: 1.0
# AUTHORS: Umash
#
# NNM-Club (nnmclub.to), which moved from nnm-club.me. Searching needs no account: a
# visitor sees the 50 best-seeded results of a search. The site only hands a .torrent
# to members, but each result's own page shows its magnet to everyone, so that is
# fetched when you download one.

import html
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from helpers import _headers
from novaprinter import prettyPrinter


class umash_nnmclub(object):
    url = "https://nnmclub.to"
    name = "NNM-Club"
    # The site's forums for each category, from its own search form. "all" sends -1.
    supported_categories = {
        "all": "-1",
        "anime": "615,616,617,648,619,620,623,622,621,632,624,627,626,625,644,628,635,634,638,646,645,639,640",
        "books": "432,755,481,557,442,441,875,1176,444,443,440,1199,433,447,445,817,818,434,1349,957,931,1152,455,453,1063,452,451,449,1153,1347,482,483,484,1343,438,485,473,472,471,895,470,896,480,436,458,457,1342,459,460,461,462,437,466,1319,463,958,1223,467,464,465,1348,469,439,477,476,475,474,886,478,486,490,657,489,488,487,1198,1227,893,491,767,299,887,301,1334,300,1341,492,558,1173,1174,1171,662,1175,1172,933,815,1170,398,816",
        "games": "410,411,412,1008,415,746,428,1009,413,414,1010,1012,1014,416,1013,1015,268,1016,1041,1018,1017,972,971,970,969,968,1146,418,1061,1060,1059,1058,1057,1056,1054,1053,1052,1051,1050,1049,1048,1047,1046,1045,1044,382,390,387,388,1264,1318,385,386,848,1321,383,384,1292,389,391",
        "movies": "216,270,218,219,954,217,1293,1298,318,320,677,1177,319,678,885,908,1310,909,910,911,912,220,221,222,882,889,224,225,226,227,1296,891,1376,1377,1378,1379,1380,1381,1299,682,694,884,1211,693,913,228,1150,1311,1313,1312,256,257,258,883,955,905,271,1210,264,265,272,1262,266,1294,713,706,577,894,578,580,579,953,581,806,714,761,809,924,812,576,590,591,588,589,598,652,599,959,956,597,593,594,819,595,587,584,586,585,600,596,1295,614,603,1308,1309,1206,1194,1062,974,609,1263,951,975,608,607,606,750,605,604,950,610,613,612,653,654,611,656",
        "music": "313,1291,680,1149,429,681,330,1256,1285,370,1260,371,1261,375,1259,374,1257,373,1258,372,1160,876,1255,376,326,1352,359,358,1353,1188,1189,328,1370,1180,1181,364,363,1179,879,322,1350,962,333,1356,965,336,1362,337,338,1351,963,334,1357,961,332,325,1354,1355,1165,1166,1168,1167,1162,352,1164,1163,1161,353,324,1327,1328,1325,1326,1365,1366,1323,1324,976,346,1363,977,345,349,1243,347,979,673,671,1224,1225,1367,980,672,1316,1317,1364,981,344,1368,983,984,982,348,674,323,1369,1187,339,1186,340,1185,341,329,1361,369,368,1218,365,1217,366,1215,1216,1213,367,331,1358,1157,711,1159,378,1359,1158,379,380,1178,1360,361,360,327,1184,824,1182,354,877,1183,1190,917",
        "software": "503,504,506,763,1335,1241,1023,717,509,508,510,1254,1042,511,916,512,561,1284,562,513,514,515,516,517,518,519,520,521,522,523,524,532,533,535,530,529,525,526,527,545,764,765,820,552,553,554,550,549,548,1240,830,833,839,1233,1236,832,829,828,1231,840,1232,841,1238,844,842,843,537,538,1151,1083,1029,1082,1028,1087,1030,1039,1038,1037,1036,1035,1034,822,1093,1092,1091,834,831,1155,1156,1099,1098,1096,1097,1095,536,563,1032,1031,1025,1026,564,1137,417,1193,1192,1102,1070,534,676,1077,267,1071,1134,1107,1075,1105,1111,1072,166,1078,1074,1076,1266,1267,1268,1269,1270,1277,1271,1272,1273,1274,1275,1372,1276,1103,1114,1113,1115,1129,1116,808,1139,988,1073",
        "tv": "1219,1221,1220,722,768,1344,779,1288,787,1141,777,786,776,785,775,1265,1242,1140,782,773,1142,772,771,783,1144,804,1290,1300,784,774,922,770,1320,780,781,1322,769,799,800,791,793,794,796,795",
    }

    timeout = 25
    row = re.compile(r'<tr class="prow\d">(.*?)</tr>', re.S)
    topic = re.compile(r'<a class="genmed topictitle" href="viewtopic\.php\?t=(\d+)"><b>(.*?)</b>', re.S)
    forum = re.compile(r'href="tracker\.php\?f=(\d+)')
    size = re.compile(r"<u>(\d+)</u>\s*[\d.,]+\s*[KMGT]?B")
    seeds = re.compile(r'class="seedmed"><b>(\d+)</b>')
    leech = re.compile(r'class="leechmed"><b>(\d+)</b>')
    added = re.compile(r'class="gensmall"><u>(\d+)</u>\s*\d\d-\d\d-\d{4}')
    magnet = re.compile(r'href="(magnet:\?xt=urn:btih:[0-9A-Fa-f]{40}[^"]*)"')
    safe_magnet = re.compile(r"magnet:\?xt=urn:btih:[0-9A-Fa-f]{40}[^\s\"'<>]*")
    topic_page = re.compile(r"/forum/viewtopic\.php\?t=\d+")
    no_results = re.compile(r"Результатов\s+поиска:\s*0\b|Подходящих\s+тем\s+не\s+найдено")
    changed = "NNM-Club's results page has changed, so Umash can't read it"

    def fetch(self, url, data=None):
        request = urllib.request.Request(url, data=data, headers=dict(_headers))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("cp1251", "replace")
        except urllib.error.HTTPError as error:
            if error.headers.get("cf-mitigated") == "challenge":
                raise RuntimeError("NNM-Club is showing programs a Cloudflare check right now. Try again later") from None
            raise RuntimeError(f"NNM-Club answered with HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Couldn't reach NNM-Club: {error.reason}") from None

    def body(self, what, cat):
        fields = [("nm", urllib.parse.unquote(what)), ("o", "10"), ("s", "2"), ("tm", "-1"), ("shf", "1"),
                  ("sha", "1"), ("ta", "-1"), ("sns", "-1"), ("sds", "-1"), ("submit", "Поиск")]
        fields += [("f[]", forum) for forum in self.supported_categories.get(cat, "-1").split(",")]
        return urllib.parse.urlencode(fields, encoding="cp1251", errors="ignore").encode()

    def read_rows(self, text):
        rows = self.row.findall(text)
        if not rows and "tablesorter" not in text and not self.no_results.search(text):
            raise RuntimeError(self.changed)
        results = [self.result(row) for row in rows]
        results = [row for row in results if row]
        if rows and not results:
            raise RuntimeError(self.changed)
        return results

    def result(self, row):
        found = self.topic.search(row)
        if not found:
            return None
        forum = self.forum.search(row)
        return {
            "forum": forum.group(1) if forum else "",
            "link": f"{self.url}/forum/viewtopic.php?t={found.group(1)}",
            "name": " ".join(html.unescape(re.sub(r"<[^>]+>", "", found.group(2))).split()),
            "size": self.first(self.size, row, "-1"),
            "seeds": int(self.first(self.seeds, row, "-1")),
            "leech": int(self.first(self.leech, row, "-1")),
            "engine_url": self.url,
            "desc_link": f"{self.url}/forum/viewtopic.php?t={found.group(1)}",
            "pub_date": int(self.first(self.added, row, "-1")),
        }

    @staticmethod
    def first(pattern, text, default):
        found = pattern.search(text)
        return found.group(1) if found else default

    def search(self, what, cat="all"):
        text = self.fetch(f"{self.url}/forum/tracker.php", self.body(what, cat))
        for row in self.read_rows(text):
            row.pop("forum")
            prettyPrinter(row)

    def download_torrent(self, page):
        if not page.startswith(self.url + "/") or not self.topic_page.fullmatch(page[len(self.url):]):
            raise RuntimeError("That isn't an NNM-Club topic link")
        found = self.magnet.search(self.fetch(page))
        if not found:
            raise RuntimeError("NNM-Club's page for this result has no magnet")
        magnet = html.unescape(found.group(1))
        if not self.safe_magnet.fullmatch(magnet):
            raise RuntimeError("The magnet on this page looks wrong")
        print(magnet + " " + page)
