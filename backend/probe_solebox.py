"""Extract auth tokens and full CONFIG blob from Solebox homepage."""
import re
import json
import urllib.parse
from curl_cffi import requests as r

resp = r.get('https://www.solebox.com/en-eu/', impersonate='chrome', timeout=15)
html = resp.text
print(f"Status: {resp.status_code}, Length: {len(html)}")

# Search for auth-related patterns
print("\n--- Auth key patterns ---")
for label, pattern in [
    ('apiKey',       r'apiKey["\s]*[:=]["\s]*([\w\-]{10,60})'),
    ('token',        r'["](token|accessToken|bearerToken)["\s]*:["\s]*([\w\-\.]{10,80})'),
    ('x-api-key',   r'x-api-key["\s]*:["\s]*([\w\-]{10,60})'),
    ('appId',        r'appId["\s]*:["\s]*([\w\-]{3,30})'),
    ('resy',         r'resy["\s]*:["\s]*([\w\-]{3,30})'),
    ('shopCountry',  r'shopCountry["\s]*:["\s]*([\w\-]{1,20})'),
    ('channelId',    r'channelId["\s]*:["\s]*([\w\-]{1,20})'),
]:
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
        print(f"  {label}: {m.group(0)[:100]}")

# Decode the full CONFIG blob
print("\n--- Full CONFIG decoded ---")
cfg_match = re.search(r'"CONFIG":"([^"]+)"', html)
if cfg_match:
    raw = cfg_match.group(1)
    decoded = urllib.parse.unquote(raw)
    try:
        obj = json.loads(decoded)
        print(json.dumps(obj, indent=2)[:3000])
    except:
        print(decoded[:3000])
else:
    print("CONFIG not found")
    # Try alternate: window.__CONFIG
    alt = re.search(r'window\.__CONFIG\s*=\s*(\{.*?\});', html, re.DOTALL)
    if alt:
        print(alt.group(1)[:2000])
