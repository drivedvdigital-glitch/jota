import requests

hosts = [
    "https://www.google.com",
    "https://www.shopify.com",
    "https://49e257-b3.myshopify.com"
]

for url in hosts:
    try:
        print(f"Testing connection to {url}...")
        r = requests.head(url, timeout=5)
        print(f"  [SUCCESS] Status code: {r.status_code}")
    except Exception as e:
        print(f"  [FAILED] {e}")
