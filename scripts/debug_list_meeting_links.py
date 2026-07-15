"""Debug helper: fetch Meetings.aspx and print anchors that look like meeting links."""

import requests
from bs4 import BeautifulSoup

URL = "https://birmingham.cmis.uk.com/birmingham/Meetings.aspx"

def main():
    s = requests.Session()
    s.headers.update({"User-Agent": "BCC_Monitoring-debug/1.0"})
    r = s.get(URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        txt = a.get_text(" ", strip=True)
        if any(x in href for x in ("ViewMeetingPublic", "/Meeting/", "/Meetings/tabid")) or "meeting" in txt.lower():
            found.append((href, txt))
    for href, txt in found[:200]:
        print(href, "-->", txt)

if __name__ == "__main__":
    main()
