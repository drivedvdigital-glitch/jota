import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
import json
import re
import cv2
import time
import base64
import requests
import numpy as np
from PIL import Image
from typing import List, Dict, Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from playwright.async_api import async_playwright

# Carrega as variáveis de ambiente (.env)
load_dotenv(override=True)

# Configuração da chave de API (Lê do .env prioritariamente, fallback para "SUA_CHAVE_API_AQUI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY or GEMINI_API_KEY == "sua_chave_de_api_do_gemini_aqui":
    GEMINI_API_KEY = "SUA_CHAVE_API_AQUI"

client = None
if GEMINI_API_KEY and GEMINI_API_KEY != "SUA_CHAVE_API_AQUI":
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("AVISO: GEMINI_API_KEY não configurada. Por favor, adicione-a no arquivo .env")

# 1. O Molde (Schema) que a IA é obrigada a seguir (sem as imagens, que vêm do Playwright)
class ProdutoExtraido(BaseModel):
    title: str = Field(description="Título corto y directo del producto en el idioma de destino requerido (máximo 40 caracteres). Debe cumplir con las políticas de Google Ads: use capitalización estándar (Title Case o Sentence Case), no use mayúsculas sostenidas (ALL CAPS), no incluya emojis ni símbolos de ningún tipo (como ✅, 🚨, ⭐, ®, ™), y no contenga términos promocionales (como 'gratis', 'descuento', 'oferta', 'envío gratis').")
    handle: str = Field(description="Identificador de URL (handle/slug) extremadamente corto, compuesto por 2 o máximo 3 palabras clave del producto, separadas por guiones (ej: 'proyector-mini', 'depilador-laser'). No incluya artículos, preposiciones ni caracteres especiales.")
    seo_description: str = Field(description="Descripción corta optimizada para SEO en el idioma de destino requerido (máximo 90 caracteres).")
    price: str = Field(description="Precio del producto extraído tal como aparece escrito en la página original (ej: 'COP 60.000', 'R$ 199,90', etc.). No realice conversiones ni cálculos de moneda.")
    features: List[str] = Field(description="Lista con 3 a 5 beneficios principales del producto en el idioma de destino requerido.")
    description_html: str = Field(description="El HTML de la descripción en el idioma de destino requerido. Si se detectó descripción original del competidor (modo traducción), devuelva exactamente ese mismo HTML conservando toda su estructura de maquetación original, divs, contenedores, clases, estilos en línea, imágenes, GIFs y formato intactos, traduciendo únicamente el texto visible al idioma de destino sin inventar o agregar textos nuevos. Si no hay descripción (modo creación), construya un diseño de 9 bloques alternados (texto e imágenes) en el idioma de destino requerido.")

# O modelo completo final que junta os dados estruturados da IA com as imagens do Playwright
class ProdutoCompleto(ProdutoExtraido):
    images: List[str] = Field(description="Lista de URLs de imagens do produto de alta qualidade.")

async def scrape_page_content(url: str) -> Dict[str, Any]:
    """
    Usa o Playwright para renderizar a página do produto
    e extrair o texto principal e todas as URLs de imagens grandes.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Configura um User-Agent moderno para evitar bloqueios simples de raspagem
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        try:
            print(f"Navegando para: {url}...")
            try:
                # Mudamos para "domcontentloaded" e reduzimos o timeout padrão para 20s.
                # Se falhar ou der timeout, capturamos o erro e tentamos prosseguir com o que já foi carregado.
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e_nav:
                print(f"Aviso: Erro de navegação ou timeout ao carregar {url} ({e_nav}). Tentando prosseguir...")
            
            # Espera até 5 segundos para o estado 'load' completo (folhas de estilo, imagens), sem travar se falhar
            try:
                await page.wait_for_load_state("load", timeout=5000)
            except Exception:
                pass
            
            # Rola a página para forçar o carregamento de imagens dinâmicas
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000) # Pausa rápida para a página respirar
            
            # Extrai todo o texto visível da página
            page_text = await page.evaluate("document.body.innerText")
            
            # Extrai o HTML da descrição rica e limpa metadados e classes indesejadas
            desc_html = await page.evaluate("""() => {
                let parts = [];
                
                // 1. Tenta pegar a descrição principal do produto
                const mainSelectors = [
                    '.product-description', '.product-single__description', 
                    '#product-description', '.description', '[itemprop="description"]',
                    '.product__description', '.product-details', '#description'
                ];
                
                let mainDescEl = null;
                for (const sel of mainSelectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText.trim().length > 30) {
                        mainDescEl = el;
                        break;
                    }
                }
                
                // Se não achou nenhum container de descrição específico, tenta o primeiro .rte que esteja fora de cabeçalho/rodapé
                if (!mainDescEl) {
                    const rtes = Array.from(document.querySelectorAll('.rte'));
                    for (const el of rtes) {
                        if (el.innerText.trim().length > 50 && !el.closest('footer') && !el.closest('header')) {
                            mainDescEl = el;
                            break;
                        }
                    }
                }
                
                if (mainDescEl) {
                    parts.push(mainDescEl.outerHTML);
                }
                
                // 2. Busca por seções de conteúdo do tema Dawn / Shopify OS 2.0 que compõem a copy
                const mainContent = document.getElementById('MainContent') || document.querySelector('main');
                if (mainContent) {
                    const sections = mainContent.querySelectorAll('.image-with-text, .rich-text, .multicolumn, .custom-html, .video-section');
                    sections.forEach(sec => {
                        // Evita duplicar se a seção estiver dentro do container principal já extraído
                        if (mainDescEl && mainDescEl.contains(sec)) {
                            return;
                        }
                        
                        // Garante que não é um widget de reviews ou recomendados
                        const secId = sec.id || '';
                        const secClass = sec.className || '';
                        if (!secId.includes('review') && !secId.includes('recommend') && 
                            !secClass.includes('review') && !secClass.includes('recommend')) {
                            parts.push(sec.outerHTML);
                        }
                    });
                }
                
                if (parts.length === 0) return '';
                
                const rawHtml = parts.join('\\n');
                
                // Limpeza do HTML no contexto do navegador
                const parser = new DOMParser();
                const doc = parser.parseFromString(rawHtml, 'text/html');
                
                // 1. Remove scripts, estilos, iframes, inputs, botões e svgs
                doc.querySelectorAll('script, style, iframe, input, button, form, noscript, svg').forEach(el => el.remove());
                
                // 2. Converte links em spans para desativar redirecionamentos a concorrentes
                doc.querySelectorAll('a').forEach(a => {
                    const span = document.createElement('span');
                    span.innerHTML = a.innerHTML;
                    if (a.hasAttribute('style')) {
                        span.setAttribute('style', a.getAttribute('style'));
                    }
                    a.parentNode.replaceChild(span, a);
                });
                
                // 3. Normaliza URLs de imagens que começam com //
                doc.querySelectorAll('img').forEach(img => {
                    let src = img.getAttribute('src') || '';
                    if (src.startsWith('//')) {
                        img.setAttribute('src', 'https:' + src);
                    }
                });
                
                // 4. Remove atributos de dados (data-*) e IDs para manter o HTML limpo, mas PRESERVA classes e inline styles para manter o layout original
                doc.body.querySelectorAll('*').forEach(el => {
                    const attribs = Array.from(el.attributes);
                    attribs.forEach(attr => {
                        const name = attr.name;
                        if (name.startsWith('data-') || name === 'id') {
                            el.removeAttribute(name);
                        }
                    });
                    
                    // 5. Limpeza especial de imagens (mantém apenas src, alt, width, height, style, class)
                    if (el.tagName.toLowerCase() === 'img') {
                        const keepAttrs = ['src', 'alt', 'width', 'height', 'style', 'class'];
                        attribs.forEach(attr => {
                            if (!keepAttrs.includes(attr.name)) {
                                el.removeAttribute(attr.name);
                            }
                        });
                    }
                });
                
                return doc.body.innerHTML.trim();
            }""")
            
            # Extrai imagens e vídeos do produto
            media_data = await page.evaluate("""() => {
                const gallerySelectors = [
                    '.product-single__photos', '.product-single__media', 
                    '.product__media-list', '.product__media-item',
                    '.product-images', '.media-gallery', '.gallery',
                    '.product__images', '.slider__slide', '.carousel'
                ];
                
                let imgs = [];
                // Tenta achar imagens dentro de containers específicos de galeria
                for (const sel of gallerySelectors) {
                    const containers = document.querySelectorAll(sel);
                    if (containers.length > 0) {
                        containers.forEach(container => {
                            const foundImgs = Array.from(container.querySelectorAll('img'));
                            foundImgs.forEach(img => {
                                let src = img.src || img.dataset.src || img.dataset.lazySrc || '';
                                if (src) {
                                    if (src.startsWith('//')) src = 'https:' + src;
                                    if (src.startsWith('http')) {
                                        const srcLower = src.toLowerCase();
                                        // Ignora logotipos, ícones de navegação, avatares ou bandeiras de idioma
                                        if (!srcLower.includes('logo') && 
                                            !srcLower.includes('icon') && 
                                            !srcLower.includes('avatar') && 
                                            !srcLower.includes('flag') && 
                                            !srcLower.includes('badge')) {
                                            imgs.push(src);
                                        }
                                    }
                                }
                            });
                        });
                        if (imgs.length > 0) break;
                    }
                }
                
                // Se não encontrou nenhuma imagem na galeria estruturada, busca no resto do body
                if (imgs.length === 0) {
                    imgs = Array.from(document.querySelectorAll('img'))
                        .map(img => {
                            let src = img.src || img.dataset.src || img.dataset.lazySrc || '';
                            if (src.startsWith('//')) src = 'https:' + src;
                            return {
                                el: img,
                                src: src
                            };
                        })
                        .filter(item => {
                            const img = item.el;
                            const w = img.naturalWidth || img.width || 0;
                            const h = img.naturalHeight || img.height || 0;
                            const srcLower = item.src.toLowerCase();
                            return w > 200 && h > 200 && 
                                   !srcLower.includes('logo') && 
                                   !srcLower.includes('icon') && 
                                   !srcLower.includes('avatar') && 
                                   !srcLower.includes('flag') && 
                                   !srcLower.includes('badge') &&
                                   item.src.startsWith('http');
                        })
                        .map(item => item.src);
                }
                
                // Busca por vídeos HTML5 na página (.mp4 ou .webm)
                let vids = [];
                document.querySelectorAll('video').forEach(video => {
                    let src = video.src || '';
                    if (src.startsWith('//')) src = 'https:' + src;
                    if (src.startsWith('http')) {
                        vids.push(src);
                    }
                    video.querySelectorAll('source').forEach(source => {
                        let sSrc = source.src || '';
                        if (sSrc.startsWith('//')) sSrc = 'https:' + sSrc;
                        if (sSrc.startsWith('http')) {
                            vids.push(sSrc);
                        }
                    });
                });
                
                // Filtra também links de vídeo em classes comuns ou do Shopify
                document.querySelectorAll('a, [data-video-src], [data-video-url]').forEach(el => {
                    let src = el.getAttribute('href') || el.getAttribute('data-video-src') || el.getAttribute('data-video-url') || '';
                    if (src.startsWith('//')) src = 'https:' + src;
                    if (src.startsWith('http') && src.toLowerCase().includes('.mp4')) {
                        vids.push(src);
                    }
                });
                
                return {
                    images: imgs,
                    videos: [...new Set(vids)]
                };
            }""")
            
            candidate_images = media_data["images"]
            candidate_videos = media_data["videos"]
            
            # Remove duplicadas agrupando por URL canônico (sem query params e sem sufixo de tamanho)
            # e seleciona a de maior resolução disponível.
            canonical_groups = {}
            for img_url in candidate_images:
                # 1. Remove query parameters para normalizar
                base_url = img_url.split('?')[0]
                # 2. Remove sufixo de tamanho como _950x, _1800x1800, etc.
                canonical_url = re.sub(
                    r'[_-](?:[0-9]+x[0-9]*|[0-9]*x[0-9]+|small|thumb|medium|large|grande|master|pico|icon|compact)(?=\.[a-zA-Z0-9]+$)',
                    '',
                    base_url,
                    flags=re.IGNORECASE
                )
                
                # 3. Calcula score de qualidade
                url_lower = img_url.lower()
                score = 50
                if '1800x1800' in url_lower or 'master' in url_lower:
                    score = 100
                elif '1024x1024' in url_lower or '1024x' in url_lower:
                    score = 90
                elif '950x' in url_lower or 'large' in url_lower or 'grande' in url_lower:
                    score = 80
                elif '160x' in url_lower or 'thumb' in url_lower or 'small' in url_lower or 'icon' in url_lower or 'compact' in url_lower:
                    score = 10
                
                # Atualiza no grupo se for o primeiro ou tiver score maior
                if canonical_url not in canonical_groups:
                    canonical_groups[canonical_url] = (img_url, score)
                else:
                    existing_url, existing_score = canonical_groups[canonical_url]
                    if score > existing_score:
                        canonical_groups[canonical_url] = (img_url, score)
            
            # Reconstrói a lista mantendo a ordem visual da primeira ocorrência do canônico
            unique_images = []
            seen_canonical = set()
            for img_url in candidate_images:
                base_url = img_url.split('?')[0]
                canonical_url = re.sub(
                    r'[_-](?:[0-9]+x[0-9]*|[0-9]*x[0-9]+|small|thumb|medium|large|grande|master|pico|icon|compact)(?=\.[a-zA-Z0-9]+$)',
                    '',
                    base_url,
                    flags=re.IGNORECASE
                )
                if canonical_url not in seen_canonical:
                    seen_canonical.add(canonical_url)
                    unique_images.append(canonical_groups[canonical_url][0])
            
            return {
                "text": page_text,
                "images": unique_images,
                "videos": candidate_videos,
                "description_html": desc_html,
                "success": True
            }
            
        except Exception as e:
            print(f"Erro ao raspar a página com Playwright: {e}")
            return {
                "text": "",
                "images": [],
                "description_html": "",
                "success": False,
                "error": str(e)
            }
        finally:
            await browser.close()

def convert_mp4_to_animated_webp(video_path: str, output_path: str, max_duration_sec: float = 5.0, target_fps: int = 10, max_width: int = 480) -> bool:
    """
    Lê o vídeo usando OpenCV, extrai os frames a uma taxa reduzida (target_fps),
    redimensiona para ser leve, aplica uma alteração sutil de pixel (invalidação de hash)
    e salva como WEBP animado.
    """
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"[convert_mp4_to_animated_webp] Erro ao abrir vídeo: {video_path}")
            return False
            
        original_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        # Evita divisão por zero
        if original_fps <= 0:
            original_fps = 25.0
            
        frame_step = max(1, round(original_fps / target_fps))
        max_frames_to_read = int(max_duration_sec * target_fps)
        
        frames_pil = []
        frame_count = 0
        read_count = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            if frame_count % frame_step == 0:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame_rgb)
                
                if img.width > max_width:
                    ratio = max_width / float(img.width)
                    new_height = int(float(img.height) * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                    
                frames_pil.append(img)
                read_count += 1
                if read_count >= max_frames_to_read:
                    break
            frame_count += 1
            
        cap.release()
        
        if not frames_pil:
            print("[convert_mp4_to_animated_webp] Nenhum frame foi extraído do vídeo.")
            return False
            
        # Invalidação sutil de hash
        first_frame = frames_pil[0]
        pixels = first_frame.load()
        r, g, b = pixels[first_frame.width - 1, first_frame.height - 1]
        pixels[first_frame.width - 1, first_frame.height - 1] = (r - 1 if r > 0 else r + 1, g, b)
        
        frame_duration_ms = int(1000 / target_fps)
        
        # Salva como WEBP animado
        first_frame.save(
            output_path,
            save_all=True,
            append_images=frames_pil[1:],
            duration=frame_duration_ms,
            loop=0,
            quality=85,
            method=4
        )
        
        for img in frames_pil:
            img.close()
            
        return True
    except Exception as e:
        print(f"[convert_mp4_to_animated_webp] Exceção durante a conversão: {e}")
        return False

async def extract_product_data(url: str, creative_video_url: str = None, target_language: str = "Espanhol da Colômbia") -> Dict[str, Any]:
    """
    Raspa a página usando o Playwright e envia o conteúdo textual
    para o Gemini 1.5 Pro extrair de forma estruturada.
    Junta os dados com as imagens obtidas diretamente do Playwright.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY in ["SUA_CHAVE_API_AQUI", "sua_chave_de_api_do_gemini_aqui"]:
        raise ValueError(
            "Chave de API do Gemini não configurada. Por favor, adicione sua GEMINI_API_KEY no arquivo .env"
        )
        
    # Executa a raspagem
    scrape_result = await scrape_page_content(url)
    if not scrape_result["success"]:
        raise Exception(f"Falha ao carregar a página: {scrape_result.get('error')}")
        
    texto_pagina = scrape_result["text"]
    imagens_brutas = scrape_result["images"]
    videos_brutos = scrape_result.get("videos", [])
    
    if creative_video_url:
        print(f"[VÍDEO] Utilizando vídeo de criativo fornecido manualmente: {creative_video_url}")
        videos_brutos.insert(0, creative_video_url)
        
    descricao_html_bruta = scrape_result.get("description_html", "")
    
    # Processamento de vídeo do concorrente para WEBP animado
    video_webp_base64 = None
    if videos_brutos:
        primeiro_video = videos_brutos[0]
        print(f"[VÍDEO] Vídeo detectado: {primeiro_video}. Baixando e convertendo para WEBP animado...")
        try:
            # Cria pasta temporária temp_media
            dir_temp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_media")
            os.makedirs(dir_temp, exist_ok=True)
            
            video_temp_path = os.path.join(dir_temp, f"temp_vid_{int(time.time())}.mp4")
            webp_temp_path = os.path.join(dir_temp, f"temp_anim_{int(time.time())}.webp")
            
            # Baixa o arquivo de vídeo
            loop = asyncio.get_event_loop()
            def download_video_file():
                try:
                    r = requests.get(primeiro_video, stream=True, timeout=20)
                    if r.status_code == 200:
                        with open(video_temp_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                        return True
                except Exception as e_dl:
                    print(f"[VÍDEO] Erro de download do vídeo: {e_dl}")
                return False
                
            download_ok = await loop.run_in_executor(None, download_video_file)
            if download_ok and os.path.exists(video_temp_path):
                # Converte para webp animado
                conversao_ok = await loop.run_in_executor(
                    None, 
                    convert_mp4_to_animated_webp, 
                    video_temp_path, 
                    webp_temp_path
                )
                
                if conversao_ok and os.path.exists(webp_temp_path):
                    with open(webp_temp_path, 'rb') as webp_file:
                        encoded_data = base64.b64encode(webp_file.read()).decode('utf-8')
                        video_webp_base64 = f"data:image/webp;base64,{encoded_data}"
                    print(f"[VÍDEO] Conversão com sucesso! Base64 gerado.")
                    
            # Limpeza dos arquivos temporários
            if os.path.exists(video_temp_path):
                os.remove(video_temp_path)
            if os.path.exists(webp_temp_path):
                os.remove(webp_temp_path)
                
        except Exception as e_vid:
            print(f"[VÍDEO] Erro geral ao processar o vídeo: {e_vid}")
            
    # Se o WEBP animado foi gerado, injeta no topo da galeria de imagens.
    # Mas no prompt do Gemini, usaremos um placeholder fictício para não estourar o limite de tokens.
    imagens_para_prompt = list(imagens_brutas)
    placeholder_url = "https://ekopy-internal-media.com/animated_product_video.webp"
    if video_webp_base64:
        imagens_para_prompt.insert(0, placeholder_url)
        imagens_brutas.insert(0, video_webp_base64)
    
    # Detecta se há uma descrição original rica disponível
    tem_copy_original = False
    if descricao_html_bruta and len(descricao_html_bruta.strip()) > 200:
        texto_limpo = re.sub(r'<[^<]+?>', '', descricao_html_bruta).strip()
        if "<img" in descricao_html_bruta.lower() or len(texto_limpo) > 100:
            tem_copy_original = True

    if tem_copy_original:
        print("[EXTRATOR] Detectada descrição rica original. Traduzindo e limpando mantendo a estrutura...")
        prompt_sistema = f"""
    Você é um tradutor técnico e copywriter de e-commerce de elite.
    Sua tarefa é analisar o HTML da descrição original fornecido, traduzir e otimizar todo o conteúdo textual para o {target_language}.

    REGRAS DO TÍTULO DO PRODUTO (COMPATIBILIDADE GOOGLE ADS):
    1. O título do produto ('title') deve ser conciso (máximo 40 caracteres) e descrever o produto em {target_language}.
    2. Use capitalização normal (Title Case ou Sentence Case). É PROIBIDO escrever títulos inteiramente em maiúsculas (ALL CAPS), exceto para siglas curtas de até 3 letras.
    3. É terminantemente PROIBIDO o uso de emojis, exclamações ou símbolos promocionais/comerciais (como ®, ™, ✅, 🚨, ⭐) no título.
    4. Não inclua termos comerciais ou promocionais como 'gratis', 'descuento', 'oferta', 'envío gratis', 'regalo' no título.

    REGRAS DE OTIMIZAÇÃO E LIMPEZA DE TEXTO:
    1. Se o texto do HTML original contiver menções a preços do concorrente (ex: "$129.900", "COP 60.000", etc.), remova essas menções a preços e ofertas financeiras específicas.
    2. Se o texto contiver menções ao nome da loja concorrente original ou links, remova-as e substitua por termos neutros (ex: "nuestra tienda").
    3. Se houver algum parágrafo ou trecho que esteja completamente desconexo ou falando de outro produto (devido a erros de raspagem), você PODE e DEVE melhorar e reescrever o texto para que condiga perfeitamente com o produto em questão de forma persuasiva.
    4. PROIBIDO o uso de símbolos de marca registrada. Remova QUALQUER caractere ® ou ™ de todo o texto.

    REGRAS DE ESTRUTURA E FORMATAÇÃO DE TAGS (ESTRUTURA DO CLIENTE):
    1. Você DEVE MANTER A ESTRUTURA DE LAYOUT ORIGINAL INTEGRALMENTE (contêineres, divs, grids, colunas, imagens, GIFs, larguras, alturas, alinhamentos, fundos de cores, classes e estilos inline idênticos). Não remova as divs ou contêineres de layout.
    2. Para manter a formatação visual padrão desejada pelo cliente para os textos:
       - Identifique qualquer frase curta, chamada de atenção, título, subtítulo ou cabeçalho de seção (mesmo que no HTML original esteja dentro de tags <p>, <span>, <div>, <b> ou <strong>) e formate-a obrigatoriamente como: `<h1><strong>[Texto do Título Traduzido]</strong></h1>` (Título 1 em Negrito).
       - Identifique os parágrafos de descrição ou blocos de texto explicativo que ficam abaixo desses cabeçalhos (mesmo que no HTML original usassem p, div, span, etc.) e formate-os obrigatoriamente como: `<h3>[Texto da Descrição Traduzido]</h3>` (Título 3) e garanta que esses blocos de texto explicativo NÃO possuam nenhuma tag de negrito (como <strong>, <b> ou estilos de negrito inline) envolvendo o texto todo.
    3. Mantenha os mesmos atributos `src` originais de todas as imagens e GIFs intactos nas tags `<img>`.

    HTML da descrição original para ser traduzido e adaptado:
    ---
    {descricao_html_bruta}
    ---

    Texto bruto complementar para contexto do produto real:
    ---
    {texto_pagina}
    ---
    """
    else:
        print("[EXTRATOR] Nenhuma descrição rica original encontrada. Criando copy de alta conversão do zero...")
        prompt_sistema = f"""
    Você é um copywriter de e-commerce de elite, especialista em conversão e mineração de produtos.
    Sua tarefa é analisar o texto bruto de uma página de vendas, seu HTML de descrição e sua lista de imagens, extrair os dados cruciais e criar uma copy completa em {target_language} do zero.

    REGRAS INEGOCIÁVEIS DE ESTRUTURA E CONTEÚDO (CRIAÇÃO DO ZERO):
    1. O idioma de saída DEVE ser estritamente o {target_language}. Use tom persuasivo e focado em conversão.
    2. PROIBIDO o uso de símbolos de marca registrada. Remova QUALQUER caractere ® ou ™ de todo o texto gerado.
    3. O 'title' DEVE ter no máximo 40 caracteres (já no idioma de destino). Deve cumprir estritamente as políticas do Google Ads:
       - Use capitalização normal (Title Case). Nunca use ALL CAPS (letras maiúsculas).
       - É PROIBIDO o uso de emojis, exclamações ou símbolos promocionais (como ®, ™, ✅, 🚨, ⭐).
       - Não contemple termos comerciais/promocionais no título (como 'envío gratis', 'descuento', 'oferta', 'regalo').

    4. O 'handle' DEVE ser um identificador de URL extremamente curto, composto por 2 ou no máximo 3 palavras-chave no idioma de destino, separadas por hífen (ex: 'proyector-mini'). Nunca inclua preposições, artigos nem caracteres especiais.
    5. A 'seo_description' DEVE ter no máximo 90 caracteres (já no idioma de destino).
    6. Limpe qualquer referência ao nome da loja original ou de concorrentes.
    7. No campo 'description_html', você DEVE obrigatoriamente construir um layout de alta conversão estruturando o HTML final para conter exatamente a seguinte ordem estrutural (não use listas simples nem tabelas para o layout principal):
       
       - BLOCO 1 (TEXTO): Título curto atraente formatado como `<h1><strong>[Título Traduzido]</strong></h1>`, seguido de um parágrafo introdutório persuasivo formatado como `<h3>[Parágrafo Traduzido]</h3>` (sem negrito).
       - BLOCO 2 (GIF/IMG): Uma tag <img src="..." style="max-width:100%; height:auto; display:block; margin: 15px auto; border-radius: 8px;" />. Use de preferência a URL de um GIF animado real da lista de imagens se disponível. Caso contrário, use a primeira imagem da lista.
       - BLOCO 3 (TEXTO): Subtítulo persuasivo de benefício formatado como `<h1><strong>[Subtítulo Traduzido]</strong></h1>`, seguido de um parágrafo detalhando o Benefício Principal 1 formatado como `<h3>[Parágrafo Traduzido]</h3>` (sem negrito).
       - BLOCO 4 (IMG): Uma tag <img src="..." style="max-width:100%; height:auto; display:block; margin: 15px auto; border-radius: 8px;" /> contendo a segunda imagem de alta qualidade da galeria.
       - BLOCO 5 (TEXTO): Subtítulo persuasivo de benefício formatado como `<h1><strong>[Subtítulo Traduzido]</strong></h1>`, seguido de um parágrafo detalhando o Benefício Principal 2 formatado como `<h3>[Parágrafo Traduzido]</h3>` (sem negrito).
       - BLOCO 6 (IMG): Uma tag <img src="..." style="max-width:100%; height:auto; display:block; margin: 15px auto; border-radius: 8px;" /> contendo a terceira imagem de alta qualidade da galeria.
       - BLOCO 7 (TEXTO): Subtítulo persuasivo de benefício formatado como `<h1><strong>[Subtítulo Traduzido]</strong></h1>`, seguido de um parágrafo detalhando o Benefício Principal 3 formatado como `<h3>[Parágrafo Traduzido]</h3>` (sem negrito).
       - BLOCO 8 (IMG): Uma tag <img src="..." style="max-width:100%; height:auto; display:block; margin: 15px auto; border-radius: 8px;" /> contendo a quarta imagem de alta qualidade da galeria.
       - BLOCO 9 (TEXTO): Parágrafo de Fechamento/Conclusão altamente persuasivo ou de oferta sutil formatado como `<h3>[Parágrafo Traduzido]</h3>` (sem negrito).

    REGRAS DE IMAGENS:
    - É OBLIGATÓRIO incluir as tags <img> com as URLs originais nas posições 2, 4, 6 e 8 da estrutura do HTML.
    - Você DEVE selecionar as imagens correspondentes a partir da lista 'Imagens da Galeria' fornecida abaixo de forma sequencial (ex: primeira imagem para o Bloco 2, segunda imagem para o Bloco 4, etc.).
    - Se a lista de 'Imagens da Galeria' possuir menos imagens do que o necessário, reutilize as melhores imagens estáticas ou pegue links de imagens reais presentes no HTML original.
    - Não invente links de imagens que não estejam presentes na lista abaixo ou no HTML original.

    Imagens da Galeria (use-as para preencher/estruturar as tags <img> do description_html conforme as regras acima):
    {imagens_para_prompt}

    Texto bruto extraído da página original:
    ---
    {texto_pagina}
    ---
    """

    global client
    if client is None:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
    models_to_try = [
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite',
        'gemini-3.5-flash',
        'gemini-3.1-flash-lite',
        'gemini-flash-latest'
    ]
    response = None
    last_error = None
    
    for model_name in models_to_try:
        try:
            print(f"Chamando a API do Gemini ({model_name}) com saída estruturada...")
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=prompt_sistema,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ProdutoExtraido,
                    temperature=0.2,
                ),
            )
            break
        except Exception as e:
            print(f"Erro ou indisponibilidade no modelo {model_name}: {e}")
            last_error = e
            continue
            
    if response is None:
        raise Exception(f"Falha ao chamar a API do Gemini (todos os modelos falharam): {last_error}")
    
    # Converte a resposta estruturada/JSON para dicionário python
    try:
        if response.parsed:
            try:
                dados_limpos = response.parsed.model_dump()
            except AttributeError:
                dados_limpos = response.parsed.dict()
        else:
            dados_limpos = json.loads(response.text)
            
        # Restabelece o base64 real do WEBP animado no description_html caso o Gemini tenha inserido a URL fictícia
        if video_webp_base64 and "description_html" in dados_limpos:
            dados_limpos["description_html"] = dados_limpos["description_html"].replace(
                placeholder_url, 
                video_webp_base64
            )
        
        # Mantém o preço exatamente como retornado/identificado no site original
        price_raw = dados_limpos.get("price")
        if price_raw is None:
            price_raw = "0"
        dados_limpos["price"] = str(price_raw).strip()
        
        # Adiciona as 5 primeiras imagens do Playwright
        dados_limpos["images"] = imagens_brutas[:5]
        return dados_limpos
    except Exception as parse_error:
        print(f"Erro ao analisar o JSON retornado pelo Gemini: {parse_error}")
        print("Resposta bruta do Gemini:")
        print(response.text)
        raise Exception(f"Erro ao parsear dados estruturados: {parse_error}")
