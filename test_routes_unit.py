import asyncio
from unittest.mock import patch, MagicMock
from main import exportar_csv, enviar_shopify
from extractor import ProdutoCompleto

async def test_all():
    # 1. Dados do produto mockado
    product_data = ProdutoCompleto(
        title="Sapato Moderno e Elegante",
        seo_description="Sapato social masculino moderno e confortável feito de couro legítimo.",
        price="R$ 299,90",
        features=["Couro legítimo de alta durabilidade", "Palmilha ortopédica macia", "Solado antiderrapante"],
        images=["https://exemplo.com/imagem1.jpg", "https://exemplo.com/imagem2.jpg"],
        description_html="<h2>Sapato Extraordinário</h2><p>Feito em couro.</p><img src='https://exemplo.com/sapato.gif'>"
    )

    print("==================================================")
    print("Testando exportar_csv...")
    response = await exportar_csv(product_data)
    csv_bytes = response.body
    csv_text = csv_bytes.decode('utf-8')
    
    # Validações do CSV
    assert "Handle" in csv_text, "Cabeçalho do CSV incorreto"
    assert "sapato-moderno-e-elegante" in csv_text, "Slugify do Handle falhou"
    assert "299.90" in csv_text, "Preço não foi limpo corretamente"
    assert "https://exemplo.com/imagem1.jpg" in csv_text, "Imagem 1 ausente"
    assert "https://exemplo.com/imagem2.jpg" in csv_text, "Imagem 2 ausente"
    assert "sapato.gif" in csv_text, "Description HTML (GIF) ausente no CSV"
    print("[SUCESSO] Teste de exportação CSV passou!")

    print("==================================================")
    print("Testando enviar_shopify...")
    # Configura variáveis de ambiente mockadas para o teste
    with patch.dict('os.environ', {
        'SHOPIFY_SHOP_NAME': 'loja-teste',
        'SHOPIFY_ACCESS_TOKEN': 'shpat_token_teste_123'
    }):
        # Mock para requests.post
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "product": {
                "id": 123456789
            }
        }
        
        with patch('requests.post', return_value=mock_response) as mock_post:
            res = await enviar_shopify(product_data)
            
            # Validações do envio para a Shopify
            assert res["success"] is True, "Upload retornou falha"
            assert res["product_id"] == 123456789, "ID do produto incorreto"
            assert "loja-teste" in res["admin_url"], "URL de admin incorreta"
            
            # Verifica se os parâmetros de chamada para post estão corretos
            mock_post.assert_called_once()
            called_url = mock_post.call_args[0][0]
            called_headers = mock_post.call_args[1]['headers']
            called_json = mock_post.call_args[1]['json']
            
            assert "loja-teste.myshopify.com/admin/api/2026-04/products.json" in called_url, "URL de API incorreta"
            assert called_headers["X-Shopify-Access-Token"] == "shpat_token_teste_123", "Token de acesso incorreto"
            assert called_json["product"]["title"] == "Sapato Moderno e Elegante", "Título incorreto no JSON de envio"
            assert called_json["product"]["status"] == "draft", "Status não é draft"
            assert "sapato.gif" in called_json["product"]["body_html"], "Description HTML (GIF) ausente no envio Shopify"
            
            print("[SUCESSO] Teste de upload Shopify passou!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(test_all())
