# Browser-Use Web Backend

## 🔧 Configuration

Le backend utilise un fichier `config.env` pour stocker les variables d'environnement de manière sécurisée.

### 📝 Setup Initial

1. **Copiez le fichier template** :
   ```bash
   cp config.env.template config.env
   ```

2. **Éditez `config.env`** avec vos vraies valeurs :
   ```bash
   # Configuration Browser-Use Web Backend
   OPENAI_API_KEY=YOUR_OPENAI_API_KEY
   OPENAI_MODEL=gpt-4o-mini
   BROWSER_USE_SETUP_LOGGING=false
   HOST=0.0.0.0
   PORT=8000
   ```

3. **Obtenez votre clé API OpenAI** :
   - Allez sur https://platform.openai.com/account/api-keys
   - Créez une nouvelle clé API
   - Copiez-la dans le fichier `config.env`

### 🚀 Démarrage

```bash
python main_no_dotenv.py
```

### 🔒 Sécurité

- ❌ **Ne commitez JAMAIS** le fichier `config.env` 
- ✅ **Utilisez** `config.env.template` pour partager la structure
- ✅ **Ajoutez** `config.env` dans `.gitignore`

### 📊 Variables Disponibles

| Variable | Description | Défaut |
|----------|-------------|--------|
| `OPENAI_API_KEY` | Clé API OpenAI (obligatoire) | - |
| `OPENAI_MODEL` | Modèle OpenAI à utiliser | `gpt-4o-mini` |
| `BROWSER_USE_SETUP_LOGGING` | Logging Browser-Use | `false` |
| `HOST` | Adresse d'écoute du serveur | `0.0.0.0` |
| `PORT` | Port d'écoute du serveur | `8000` |

### 🐛 Dépannage

- **Erreur "Clé API non configurée"** : Vérifiez que `config.env` existe et contient une clé API valide
- **Erreur "401 Unauthorized"** : Votre clé API n'est pas valide ou a expiré
- **Fichier non trouvé** : Assurez-vous que `config.env` est dans le même dossier que `main_no_dotenv.py` 