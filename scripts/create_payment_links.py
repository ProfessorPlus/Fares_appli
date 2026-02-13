"""
💳 Create Payment Links
Génération des liens de paiement Stripe
+ Audit de complétude (familles/profs manquants)
VERSION CLOUD - Compatible Streamlit Cloud avec Google Drive
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

# Import du storage manager pour compatibilité cloud
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


def build_product_name(lessons):
    """Construit le nom du produit Stripe"""
    students = list({L["student"] for L in lessons if L.get("student")})
    students.sort()
    students = students[:2]

    if not students:
        return "Soutien scolaire"

    first = students[0]
    if "," in first:
        last_name, first_name = [s.strip() for s in first.split(",", 1)]
    else:
        parts = first.split()
        last_name = parts[-1]
        first_name = " ".join(parts[:-1]) if len(parts) > 1 else ""

    base = f"{last_name} {first_name}".strip()

    if len(students) == 2:
        second = students[1]
        if "," in second:
            _, second_first = [s.strip() for s in second.split(",", 1)]
        else:
            parts2 = second.split()
            second_first = parts2[0] if parts2 else second
        base = f"{base} & {second_first}"

    return f"Soutien scolaire | {base}"


def run_create_payment_links(
    data,
    secrets,
    familles_euros,
    tarifs_speciaux,
    use_on_behalf,
    selected_teachers,
    data_dir,
    callback=None,
    payment_method_types=None,
    target_family_ids=None,
    skip_if_exists=True,
):
    """
    Génère les liens de paiement Stripe.
    - target_family_ids: liste de fam_id à traiter (sinon toutes)
    - skip_if_exists: évite de recréer un lien déjà généré (output json)
    """

    if stripe is None:
        return {"success": False, "error": "Module stripe non installé. pip install stripe"}

    def update(progress, message):
        if callback:
            callback(progress, message)

    try:
        stripe.api_key = secrets["stripe"]["platform_secret_key"]
        TEACHERS = secrets.get("teachers", {})

        # ---------------------------
        # Charger les liens existants (local ou Drive)
        # ---------------------------
        existing_index = set()
        output_path = os.path.join(data_dir, "payment_links_output.json")
        
        # Essayer de charger depuis storage_manager (supporte Drive)
        prev = None
        if STORAGE_AVAILABLE and skip_if_exists:
            prev = load_json("payment_links_output.json", "data", default=None)
        
        # Fallback: fichier local
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
                    normalize(it.get("teacher", "")),
                    (it.get("currency") or "").lower(),
                    float(it.get("amount") or 0),
                    str(it.get("invoice_date") or ""),
                ))

        def already_exists(fam_id, teacher_name, currency, total_amount, invoice_date):
            key = (str(fam_id), normalize(teacher_name), currency.lower(), float(total_amount), str(invoice_date))
            key2 = (str(fam_id), normalize(teacher_name), currency.lower(), float(total_amount), "")
            return key in existing_index or key2 in existing_index

        FAMILLES_EUROS = {name.lower(): True for name in familles_euros}

        def is_eur_family(name):
            if not isinstance(name, str):
                return False
            return name.lower().strip() in FAMILLES_EUROS

        TEACHER_MAP = {normalize(tid): tid for tid in TEACHERS.keys()}
        if "Ricardo Hounsinou" in TEACHERS:
            TEACHER_MAP[normalize("Ricardo H")] = "Ricardo Hounsinou"

        def get_special_pay_rate(teacher_name, parent_name, students):
            teacher_norm = normalize(teacher_name)
            parent_norm = normalize(parent_name)
            students_norm = [normalize(s) for s in students]

            for tarif in tarifs_speciaux:
                tarif_teacher = normalize(tarif.get("teacher", ""))
                tarif_parent = normalize(tarif.get("parent", ""))
                tarif_student = normalize(tarif.get("student", ""))

                if tarif_teacher and tarif_teacher != teacher_norm:
                    continue

                matched = False
                if tarif_parent and tarif_parent == parent_norm:
                    matched = True
                if tarif_student and tarif_student in students_norm:
                    matched = True

                if matched:
                    return tarif.get("pay_rate")
            return None

        output_links = []
        today = datetime.today().strftime("%Y-%m-%d")

        absences_ignorees = 0
        absences_facturees = 0
        tarifs_speciaux_appliques = 0
        profs_inconnus = []

        expected_families = {}
        created_families = set()

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

            currency = "eur" if is_eur_family(parent_name) else "chf"
            lessons = fam.get("lessons", [])
            if not lessons:
                continue

            billable_amount = 0.0
            for L in lessons:
                if L.get("attendance_status") == "AbsentNotice":
                    continue
                billable_amount += float(L.get("amount") or 0)

            if billable_amount > 0:
                expected_families[fam_id] = {
                    "parent_name": parent_name,
                    "billable_amount": round(billable_amount, 2),
                    "currency": currency.upper(),
                }

            lessons_by_teacher = {}
            for L in lessons:
                status = L.get("attendance_status")

                if status == "AbsentNotice":
                    absences_ignorees += 1
                    continue
                if status == "AbsentNoMakeup":
                    absences_facturees += 1

                tb_name = L.get("teacher") or ""
                normalized_name = normalize(tb_name)
                tid = TEACHER_MAP.get(normalized_name)

                if not tid:
                    if tb_name and tb_name not in profs_inconnus:
                        profs_inconnus.append(tb_name)
                    continue

                lessons_by_teacher.setdefault(tid, []).append(L)

            for tid, t_lessons in lessons_by_teacher.items():
                teacher_cfg = TEACHERS.get(tid, {})
                teacher_name = tid
                connect_id = teacher_cfg.get("connect_account_id") or ""

                total_amount = sum(float(L.get("amount") or 0) for L in t_lessons)
                if total_amount <= 0:
                    continue

                # Skip si déjà créé
                if skip_if_exists and already_exists(fam_id, teacher_name, currency, total_amount, today):
                    created_families.add(fam_id)
                    continue

                students = list({L.get("student", "") for L in t_lessons if L.get("student")})
                special_rate = get_special_pay_rate(teacher_name, parent_name, students)
                if special_rate is not None:
                    pay_rate = float(special_rate)
                    tarifs_speciaux_appliques += 1
                else:
                    pay_rate = float(teacher_cfg.get("pay_rate", {}).get(currency, 0))

                total_hours = sum((L.get("duration_min") or 0) / 60 for L in t_lessons)
                teacher_amount = round(pay_rate * total_hours, 2)

                total_cents = int(round(total_amount * 100))
                teacher_cents = int(round(teacher_amount * 100))
                platform_fee = max(total_cents - teacher_cents, 0)

                product_name = build_product_name(t_lessons)

                price = stripe.Price.create(
                    unit_amount=total_cents,
                    currency=currency,
                    product_data={"name": product_name},
                )

                customer_id = None
                if parent_email:
                    res = stripe.Customer.list(email=parent_email, limit=1)
                    if res.data:
                        customer_id = res.data[0].id

                is_ilyess = teacher_name.lower().strip() == "ilyess guerrouj"
                use_ob_for_this_teacher = (
                    use_on_behalf and connect_id and not is_ilyess and
                    teacher_name in (selected_teachers or [])
                )
                use_split_for_this_teacher = bool(connect_id)

                params = {
                    "line_items": [{"price": price.id, "quantity": 1}],
                    "customer_creation": "if_required" if customer_id else "always",
                    "on_behalf_of": connect_id if use_ob_for_this_teacher else None,
                    "transfer_data": {"destination": connect_id} if use_split_for_this_teacher else None,
                    "application_fee_amount": platform_fee if use_split_for_this_teacher else None,
                    "restrictions": {"completed_sessions": {"limit": 1}},
                    "metadata": {
                        "currency": currency,
                        "family_id": fam_id,
                        "parent_name": parent_name,
                        "parent_email": parent_email,
                        "teacher_name": teacher_name,
                        "product_name": product_name,
                        "invoice_date": today,
                    },
                    "payment_intent_data": {
                        "metadata": {
                            "teacher_account": connect_id or "platform",
                            "gross_amount": f"{total_amount:.2f} {currency.upper()}",
                            "platform_fee": f"{platform_fee/100:.2f} {currency.upper()}",
                            "teacher_share": f"{teacher_cents/100:.2f} {currency.upper()}",
                            "invoice_date": today,
                            "product_name": product_name,
                        }
                    },
                    "after_completion": {"type": "hosted_confirmation"},
                }

                ALLOWED_PM = {"card", "link", "klarna", "twint"}
                pm_types = list(payment_method_types) if payment_method_types else None
                if currency != "chf" and pm_types:
                    pm_types = [pm for pm in pm_types if pm != "twint"]
                if pm_types:
                    filtered = [pm for pm in pm_types if pm in ALLOWED_PM]
                    params["payment_method_types"] = filtered if filtered else ["card"]

                params = {k: v for k, v in params.items() if v is not None}

                link = stripe.PaymentLink.create(**params)

                created_families.add(fam_id)

                output_links.append({
                    "family_id": fam_id,
                    "parent": parent_name,
                    "teacher": teacher_name,
                    "currency": currency,
                    "students_label": product_name,
                    "amount": total_amount,
                    "teacher_pay": teacher_amount,
                    "payment_link": link.url,
                    "invoice_date": today,
                })

        missing_families = []
        for fam_id, info in expected_families.items():
            if fam_id not in created_families:
                missing_families.append({
                    "family_id": fam_id,
                    "parent_name": info["parent_name"],
                    "billable_amount": info["billable_amount"],
                    "currency": info["currency"],
                })

        update(90, "💾 Sauvegarde...")

        os.makedirs(data_dir, exist_ok=True)

        # Merge avec l'existant
        merged = prev if prev else []
        merged.extend(output_links)

        # Sauvegarde locale
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

        # Sauvegarde Google Drive (si disponible)
        drive_saved = False
        if STORAGE_AVAILABLE:
            try:
                result = save_json("payment_links_output.json", merged, folder="data")
                if result.get("success") and result.get("drive_id"):
                    drive_saved = True
            except Exception as e:
                print(f"⚠️ Erreur sauvegarde Drive: {e}")

        nb_expected = len(expected_families)
        nb_created = len(created_families)

        report = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "ok": (len(missing_families) == 0 and len(profs_inconnus) == 0),
            "links_count": len(merged),
            "expected_families_count": nb_expected,
            "created_families_count": nb_created,
            "absences_ignorees": absences_ignorees,
            "absences_facturees": absences_facturees,
            "tarifs_speciaux_appliques": tarifs_speciaux_appliques,
            "profs_inconnus": profs_inconnus,
            "missing_families": missing_families,
        }
        
        # Sauvegarde rapport local
        report_path = os.path.join(data_dir, "payment_links_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Sauvegarde rapport sur Drive
        if STORAGE_AVAILABLE:
            try:
                save_json("payment_links_report.json", report, folder="data")
            except Exception:
                pass

        update(100, "✅ Terminé !")

        return {
            "success": True,
            "links_count": len(merged),
            "expected_families": nb_expected,
            "created_families": nb_created,
            "absences": absences_ignorees,
            "absences_facturees": absences_facturees,
            "tarifs_speciaux": tarifs_speciaux_appliques,
            "profs_inconnus": profs_inconnus,
            "missing_families": missing_families,
            "output_path": output_path,
            "report_path": report_path,
            "links": merged[:10],
            "drive_saved": drive_saved,
        }

    except stripe.error.AuthenticationError:
        return {"success": False, "error": "Erreur d'authentification Stripe - Vérifiez votre clé API"}
    except Exception as e:
        return {"success": False, "error": str(e)}