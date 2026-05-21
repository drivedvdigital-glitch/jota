import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
import re
import csv
import io
import requests
import unicodedata
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from extractor import extract_product_data, ProdutoCompleto

app = FastAPI(
    title="Extrator de Produtos Universal",
    description="API de extração de dados estruturados de produtos usando Playwright e Gemini Pro, com exportação para Shopify",
    version="1.0.0"
)

# Habilita CORS para aceitar requisições de origens diferentes (ex: arquivos locais file://)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelo de requisição conforme o protótipo
class RequestExtrair(BaseModel):
    url: str

# Modelo de resposta que encapsula o status e o produto completo
class ResponseExtrair(BaseModel):
    status: str = Field(example="sucesso")
    produto: ProdutoCompleto

def slugify(text: str) -> str:
    """
    Normaliza a string para criar um Handle amigável de URL (slug).
    Ex: "Minha Calça Jeans!" -> "minha-calca-jeans"
    """
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s_]+', '-', text).strip('-')
    return text

def clean_price(price_str: str) -> str:
    """
    Limpa e formata strings de preço em formatos variados para um padrão decimal compatível com Shopify.
    Exemplos: "COP 607,230.00" -> "607230.00", "R$ 1.234,56" -> "1234.56", "607.230" -> "607230"
    """
    cleaned = re.sub(r'[^\d.,]', '', price_str).strip()
    if not cleaned:
        return "0.00"
    
    # Se contém tanto vírgula quanto ponto
    if ',' in cleaned and '.' in cleaned:
        comma_idx = cleaned.rfind(',')
        period_idx = cleaned.rfind('.')
        if comma_idx > period_idx:
            # Vírgula é decimal, ponto é milhar
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            # Ponto é decimal, vírgula é milhar
            cleaned = cleaned.replace(',', '')
    # Se contém apenas vírgula
    elif ',' in cleaned:
        parts = cleaned.split(',')
        if len(parts[-1]) <= 2:
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    # Se contém apenas ponto
    elif '.' in cleaned:
        parts = cleaned.split('.')
        if len(parts[-1]) == 3:
            cleaned = cleaned.replace('.', '')
        else:
            # Mantém o ponto como decimal
            pass
            
    return cleaned

@app.get("/", response_class=HTMLResponse)
async def read_index():
    """
    Retorna a página inicial (dashboard interativo) do extrator.
    """
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Template index.html não encontrado")
    
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/extrair", response_model=ResponseExtrair)
async def extrair_produto(request: RequestExtrair):
    """
    Endpoint POST para extrair dados estruturados de um produto a partir de sua URL.
    """
    url = request.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="A URL fornecida deve iniciar com http:// ou https://")
        
    try:
        dados_produto = await extract_product_data(url)
        return {
            "status": "sucesso",
            "produto": dados_produto
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/exportar-csv")
async def exportar_csv(produto: ProdutoCompleto):
    """
    Gera um arquivo CSV no formato de importação padrão da Shopify a partir dos dados do produto.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Cabeçalhos padrão exigidos pela Shopify para importação de produtos
    headers = [
        "Handle", "Title", "Body (HTML)", "Vendor", "Standard Product Type", 
        "Custom Product Type", "Tags", "Published", "Option1 Name", 
        "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name", 
        "Option3 Value", "Variant SKU", "Variant Grams", "Variant Inventory Tracker", 
        "Variant Inventory Qty", "Variant Inventory Policy", "Variant Fulfillment Service", 
        "Variant Price", "Variant Compare At Price", "Variant Requires Shipping", 
        "Variant Taxable", "Variant Barcode", "Image Src", "Image Position", 
        "Image Alt Text", "Gift Card", "SEO Title", "SEO Description", 
        "Google Shopping / Google Product Category", "Google Shopping / Gender", 
        "Google Shopping / Age Group", "Google Shopping / MPN", 
        "Google Shopping / AdWords Grouping", "Google Shopping / AdWords Labels", 
        "Google Shopping / Condition", "Google Shopping / Custom Product", 
        "Google Shopping / Custom Label 0", "Google Shopping / Custom Label 1", 
        "Google Shopping / Custom Label 2", "Google Shopping / Custom Label 3", 
        "Google Shopping / Custom Label 4", "Variant Image", "Variant Weight Unit", 
        "Variant Tax Code", "Cost per item", "Price / International", 
        "Compare At Price / International", "Status"
    ]
    
    writer.writerow(headers)
    
    handle = slugify(produto.title)
    
    # Constrói o corpo do produto em HTML usando a descrição rica ou o fallback
    body_html = produto.description_html
    if not body_html:
        features_html = "".join([f"<li>{f}</li>" for f in produto.features])
        body_html = f"<p>{produto.seo_description}</p>"
        if features_html:
            body_html += f"<p><strong>Principais Benefícios:</strong></p><ul>{features_html}</ul>"
        
    # Limpa caracteres de moeda e formata o preço para ponto decimal usando a função clean_price
    price_cleaned = clean_price(produto.price)
    
    # Primeira linha: Detalhes gerais do produto + primeira imagem
    first_image = produto.images[0] if produto.images else ""
    first_row = ["" for _ in range(len(headers))]
    
    first_row[headers.index("Handle")] = handle
    first_row[headers.index("Title")] = produto.title
    first_row[headers.index("Body (HTML)")] = body_html
    first_row[headers.index("Vendor")] = "Extrator Universal"
    first_row[headers.index("Published")] = "false"  # Desativa para rascunho
    first_row[headers.index("Option1 Name")] = "Title"
    first_row[headers.index("Option1 Value")] = "Default Title"
    first_row[headers.index("Variant Price")] = price_cleaned
    first_row[headers.index("Variant Grams")] = "0"
    first_row[headers.index("Variant Inventory Tracker")] = "shopify"
    first_row[headers.index("Variant Inventory Qty")] = "99"
    first_row[headers.index("Variant Inventory Policy")] = "deny"
    first_row[headers.index("Variant Fulfillment Service")] = "manual"
    first_row[headers.index("Variant Requires Shipping")] = "true"
    first_row[headers.index("Variant Taxable")] = "true"
    first_row[headers.index("Image Src")] = first_image
    if first_image:
        first_row[headers.index("Image Position")] = "1"
        first_row[headers.index("Image Alt Text")] = produto.title
    first_row[headers.index("Status")] = "draft"  # Rascunho
    
    writer.writerow(first_row)
    
    # Linhas secundárias: Apenas para adicionar as imagens extras ao mesmo Handle
    for idx, img_url in enumerate(produto.images[1:], start=2):
        row = ["" for _ in range(len(headers))]
        row[headers.index("Handle")] = handle
        row[headers.index("Image Src")] = img_url
        row[headers.index("Image Position")] = str(idx)
        row[headers.index("Image Alt Text")] = f"{produto.title} - Imagen {idx}"
        writer.writerow(row)
        
    csv_content = output.getvalue()
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=produto_{handle}.csv",
            "Content-Transfer-Encoding": "binary"
        }
    )

@app.post("/enviar-shopify")
async def enviar_shopify(produto: ProdutoCompleto):
    """
    Conecta na Admin API da Shopify e cria o produto diretamente como rascunho.
    """
    shop_name = os.getenv("SHOPIFY_SHOP_NAME")
    access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    client_id = os.getenv("SHOPIFY_CLIENT_ID")
    
    # Validações das chaves do .env
    if not shop_name or shop_name in ["sua-loja-shopify-slug", ""]:
        raise HTTPException(
            status_code=400, 
            detail="Nome da loja Shopify não configurado no arquivo .env (SHOPIFY_SHOP_NAME)"
        )
    if not access_token or access_token in ["shpat_seu_access_token_aqui", "shpss_seu_client_secret_aqui", ""]:
        raise HTTPException(
            status_code=400, 
            detail="Access Token da Shopify não configurado no arquivo .env (SHOPIFY_ACCESS_TOKEN)"
        )
        
    # Limpa o domínio caso o usuário tenha inserido o link completo
    shop_name = shop_name.replace(".myshopify.com", "").replace("https://", "").replace("http://", "").strip()
    
    actual_token = access_token
    
    # Suporte ao fluxo moderno da Shopify de 2026 (Client Credentials Grant)
    if access_token.startswith("shpss_"):
        if not client_id or client_id.strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Para utilizar aplicativos da Shopify criados após 1º de janeiro de 2026, você deve fornecer o 'SHOPIFY_CLIENT_ID' no arquivo .env, pois a Chave Secreta (shpss_...) precisa ser trocada por um token temporário."
            )
        
        token_url = f"https://{shop_name}.myshopify.com/admin/oauth/access_token"
        token_payload = {
            "client_id": client_id.strip(),
            "client_secret": access_token.strip(),
            "grant_type": "client_credentials"
        }
        
        max_token_retries = 3
        token_response = None
        last_token_err = None
        for attempt in range(1, max_token_retries + 1):
            try:
                loop = asyncio.get_event_loop()
                def fetch_temp_token():
                    return requests.post(
                        token_url,
                        data=token_payload,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        timeout=12
                    )
                token_response = await loop.run_in_executor(None, fetch_temp_token)
                break
            except Exception as e:
                last_token_err = e
                if attempt == max_token_retries:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Erro de conexão persistente com a Shopify para obter o token temporário: {str(e)}"
                    )
                await asyncio.sleep(1)
                
        if token_response is not None:
            if token_response.status_code == 200:
                token_data = token_response.json()
                actual_token = token_data.get("access_token")
                if not actual_token:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Resposta da Shopify não contém o access_token: {token_response.text}"
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Falha na autenticação OAuth da Shopify (Código {token_response.status_code}): {token_response.text}"
                )
    
    # Constrói o corpo do produto em HTML usando a descrição rica ou o fallback
    body_html = produto.description_html
    if not body_html:
        features_html = "".join([f"<li>{f}</li>" for f in produto.features])
        body_html = f"<p>{produto.seo_description}</p>"
        if features_html:
            body_html += f"<p><strong>Principais Benefícios:</strong></p><ul>{features_html}</ul>"
        
    # Limpa caracteres de moeda e formata o preço para ponto decimal usando a função clean_price
    price_cleaned = clean_price(produto.price)
    
    # Monta a lista de imagens para a Shopify com Alt Text para SEO/metadados
    shopify_images = []
    for idx, img in enumerate(produto.images, start=1):
        shopify_images.append({
            "src": img,
            "alt": f"{produto.title} - Imagen {idx}"
        })
    
    # Payload para a API Admin REST da Shopify
    product_payload = {
        "product": {
            "title": produto.title,
            "body_html": body_html,
            "vendor": "Extrator Universal",
            "status": "draft",  # Cria como rascunho
            "images": shopify_images,
            "variants": [
                {
                    "price": price_cleaned,
                    "inventory_management": "shopify",
                    "inventory_quantity": 99,
                    "requires_shipping": True,
                    "taxable": True
                }
            ]
        }
    }
    
    url = f"https://{shop_name}.myshopify.com/admin/api/2026-04/products.json"
    headers = {
        "X-Shopify-Access-Token": actual_token,
        "Content-Type": "application/json"
    }
    
    max_product_retries = 3
    response = None
    last_product_err = None
    for attempt in range(1, max_product_retries + 1):
        try:
            # Executa chamada de API de forma síncrona dentro de um pool para não bloquear o loop de eventos
            loop = asyncio.get_event_loop()
            
            def request_call():
                return requests.post(url, json=product_payload, headers=headers, timeout=15)
                
            response = await loop.run_in_executor(None, request_call)
            break
        except Exception as e:
            last_product_err = e
            if attempt == max_product_retries:
                raise HTTPException(status_code=500, detail=f"Falha de conexão persistente com a Shopify: {str(e)}")
            await asyncio.sleep(1)
            
    if response is not None:
        if response.status_code == 201:
            res_data = response.json()
            product_id = res_data["product"]["id"]
            admin_url = f"https://admin.shopify.com/store/{shop_name}/products/{product_id}"
            return {
                "success": True,
                "message": "Produto enviado diretamente para a Shopify com sucesso!",
                "product_id": product_id,
                "admin_url": admin_url
            }
        else:
            detail_msg = f"Erro retornado pela Shopify (Código {response.status_code}): {response.text}"
            raise HTTPException(status_code=500, detail=detail_msg)
    else:
        raise HTTPException(status_code=500, detail=f"Falha de conexão com a Shopify (sem resposta): {str(last_product_err)}")

if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "127.0.0.1")
    
    print(f"Iniciando o servidor FastAPI em http://{host}:{port}")
    # reload=True é incompatível com Playwright no Windows devido ao SelectorEventLoop
    uvicorn.run("main:app", host=host, port=port, reload=False)
