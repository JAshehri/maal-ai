import httpx
from bs4 import BeautifulSoup


url = "https://www.saso.gov.sa/ar/Laws-And-Regulations/technical_regulations/Pages/default.aspx"
response = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": "Maal-Regulatory-Monitor/2.0"})
response.encoding = "utf-8"
print(response.status_code, len(response.content), response.url)
soup = BeautifulSoup(response.text, "html.parser")
for select in soup.find_all("select"):
    if any(option.get("value") == "100" for option in select.find_all("option")):
        print("PAGE_SIZE_SELECT", select)
items = []
for anchor in soup.find_all("a", href=True):
    text = " ".join(anchor.get_text(" ", strip=True).split())
    href = anchor["href"]
    if "تاريخ الاعتماد" in text or "تحميل" in text or ".pdf" in href.lower():
        items.append((text, href, anchor.get("class"), anchor.parent.get("class") if anchor.parent else None))
print("items", len(items))
for item in items[:40]:
    print(item)
for token in ("la2e7a", "pagination", "LoadMore", "rulesAndRegulationsList"):
    position = response.text.find(token)
    print("TOKEN", token, position, response.text[max(0, position - 500):position + 1200] if position >= 0 else "")

page_size = soup.find("select", id=lambda value: value and value.endswith("DDL_PageSize"))
if page_size:
    payload = {item.get("name"): item.get("value", "") for item in soup.find_all("input") if item.get("name")}
    payload["__EVENTTARGET"] = page_size["name"]
    payload["__EVENTARGUMENT"] = ""
    payload[page_size["name"]] = "100"
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Maal-Regulatory-Monitor/2.0"}) as client:
        enlarged = client.post(url, data=payload)
    enlarged.encoding = "utf-8"
    enlarged_soup = BeautifulSoup(enlarged.text, "html.parser")
    print("POSTED", enlarged.status_code, len(enlarged.content), len(enlarged_soup.select("a.rulesAndRegulationsListItem")))
