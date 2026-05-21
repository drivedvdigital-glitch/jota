import asyncio
import os
from dotenv import load_dotenv
from extractor import scrape_page_content, extract_product_data

# Carrega configurações
load_dotenv()

async def run_test():
    # URL pública de testes (e-commerce fictício de livros)
    test_url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    
    print("==================================================")
    # Passo 1: Testar o Playwright (local)
    print("Passo 1: Testando a raspagem com Playwright...")
    scrape_result = await scrape_page_content(test_url)
    
    if scrape_result["success"]:
        print("\n[SUCESSO] Playwright conseguiu carregar e raspar a página!")
        print(f"Caracteres de texto extraídos: {len(scrape_result['text'])}")
        print(f"Imagens encontradas: {len(scrape_result['images'])}")
        if scrape_result["images"]:
            print(f"Primeira imagem encontrada: {scrape_result['images'][0]}")
    else:
        print(f"\n[ERRO] Falha no Playwright: {scrape_result.get('error')}")
        return

    print("==================================================")
    # Passo 2: Testar a extração com Gemini
    print("Passo 2: Testando a extração do Gemini...")
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key or api_key == "sua_chave_de_api_do_gemini_aqui":
        print("\n[AVISO] GEMINI_API_KEY não configurada no arquivo .env.")
        print("Para testar o Gemini, adicione a chave no arquivo .env e execute novamente.")
        print("A parte do Playwright já está funcionando 100%!")
        print("==================================================")
        return
        
    try:
        print("Chamando API do Gemini com o texto extraído...")
        produto = await extract_product_data(test_url)
        print("\n[SUCESSO] Gemini extraiu os dados de forma estruturada:")
        print(f"  Título: {produto['title']}")
        print(f"  Preço: {produto['price']}")
        print(f"  Descrição SEO: {produto['seo_description']}")
        print(f"  Benefícios (features): {produto['features']}")
        print(f"  Imagens do Produto: {produto['images']}")
    except Exception as e:
        print(f"\n[ERRO] Falha ao comunicar/processar dados no Gemini: {e}")
        
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_test())
