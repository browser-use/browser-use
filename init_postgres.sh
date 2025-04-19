#!/bin/bash

# Verifica se o PostgreSQL está instalado
if ! command -v psql &> /dev/null; then
    echo "PostgreSQL não está instalado. Instalando..."
    sudo apt-get update
    sudo apt-get install -y postgresql postgresql-contrib
fi

# Inicia o serviço do PostgreSQL
sudo service postgresql start

# Espera o PostgreSQL iniciar
sleep 5

# Cria o banco de dados e usuário se não existirem
sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD 'postgres' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE browser_use OWNER postgres;"

echo "PostgreSQL configurado e pronto para uso!" 