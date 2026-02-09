"""
🔔 Send Payment Reminders
Envoie des rappels de paiement aux familles n'ayant pas encore payé
VERSION CORRIGÉE - Gère les sous-dossiers par famille
"""

import os
import smtplib
import unicodedata
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from difflib import SequenceMatcher
import time
import requests


MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


def normalize(s):
    """Normalise un nom : minuscules, sans accents, espaces propres"""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace("-", " ")
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    if "," in s:
        p = [x.strip() for x in s.split(",", 1)]
        if len(p) == 2:
            s = f"{p[1]} {p[0]}"
    return s.strip()


def get_default_reminder_template(month_name=None, year=None):
    """Retourne le template d'email de rappel par défaut."""
    
    if not month_name:
        now = datetime.now()
        month_name = MONTHS_FR[now.month - 1]
        year = now.year
    
    return {
        "subject": f"Rappel - Facture(s) en attente - Soutien scolaire - {month_name} {year}",
        "body": f"""Bonjour,

J'espère que vous allez bien.

Je me permets de vous relancer concernant la/les facture(s) de soutien scolaire du mois de {month_name} {year} qui reste(nt) en attente de règlement.

Vous trouverez ci-joint la/les facture(s) correspondante(s). Vous pouvez régler directement en cliquant sur le bouton "Payer en ligne" dans le PDF.

Merci de procéder au paiement dès que possible.

N'hésitez pas à me contacter si vous avez des questions ou si vous avez déjà effectué le paiement.

Cordialement,
Professor+
"""
    }


def get_unpaid_families_from_notion(secrets, callback=None):
    """
    Récupère la liste des familles n'ayant pas encore payé depuis Notion.
    
    Returns:
        list: [{"parent_name": str, "parent_email": str, "amount": float, "date": str}]
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        def notion_request(method, endpoint, json_data=None):
            time.sleep(0.35)
            url = f"https://api.notion.com/v1/{endpoint}"
            
            if method == "POST":
                r = requests.post(url, headers=HEADERS, json=json_data, timeout=30)
            else:
                return None
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 2))
                time.sleep(retry)
                return notion_request(method, endpoint, json_data)
            
            if r.status_code in [200, 201]:
                return r.json()
            return None
        
        update(10, "📥 Chargement des données Notion...")
        
        # Filtrer les non-payés
        all_rows = []
        cursor = None
        
        while True:
            payload = {
                "filter": {
                    "property": "Payé",
                    "checkbox": {"equals": False}
                }
            }
            if cursor:
                payload["start_cursor"] = cursor
            
            data = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", payload)
            if not data:
                break
            
            all_rows.extend(data.get("results", []))
            
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        
        update(50, f"📊 {len(all_rows)} familles non payées trouvées")
        
        unpaid = []
        for row in all_rows:
            props = row["properties"]
            
            # Famille
            famille = ""
            famille_prop = props.get("Famille", {})
            if famille_prop.get("title"):
                famille = famille_prop["title"][0]["plain_text"] if famille_prop["title"] else ""
            
            # Email
            email_prop = props.get("Email parent", {})
            if email_prop.get("email"):
                email = email_prop["email"]
            elif email_prop.get("rich_text"):
                email = email_prop["rich_text"][0]["plain_text"] if email_prop["rich_text"] else ""
            else:
                email = ""
            
            # Montant
            montant = props.get("Montant total dû", {}).get("number", 0)
            
            # Date
            date_cours = None
            if props.get("Date cours factures", {}).get("date"):
                date_cours = props["Date cours factures"]["date"].get("start")
            
            if famille and email:
                unpaid.append({
                    "parent_name": famille,
                    "parent_email": email,
                    "amount": montant,
                    "date": date_cours,
                    "page_id": row["id"]
                })
        
        return {"success": True, "unpaid": unpaid}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_send_reminders(secrets, data, invoice_folder, data_dir,
                       custom_subject=None, custom_body=None,
                       selected_families=None, send_to_test=False,
                       callback=None):
    """
    Envoie des rappels de paiement aux familles n'ayant pas payé.
    
    Args:
        secrets: Configuration YAML
        data: Données des familles (pour matcher les factures)
        invoice_folder: Dossier contenant les factures
        data_dir: Dossier des données
        custom_subject: Sujet personnalisé (optionnel)
        custom_body: Corps personnalisé (optionnel)
        selected_families: Liste des parent_name à relancer (None = tous)
        send_to_test: Si True, envoie uniquement à l'email de test
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "sent": int, "errors": list}
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        # Config email
        gmail_config = secrets.get("gmail", {})
        sender_email = gmail_config.get("email")
        app_password = gmail_config.get("app_password")
        
        if not sender_email or not app_password:
            return {"success": False, "error": "Configuration email manquante dans secrets.yaml"}
        
        # Récupérer les familles non payées depuis Notion
        update(5, "📥 Récupération des impayés depuis Notion...")
        result = get_unpaid_families_from_notion(secrets, callback)
        
        if not result["success"]:
            return result
        
        unpaid_families = result["unpaid"]
        
        if not unpaid_families:
            return {"success": True, "sent": 0, "message": "Aucune famille avec paiement en attente"}
        
        # Filtrer si sélection
        if selected_families:
            unpaid_families = [f for f in unpaid_families if f["parent_name"] in selected_families]
        
        update(20, f"📊 {len(unpaid_families)} famille(s) à relancer")
        
        # Template
        template = get_default_reminder_template()
        subject = custom_subject or template["subject"]
        body = custom_body or template["body"]
        
        # Connexion SMTP
        update(30, "🔌 Connexion au serveur email...")
        
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        
        sent = 0
        errors = []
        total = len(unpaid_families)
        
        for i, family in enumerate(unpaid_families):
            progress = int(30 + (i / total * 65))
            
            recipient = sender_email if send_to_test else family["parent_email"]
            
            update(progress, f"📧 Rappel à {family['parent_name']}...")
            
            try:
                # Créer le message
                msg = MIMEMultipart()
                msg["From"] = sender_email
                msg["To"] = recipient
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))
                
                # Chercher et attacher les factures correspondantes
                # ⚠️ STRUCTURE : invoice_folder contient des sous-dossiers par famille
                attached_count = 0
                
                if os.path.exists(invoice_folder):
                    parent_norm = normalize(family["parent_name"])
                    
                    # Scanner les sous-dossiers
                    for item in os.listdir(invoice_folder):
                        item_path = os.path.join(invoice_folder, item)
                        
                        if os.path.isdir(item_path):
                            folder_norm = normalize(item)
                            
                            # Vérifier si ce dossier correspond à la famille
                            score = SequenceMatcher(None, folder_norm, parent_norm).ratio()
                            
                            if score > 0.7 or folder_norm == parent_norm:
                                # Attacher tous les PDFs de ce dossier
                                for pdf in os.listdir(item_path):
                                    if pdf.lower().endswith(".pdf"):
                                        invoice_path = os.path.join(item_path, pdf)
                                        with open(invoice_path, "rb") as f:
                                            part = MIMEBase("application", "pdf")
                                            part.set_payload(f.read())
                                            encoders.encode_base64(part)
                                            part.add_header("Content-Disposition", f"attachment; filename={pdf}")
                                            msg.attach(part)
                                            attached_count += 1
                                break  # On a trouvé le bon dossier
                        
                        # Fallback: PDFs à la racine
                        elif item.lower().endswith(".pdf"):
                            pdf_lower = item.lower()
                            name_parts = parent_norm.split()
                            if any(part in pdf_lower for part in name_parts if len(part) > 2):
                                invoice_path = os.path.join(invoice_folder, item)
                                with open(invoice_path, "rb") as f:
                                    part = MIMEBase("application", "pdf")
                                    part.set_payload(f.read())
                                    encoders.encode_base64(part)
                                    part.add_header("Content-Disposition", f"attachment; filename={item}")
                                    msg.attach(part)
                                    attached_count += 1
                
                # Envoyer
                server.sendmail(sender_email, recipient, msg.as_string())
                sent += 1
                
            except Exception as e:
                errors.append(f"{family['parent_name']}: {str(e)}")
        
        server.quit()
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "sent": sent,
            "total": total,
            "errors": errors,
            "test_mode": send_to_test
        }
        
    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": "Erreur d'authentification Gmail"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def should_send_automatic_reminder():
    """Vérifie si on est le 11 du mois (pour rappel automatique)."""
    return datetime.now().day == 11


def get_reminder_settings_path(config_dir):
    """Retourne le chemin du fichier de paramètres des rappels."""
    return os.path.join(config_dir, "reminder_settings.yaml")
