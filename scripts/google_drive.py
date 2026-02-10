"""
📁 Google Drive Integration for Professor+
Upload/Download files to Google Drive for persistent storage on Streamlit Cloud
"""

import os
import json
import io
import streamlit as st
from datetime import datetime

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload


# ===========================
# CONFIGURATION
# ===========================
SCOPES = ['https://www.googleapis.com/auth/drive']
ROOT_FOLDER_ID = "19Kco_Tu_gZxVgzWuQb5gvB7-7Z3LS-8E"  # Ton dossier Professor_Plus_Data


def get_credentials():
    """
    Récupère les credentials Google depuis:
    - Streamlit Cloud: st.secrets["google_service_account"]
    - Local: fichier JSON
    """
    # 1. Essayer st.secrets (Streamlit Cloud)
    try:
        if hasattr(st, 'secrets') and 'google_service_account' in st.secrets:
            service_account_info = dict(st.secrets['google_service_account'])
            return service_account.Credentials.from_service_account_info(
                service_account_info, scopes=SCOPES
            )
    except Exception as e:
        pass
    
    # 2. Essayer fichier local
    local_paths = [
        os.path.join(os.path.dirname(__file__), "..", "config", "google_service_account.json"),
        os.path.join(os.path.dirname(__file__), "..", "google_service_account.json"),
    ]
    
    for path in local_paths:
        if os.path.exists(path):
            return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    
    return None


def get_drive_service():
    """Crée le service Google Drive."""
    creds = get_credentials()
    if not creds:
        return None
    return build('drive', 'v3', credentials=creds)


# ===========================
# FONCTIONS UTILITAIRES
# ===========================
def find_or_create_folder(service, folder_name, parent_id=None):
    """Trouve ou crée un dossier dans Google Drive."""
    parent_id = parent_id or ROOT_FOLDER_ID
    
    # Chercher si le dossier existe
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    
    # Créer le dossier
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    folder = service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')


def find_file(service, filename, folder_id=None):
    """Trouve un fichier par son nom dans un dossier."""
    folder_id = folder_id or ROOT_FOLDER_ID
    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name, modifiedTime)").execute()
    files = results.get('files', [])
    return files[0] if files else None


def list_files_in_folder(service, folder_id=None):
    """Liste tous les fichiers dans un dossier."""
    folder_id = folder_id or ROOT_FOLDER_ID
    query = f"'{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name, mimeType, modifiedTime)").execute()
    return results.get('files', [])


# ===========================
# UPLOAD FUNCTIONS
# ===========================
def upload_file(local_path, drive_filename=None, folder_id=None):
    """
    Upload un fichier local vers Google Drive.
    
    Args:
        local_path: Chemin du fichier local
        drive_filename: Nom du fichier sur Drive (optionnel, utilise le nom local sinon)
        folder_id: ID du dossier destination (optionnel, utilise ROOT sinon)
    
    Returns:
        dict: {"success": bool, "file_id": str, "error": str}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        folder_id = folder_id or ROOT_FOLDER_ID
        drive_filename = drive_filename or os.path.basename(local_path)
        
        # Vérifier si le fichier existe déjà
        existing = find_file(service, drive_filename, folder_id)
        
        # Déterminer le type MIME
        mime_type = 'application/octet-stream'
        if local_path.endswith('.json'):
            mime_type = 'application/json'
        elif local_path.endswith('.yaml') or local_path.endswith('.yml'):
            mime_type = 'text/yaml'
        elif local_path.endswith('.pdf'):
            mime_type = 'application/pdf'
        
        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        
        if existing:
            # Mettre à jour le fichier existant
            file = service.files().update(
                fileId=existing['id'],
                media_body=media
            ).execute()
        else:
            # Créer un nouveau fichier
            file_metadata = {
                'name': drive_filename,
                'parents': [folder_id]
            }
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
        
        return {"success": True, "file_id": file.get('id')}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def upload_bytes(content, drive_filename, folder_id=None, mime_type='application/octet-stream'):
    """
    Upload des bytes directement vers Google Drive.
    
    Args:
        content: bytes ou str à uploader
        drive_filename: Nom du fichier sur Drive
        folder_id: ID du dossier destination
        mime_type: Type MIME du fichier
    
    Returns:
        dict: {"success": bool, "file_id": str, "error": str}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        folder_id = folder_id or ROOT_FOLDER_ID
        
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        # Vérifier si le fichier existe déjà
        existing = find_file(service, drive_filename, folder_id)
        
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)
        
        if existing:
            file = service.files().update(
                fileId=existing['id'],
                media_body=media
            ).execute()
        else:
            file_metadata = {
                'name': drive_filename,
                'parents': [folder_id]
            }
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
        
        return {"success": True, "file_id": file.get('id')}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def upload_json(data, drive_filename, folder_id=None):
    """Upload un dict Python en tant que fichier JSON."""
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return upload_bytes(content, drive_filename, folder_id, 'application/json')


# ===========================
# DOWNLOAD FUNCTIONS
# ===========================
def download_file(file_id, local_path):
    """
    Télécharge un fichier depuis Google Drive.
    
    Args:
        file_id: ID du fichier sur Drive
        local_path: Chemin local de destination
    
    Returns:
        dict: {"success": bool, "error": str}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        request = service.files().get_media(fileId=file_id)
        
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        with open(local_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        
        return {"success": True}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def download_file_by_name(filename, local_path, folder_id=None):
    """
    Télécharge un fichier par son nom.
    
    Args:
        filename: Nom du fichier sur Drive
        local_path: Chemin local de destination
        folder_id: ID du dossier source
    
    Returns:
        dict: {"success": bool, "error": str}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        file = find_file(service, filename, folder_id)
        if not file:
            return {"success": False, "error": f"Fichier '{filename}' non trouvé"}
        
        return download_file(file['id'], local_path)
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def download_bytes(file_id):
    """
    Télécharge un fichier et retourne son contenu en bytes.
    
    Returns:
        dict: {"success": bool, "content": bytes, "error": str}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        return {"success": True, "content": buffer.getvalue()}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def download_json(filename, folder_id=None):
    """
    Télécharge un fichier JSON et retourne le dict.
    
    Returns:
        dict: {"success": bool, "data": dict, "error": str}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        file = find_file(service, filename, folder_id)
        if not file:
            return {"success": False, "error": f"Fichier '{filename}' non trouvé"}
        
        result = download_bytes(file['id'])
        if not result['success']:
            return result
        
        data = json.loads(result['content'].decode('utf-8'))
        return {"success": True, "data": data}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===========================
# FOLDER SYNC FUNCTIONS
# ===========================
def sync_folder_to_drive(local_folder, drive_folder_name=None, parent_id=None):
    """
    Synchronise un dossier local vers Google Drive.
    
    Args:
        local_folder: Chemin du dossier local
        drive_folder_name: Nom du dossier sur Drive (optionnel)
        parent_id: ID du dossier parent sur Drive
    
    Returns:
        dict: {"success": bool, "uploaded": int, "errors": list}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        drive_folder_name = drive_folder_name or os.path.basename(local_folder)
        folder_id = find_or_create_folder(service, drive_folder_name, parent_id)
        
        uploaded = 0
        errors = []
        
        for root, dirs, files in os.walk(local_folder):
            # Calculer le chemin relatif
            rel_path = os.path.relpath(root, local_folder)
            
            # Créer les sous-dossiers si nécessaire
            current_folder_id = folder_id
            if rel_path != '.':
                for part in rel_path.split(os.sep):
                    current_folder_id = find_or_create_folder(service, part, current_folder_id)
            
            # Uploader les fichiers
            for filename in files:
                local_path = os.path.join(root, filename)
                result = upload_file(local_path, filename, current_folder_id)
                if result['success']:
                    uploaded += 1
                else:
                    errors.append(f"{filename}: {result['error']}")
        
        return {"success": True, "uploaded": uploaded, "errors": errors, "folder_id": folder_id}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def sync_folder_from_drive(drive_folder_id, local_folder):
    """
    Télécharge un dossier depuis Google Drive.
    
    Args:
        drive_folder_id: ID du dossier sur Drive
        local_folder: Chemin du dossier local de destination
    
    Returns:
        dict: {"success": bool, "downloaded": int, "errors": list}
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        os.makedirs(local_folder, exist_ok=True)
        
        downloaded = 0
        errors = []
        
        def download_recursive(folder_id, local_path):
            nonlocal downloaded, errors
            
            files = list_files_in_folder(service, folder_id)
            
            for file in files:
                file_path = os.path.join(local_path, file['name'])
                
                if file['mimeType'] == 'application/vnd.google-apps.folder':
                    # C'est un dossier, récursion
                    os.makedirs(file_path, exist_ok=True)
                    download_recursive(file['id'], file_path)
                else:
                    # C'est un fichier
                    result = download_file(file['id'], file_path)
                    if result['success']:
                        downloaded += 1
                    else:
                        errors.append(f"{file['name']}: {result['error']}")
        
        download_recursive(drive_folder_id, local_folder)
        
        return {"success": True, "downloaded": downloaded, "errors": errors}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===========================
# HELPER FUNCTIONS
# ===========================
def ensure_drive_structure():
    """
    Crée la structure de dossiers sur Google Drive si nécessaire.
    
    Structure:
    - Professor_Plus_Data/
      - data/
      - Factures/
      - config/
    """
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Google Drive non configuré"}
    
    try:
        folders = {}
        for folder_name in ['data', 'Factures', 'config']:
            folder_id = find_or_create_folder(service, folder_name, ROOT_FOLDER_ID)
            folders[folder_name] = folder_id
        
        return {"success": True, "folders": folders}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_connection():
    """Teste la connexion à Google Drive."""
    service = get_drive_service()
    if not service:
        return {"success": False, "error": "Credentials non trouvées"}
    
    try:
        # Essayer de lister les fichiers dans le dossier root
        results = service.files().list(
            q=f"'{ROOT_FOLDER_ID}' in parents",
            pageSize=1,
            fields="files(id, name)"
        ).execute()
        
        return {"success": True, "message": "Connexion Google Drive OK"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}