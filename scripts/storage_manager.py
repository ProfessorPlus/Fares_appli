"""
💾 Storage Manager
Gère le stockage des fichiers avec Google Drive pour Streamlit Cloud.
Abstrait les opérations de lecture/écriture pour fonctionner en local et sur le cloud.
"""

import os
import json
import io
import streamlit as st
from datetime import datetime

# Import Google Drive (optionnel)
try:
    from scripts.google_drive import (
        get_drive_service, find_or_create_folder, find_file,
        upload_file, upload_bytes, upload_json,
        download_file, download_file_by_name, download_json,
        sync_folder_to_drive, sync_folder_from_drive,
        ROOT_FOLDER_ID, ensure_drive_structure
    )
    DRIVE_AVAILABLE = True
except ImportError:
    DRIVE_AVAILABLE = False

from scripts.config_loader import is_streamlit_cloud, get_data_dir, get_invoices_dir


# ===========================
# CACHE DES FOLDER IDS
# ===========================
_folder_ids_cache = {}


def _get_folder_id(folder_name):
    """Récupère ou crée un dossier sur Google Drive et cache l'ID."""
    if folder_name in _folder_ids_cache:
        return _folder_ids_cache[folder_name]
    
    if not DRIVE_AVAILABLE:
        return None
    
    service = get_drive_service()
    if not service:
        return None
    
    folder_id = find_or_create_folder(service, folder_name, ROOT_FOLDER_ID)
    _folder_ids_cache[folder_name] = folder_id
    return folder_id


# ===========================
# FONCTIONS DE STOCKAGE UNIFIÉES
# ===========================

def save_json(filename, data, folder="data"):
    """
    Sauvegarde un dict en JSON.
    
    Args:
        filename: Nom du fichier (ex: "payment_links_output.json")
        data: Dict à sauvegarder
        folder: Dossier ("data", "config", "Factures")
    
    Returns:
        dict: {"success": bool, "local_path": str, "drive_id": str, "error": str}
    """
    result = {"success": False, "local_path": None, "drive_id": None}
    
    # 1. Toujours sauvegarder localement (pour usage immédiat)
    if folder == "data":
        local_dir = get_data_dir()
    elif folder == "Factures":
        local_dir = get_invoices_dir()
    else:
        local_dir = os.path.join(get_data_dir(), "..", folder)
    
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, filename)
    
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        result["local_path"] = local_path
    except Exception as e:
        result["error"] = f"Erreur sauvegarde locale: {e}"
        return result
    
    # 2. Si Streamlit Cloud, sauvegarder aussi sur Google Drive
    if is_streamlit_cloud() and DRIVE_AVAILABLE:
        try:
            folder_id = _get_folder_id(folder)
            if folder_id:
                drive_result = upload_json(data, filename, folder_id)
                if drive_result["success"]:
                    result["drive_id"] = drive_result["file_id"]
        except Exception as e:
            print(f"⚠️ Erreur upload Drive: {e}")
    
    result["success"] = True
    return result


def load_json(filename, folder="data", default=None):
    """
    Charge un fichier JSON.
    
    Args:
        filename: Nom du fichier
        folder: Dossier ("data", "config", "Factures")
        default: Valeur par défaut si non trouvé
    
    Returns:
        dict: Données chargées ou default
    """
    
    # 1. D'abord essayer le fichier local (plus rapide)
    if folder == "data":
        local_dir = get_data_dir()
    elif folder == "Factures":
        local_dir = get_invoices_dir()
    else:
        local_dir = os.path.join(get_data_dir(), "..", folder)
    
    local_path = os.path.join(local_dir, filename)
    
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Erreur lecture locale {filename}: {e}")
    
    # 2. Si Streamlit Cloud et pas trouvé localement, essayer Google Drive
    if is_streamlit_cloud() and DRIVE_AVAILABLE:
        try:
            folder_id = _get_folder_id(folder)
            if folder_id:
                drive_result = download_json(filename, folder_id)
                if drive_result["success"]:
                    # Sauvegarder localement pour usage futur
                    os.makedirs(local_dir, exist_ok=True)
                    with open(local_path, "w", encoding="utf-8") as f:
                        json.dump(drive_result["data"], f, indent=2, ensure_ascii=False)
                    return drive_result["data"]
        except Exception as e:
            print(f"⚠️ Erreur download Drive {filename}: {e}")
    
    return default


def save_file(local_path, drive_folder="data", drive_filename=None):
    """
    Sauvegarde un fichier local vers Google Drive.
    
    Args:
        local_path: Chemin du fichier local
        drive_folder: Dossier destination sur Drive
        drive_filename: Nom sur Drive (optionnel, utilise le nom local sinon)
    
    Returns:
        dict: {"success": bool, "drive_id": str, "error": str}
    """
    if not os.path.exists(local_path):
        return {"success": False, "error": f"Fichier non trouvé: {local_path}"}
    
    if not is_streamlit_cloud() or not DRIVE_AVAILABLE:
        return {"success": True, "drive_id": None, "message": "Mode local, pas d'upload Drive"}
    
    try:
        folder_id = _get_folder_id(drive_folder)
        if folder_id:
            result = upload_file(local_path, drive_filename, folder_id)
            return result
        return {"success": False, "error": "Dossier Drive non trouvé"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def download_from_drive(drive_filename, local_path, drive_folder="data"):
    """
    Télécharge un fichier depuis Google Drive.
    
    Args:
        drive_filename: Nom du fichier sur Drive
        local_path: Chemin de destination locale
        drive_folder: Dossier source sur Drive
    
    Returns:
        dict: {"success": bool, "error": str}
    """
    if not DRIVE_AVAILABLE:
        return {"success": False, "error": "Google Drive non disponible"}
    
    try:
        folder_id = _get_folder_id(drive_folder)
        if folder_id:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            return download_file_by_name(drive_filename, local_path, folder_id)
        return {"success": False, "error": "Dossier Drive non trouvé"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===========================
# GESTION DES FACTURES
# ===========================

def save_invoice_folder(local_folder_path, year_month_name=None):
    """
    Sauvegarde un dossier de factures complet vers Google Drive.
    
    Args:
        local_folder_path: Chemin du dossier local (ex: /tmp/Factures/2026/Février - 01-02-2026)
        year_month_name: Nom du sous-dossier (optionnel, déduit du chemin sinon)
    
    Returns:
        dict: {"success": bool, "uploaded": int, "errors": list}
    """
    if not os.path.exists(local_folder_path):
        return {"success": False, "error": f"Dossier non trouvé: {local_folder_path}"}
    
    if not is_streamlit_cloud() or not DRIVE_AVAILABLE:
        return {"success": True, "uploaded": 0, "message": "Mode local, pas d'upload Drive"}
    
    try:
        # Structure: Factures/2026/Février - 01-02-2026/...
        factures_folder_id = _get_folder_id("Factures")
        if not factures_folder_id:
            return {"success": False, "error": "Dossier Factures non trouvé sur Drive"}
        
        # Extraire l'année et le nom du mois depuis le chemin
        path_parts = local_folder_path.rstrip("/").split("/")
        month_folder_name = path_parts[-1]  # ex: "Février - 01-02-2026"
        year_folder_name = path_parts[-2] if len(path_parts) >= 2 else str(datetime.now().year)
        
        # Créer/trouver le dossier année
        service = get_drive_service()
        year_folder_id = find_or_create_folder(service, year_folder_name, factures_folder_id)
        
        # Sync le dossier du mois
        result = sync_folder_to_drive(local_folder_path, month_folder_name, year_folder_id)
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_invoice_folder(year, month_folder_name, local_base_path=None):
    """
    Télécharge un dossier de factures depuis Google Drive.
    
    Args:
        year: Année (ex: "2026")
        month_folder_name: Nom du dossier mois (ex: "Février - 01-02-2026")
        local_base_path: Chemin de base local (optionnel)
    
    Returns:
        dict: {"success": bool, "local_path": str, "downloaded": int, "errors": list}
    """
    if not DRIVE_AVAILABLE:
        return {"success": False, "error": "Google Drive non disponible"}
    
    try:
        local_base = local_base_path or get_invoices_dir()
        local_path = os.path.join(local_base, str(year), month_folder_name)
        
        # Trouver le dossier sur Drive
        service = get_drive_service()
        factures_folder_id = _get_folder_id("Factures")
        
        if not factures_folder_id:
            return {"success": False, "error": "Dossier Factures non trouvé sur Drive"}
        
        # Trouver le dossier année
        year_file = find_file(service, str(year), factures_folder_id)
        if not year_file:
            return {"success": False, "error": f"Dossier année {year} non trouvé"}
        
        # Trouver le dossier mois
        month_file = find_file(service, month_folder_name, year_file["id"])
        if not month_file:
            return {"success": False, "error": f"Dossier {month_folder_name} non trouvé"}
        
        # Télécharger
        result = sync_folder_from_drive(month_file["id"], local_path)
        result["local_path"] = local_path
        return result
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_invoice_folders():
    """
    Liste tous les dossiers de factures disponibles.
    
    Returns:
        list: [{"year": str, "month": str, "path": str, "source": "local"|"drive"}]
    """
    folders = []
    
    # 1. Lister les dossiers locaux
    local_base = get_invoices_dir()
    if os.path.exists(local_base):
        for year in os.listdir(local_base):
            year_path = os.path.join(local_base, year)
            if os.path.isdir(year_path):
                for month_folder in os.listdir(year_path):
                    month_path = os.path.join(year_path, month_folder)
                    if os.path.isdir(month_path):
                        folders.append({
                            "year": year,
                            "month": month_folder,
                            "path": month_path,
                            "source": "local"
                        })
    
    # 2. Si Streamlit Cloud, lister aussi Google Drive
    if is_streamlit_cloud() and DRIVE_AVAILABLE:
        try:
            from scripts.google_drive import list_files_in_folder
            
            service = get_drive_service()
            factures_folder_id = _get_folder_id("Factures")
            
            if factures_folder_id:
                # Lister les années
                years = list_files_in_folder(service, factures_folder_id)
                for year_file in years:
                    if year_file["mimeType"] == "application/vnd.google-apps.folder":
                        # Lister les mois
                        months = list_files_in_folder(service, year_file["id"])
                        for month_file in months:
                            if month_file["mimeType"] == "application/vnd.google-apps.folder":
                                # Vérifier si pas déjà dans la liste locale
                                exists = any(
                                    f["year"] == year_file["name"] and f["month"] == month_file["name"]
                                    for f in folders
                                )
                                if not exists:
                                    folders.append({
                                        "year": year_file["name"],
                                        "month": month_file["name"],
                                        "path": None,  # Pas encore téléchargé
                                        "source": "drive",
                                        "drive_id": month_file["id"]
                                    })
        except Exception as e:
            print(f"⚠️ Erreur listing Drive: {e}")
    
    # Trier par date
    def sort_key(f):
        try:
            # Extraire la date du nom de dossier "Février - 01-02-2026"
            date_part = f["month"].split(" - ")[-1]
            return datetime.strptime(date_part, "%d-%m-%Y")
        except:
            return datetime.min
    
    folders.sort(key=sort_key, reverse=True)
    return folders


# ===========================
# INITIALISATION AU DÉMARRAGE
# ===========================

def init_storage():
    """
    Initialise le stockage au démarrage de l'app.
    - Crée les dossiers locaux
    - Vérifie la connexion Google Drive si sur le cloud
    - Synchronise les données essentielles depuis Drive
    
    Returns:
        dict: {"success": bool, "drive_connected": bool, "message": str}
    """
    result = {
        "success": True,
        "drive_connected": False,
        "message": ""
    }
    
    # 1. Créer les dossiers locaux
    get_data_dir()
    get_invoices_dir()
    
    # 2. Vérifier Google Drive si sur le cloud
    if is_streamlit_cloud() and DRIVE_AVAILABLE:
        try:
            # Tester la connexion
            drive_result = ensure_drive_structure()
            if drive_result["success"]:
                result["drive_connected"] = True
                result["message"] = "Google Drive connecté"
                
                # Synchroniser les fichiers de données essentiels
                essential_files = [
                    "full_output_tb_SIMPLE.json",
                    "payment_links_output.json",
                    "payment_links_report.json"
                ]
                
                for filename in essential_files:
                    load_json(filename, "data")  # Télécharge depuis Drive si existe
                    
            else:
                result["message"] = f"Erreur Drive: {drive_result.get('error')}"
        except Exception as e:
            result["message"] = f"Erreur init Drive: {e}"
    else:
        result["message"] = "Mode local" if not is_streamlit_cloud() else "Google Drive non configuré"
    
    return result