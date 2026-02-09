"""
📥 Extract TutorBird
Extraction des leçons depuis l'API TutorBird
"""

import os
import json
import requests
from datetime import datetime


def run_extraction(secrets, start_date, end_date, start_time, end_time, data_dir, callback=None):
    """
    Extrait les leçons de TutorBird pour une période donnée.
    
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
        update(10, "📚 Récupération des étudiants...")
        
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
        update(30, "👨‍👩‍👧 Récupération des parents...")
        
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
        update(50, "📖 Récupération des leçons...")
        
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
        # TRAITEMENT DES DONNÉES
        # ===============================
        update(70, "🔄 Traitement des données...")
        
        families = {}
        
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
            
            # Créer la famille si elle n'existe pas
            if fam_id not in families:
                pname, pemail = choose_parent(fam_id)
                families[fam_id] = {
                    "family_id": fam_id,
                    "family_name": s_info.get("family_name"),
                    "parent_name": pname,
                    "parent_email": pemail,
                    "lessons": [],
                    "total_courses": 0.0,
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
        
        # ===============================
        # SAUVEGARDE
        # ===============================
        update(90, "💾 Sauvegarde...")
        
        output_path = os.path.join(data_dir, "full_output_tb_SIMPLE.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(families, f, indent=2, ensure_ascii=False)
        
        update(100, "✅ Terminé !")
        
        # Stats
        total_lessons = sum(len(f["lessons"]) for f in families.values())
        total_amount = sum(f["total_courses"] for f in families.values())
        
        return {
            "success": True,
            "families": len(families),
            "lessons": total_lessons,
            "amount": total_amount,
            "output_path": output_path
        }
        
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Timeout - L'API TutorBird ne répond pas"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Erreur de connexion - Vérifiez votre connexion internet"}
    except Exception as e:
        return {"success": False, "error": str(e)}
