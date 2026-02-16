"""
📥 Extract TutorBird - VERSION FARES
Extraction des leçons + transactions + calcul des soldes
VERSION CLOUD - Compatible Streamlit Cloud avec Google Drive
"""

import os
import json
import requests
from datetime import datetime

# Import du storage manager pour compatibilité cloud
try:
    from scripts.storage_manager import save_json
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False


def run_extraction(secrets, start_date, end_date, start_time, end_time, data_dir, callback=None):
    """
    Extrait les leçons ET transactions de TutorBird pour une période donnée.
    Calcule les soldes (solde_initial, solde_final_reel, total_payments).
    
    Args:
        secrets: Configuration YAML chargée
        start_date: Date de début (date)
        end_date: Date de fin (date)
        start_time: Heure de début (time)
        end_time: Heure de fin (time)
        data_dir: Dossier pour sauvegarder le JSON
        callback: Fonction callback(progress, message) pour UI
    
    Returns:
        dict: {"success": bool, "families": int, "lessons": int, "amount": float, "error": str}
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        TB_BASE = "https://api.tutorbird.com/v1"
        TB_API_KEY = secrets["tutorbird"]["api_key"]
        HEADERS = {"Authorization": f"Bearer {TB_API_KEY}", "Content-Type": "application/json"}
        
        # Combiner date + heure
        start_dt = datetime.combine(start_date, start_time)
        end_dt = datetime.combine(end_date, end_time)
        
        # ===============================
        # EXTRACTION DES ÉTUDIANTS
        # ===============================
        update(5, "📚 Récupération des étudiants...")
        
        r = requests.get(f"{TB_BASE}/students", headers=HEADERS, timeout=30)
        if not r.ok:
            return {"success": False, "error": f"Erreur API students: {r.status_code}"}
        
        students_raw = r.json().get("ItemSubset") or r.json().get("Items") or r.json()
        students = {}
        for s in students_raw:
            students[s["ID"]] = {
                "name": s.get("Name"),
                "family": s.get("FamilyID"),
                "family_name": s.get("FamilyName"),
            }
        
        # ===============================
        # EXTRACTION DES PARENTS
        # ===============================
        update(15, "👨‍👩‍👧 Récupération des parents...")
        
        r = requests.get(f"{TB_BASE}/parents", headers=HEADERS, timeout=30)
        if not r.ok:
            return {"success": False, "error": f"Erreur API parents: {r.status_code}"}
        
        parents_raw = r.json().get("ItemSubset") or r.json().get("Items") or r.json()
        parents = {}
        for p in parents_raw:
            parents.setdefault(p["FamilyID"], []).append(p)
        
        # Fonction pour choisir le bon parent
        def choose_parent(fam_id):
            plist = parents.get(fam_id, [])
            if not plist:
                return None, None
            
            def email_of(p):
                e = p.get("Email") or {}
                return e.get("EmailAddress")
            
            # Parent préféré avec email
            for p in plist:
                if p.get("IsPreferredInvoiceRecipient") and email_of(p):
                    return f"{p['LastName']} {p['FirstName']}", email_of(p)
            
            # Sinon n'importe quel parent avec email
            for p in plist:
                if email_of(p):
                    return f"{p['LastName']} {p['FirstName']}", email_of(p)
            
            # Sinon premier parent
            p = plist[0]
            return f"{p['LastName']} {p['FirstName']}", email_of(p)
        
        # ===============================
        # EXTRACTION DES LEÇONS
        # ===============================
        update(30, "📖 Récupération des leçons...")
        
        r = requests.get(
            f"{TB_BASE}/attendance",
            headers=HEADERS,
            params={
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d")
            },
            timeout=30
        )
        if not r.ok:
            return {"success": False, "error": f"Erreur API attendance: {r.status_code}"}
        
        lessons_raw = r.json().get("ItemSubset") or r.json().get("Items") or r.json()
        
        # ===============================
        # EXTRACTION DES TRANSACTIONS
        # ===============================
        update(45, "💰 Récupération des transactions...")
        
        r = requests.get(
            f"{TB_BASE}/transactions",
            headers=HEADERS,
            params={
                "offset": 0,
                "limit": 2000,
                "orderby": "Date",
                "fields": "Date,FamilyID,Payment,Charge,AccountBalance,DisplayDescription,Method"
            },
            timeout=30
        )
        if not r.ok:
            return {"success": False, "error": f"Erreur API transactions: {r.status_code}"}
        
        all_transactions = r.json().get("ItemSubset") or r.json().get("Items") or r.json()
        
        # ===============================
        # TRAITEMENT DES DONNÉES
        # ===============================
        update(60, "🔄 Traitement des leçons...")
        
        families = {}
        families_with_lessons = set()
        
        # ---- PART 1 : Leçons ----
        for L in lessons_raw:
            dt_str = L.get("EventStartDate")
            if not dt_str:
                continue
            
            dt = datetime.fromisoformat(dt_str)
            
            # Filtrer par période exacte (avec heures)
            if not (start_dt <= dt <= end_dt):
                continue
            
            sid = (L.get("Student") or {}).get("ID")
            s_info = students.get(sid, {})
            fam_id = s_info.get("family")
            
            if not fam_id:
                continue
            
            families_with_lessons.add(fam_id)
            
            # Créer la famille si elle n'existe pas
            if fam_id not in families:
                pname, pemail = choose_parent(fam_id)
                families[fam_id] = {
                    "family_id": fam_id,
                    "family_name": s_info.get("family_name"),
                    "parent_name": pname,
                    "parent_email": pemail,
                    "lessons": [],
                    "transactions_before": [],
                    "transactions_period": [],
                    "total_courses": 0.0,
                    "total_payments": 0.0,
                    "solde_initial": 0.0,
                    "solde_final_reel": 0.0,
                }
            
            amount = float(L.get("OriginalChargeAmount") or 0)
            
            # Ajouter la leçon avec TOUS les champs importants
            families[fam_id]["lessons"].append({
                "date": dt.strftime("%d.%m.%Y"),
                "time": dt.strftime("%H:%M"),
                "student": (L.get("Student") or {}).get("Name"),
                "teacher": (L.get("Teacher") or {}).get("Name"),
                "duration_min": L.get("EventDuration"),
                "amount": amount,
                "attendance_status": L.get("AttendanceStatus"),
            })
            
            families[fam_id]["total_courses"] += amount
        
        # ---- PART 2 : Transactions ----
        update(75, "💳 Traitement des transactions...")
        
        for T in all_transactions:
            fam_id = T.get("FamilyID")
            if fam_id not in families_with_lessons:
                continue
            
            # S'assurer que la famille existe
            if fam_id not in families:
                continue
            
            dt = datetime.fromisoformat(T["Date"])
            pay = float(T.get("Payment") or 0)
            bal = float(T.get("AccountBalance") or 0)
            
            if dt < start_dt:
                families[fam_id]["transactions_before"].append(bal)
            
            elif start_dt <= dt <= end_dt:
                families[fam_id]["transactions_period"].append({
                    "date": T["Date"],
                    "payment": pay,
                    "charge": float(T.get("Charge") or 0),
                    "balance": bal,
                    "description": T.get("DisplayDescription"),
                    "method": T.get("Method"),
                })
                
                families[fam_id]["total_payments"] += pay
        
        # ---- PART 3 : Calcul final réel ----
        update(85, "🧮 Calcul des soldes...")
        
        for fam_id, fam in families.items():
            # solde_initial = dernier AccountBalance avant période
            if fam["transactions_before"]:
                fam["solde_initial"] = fam["transactions_before"][-1]
            else:
                fam["solde_initial"] = 0.0
            
            # solde_final_reel = solde_initial + cours - paiements
            fam["solde_final_reel"] = (
                fam["total_courses"] - fam["total_payments"] - fam["solde_initial"]
            )
        
        # ===============================
        # SAUVEGARDE (locale + Google Drive si cloud)
        # ===============================
        update(92, "💾 Sauvegarde...")
        
        # Sauvegarde locale (toujours)
        os.makedirs(data_dir, exist_ok=True)
        output_path = os.path.join(data_dir, "full_output_tb_SIMPLE.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(families, f, indent=2, ensure_ascii=False)
        
        # Sauvegarde Google Drive (si disponible et sur le cloud)
        drive_saved = False
        if STORAGE_AVAILABLE:
            try:
                result = save_json("full_output_tb_SIMPLE.json", families, folder="data")
                if result.get("success") and result.get("drive_id"):
                    drive_saved = True
            except Exception as e:
                print(f"⚠️ Erreur sauvegarde Drive: {e}")
        
        update(100, "✅ Terminé !")
        
        # Stats
        total_lessons = sum(len(f["lessons"]) for f in families.values())
        total_amount = sum(f["total_courses"] for f in families.values())
        total_solde = sum(f["solde_final_reel"] for f in families.values() if f["solde_final_reel"] > 0)
        
        return {
            "success": True,
            "families": len(families),
            "lessons": total_lessons,
            "amount": total_amount,
            "solde_total": total_solde,
            "output_path": output_path,
            "drive_saved": drive_saved
        }
        
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Timeout - L'API TutorBird ne répond pas"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Erreur de connexion - Vérifiez votre connexion internet"}
    except Exception as e:
        return {"success": False, "error": str(e)}