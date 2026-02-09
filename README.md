# 🎓 Professor+ Admin Dashboard

Application de gestion pour Professor+ - Soutien scolaire sur-mesure.

## 🚀 Fonctionnalités

- **📥 Extract TutorBird** : Charger les leçons depuis TutorBird
- **📄 Générer Factures** : Créer les PDFs de factures
- **💳 Payment Links** : Créer les liens de paiement Stripe
- **📧 Envoi Emails** : Envoyer factures et rappels
- **🔄 Sync Notion** : Synchroniser avec Notion
- **⚙️ Configuration** : Gérer profs, tarifs, API keys

## 📦 Installation locale

```bash
# Cloner le repo
git clone https://github.com/votre-repo/professor-plus-admin.git
cd professor-plus-admin

# Installer les dépendances
pip install -r requirements.txt

# Lancer l'app
streamlit run app.py
```

## ☁️ Déploiement sur Streamlit Cloud

1. **Créer un compte** sur [share.streamlit.io](https://share.streamlit.io)

2. **Connecter GitHub** et sélectionner le repo

3. **Configurer les secrets** dans les settings Streamlit Cloud :
   - Aller dans App Settings → Secrets
   - Coller le contenu de `secrets.yaml`

4. **Déployer** - l'app sera accessible via une URL publique

## 📁 Structure du projet

```
professor_plus_app/
├── app.py                 # Application principale
├── requirements.txt       # Dépendances Python
├── assets/
│   └── logo.png          # Logo Professor+
├── utils/
│   ├── __init__.py
│   ├── config.py         # Gestion configuration
│   ├── helpers.py        # Fonctions utilitaires
│   ├── tutorbird.py      # API TutorBird
│   └── stripe_utils.py   # API Stripe
└── data/                  # Données (gitignore)
    ├── secrets.yaml
    ├── familles_euros.yaml
    └── tarifs_speciaux.yaml
```

## ⚙️ Configuration

### secrets.yaml

```yaml
notion:
  token: "ntn_xxx"
  paiements_database_id: "xxx"
  root_page_paiements: "xxx"

stripe:
  platform_secret_key: "sk_live_xxx"

tutorbird:
  api_key: "eyJxxx"

gmail:
  email: "xxx@gmail.com"
  app_password: "xxxx xxxx xxxx xxxx"

teachers:
  "Bruno Lamaison":
    connect_account_id: "acct_xxx"
    pay_rate:
      chf: 25
      eur: 25
```

### familles_euros.yaml

```yaml
euros:
  - "Nom Parent 1"
  - "Nom Parent 2"
```

### tarifs_speciaux.yaml

```yaml
tarifs_speciaux:
  - teacher: "Jabrane Karkouri"
    parent: "Nikitina Anna"
    pay_rate: 40
```

## 🔐 Sécurité

- **Ne jamais commiter** les fichiers secrets (`.yaml` avec API keys)
- Utiliser les **Streamlit Secrets** en production
- Les fichiers sensibles sont dans `.gitignore`

## 📞 Support

Contact : professorplus.soutienscolaire@gmail.com
