#!/usr/bin/env python3
"""
🔧 Script de setup pour Browser-Use Web Backend
Automatise la configuration initiale avec config.env
"""

import os
import shutil
import sys

def setup_backend():
    """Configuration initiale du backend"""
    print("🚀 Setup Browser-Use Web Backend")
    print("=" * 50)
    
    # Vérifier si config.env existe
    config_file = "config.env"
    template_file = "config.env.template"
    
    if os.path.exists(config_file):
        print(f"✅ {config_file} existe déjà")
        
        # Demander s'il faut le recréer
        response = input("🔄 Voulez-vous le recréer ? (y/N): ").lower()
        if response != 'y':
            print("⏭️ Configuration ignorée")
            return
    
    # Copier le template
    if os.path.exists(template_file):
        shutil.copy(template_file, config_file)
        print(f"📋 {config_file} créé depuis le template")
    else:
        print(f"❌ Template {template_file} non trouvé")
        return
    
    # Demander la clé API
    print("\n🔑 Configuration de la clé API OpenAI")
    print("📝 Obtenez votre clé sur: https://platform.openai.com/account/api-keys")
    
    api_key = input("🔐 Entrez votre clé API OpenAI: ").strip()
    
    if not api_key:
        print("⚠️ Aucune clé API fournie - vous devrez l'ajouter manuellement")
        return
    
    if not api_key.startswith('sk-'):
        print("⚠️ La clé API semble invalide (doit commencer par 'sk-')")
        response = input("🤔 Continuer quand même ? (y/N): ").lower()
        if response != 'y':
            return
    
    # Mettre à jour le fichier config.env
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remplacer la clé API
        content = content.replace('sk-proj-VOTRE_CLE_API_ICI', api_key)
        
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ Clé API configurée dans {config_file}")
        
    except Exception as e:
        print(f"❌ Erreur lors de la configuration: {e}")
        return
    
    # Vérifier les dépendances
    print("\n📦 Vérification des dépendances...")
    try:
        import fastapi
        import uvicorn
        import browser_use
        print("✅ Toutes les dépendances sont installées")
    except ImportError as e:
        print(f"⚠️ Dépendance manquante: {e}")
        print("📝 Installez avec: pip install -r requirements.txt")
    
    print("\n🎉 Configuration terminée !")
    print("🚀 Démarrez le serveur avec: python main_no_dotenv.py")
    print("🌐 Interface web: http://localhost:3000")
    print("📚 API docs: http://localhost:8000/docs")

if __name__ == "__main__":
    setup_backend() 