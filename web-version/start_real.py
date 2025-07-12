#!/usr/bin/env python3
"""
🚀 Lanceur Browser-Use Web Version Réelle
Lance automatiquement le backend et le frontend
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def main():
    print("🚀 Browser-Use Web - Démarrage Version Réelle")
    print("=" * 50)
    
    # Vérifier Python
    python_version = sys.version_info
    if python_version < (3, 11):
        print("❌ Python 3.11+ requis")
        print(f"Version actuelle: {python_version.major}.{python_version.minor}")
        return
    
    print(f"✅ Python {python_version.major}.{python_version.minor} détecté")
    
    # Chemins
    project_root = Path(__file__).parent.parent
    backend_dir = Path(__file__).parent / "backend"
    
    print(f"📁 Projet: {project_root}")
    print(f"📁 Backend: {backend_dir}")
    
    # Vérifier browser-use
    browser_use_path = project_root
    if not (browser_use_path / "browser_use").exists():
        print("❌ Module browser_use non trouvé")
        print(f"Recherché dans: {browser_use_path}")
        return
    
    print("✅ Module browser_use trouvé")
    
    # Vérifier les dépendances
    try:
        import fastapi
        import uvicorn
        import websockets
        print("✅ Dépendances FastAPI disponibles")
    except ImportError as e:
        print(f"❌ Dépendances manquantes: {e}")
        print("📦 Installation des dépendances...")
        
        # Installer les dépendances
        subprocess.run([
            sys.executable, "-m", "pip", "install", 
            "-r", str(backend_dir / "requirements_real.txt")
        ], check=True)
        
        print("✅ Dépendances installées")
    
    # Vérifier browser-use installé
    try:
        sys.path.insert(0, str(project_root))
        import browser_use
        print("✅ Browser-Use importé avec succès")
    except ImportError as e:
        print(f"❌ Erreur import Browser-Use: {e}")
        print("📦 Installation locale de Browser-Use...")
        
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-e", str(project_root)
        ], check=True)
        
        print("✅ Browser-Use installé localement")
    
    # Vérifier Playwright
    try:
        subprocess.run([
            sys.executable, "-m", "playwright", "install", "chromium"
        ], check=True, capture_output=True)
        print("✅ Playwright Chromium installé")
    except Exception:
        print("⚠️  Problème avec Playwright (peut être ignoré)")
    
    # Vérifier .env
    env_file = project_root / ".env"
    if not env_file.exists():
        print("⚠️  Fichier .env non trouvé")
        print("Créer un fichier .env avec OPENAI_API_KEY=votre_clé")
    else:
        print("✅ Fichier .env trouvé")
    
    print("\n🎯 Lancement du backend Browser-Use...")
    print("🌐 Backend: http://localhost:8000")
    print("🧪 Test: http://localhost:8000/test")
    print("📚 API Docs: http://localhost:8000/docs")
    print("🎮 Frontend: http://localhost:3001")
    print("-" * 50)
    
    # Vérifier que le répertoire backend existe
    if not backend_dir.exists():
        print(f"❌ Répertoire backend non trouvé: {backend_dir}")
        return
    
    # Changer vers le répertoire backend
    os.chdir(backend_dir)
    
    # Lancer le serveur
    try:
        subprocess.run([
            sys.executable, "main_real.py"
        ], check=True)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur")
    except Exception as e:
        print(f"❌ Erreur: {e}")

if __name__ == "__main__":
    main() 