import os
import requests
import json
from dotenv import load_dotenv

# Load env variables
load_dotenv(dotenv_path=r"C:\Users\Usuário\.\.gemini\antigravity-ide\scratch\ai-agent-project\.env")

shop_name = os.getenv("SHOPIFY_SHOP_NAME")
access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
client_id = os.getenv("SHOPIFY_CLIENT_ID")

if not shop_name or not access_token:
    print("Variables in env missing!")
    exit(1)

shop_cleaned = shop_name.replace(".myshopify.com", "").replace("https://", "").replace("http://", "").strip()

# Exchange token if shpss_
actual_token = access_token
if access_token.startswith("shpss_"):
    token_url = f"https://{shop_cleaned}.myshopify.com/admin/oauth/access_token"
    token_payload = {
        "client_id": client_id.strip(),
        "client_secret": access_token.strip(),
        "grant_type": "client_credentials"
    }
    res_token = requests.post(token_url, data=token_payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    if res_token.status_code == 200:
        actual_token = res_token.json().get("access_token")
        print("OAuth token exchanged successfully.")
    else:
        print("OAuth token exchange failed.")
        exit(1)

# Step 1: Extract product data with a manual creative video URL
print("\n--- Step 1: Extracting product with manual creative video URL ---")
extrair_url = "http://127.0.0.1:8000/extrair"
payload_extract = {
    "url": "https://romancol.com/products/el-cine-del-futuro-llego-a-tu-casa",
    "creative_video_url": "https://www.w3schools.com/html/mov_bbb.mp4"
}

try:
    r_extract = requests.post(extrair_url, json=payload_extract, timeout=300)
    print(f"Extraction Status: {r_extract.status_code}")
    if r_extract.status_code != 200:
        print(f"Extraction failed: {r_extract.text}")
        exit(1)
    
    extracted_data = r_extract.json()
    produto = extracted_data["produto"]
    print("Extracted successfully!")
    print(f"Title: {produto['title']}")
    print(f"Initial Handle: {produto['handle']}")
    
    # Verify manual video WebP is inside the description_html
    if "data:image/webp;base64" in produto["description_html"]:
        print("[SUCESSO] WebP animado (base64) está na copy HTML!")
    else:
        print("[AVISO] WebP animado NÃO está na copy HTML.")
        
    # Step 2: Set custom handle
    custom_handle = "proyector-mini-chapa-maxima-test"
    produto["handle"] = custom_handle
    print(f"\n--- Step 2: Modifying handle to: {custom_handle} ---")
    
    # Step 3: Send to Shopify
    print("\n--- Step 3: Sending product to Shopify ---")
    enviar_url = "http://127.0.0.1:8000/enviar-shopify"
    r_enviar = requests.post(enviar_url, json=produto, timeout=300)
    print(f"Send to Shopify Status: {r_enviar.status_code}")
    if r_enviar.status_code != 200:
        print(f"Send failed: {r_enviar.text}")
        exit(1)
        
    enviar_res = r_enviar.json()
    product_id = enviar_res["product_id"]
    print(f"Product created in Shopify! ID: {product_id}")
    print(f"Admin URL: {enviar_res['admin_url']}")
    
    # Step 4: Verify details from Shopify
    print("\n--- Step 4: Fetching product from Shopify to verify handle and type/vendor ---")
    verify_url = f"https://{shop_cleaned}.myshopify.com/admin/api/2026-04/products/{product_id}.json"
    headers = {
        "X-Shopify-Access-Token": actual_token,
        "Content-Type": "application/json"
    }
    r_get = requests.get(verify_url, headers=headers, timeout=15)
    if r_get.status_code == 200:
        shopify_product = r_get.json()["product"]
        print(f"Shopify Handle: {shopify_product['handle']}")
        print(f"Shopify Vendor: {shopify_product['vendor']}")
        print(f"Shopify Product Type: {shopify_product['product_type']}")
        
        # Check assertions
        assert shopify_product["handle"] == custom_handle, f"Handle mismatch: {shopify_product['handle']} vs {custom_handle}"
        assert shopify_product["vendor"] == "Ofertas Colombianas", f"Vendor mismatch: {shopify_product['vendor']}"
        assert shopify_product["product_type"] == "Otro", f"Product Type mismatch: {shopify_product['product_type']}"
        print("\n[PERFEITO] Todos os campos do produto foram persistidos corretamente na Shopify!")
    else:
        print(f"Failed to fetch product from Shopify: {r_get.text}")
        
    # Step 5: Clean up by deleting the product
    print("\n--- Step 5: Deleting test product ---")
    r_delete = requests.delete(verify_url, headers=headers, timeout=15)
    print(f"Delete Status: {r_delete.status_code}")
    if r_delete.status_code == 200:
        print("Test product deleted successfully.")
    else:
        print(f"Delete failed: {r_delete.text}")

except Exception as e:
    print(f"Exception occurred: {e}")
