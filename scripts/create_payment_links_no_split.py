"""
💳 Create Payment Links - NO SPLIT - VERSION FARES
Tout va sur le compte Stripe principal de Fares (pas de split).
Basé sur solde_final_reel comme la version normale de Fares.
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

try:
    from scripts.storage_manager import save_json, load_json
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False


def normalize(s):
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
    if not isinstance(student, str) or not student.strip():
        return "Élève"
    parts = [p.strip() for p in student.split(",")]
    if len(parts) == 2:
        last, first = parts
        return f"{first} {last}"
    return student


def parse_dt(date_str):
    try:
        return datetime.strptime(date_str, "%d.%m.%Y")
    except Exception:
        return datetime.min


def select_unpaid_lessons_for_family(fam):
    """Sélectionne les cours impayés basé sur solde_final_reel."""
    solde = float(fam.get("solde_final_reel") or 0)
    lessons = fam.get("lessons", [])

    if solde <= 0 or not lessons:
        return []

    all_lessons = []
    for L in lessons:
        if L.get("attendance_status") == "AbsentNotice":
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


def run_create_payment_links_no_split(
    data,
    secrets_no_prof,
    familles_euros,
    data_dir,
    callback=None,
    payment_method_types=None,
    target_family_ids=None,
    skip_if_exists=True,
):
    """
    Génère les liens Stripe SANS split pour Fares.
    Basé sur solde_final_reel. Un seul lien par famille.
    """

    if stripe is None:
        return {"success": False, "error": "Module stripe non installé"}

    def update(progress, message):
        if callback:
            callback(progress, message)

    try:
        stripe.api_key = secrets_no_prof["stripe"]["platform_secret_key"]

        # Charger liens existants
        existing_index = set()
        output_path = os.path.join(data_dir, "payment_links_output.json")

        prev = None
        if STORAGE_AVAILABLE and skip_if_exists:
            prev = load_json("payment_links_output.json", "data", default=None)
        if prev is None and skip_if_exists and os.path.exists(output_path):
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    prev = json.load(f)
            except Exception:
                prev = []

        if prev:
            for it in prev:
                existing_index.add((
                    str(it.get("family_id", "")),
                    float(it.get("amount") or 0),
                    str(it.get("invoice_date") or ""),
                ))

        PAYMENT_METHOD_TYPES = payment_method_types or ["card", "link", "twint"]

        output_links = []
        today = datetime.today().strftime("%Y-%m-%d")
        absences_ignorees = 0
        families_skipped = 0

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

            solde = float(fam.get("solde_final_reel") or 0)
            if solde <= 0:
                families_skipped += 1
                continue

            # Compter absences
            for L in fam.get("lessons", []):
                if L.get("attendance_status") == "AbsentNotice":
                    absences_ignorees += 1

            # Sélectionner les cours impayés
            unpaid_lessons = select_unpaid_lessons_for_family(fam)
            if not unpaid_lessons:
                continue

            total_amount = sum(L["amount"] for L in unpaid_lessons)
            if total_amount <= 0:
                continue

            # Skip si déjà créé
            key = (str(fam_id), float(total_amount), str(today))
            key2 = (str(fam_id), float(total_amount), "")
            if skip_if_exists and (key in existing_index or key2 in existing_index):
                continue

            total_cents = int(round(total_amount * 100))

            # Nom du produit
            student_name = unpaid_lessons[0].get("student", "Élève")
            product_name = f"Soutien scolaire | {pretty_student_name(student_name)}"

            price = stripe.Price.create(
                unit_amount=total_cents,
                currency="chf",
                product_data={"name": product_name},
            )

            params = {
                "line_items": [{"price": price.id, "quantity": 1}],
                "customer_creation": "always",
                "payment_method_types": PAYMENT_METHOD_TYPES,
                "restrictions": {"completed_sessions": {"limit": 1}},
                "metadata": {
                    "family_id": fam_id,
                    "parent_name": parent_name,
                    "parent_email": parent_email,
                    "product_name": product_name,
                    "invoice_date": today,
                    "mode": "no_split",
                },
                "payment_intent_data": {
                    "metadata": {
                        "gross_amount": f"{total_amount:.2f} CHF",
                        "invoice_date": today,
                        "product_name": product_name,
                        "mode": "no_split",
                    }
                },
                "after_completion": {"type": "hosted_confirmation"},
            }

            link = stripe.PaymentLink.create(**params)

            output_links.append({
                "family_id": fam_id,
                "parent": parent_name,
                "teacher": "— (tout sur compte principal)",
                "currency": "chf",
                "students_label": product_name,
                "amount": total_amount,
                "teacher_pay": 0,
                "payment_link": link.url,
                "invoice_date": today,
                "mode": "no_split",
            })

        update(90, "💾 Sauvegarde...")

        os.makedirs(data_dir, exist_ok=True)
        merged = prev if prev else []
        merged.extend(output_links)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

        if STORAGE_AVAILABLE:
            try:
                save_json("payment_links_output.json", merged, folder="data")
            except Exception:
                pass

        update(100, "✅ Terminé !")

        return {
            "success": True,
            "links_count": len(output_links),
            "total_merged": len(merged),
            "absences_ignorees": absences_ignorees,
            "families_skipped_no_solde": families_skipped,
            "output_path": output_path,
            "links": output_links[:10],
        }

    except stripe.error.AuthenticationError:
        return {"success": False, "error": "Erreur d'authentification Stripe - Vérifiez la clé dans Fares_secrets_no_prof.yaml"}
    except Exception as e:
        return {"success": False, "error": str(e)}