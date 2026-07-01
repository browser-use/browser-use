# Comet — AI Web Navigation Agent

> **browser-use** + **Gemini 2.5 Pro** + **Chrome Profile** + **Vision** + **Memory**

Comet est un agent de navigation web IA autonome construit sur [browser-use](https://github.com/browser-use/browser-use).
Il herite de vos sessions Chrome (Gmail, LinkedIn, Amazon...) sans jamais declencher de 2FA.

---

## Installation rapide (Windows 10/11)

```bash
# 1. Cloner le repo
git clone https://github.com/achreflouati/browser-use-comet.git
cd browser-use-comet

# 2. Creer un environnement virtuel
python -m venv .venv
.venv\Scripts\activate

# 3. Installer les dependances
pip install -r comet/requirements.txt
pip install playwright
playwright install chromium

# 4. Configurer la cle API
copy .env.example .env
# Ouvrir .env et remplir GEMINI_API_KEY

# 5. Lancer Comet
python -m comet.main
```

---

## Architecture

```
browser-use-comet/
├── comet/
│   ├── main.py                  # Orchestrateur principal
│   ├── config.py                # Configuration centrale
│   ├── requirements.txt         # Dependances Comet
│   ├── agent/
│   │   ├── memory.py            # Memoire court + long terme (ChromaDB)
│   │   └── vision.py            # Gemini Vision - analyse screenshots
│   ├── tools/
│   │   └── filesystem.py        # Excel / Word / PDF / CSV / JSON
│   └── utils/
│       ├── logger.py            # Rich logger + fichier log
│       ├── retry.py             # Retry + Circuit Breaker
│       └── chrome_profile.py    # Profil Chrome persistant Windows
├── .env.example
└── COMET_README.md
```

---

## Exemples d'utilisation

```
Comet> Lis le fichier C:/leads.xlsx et envoie un email Gmail a chaque contact.

Comet> Va sur LinkedIn, recherche Python developer Paris,
       sauvegarde les 10 premiers profils dans output.xlsx.

Comet> Ouvre Amazon, recherche mechanical keyboard,
       genere un rapport Word avec les 5 meilleurs produits.
```

---

## Variables d'environnement

| Variable | Description | Requis |
|---|---|---|
| `GEMINI_API_KEY` | Cle Google AI Studio | oui |
| `CHROME_USER_DATA_DIR` | Chemin profil Chrome | non - auto-detecte |
| `CHROME_PROFILE` | Nom du profil Chrome | non - Default |
| `CAPTCHA_API_KEY` | Cle 2captcha | non - optionnel |

---

## Branches

| Branche | Description |
|---|---|
| `main` | browser-use upstream |
| `comet-integration` | Couche Comet active |
