"""
💳 Create Payment Links - VERSION FARES
Génération des liens de paiement Stripe basée sur solde_final_reel
- PLUS DE on_behalf_of
- Split OK: transfer_data + application_fee_amount (si Connect)
- Moyens de paiement identiques pour TOUS: card + link + twint
- AbsentNotice = NON facturé
- AbsentNoMakeup = Facturé
VERSION CLOUD - Sauvegarde sur Google Drive via storage_manager
"""

import os
import json
import re
import unicodedata
from datetime import datetime

try:
    import stripe
except ImportError:
    stripe = None

# Import du storage manager pour la persistance Cloud
try:
    from scripts.storage_manager import save_json, load_json
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False


def normalize(s):
    """Normalise un nom : minuscules, sans accents, espaces propres"""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    if "," in s:
        p = [x.strip() for x in s.split(",", 1)]
        if len(p) == 2:
            s = f"{p[1]} {p[0]}"
    return s.strip()


def pretty_student_name(student: str) -> str:
    """Formate le nom de l'élève pour l'affichage"""
    if not isinstance(student, str) or not student.strip():
        return "Élève"
    parts = [p.strip() for p in student.split(",")]
    if len(parts) == 2:
        last, first = parts
        return f"{first} {last}"
    return student


def parse_dt(date_str):
    """Parse une date DD.MM.YYYY"""
    try:
        return datetime.strptime(date_str, "%d.%m.%Y")
    except Exception:
        return datetime.min


def select_unpaid_lessons_for_family(fam):
    """
    Sélectionne les cours impayés à facturer basé sur solde_final_reel.
    - Exclut AbsentNotice (absence signalée = non facturé)
    - Inclut AbsentNoMakeup (absence sans rattrapage = facturé)
    """
    solde = float(fam.get("solde_final_reel") or 0)
    lessons = fam.get("lessons", [])
    
    if solde <= 0 or not lessons:
        return []
    
    all_lessons = []
    for L in lessons:
        attendance = L.get("attendance_status", "")
        if attendance == "AbsentNotice":
            # Absence signalée = NON facturé
            continue
        
        amt = float(L.get("amount") or 0)
        if amt <= 0:
            continue
        
        L2 = dict(L)
        L2["amount"] = amt
        L2["dt"] = parse_dt(L.get("date"))
        all_lessons.append(L2)
    
    all_lessons.sort(key=lambda x: x["dt"], reverse=True)
    
    selected = []
    running_total = 0.0
    
    for L in all_lessons:
        amt = L["amount"]
        if running_total + amt <= solde + 1e-6:
            selected.append(L)
            running_total += amt
        if abs(running_total - solde) <= 1e-6:
            break
    
    return selected


def run_create_payment_links(
    data,
    secrets,
    familles_euros,
    tarifs_speciaux,
    use_on_behalf,  # Ignoré pour Fares (toujours False)
    selected_teachers,  # Ignoré pour Fares
    data_dir,
    callback=None,
    payment_method_types=None,
    target_family_ids=None,
    skip_if_exists=True,
):
    """
    Génère les liens de paiement Stripe pour Fares.
    Basé sur solde_final_reel, pas sur le total des cours.
    """
    
    if stripe is None:
        return {"success": False, "error": "Module stripe non installé. pip install stripe"}
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        stripe.api_key = secrets["stripe"]["platform_secret_key"]
        TEACHERS = secrets.get("teachers", {})
        
        # Moyens de paiement unifiés pour Fares
        PAYMENT_METHOD_TYPES = ["card", "link", "twint"]
        
        # ---------------------------
        # Charger les liens existants (local OU Google Drive)
        # ---------------------------
        existing_index = set()
        output_path = os.path.join(data_dir, "payment_links_output.json")
        
        prev = []
        if STORAGE_AVAILABLE and skip_if_exists:
            prev = load_json("payment_links_output.json", "data", default=[])
        elif skip_if_exists and os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    prev = json.load(f) or []
            except Exception:
                prev = []
        
        for it in prev:
            existing_index.add((
                str(it.get("family_id", "")),
                normalize(it.get("teacher", "")),
                float(it.get("amount") or 0),
                str(it.get("invoice_date") or ""),
            ))
        
        def already_exists(fam_id, teacher_name, total_amount, invoice_date):
            key = (str(fam_id), normalize(teacher_name), float(total_amount), str(invoice_date))
            key2 = (str(fam_id), normalize(teacher_name), float(total_amount), "")
            return key in existing_index or key2 in existing_index
        
        TEACHER_MAP = {normalize(tid): tid for tid in TEACHERS.keys()}
        
        output_links = []
        today = datetime.today().strftime("%Y-%m-%d")
        
        # Stats
        absences_ignorees = 0
        absences_facturees = 0
        profs_inconnus = []
        families_skipped_no_solde = 0
        
        # Filtrage fam_id
        all_items = list(data.items())
        if target_family_ids:
            target_set = {str(x) for x in target_family_ids}
            all_items = [(fid, fam) for (fid, fam) in all_items if str(fid) in target_set]
        
        total_families = len(all_items)
        current = 0
        
        for fam_id, fam in all_items:
            current += 1
            progress = int(current / max(total_families, 1) * 80)
            
            parent_name = fam.get("parent_name") or fam.get("family_name") or ""
            parent_email = fam.get("parent_email") or ""
            
            update(progress, f"🔄 {parent_name} ({current}/{total_families})")
            
            # Vérifier le solde - si <= 0, on skip
            solde = float(fam.get("solde_final_reel") or 0)
            if solde <= 0:
                families_skipped_no_solde += 1
                continue
            
            # Stats absences
            for L in fam.get("lessons", []):
                if L.get("attendance_status") == "AbsentNotice":
                    absences_ignorees += 1
                if L.get("attendance_status") == "AbsentNoMakeup":
                    absences_facturees += 1
            
            # Sélectionner les cours impayés
            unpaid_lessons = select_unpaid_lessons_for_family(fam)
            if not unpaid_lessons:
                continue
            
            # Regrouper par professeur
            lessons_by_teacher = {}
            for L in unpaid_lessons:
                tb_name = L.get("teacher") or ""
                lessons_by_teacher.setdefault(tb_name, []).append(L)
            
            # Cas spécial Tiziana (fml_tP1WJW) - jamais de lien pour Fares
            is_tiziana = (fam_id == "fml_tP1WJW")
            
            for teacher_name, t_lessons in lessons_by_teacher.items():
                # Cas spécial Tiziana
                if is_tiziana and teacher_name == "Fares Chouchene":
                    continue
                
                # Trouver la config du prof
                normalized_name = normalize(teacher_name)
                tid = TEACHER_MAP.get(normalized_name, teacher_name)
                teacher_cfg = TEACHERS.get(tid, TEACHERS.get(teacher_name, {}))
                
                if not teacher_cfg and teacher_name not in profs_inconnus:
                    profs_inconnus.append(teacher_name)
                
                total_amount = sum(L["amount"] for L in t_lessons)
                if total_amount <= 0:
                    continue
                
                # Skip si déjà créé
                if skip_if_exists and already_exists(fam_id, teacher_name, total_amount, today):
                    continue
                
                connect_id = (teacher_cfg.get("connect_account_id") or "").strip()
                pay_rate = float(teacher_cfg.get("pay_rate", {}).get("chf", 0))
                
                total_hours = sum((L.get("duration_min") or 0) / 60 for L in t_lessons)
                teacher_amount = round(pay_rate * total_hours, 2)
                
                total_cents = int(round(total_amount * 100))
                teacher_cents = int(round(teacher_amount * 100))
                application_fee = max(total_cents - teacher_cents, 0)
                
                student_name = t_lessons[0].get("student", "Élève")
                product_name = f"Soutien scolaire | {pretty_student_name(student_name)}"
                
                # Création du Price Stripe
                price = stripe.Price.create(
                    unit_amount=total_cents,
                    currency="chf",
                    product_data={
                        "name": product_name,
                        "metadata": {
                            "student_name": student_name,
                            "teacher_name": teacher_name
                        }
                    }
                )
                
                # Construction PaymentLink (SANS on_behalf_of pour Fares)
                params = {
                    "line_items": [{"price": price.id, "quantity": 1}],
                    "customer_creation": "always",
                    "payment_method_types": PAYMENT_METHOD_TYPES,
                    
                    # Split si connect_id présent
                    "transfer_data": {"destination": connect_id} if connect_id else None,
                    "application_fee_amount": application_fee if connect_id else None,
                    
                    "metadata": {
                        "family_id": fam_id,
                        "teacher_name": teacher_name,
                        "student_name": student_name,
                        "parent_name": parent_name,
                        "parent_email": parent_email,
                        "invoice_date": today,
                        "type": "professorplus_payment",
                    },
                    
                    "after_completion": {"type": "hosted_confirmation"},
                }
                
                params = {k: v for k, v in params.items() if v is not None}
                
                link = stripe.PaymentLink.create(**params)
                
                output_links.append({
                    "family_id": fam_id,
                    "parent": parent_name,
                    "student": student_name,
                    "teacher": teacher_name,
                    "currency": "chf",
                    "amount": total_amount,
                    "teacher_pay": teacher_amount,
                    "payment_link": link.url,
                    "invoice_date": today,
                })
        
        update(90, "💾 Sauvegarde...")
        
        os.makedirs(data_dir, exist_ok=True)
        
        # Merge avec l'existant
        merged = list(prev)
        merged.extend(output_links)
        
        # Sauvegarde (Local + Google Drive)
        drive_saved = False
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        
        if STORAGE_AVAILABLE:
            try:
                result = save_json("payment_links_output.json", merged, folder="data")
                if result.get("success") and result.get("drive_id"):
                    drive_saved = True
            except Exception as e:
                print(f"⚠️ Erreur sauvegarde Drive: {e}")
        
        # Rapport
        report = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "ok": len(profs_inconnus) == 0,
            "links_count": len(merged),
            "new_links": len(output_links),
            "absences_ignorees": absences_ignorees,
            "absences_facturees": absences_facturees,
            "families_skipped_no_solde": families_skipped_no_solde,
            "profs_inconnus": profs_inconnus,
        }
        
        report_path = os.path.join(data_dir, "payment_links_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        if STORAGE_AVAILABLE:
            try:
                save_json("payment_links_report.json", report, folder="data")
            except Exception:
                pass
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "links_count": len(merged),
            "new_links": len(output_links),
            "absences": absences_ignorees,
            "absences_facturees": absences_facturees,
            "families_skipped_no_solde": families_skipped_no_solde,
            "profs_inconnus": profs_inconnus,
            "output_path": output_path,
            "report_path": report_path,
            "links": merged[:10],
            "drive_saved": drive_saved,
        }
    
    except stripe.error.AuthenticationError:
        return {"success": False, "error": "Erreur d'authentification Stripe - Vérifiez votre clé API"}
    except Exception as e:
        return {"success": False, "error": str(e)}