import html
import re

import httpx


url = "https://nca.gov.sa/ar/regulatory-documents/controls-list/ecc/"
response = httpx.get(
    url,
    timeout=30,
    follow_redirects=True,
    headers={"User-Agent": "Maal-Regulatory-Monitor/1.0"},
)
print(response.status_code, response.url, response.headers.get("content-type"))
links = sorted(
    {
        html.unescape(match)
        for match in re.findall(r'href=["\']([^"\']+)', response.text, re.IGNORECASE)
    }
)
for link in links:
    if any(token in link.lower() for token in ("pdf", "download", "ecc")):
        print(link)
