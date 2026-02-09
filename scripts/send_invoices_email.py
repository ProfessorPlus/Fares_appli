"""
📧 Send Invoices Email
Envoie les factures par email aux familles
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime


MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


def get_default_email_template(month_name=None, year=None):
    """Retourne le template d'email par défaut."""
    
    if not month_name:
        now = datetime.now()
        month_name = MONTHS_FR[now.month - 1]
        year = now.year
    
    return {
        "subject": f"Facture(s) - Soutien scolaire - {month_name} {year}",
        "body": f"""Bonjour,

J'espère que vous allez bien.

Veuillez trouver ci-joint votre/vos facture(s) pour les cours de soutien scolaire du mois de {month_name} {year}.

Vous pouvez régler directement en cliquant sur le bouton "Payer en ligne" dans la facture PDF.

Merci de procéder au paiement dans les plus brefs délais, avant le 10 {month_name} {year}.

Cordialement,
Professor+
"""
    }


def get_families_from_folder(invoice_folder, data):
    """
    Récupère la liste des familles avec leurs factures.
    
    Returns:
        list: [{"parent_name": str, "parent_email": str, "invoices": [paths], "total": float}]
    """
    families = []
    
    if not os.path.exists(invoice_folder):
        return families
    
    # Lister tous les fichiers PDF
    pdf_files = [f for f in os.listdir(invoice_folder) if f.endswith(".pdf")]
    
    # Grouper par famille (en utilisant data pour récupérer les emails)
    family_invoices = {}
    
    for pdf in pdf_files:
        # Extraire le nom de famille du fichier
        # Format attendu: "Facture_NomFamille_Prof_Date.pdf" ou similaire
        parts = pdf.replace(".pdf", "").split("_")
        if len(parts) >= 2:
            family_name = parts[1]  # Supposons que le nom est en 2ème position
        else:
            family_name = pdf.replace(".pdf", "")
        
        if family_name not in family_invoices:
            family_invoices[family_name] = []
        family_invoices[family_name].append(os.path.join(invoice_folder, pdf))
    
    # Matcher avec les données pour récupérer les emails
    for fam_id, fam in data.items():
        parent_name = fam.get("parent_name") or fam.get("family_name") or ""
        parent_email = fam.get("parent_email") or ""
        total_amount = fam.get("total_courses", 0)
        
        # Chercher les factures correspondantes
        invoices = []
        for pdf in pdf_files:
            # Normaliser pour comparaison
            pdf_lower = pdf.lower()
            name_parts = parent_name.lower().replace(",", " ").split()
            
            # Vérifier si le nom apparaît dans le fichier
            if any(part in pdf_lower for part in name_parts if len(part) > 2):
                invoices.append(os.path.join(invoice_folder, pdf))
        
        if invoices and parent_email:
            families.append({
                "family_id": fam_id,
                "parent_name": parent_name,
                "parent_email": parent_email,
                "invoices": invoices,
                "total": total_amount,
                "invoice_count": len(invoices)
            })
    
    return families


def run_send_invoices(secrets, data, invoice_folder, 
                      custom_subject=None, custom_body=None,
                      selected_families=None, send_to_test=False,
                      callback=None):
    """
    Envoie les factures par email.
    
    Args:
        secrets: Configuration YAML
        data: Données des familles
        invoice_folder: Dossier contenant les factures
        custom_subject: Sujet personnalisé (optionnel)
        custom_body: Corps personnalisé (optionnel)
        selected_families: Liste des family_id à envoyer (None = tous)
        send_to_test: Si True, envoie uniquement à l'email de test
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "sent": int, "total": int, "errors": list}
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
            return {"success": False, "error": "Configuration email manquante dans secrets.yaml (gmail.email et gmail.app_password)"}
        
        # Template par défaut
        template = get_default_email_template()
        subject = custom_subject or template["subject"]
        body = custom_body or template["body"]
        
        update(10, "📧 Préparation des emails...")
        
        # Récupérer les familles avec factures
        families = get_families_from_folder(invoice_folder, data)
        
        if not families:
            return {"success": False, "error": "Aucune facture trouvée ou aucune famille avec email"}
        
        # Filtrer si sélection
        if selected_families:
            families = [f for f in families if f["family_id"] in selected_families]
        
        update(20, f"📊 {len(families)} famille(s) à contacter")
        
        # Connexion SMTP
        update(30, "🔌 Connexion au serveur email...")
        
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        
        sent = 0
        errors = []
        total = len(families)
        
        for i, family in enumerate(families):
            progress = int(30 + (i / total * 65))
            
            recipient = sender_email if send_to_test else family["parent_email"]
            
            update(progress, f"📧 Envoi à {family['parent_name']}...")
            
            try:
                # Créer le message
                msg = MIMEMultipart()
                msg["From"] = sender_email
                msg["To"] = recipient
                
                # Adapter le sujet (singulier/pluriel)
                final_subject = subject
                if family["invoice_count"] > 1:
                    final_subject = final_subject.replace("Facture -", "Factures -")
                else:
                    final_subject = final_subject.replace("Facture(s)", "Facture")
                
                msg["Subject"] = final_subject
                
                # Adapter le corps (singulier/pluriel)
                final_body = body
                if family["invoice_count"] > 1:
                    final_body = final_body.replace("votre/vos facture(s)", "vos factures")
                    final_body = final_body.replace("ci-joint votre facture", "ci-joint vos factures")
                else:
                    final_body = final_body.replace("votre/vos facture(s)", "votre facture")
                
                msg.attach(MIMEText(final_body, "plain"))
                
                # Attacher les factures
                for invoice_path in family["invoices"]:
                    if os.path.exists(invoice_path):
                        with open(invoice_path, "rb") as f:
                            part = MIMEBase("application", "pdf")
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            filename = os.path.basename(invoice_path)
                            part.add_header("Content-Disposition", f"attachment; filename={filename}")
                            msg.attach(part)
                
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
        return {"success": False, "error": "Erreur d'authentification Gmail. Vérifiez l'email et le mot de passe d'application."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_send_test_email(secrets, invoice_folder, data, family_ids=None, callback=None):
    """
    Envoie les factures sélectionnées à l'email de test uniquement.
    """
    return run_send_invoices(
        secrets, data, invoice_folder,
        selected_families=family_ids,
        send_to_test=True,
        callback=callback
    )
