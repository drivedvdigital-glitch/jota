import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
from dotenv import load_dotenv
load_dotenv(override=True)
import re
import csv
import io
import requests
import unicodedata
import time
import base64
import gc
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image, ImageSequence
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from extractor import extract_product_data, ProdutoCompleto

app = FastAPI(
    title="EKopy",
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



# Configuração multi-países (idiomas e credenciais da Shopify)
CONFIG_PAISES = {
    "colombia": {
        "idioma": "Espanhol da Colômbia (Español de Colombia)",
        "shop_env": "SHOPIFY_SHOP_NAME_COLOMBIA",
        "token_env": "SHOPIFY_ACCESS_TOKEN_COLOMBIA",
        "client_env": "SHOPIFY_CLIENT_ID_COLOMBIA"
    },
    "romania": {
        "idioma": "Romeno (Rumano)",
        "shop_env": "SHOPIFY_SHOP_NAME_ROMANIA",
        "token_env": "SHOPIFY_ACCESS_TOKEN_ROMANIA",
        "client_env": "SHOPIFY_CLIENT_ID_ROMANIA"
    }
}

# Modelo de requisição conforme o protótipo
class RequestExtrair(BaseModel):
    url: str
    creative_video_url: str | None = None
    country: str | None = "colombia"

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

def processar_imagem_pil(conteudo_binario: bytes, eh_gif: bool = False):
    resultado = None
    mime_type = None
    ext = None
    is_animated = False
    
    try:
        with Image.open(BytesIO(conteudo_binario)) as img:
            ja_otimizada = (img.format == 'WEBP')
            is_animated = getattr(img, "is_animated", False)
            
            if is_animated or eh_gif:
                is_animated = True
                frames = []
                for i, frame in enumerate(ImageSequence.Iterator(img)):
                    f = frame.copy()
                    if f.mode not in ("RGB", "RGBA"):
                        f = f.convert("RGBA")
                    if i == 0:
                        pixels = f.load()
                        if len(pixels[f.width-1, f.height-1]) == 4:
                            r, g, b, a = pixels[f.width-1, f.height-1]
                            pixels[f.width-1, f.height-1] = (r - 1 if r > 0 else r + 1, g, b, a)
                        else:
                            r, g, b = pixels[f.width-1, f.height-1]
                            pixels[f.width-1, f.height-1] = (r - 1 if r > 0 else r + 1, g, b)
                    frames.append(f)
                
                formato_saida = 'WEBP' if (img.format == 'WEBP' or (is_animated and not eh_gif)) else 'GIF'
                with BytesIO() as output:
                    if formato_saida == 'WEBP':
                        frames[0].save(output, format='WEBP', save_all=True, append_images=frames[1:], loop=0, quality=85)
                        mime_type, ext = "image/webp", "webp"
                    else:
                        frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:], loop=0, optimize=True)
                        mime_type, ext = "image/gif", "gif"
                    resultado = output.getvalue()
                
                for f in frames:
                    f.close()
                del frames
                
            else:
                if img.mode in ("RGBA", "P"): 
                    img = img.convert("RGB")
                    
                with BytesIO() as output:
                    if not ja_otimizada:
                        img_resized = img.resize((int(img.width * 0.99), int(img.height * 0.99)), Image.LANCZOS)
                        img_resized.save(output, format='WEBP', quality=90)
                        img_resized.close() 
                    else:
                        pixels = img.load()
                        r, g, b = pixels[img.width-1, img.height-1]
                        pixels[img.width-1, img.height-1] = (r - 1 if r > 0 else r + 1, g, b)
                        img.save(output, format='WEBP', lossless=True)
                        
                    resultado = output.getvalue()
                mime_type, ext = "image/webp", "webp"
    except Exception as e:
        print(f"[ERRO processar_imagem_pil] {e}")
        return None, None, None, False

    del conteudo_binario
    gc.collect() 
    
    return resultado, mime_type, ext, is_animated

async def upload_arquivo_global_async(binario: bytes, nome_arquivo: str, mime_type: str, shop_name: str, token: str) -> str | None:
    url = f"https://{shop_name}.myshopify.com/admin/api/2026-04/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    
    query_staged = """
    mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
      stagedUploadsCreate(input: $input) {
        stagedTargets {
          url
          resourceUrl
          parameters {
            name
            value
          }
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    
    loop = asyncio.get_event_loop()
    
    try:
        def post_staged():
            return requests.post(
                url,
                headers=headers,
                json={
                    "query": query_staged,
                    "variables": {
                        "input": [{
                            "filename": nome_arquivo,
                            "mimeType": mime_type,
                            "resource": "IMAGE",
                            "httpMethod": "POST"
                        }]
                    }
                },
                timeout=15
            )
            
        res_staged = await loop.run_in_executor(None, post_staged)
        if res_staged.status_code != 200:
            print(f"[stagedUploadsCreate] Erro HTTP {res_staged.status_code}: {res_staged.text}")
            return None
            
        res_json = res_staged.json()
        if "errors" in res_json:
            print(f"[stagedUploadsCreate] Erros GraphQL: {res_json['errors']}")
            
        data = res_json.get('data')
        if not isinstance(data, dict):
            print(f"[stagedUploadsCreate] Data inválido ou nulo na resposta: {res_json}")
            return None
            
        staged_upload_data = data.get('stagedUploadsCreate') or {}
        user_errors = staged_upload_data.get('userErrors')
        if user_errors:
            print(f"[stagedUploadsCreate] userErrors: {user_errors}")
            
        staged_targets = staged_upload_data.get('stagedTargets', [])
        if not staged_targets:
            print(f"[stagedUploadsCreate] Não retornou stagedTargets: {res_json}")
            return None
            
        target = staged_targets[0]
        data_params = {p['name']: p['value'] for p in target['parameters']}
        
        def post_aws():
            return requests.post(
                target['url'],
                data=data_params,
                files={'file': (nome_arquivo, binario, mime_type)},
                timeout=30
            )
            
        res_aws = await loop.run_in_executor(None, post_aws)
        if res_aws.status_code not in (200, 201, 204):
            print(f"[AWS Upload] Erro status {res_aws.status_code}: {res_aws.text}")
            return None
            
        query_create = """
        mutation fileCreate($files: [FileCreateInput!]!) {
          fileCreate(files: $files) {
            files {
              id
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        
        def post_create():
            return requests.post(
                url,
                headers=headers,
                json={
                    "query": query_create,
                    "variables": {
                        "files": [{
                            "originalSource": target['resourceUrl'],
                            "contentType": "IMAGE"
                        }]
                    }
                },
                timeout=15
            )
            
        res_create = await loop.run_in_executor(None, post_create)
        if res_create.status_code != 200:
            print(f"[fileCreate] Erro HTTP {res_create.status_code}: {res_create.text}")
            return None
            
        res_create_json = res_create.json()
        if "errors" in res_create_json:
            print(f"[fileCreate] Erros GraphQL: {res_create_json['errors']}")
            
        create_data = res_create_json.get('data')
        if not isinstance(create_data, dict):
            print(f"[fileCreate] Data inválido ou nulo na resposta: {res_create_json}")
            return None
            
        file_create_data = create_data.get('fileCreate') or {}
        create_user_errors = file_create_data.get('userErrors')
        if create_user_errors:
            print(f"[fileCreate] userErrors: {create_user_errors}")
            
        files = file_create_data.get('files', [])
        if not files:
            print(f"[fileCreate] Não retornou arquivos: {res_create_json}")
            return None
            
        file_id = files[0]['id']
        
        query_node = f"""
        query {{
          node(id: "{file_id}") {{
            ... on MediaImage {{
              image {{
                url
              }}
            }}
            ... on GenericFile {{
              url
            }}
          }}
        }}
        """
        
        for _ in range(15):
            await asyncio.sleep(2)
            
            def check_node():
                return requests.post(
                    url,
                    headers=headers,
                    json={"query": query_node},
                    timeout=10
                )
                
            res_node = await loop.run_in_executor(None, check_node)
            if res_node.status_code == 200:
                node_res_json = res_node.json()
                if "errors" in node_res_json:
                    print(f"[check_node] Erros GraphQL: {node_res_json['errors']}")
                    
                node_data_root = node_res_json.get('data')
                if isinstance(node_data_root, dict):
                    node_data = node_data_root.get('node')
                    if node_data:
                        final_url = node_data.get('image', {}).get('url') or node_data.get('url')
                        if final_url:
                            return final_url
        
        print(f"[Polling URL] Timeout ao aguardar URL final da imagem {file_id}")
        return None
        
    except Exception as e:
        print(f"[ERRO upload_arquivo_global_async] {e}")
        return None

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
        creative_video = request.creative_video_url.strip() if (request.creative_video_url and request.creative_video_url.strip()) else None
        country_key = (request.country or "colombia").strip().lower()
        country_conf = CONFIG_PAISES.get(country_key, CONFIG_PAISES["colombia"])
        target_lang = country_conf["idioma"]
        
        dados_produto = await extract_product_data(url, creative_video, target_lang)
        return {
            "status": "sucesso",
            "produto": dados_produto
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/enviar-shopify")
async def enviar_shopify(produto: ProdutoCompleto, country: str = "colombia"):
    """
    Conecta na Admin API da Shopify e cria o produto diretamente.
    """
    country_key = country.strip().lower()
    country_conf = CONFIG_PAISES.get(country_key, CONFIG_PAISES["colombia"])
    
    # Busca chaves específicas do país
    shop_name = os.getenv(country_conf["shop_env"])
    access_token = os.getenv(country_conf["token_env"])
    client_id = os.getenv(country_conf["client_env"])
    
    # Fallback para chaves genéricas legadas para compatibilidade retroativa
    if not shop_name or shop_name.strip() == "":
        shop_name = os.getenv("SHOPIFY_SHOP_NAME")
    if not access_token or access_token.strip() == "":
        access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    if not client_id or client_id.strip() == "":
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
                error_text = token_response.text
                if "application_cannot_be_found" in error_text:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Erro na Shopify (application_cannot_be_found): O app com a Chave de API '{client_id}' "
                            f"não foi instalado ou não foi encontrado na loja '{shop_name}'.\n\n"
                            "Para corrigir isso, você tem duas opções:\n\n"
                            "Opção 1: Instalar o app do Shopify Partners na loja da Romênia\n"
                            "1. No painel de Parceiro do Shopify (Partners Dashboard), vá em 'Apps' e clique no seu aplicativo (EKopy APP).\n"
                            "2. Vá em 'Distribution' (Distribuição) no menu lateral.\n"
                            "3. Escolha 'Custom distribution' (Distribuição personalizada).\n"
                            "4. Digite o domínio completo da sua loja da Romênia (hnhrrf-hm.myshopify.com).\n"
                            "5. Gere o link de instalação, abra-o em outra aba (no mesmo navegador onde você está logado na loja da Romênia) e clique em 'Instalar'.\n\n"
                            "Opção 2 (Recomendada - Mais Simples): Usar um Token de Acesso direto (shpat_...)\n"
                            "1. Acesse o admin da sua loja da Romênia (https://admin.shopify.com/store/hnhrrf-hm).\n"
                            "2. Vá em Configurações > Apps e canais de vendas > Desenvolver apps.\n"
                            "3. Clique em 'Criar um app', configure os escopos da API Admin (write_products, write_files, read_products, read_files).\n"
                            "4. Instale o app e copie o token que começa com 'shpat_' (revelado apenas uma vez).\n"
                            "5. Abra o arquivo '.env' e altere a linha:\n"
                            "   SHOPIFY_ACCESS_TOKEN_ROMANIA=[cole seu token shpat_ aqui]\n"
                            "6. Apague o valor ou comente a linha 'SHOPIFY_CLIENT_ID_ROMANIA' no '.env'.\n"
                            "Dessa forma, o sistema se conectará diretamente sem precisar do fluxo Partner OAuth!"
                        )
                    )
                raise HTTPException(
                    status_code=400,
                    detail=f"Falha na autenticação OAuth da Shopify (Código {token_response.status_code}): {token_response.text}"
                )
    
    # Processa as imagens da galeria de forma paralela assíncrona com conversão para WebP/GIF e limpeza de metadados
    
    # Extrai imagens adicionais do description_html para que também sejam enviadas ao Shopify, limpas e mapeadas
    imagens_extras = []
    body_html_inicial = produto.description_html
    if body_html_inicial:
        try:
            soup_imgs = BeautifulSoup(body_html_inicial, 'html.parser')
            for img_tag in soup_imgs.find_all('img'):
                src = img_tag.get('src', '').strip()
                if src:
                    if (src.startswith('http') or src.startswith('data:image/')) and src not in produto.images and src not in imagens_extras:
                        imagens_extras.append(src)
        except Exception as e_extra_parse:
            print(f"[SHOPIFY UPLOAD] Erro ao extrair imagens adicionais do HTML: {e_extra_parse}")

    todas_imagens_para_enviar = list(produto.images)
    for img_extra in imagens_extras:
        if img_extra not in todas_imagens_para_enviar:
            todas_imagens_para_enviar.append(img_extra)
            
    async def processar_e_codificar_imagem_galeria(img_data, idx):
        try:
            loop = asyncio.get_event_loop()
            
            # Verifica se é uma imagem local base64 (enviada pelo frontend)
            if img_data.startswith("data:image/"):
                header, encoded = img_data.split(",", 1)
                conteudo = base64.b64decode(encoded)
                eh_gif = "image/gif" in header or "image/webp" in header
            else:
                # É uma URL HTTP
                def download_img():
                    return requests.get(img_data, timeout=15)
                res = await loop.run_in_executor(None, download_img)
                if res.status_code != 200:
                    raise Exception(f"Erro HTTP {res.status_code}")
                conteudo = res.content
                eh_gif = img_data.lower().split('?')[0].endswith('.gif') or 'gif' in img_data.lower()
                
            binario, mime_type, ext, is_animated = await loop.run_in_executor(
                None, 
                processar_imagem_pil, 
                conteudo, 
                eh_gif
            )
            
            if binario:
                filename = f"clean_galeria_{idx}_{int(time.time())}.{ext}"
                base64_data = base64.b64encode(binario).decode('utf-8')
                return {
                    "attachment": base64_data,
                    "filename": filename,
                    "alt": f"{produto.title} - Imagen {idx}",
                    "is_gif": is_animated,
                    "original_idx": idx,
                    "original_url": img_data
                }
        except Exception as e:
            print(f"[ERRO galeria imagem {idx}] {e}")
            
        # Fallback para mídias HTTP se der erro e não for local base64
        if not img_data.startswith("data:image/"):
            return {
                "src": img_data,
                "alt": f"{produto.title} - Imagen {idx}",
                "is_gif": img_data.lower().split('?')[0].endswith('.gif') or 'gif' in img_data.lower(),
                "original_idx": idx,
                "original_url": img_data
            }
        return None

    galeria_tasks = [processar_e_codificar_imagem_galeria(img, idx) for idx, img in enumerate(todas_imagens_para_enviar, start=1)]
    resultados = await asyncio.gather(*galeria_tasks)
    
    shopify_images_payload = []
    imagens_enviadas_meta = []
    pos = 1
    for img_res in resultados:
        if img_res is not None:
            imagens_enviadas_meta.append({
                "original_idx": img_res.get("original_idx"),
                "is_gif": img_res.get("is_gif", False),
                "position_enviada": pos,
                "original_url": img_res.get("original_url")
            })
            pos += 1
            # Mantém apenas chaves válidas para a criação REST do Shopify
            payload_img = {k: v for k, v in img_res.items() if k in ["attachment", "filename", "alt", "src"]}
            shopify_images_payload.append(payload_img)

    # Inicialmente define o body_html
    body_html = produto.description_html
    if not body_html:
        features_html = "".join([f"<li>{f}</li>" for f in produto.features])
        body_html = f"<p>{produto.seo_description}</p>"
        if features_html:
            body_html += f"<p><strong>Principais Benefícios:</strong></p><ul>{features_html}</ul>"
        
    # Evita enviar o base64 gigante no POST inicial (limite de 512KB do Shopify para body_html)
    if body_html:
        try:
            soup_temp = BeautifulSoup(body_html, 'html.parser')
            img_tags_temp = soup_temp.find_all('img')
            for i, img_tag in enumerate(img_tags_temp):
                img_src = img_tag.get('src', '')
                if img_src and img_src.startswith('data:image/'):
                    img_tag['src'] = f"https://placeholder.com/temp-image-{i+1}.webp"
            body_html = str(soup_temp)
        except Exception as e_clean:
            print(f"[SHOPIFY UPLOAD] Erro ao limpar base64 do body_html inicial: {e_clean}")

    # Limpa caracteres de moeda e formata o preço para ponto decimal usando a função clean_price
    price_cleaned = clean_price(produto.price)

    
    # Sanitiza o handle sugerido pela IA ou cria um a partir do título caso venha em branco
    print(f"[SHOPIFY UPLOAD] Handle recebido do frontend: {produto.handle}")
    handle_cleaned = slugify(produto.handle) if (hasattr(produto, "handle") and produto.handle) else slugify(produto.title)
    print(f"[SHOPIFY UPLOAD] Handle sanitizado para envio: {handle_cleaned}")
    
    # Payload para a API Admin REST da Shopify (inicia sem imagens para evitar erro 413)
    product_payload = {
        "product": {
            "title": produto.title,
            "handle": handle_cleaned,
            "body_html": body_html,
            "vendor": "Ofertas Colombianas",
            "product_type": "Otro",
            "status": "active",  # Cria como ativo
            "images": [],
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
            
            # Upload das imagens uma a uma para evitar erro 413 (Payload Too Large)
            mapa_urls_cdn = {}
            for img_res in resultados:
                if img_res is None:
                    continue
                    
                upload_img_url = f"https://{shop_name}.myshopify.com/admin/api/2026-04/products/{product_id}/images.json"
                
                # Prepara o payload para upload individual contendo apenas chaves válidas do Shopify
                img_payload = {k: v for k, v in img_res.items() if k in ["attachment", "filename", "alt", "src"]}
                single_payload = {
                    "image": img_payload
                }
                
                max_img_retries = 3
                img_response = None
                for attempt in range(1, max_img_retries + 1):
                    try:
                        def upload_call():
                            return requests.post(upload_img_url, json=single_payload, headers=headers, timeout=25)
                        img_response = await loop.run_in_executor(None, upload_call)
                        if img_response.status_code in (200, 201):
                            break
                    except Exception as e_img:
                        print(f"[IMAGE UPLOAD] Tentativa {attempt} falhou para imagem {img_res.get('filename')}: {e_img}")
                    await asyncio.sleep(1)
                
                if img_response is not None and img_response.status_code in (200, 201):
                    uploaded_img_data = img_response.json().get("image")
                    if uploaded_img_data:
                        cdn_url = uploaded_img_data.get("src")
                        original_url = img_res.get("original_url")
                        if original_url and cdn_url:
                            mapa_urls_cdn[original_url] = cdn_url
                        print(f"[IMAGE UPLOAD] Imagem {img_res.get('filename')} enviada e mapeada com sucesso: {cdn_url}")
                else:
                    status_code = img_response.status_code if img_response else "N/A"
                    text_err = img_response.text if img_response else "Sem resposta"
                    print(f"[IMAGE UPLOAD] Erro ao enviar imagem {img_res.get('filename')}: Código {status_code} - {text_err}")
                        
            # Se houver body_html, substituímos as imagens internas pelos links definitivos do CDN do cliente baseando-se nas URLs originais
            if produto.description_html:
                soup = BeautifulSoup(produto.description_html, 'html.parser')
                img_tags = soup.find_all('img')
                for img_tag in img_tags:
                    src = img_tag.get('src', '').strip()
                    if not src:
                        continue
                        
                    # 1. Tenta correspondência exata de URL
                    if src in mapa_urls_cdn:
                        img_tag['src'] = mapa_urls_cdn[src]
                        print(f"[COPY UPDATE] Imagem substituída por correspondência exata: {src} -> {mapa_urls_cdn[src]}")
                    else:
                        # 2. Tenta correspondência parcial (removendo query parameters)
                        src_clean = src.split('?')[0]
                        for orig_url, cdn_url in mapa_urls_cdn.items():
                            if orig_url.split('?')[0] == src_clean:
                                img_tag['src'] = cdn_url
                                print(f"[COPY UPDATE] Imagem substituída por correspondência parcial: {src} -> {cdn_url}")
                                break
                                
                # Fail-safe: remove qualquer imagem base64 restante para evitar erro 413 no PUT
                for img_tag in soup.find_all('img'):
                    src = img_tag.get('src', '').strip()
                    if src.startswith('data:image/'):
                        print(f"[COPY FAIL-SAFE] Removendo tag de imagem base64 não mapeada para evitar erro 413: {src[:50]}...")
                        img_tag.decompose()
                        
                # Sempre reconstrói o HTML final, preservando o layout original
                body_html_final = str(soup)
                
                # Atualiza o produto via chamada PUT REST rápida para salvar a copy otimizada com imagens hospedadas
                put_url = f"https://{shop_name}.myshopify.com/admin/api/2026-04/products/{product_id}.json"
                put_payload = {
                    "product": {
                        "id": product_id,
                        "handle": handle_cleaned,
                        "body_html": body_html_final
                    }
                }
                
                try:
                    def put_call():
                        return requests.put(put_url, json=put_payload, headers=headers, timeout=15)
                    put_res = await loop.run_in_executor(None, put_call)
                    if put_res.status_code == 200:
                        print("[PUT UPDATE COPY] Copy atualizada com sucesso no CDN da Shopify!")
                    else:
                        print(f"[PUT UPDATE COPY] Erro ao atualizar copy: Código {put_res.status_code} - {put_res.text}")
                except Exception as e_put:
                    print(f"[PUT UPDATE COPY] Falha ao fazer PUT de atualização: {e_put}")
            
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
