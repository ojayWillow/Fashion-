from curl_cffi import requests as cffi_requests

URL = "https://www.solebox.com/en-eu/p/47-nhl-anaheim-ducks-clean-up-cap-black-85706"

r = cffi_requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    impersonate="chrome",
    timeout=20,
)

with open("solebox_page.html", "w", encoding="utf-8") as f:
    f.write(r.text)

print(f"Saved {len(r.text)} chars to solebox_page.html")
print("Now open the file in VS Code and search for the description text you see on the Solebox page")
