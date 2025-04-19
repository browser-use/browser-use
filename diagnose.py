#!/usr/bin/env python3
"""
Diagnóstico do ambiente Browser-use API
Este script verifica se todas as dependências necessárias estão disponíveis
e se o ambiente está corretamente configurado.
"""

import sys
import os
import importlib.util
import subprocess
import platform
import json

print("Iniciando diagnóstico do Browser-use API...\n")

# Versão do Python
print(f"Versão do Python: {platform.python_version()}")
if sys.version_info < (3, 11):
    print("⚠️ AVISO: Versão mínima do Python requerida é 3.11!")
else:
    print("✅ Versão do Python OK")

# Verificar dependências obrigatórias
required_packages = [
    "fastapi",
    "uvicorn",
    "playwright",
    "langchain_google_genai",
    "browser_use",
]

missing_packages = []
for package in required_packages:
    spec = importlib.util.find_spec(package)
    if spec is None:
        missing_packages.append(package)
        print(f"❌ Pacote '{package}' não encontrado")
    else:
        try:
            module = importlib.import_module(package)
            version = getattr(module, "__version__", "versão desconhecida")
            print(f"✅ {package} instalado (versão {version})")
        except ImportError as e:
            print(f"⚠️ {package} encontrado mas não pode ser importado: {e}")

# Verificar variáveis de ambiente
env_vars = [
    "PLAYWRIGHT_BROWSERS_PATH",
    "BROWSER_USE_DEBUG",
    "BROWSER_USE_HEADLESS",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
]

print("\nVariáveis de ambiente:")
for var in env_vars:
    if var in os.environ:
        value = "***" if "KEY" in var or "TOKEN" in var else os.environ[var]
        print(f"✅ {var} = {value}")
    else:
        print(f"⚠️ {var} não definida")

# Verificar disponibilidade do Xvfb
print("\nVerificando disponibilidade do Xvfb:")
try:
    xvfb_version = subprocess.run(
        ["Xvfb", "-version"], 
        capture_output=True, 
        text=True, 
        check=False
    )
    if xvfb_version.returncode == 0:
        print(f"✅ Xvfb disponível: {xvfb_version.stderr.strip()}")
    else:
        print(f"❌ Xvfb não disponível (código {xvfb_version.returncode})")
except FileNotFoundError:
    print("❌ Xvfb não encontrado no PATH")

# Verificar navegadores do Playwright
print("\nVerificando navegadores do Playwright:")
try:
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browsers = {
            "chromium": False,
            "firefox": False,
            "webkit": False
        }
        
        try:
            browser = p.chromium.launch()
            browsers["chromium"] = True
            browser.close()
        except Exception as e:
            print(f"❌ Erro ao iniciar Chromium: {e}")
        
        for name, available in browsers.items():
            if available:
                print(f"✅ {name.capitalize()} disponível")
            else:
                print(f"⚠️ {name.capitalize()} não verificado")
except Exception as e:
    print(f"❌ Erro ao inicializar Playwright: {e}")

# Verificar arquivo server.py
print("\nVerificando arquivo server.py:")
if os.path.exists("server.py"):
    print(f"✅ Arquivo server.py encontrado")
    with open("server.py", "r") as f:
        content = f.read()
        if "langchain_google_genai" in content:
            print("✅ server.py utiliza langchain_google_genai")
        else:
            print("ℹ️ server.py não parece utilizar langchain_google_genai diretamente")
else:
    print("❌ Arquivo server.py não encontrado no diretório atual")

print("\nDiagnóstico concluído!")

if missing_packages:
    print(f"\n⚠️ Os seguintes pacotes necessários estão faltando: {', '.join(missing_packages)}")
    print("Execute o seguinte comando para instalar os pacotes faltantes:")
    print(f"pip install {' '.join(missing_packages)}")
else:
    print("\n✅ Todas as dependências requeridas estão instaladas") 