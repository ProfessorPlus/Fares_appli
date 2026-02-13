"""
🔧 Config Loader - Version Hybride
==================================
- Google Service Account: depuis st.secrets (TOML) pour pouvoir se connecter à Drive
- Reste de la config (notion, stripe, teachers...): depuis secrets.yaml sur Google Drive

Usage:
    from scripts.config_loader import load_secrets, is_streamlit_cloud
    
    secrets = load_secrets()
    if secrets:
        notion_token = secrets["notion"]["token"]
"""

import os
import io
import streamlit as st

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# ===========================
# DÉTECTION ENVIRONNEMENT
# ===========================

def is_streamlit_cloud():
    """Détecte si on est sur Streamlit Cloud."""
    return (
        os.environ.get("STREAMLIT_SHARING_MODE") == "true" or
        os.environ.get("STREAMLIT_SERVER_HEADLESS") == "true" or
        not os.path.exists("secrets.yaml") and not os.path.exists("config/secrets.yaml")
    )


def get_data_dir():
    """Retourne le dossier data approprié."""
    if is_streamlit_cloud():
        data_dir = "/tmp/data"
    else:
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.abspath(data_dir)


def get_invoices_dir():
    """Retourne le dossier factures approprié."""
    if is_streamlit_cloud():
        invoices_dir = "/tmp/Factures"
    else:
        invoices_dir = os.path.join(os.path.dirname(__file__), "..", "Factures")
    os.makedirs(invoices_dir, exist_ok=True)
    return os.path.abspath(invoices_dir)


# ===========================
# GOOGLE DRIVE CONNECTION
# ===========================

def _get_drive_service():
    """
    Crée le service Google Drive en utilisant st.secrets.
    Le google_service_account DOIT être dans st.secrets (TOML).
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        
        if hasattr(st, 'secrets') and 'google_service_account' in st.secrets:
            creds_info = dict(st.secrets['google_service_account'])
            creds = service_account.Credentials.from_service_account_info(
                creds_info,
                scopes=['https://www.googleapis.com/auth/drive']
            )
            return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"⚠️ Erreur connexion Drive: {e}")
    
    return None


def _download_secrets_from_drive(drive_service, folder_id):
    """Télécharge secrets.yaml depuis Google Drive."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
        
        # Chercher le fichier secrets.yaml dans le dossier config
        # D'abord trouver le dossier config
        query = f"name='config' and mimeType='application/vnd.google-apps.folder' and '{folder_id}' in parents and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        config_files = results.get('files', [])
        
        config_folder_id = config_files[0]['id'] if config_files else folder_id
        
        # Chercher secrets.yaml
        query = f"name='secrets.yaml' and '{config_folder_id}' in parents and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        if not files:
            # Essayer à la racine du dossier Professor_Plus_Data
            query = f"name='secrets.yaml' and '{folder_id}' in parents and trashed=false"
            results = drive_service.files().list(q=query, fields="files(id)").execute()
            files = results.get('files', [])
        
        if not files:
            print("⚠️ secrets.yaml non trouvé sur Google Drive")
            return None
        
        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        buffer.seek(0)
        return buffer.read().decode('utf-8')
        
    except Exception as e:
        print(f"⚠️ Erreur téléchargement secrets.yaml: {e}")
        return None


# ===========================
# CHARGEMENT DES SECRETS
# ===========================

# Cache pour éviter de recharger à chaque appel
_secrets_cache = None

def load_secrets(force_reload=False):
    """
    Charge les secrets depuis:
    1. Streamlit Cloud: secrets.yaml sur Google Drive (connecté via st.secrets)
    2. Local: fichier secrets.yaml dans config/ ou racine
    
    Args:
        force_reload: Force le rechargement même si en cache
    
    Returns:
        dict: Configuration complète ou None si non trouvée
    """
    global _secrets_cache
    
    if _secrets_cache is not None and not force_reload:
        return _secrets_cache
    
    secrets = None
    
    # 1. Mode Streamlit Cloud: charger depuis Google Drive
    if is_streamlit_cloud():
        print("☁️ Mode Streamlit Cloud détecté")
        
        if not YAML_AVAILABLE:
            print("❌ Module yaml non installé")
            return None
        
        # Récupérer le ROOT_FOLDER_ID depuis st.secrets ou utiliser la valeur par défaut
        root_folder_id = None
        if hasattr(st, 'secrets'):
            root_folder_id = st.secrets.get("google_drive", {}).get("root_folder_id")
        
        if not root_folder_id:
            # Valeur par défaut (ton dossier Professor_Plus_Data)
            root_folder_id = "19Kco_Tu_gZxVgzWuQb5gvB7-7Z3LS-8E"
        
        drive_service = _get_drive_service()
        if drive_service:
            yaml_content = _download_secrets_from_drive(drive_service, root_folder_id)
            if yaml_content:
                try:
                    secrets = yaml.safe_load(yaml_content)
                    print("✅ secrets.yaml chargé depuis Google Drive")
                except Exception as e:
                    print(f"❌ Erreur parsing YAML: {e}")
        else:
            print("❌ Impossible de se connecter à Google Drive")
            print("   Vérifiez que google_service_account est dans st.secrets")
    
    # 2. Mode local: charger depuis fichier
    else:
        print("💻 Mode local détecté")
        
        if not YAML_AVAILABLE:
            print("❌ Module yaml non installé")
            return None
        
        local_paths = [
            os.path.join(os.path.dirname(__file__), "..", "config", "secrets.yaml"),
            os.path.join(os.path.dirname(__file__), "..", "secrets.yaml"),
            "config/secrets.yaml",
            "secrets.yaml",
        ]
        
        for path in local_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        secrets = yaml.safe_load(f)
                    print(f"✅ secrets.yaml chargé depuis {path}")
                    break
                except Exception as e:
                    print(f"⚠️ Erreur lecture {path}: {e}")
    
    _secrets_cache = secrets
    return secrets


def clear_secrets_cache():
    """Vide le cache des secrets (utile pour recharger après modification)."""
    global _secrets_cache
    _secrets_cache = None


# ===========================
# HELPERS
# ===========================

def get_secret(key_path, default=None):
    """
    Accède à une valeur de secret par chemin.
    
    Args:
        key_path: Chemin séparé par des points (ex: "notion.token")
        default: Valeur par défaut si non trouvée
    
    Example:
        token = get_secret("notion.token")
        pay_rate = get_secret("teachers.Bruno Lamaison.pay_rate.chf", 55)
    """
    secrets = load_secrets()
    if not secrets:
        return default
    
    keys = key_path.split(".")
    value = secrets
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value