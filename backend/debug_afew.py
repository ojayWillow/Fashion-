"""Debug script v2 - find images and availability in HTML."""
import requests
import json
import re

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

print("=== FETCHING PAGE ===")
r = requests.get("https://en.afew-store.com/products/converse-chuck-70-ox-light-dune-black-egret", timeout=15, headers=headers)
html = r.text
print(f"Length: {len(html)}")

print()
print("=== ALL CDN IMAGES (no /products/ filter) ===")
cdn_matches = re.findall(r'(?:https?:)?//cdn\.shopify\.com/s/files/[^"\s)}\'><]+\.(?:jpg|jpeg|png|webp)', html, re.IGNORECASE)
unique = set()
for u in cdn_matches:
    clean = re.sub(r'_(pico|icon|thumb|small|compact|medium|large|grande|original|master|\d+x\d*|\d*x\d+)\.', '.', u.split('?')[0]).lower()
    if clean not in unique:
        unique.add(clean)
        print(f"  {u[:150]}")
print(f"Total unique CDN images: {len(unique)}")

print()
print("=== LOOKING FOR EMBEDDED PRODUCT JSON ===")
# Search for variant availability in embedded JS
patterns = [
    (r'"available"\s*:\s*(true|false)', 'available fields'),
    (r'"variants"\s*:\s*\[', 'variants arrays'),
]
for pat, desc in patterns:
    matches = re.findall(pat, html)
    print(f"{desc}: {len(matches)} matches")
    if desc == 'available fields':
        from collections import Counter
        print(f"  Values: {Counter(matches)}")

print()
print("=== SEARCHING FOR PRODUCT DATA IN SCRIPTS ===")
script_pattern = r'<script[^>]*>(.*?)</script>'
for i, match in enumerate(re.findall(script_pattern, html, re.DOTALL)):
    if '"available"' in match and '"variants"' in match:
        print(f"Script #{i}: contains variants+available ({len(match)} chars)")
        # Try to find the JSON object
        try:
            # Find anything that looks like a product JSON
            json_pat = r'(\{[^{}]*"variants"\s*:\s*\[[^\]]*\].*?\})'
            for j_match in re.findall(json_pat, match, re.DOTALL)[:1]:
                print(f"  Found JSON-like block ({len(j_match)} chars)")
                print(f"  First 300 chars: {j_match[:300]}")
        except Exception as e:
            print(f"  Parse error: {e}")
        # Also just show a snippet around 'available'
        idx = match.find('"available"')
        if idx >= 0:
            snippet = match[max(0,idx-50):idx+100]
            print(f"  Snippet: ...{snippet}...")
