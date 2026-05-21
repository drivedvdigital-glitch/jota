# Imagem oficial do Playwright pré-configurada com Chromium e todas as dependências de sistema
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Define o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copia a lista de dependências
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia os arquivos do projeto (código fonte, templates, etc.)
COPY . .

# Expõe a porta do servidor (Render/Railway injetarão a porta correta)
EXPOSE 8000

# Executa o servidor FastAPI com Uvicorn escutando na porta definida pela variável PORT
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
