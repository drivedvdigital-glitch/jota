import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

shop_name = os.getenv("SHOPIFY_SHOP_NAME")
access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
client_id = os.getenv("SHOPIFY_CLIENT_ID")

print(f"Shop Name: {shop_name}")
print(f"Access Token: {access_token[:10]}...")
print(f"Client ID: {client_id}")

actual_token = access_token

if access_token.startswith("shpss_"):
    print("\n--- Testing Shopify Token Exchange ---")
    token_url = f"https://{shop_name}.myshopify.com/admin/oauth/access_token"
    token_payload = {
        "client_id": client_id.strip(),
        "client_secret": access_token.strip(),
        "grant_type": "client_credentials"
    }
    try:
        r = requests.post(token_url, data=token_payload, timeout=15)
        print(f"Token exchange response status: {r.status_code}")
        print(f"Response: {r.text}")
        if r.status_code == 200:
            actual_token = r.json().get("access_token")
    except Exception as e:
        print(f"Token exchange failed: {e}")

print("\n--- Testing Shopify Products GET ---")
products_url = f"https://{shop_name}.myshopify.com/admin/api/2026-04/products.json"
headers = {
    "X-Shopify-Access-Token": actual_token,
    "Content-Type": "application/json"
}

try:
    print(f"Connecting to {products_url}...")
    r = requests.get(products_url, headers=headers, timeout=15)
    print(f"Products API response status: {r.status_code}")
    print(f"Response (first 300 chars): {r.text[:300]}")
except Exception as e:
    print(f"Products API failed: {e}")
