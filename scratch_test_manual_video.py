import asyncio
from main import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_extraction_with_manual_video():
    payload = {
        "url": "https://romancol.com/products/el-cine-del-futuro-llego-a-tu-casa",
        "creative_video_url": "https://www.w3schools.com/html/mov_bbb.mp4"
    }
    print("Enviando requisição de extração com vídeo de criativo manual...")
    response = client.post("/extrair", json=payload)
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("Extração com sucesso!")
        produto = data["produto"]
        print(f"Título: {produto['title']}")
        print(f"Handle gerado: {produto['handle']}")
        
        # Verifica se o primeiro bloco da copy é a tag img contendo base64 do webp animado
        html = produto["description_html"]
        print("Tamanho do HTML da copy:", len(html))
        if "data:image/webp;base64" in html:
            print("[SUCESSO] WebP animado (base64) foi injetado com sucesso na copy de vendas!")
        else:
            print("[ALERTA] WebP animado não encontrado na copy. Verifique se o download e conversão ocorreram de fato.")
    else:
        print(f"Erro: {response.text}")

if __name__ == "__main__":
    test_extraction_with_manual_video()
