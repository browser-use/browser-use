#!/bin/bash

# Configurar variáveis de ambiente para o Playwright
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/tmp/playwright-browsers}
export BROWSER_USE_DEBUG=${BROWSER_USE_DEBUG:-true}
export DISPLAY=:99

echo "Iniciando script de inicialização..."

# Carregar variáveis de ambiente do arquivo .env se existir
if [ -f .env ]; then
    echo "Carregando variáveis de ambiente do arquivo .env..."
    # Usar source para carregar as variáveis corretamente
    set -a
    source .env
    set +a
else
    echo "Arquivo .env não encontrado. Usando variáveis de ambiente padrão."
    # Definir variáveis padrão para PostgreSQL
    export POSTGRES_USER=${POSTGRES_USER:-postgres}
    export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres}
    export POSTGRES_DB=${POSTGRES_DB:-browser_use}
    export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
    export POSTGRES_PORT=${POSTGRES_PORT:-5432}
    export DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
fi

# Verifica se o psutil está instalado
if ! python3 -c "import psutil" &> /dev/null; then
    echo "psutil não está instalado. Instalando..."
    pip3 install psutil
fi

# Verifica se o playwright está instalado
if ! command -v playwright &> /dev/null; then
    echo "playwright não está instalado. Instalando..."
    pip3 install playwright
    playwright install
fi

# Verifica se as variáveis de ambiente do PostgreSQL estão configuradas
if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_PASSWORD" ] || [ -z "$POSTGRES_DB" ]; then
    echo "Erro: Variáveis de ambiente do PostgreSQL não configuradas"
    echo "Por favor, configure as seguintes variáveis no arquivo .env:"
    echo "POSTGRES_USER=postgres"
    echo "POSTGRES_PASSWORD=postgres"
    echo "POSTGRES_DB=browser_use"
    exit 1
fi

# Verificar variáveis de ambiente críticas
check_env_var() {
    local var=$1
    local desc=$2
    if [ -z "${!var}" ]; then
        echo "Erro: $desc não configurado"
        echo "Por favor, configure a variável $var no arquivo .env"
        exit 1
    fi
}

check_env_var "POSTGRES_USER" "Usuário do PostgreSQL"
check_env_var "POSTGRES_PASSWORD" "Senha do PostgreSQL"
check_env_var "POSTGRES_DB" "Nome do banco de dados"
check_env_var "POSTGRES_HOST" "Host do PostgreSQL"
check_env_var "POSTGRES_PORT" "Porta do PostgreSQL"

# Iniciar o servidor FastAPI
echo "Iniciando servidor FastAPI..."
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --reload 