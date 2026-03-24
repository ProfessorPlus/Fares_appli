"""
👨‍🏫 Recap Profs - VERSION FARES
Calcul des montants à payer aux professeurs en CHF
Tout est en CHF — pas de conversion EUR nécessaire.

⚡ Prend en compte les paiements déjà effectués (solde_final_reel)
   pour ne comptabiliser que les cours réellement impayés.
"""

import unicodedata
from collections import defaultdict
from datetime import datetime


PAYABLE_STATUSES = {"Present", "Unrecorded", "AbsentNoMakeup"}


def norm(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _parse_dt(date_str):
    """Parse une date DD.MM.YYYY"""
    try:
        return datetime.strptime(date_str, "%d.%m.%Y")
    except Exception:
        return datetime.min


def _select_unpaid_lessons(fam):
    """
    Sélectionne les cours impayés d'une famille basé sur solde_final_reel.
    Même logique que create_payment_links.select_unpaid_lessons_for_family.
    
    - Si solde_final_reel <= 0 → famille à jour → aucun cours impayé
    - Sinon, prend les cours les plus récents jusqu'à couvrir le solde
    - Exclut AbsentNotice (absence signalée = non facturé)
    - Inclut AbsentNoMakeup (absence sans rattrapage = facturé)
    
    Returns:
        list: cours impayés sélectionnés
    """
    solde = float(fam.get("solde_final_reel") or 0)
    lessons = fam.get("lessons", [])

    if solde <= 0 or not lessons:
        return []

    all_lessons = []
    for L in lessons:
        attendance = L.get("attendance_status", "")
        if attendance == "AbsentNotice":
            continue

        amt = float(L.get("amount") or 0)
        if amt <= 0:
            continue

        L2 = dict(L)
        L2["amount"] = amt
        L2["dt"] = _parse_dt(L.get("date"))
        all_lessons.append(L2)

    # Cours les plus récents en premier
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


def compute_teacher_recap(data, secrets, familles_euros=None, tarifs_speciaux=None, **kwargs):
    """
    Calcule le récap des montants à payer à chaque prof en CHF.
    
    ⚡ Ne comptabilise que les cours IMPAYÉS (basé sur solde_final_reel).
       Les cours déjà réglés par les familles sont exclus du calcul.
    
    Args:
        data: dict des familles (full_output_tb_SIMPLE.json)
        secrets: config YAML
        familles_euros: ignoré (tout est CHF pour Fares)
        tarifs_speciaux: liste des tarifs spéciaux
        **kwargs: accepte extraction_end_date etc. (ignoré car pas de FX)
    
    Returns:
        dict: {
            "teachers": {teacher_name: {chf, nb_lessons, total_hours, details}},
            "grand_total": float,
            "total_lessons": int,
            "families_fully_paid": int,
            "families_with_balance": int,
        }
    """
    teachers_cfg = secrets.get("teachers", {})
    tarifs_speciaux = tarifs_speciaux or []

    # Build lookup
    teacher_lookup = {}
    for cfg_name in teachers_cfg:
        teacher_lookup[norm(cfg_name)] = cfg_name

    # Tarifs spéciaux lookup
    special_rates = {}
    for ts in tarifs_speciaux:
        t = norm(ts.get("teacher", ""))
        if ts.get("parent"):
            special_rates[(t, "parent", norm(ts["parent"]))] = ts["pay_rate"]
        if ts.get("student"):
            special_rates[(t, "student", norm(ts["student"]))] = ts["pay_rate"]

    def get_special_rate(teacher_name, parent_name, student_name):
        tn = norm(teacher_name)
        r = special_rates.get((tn, "parent", norm(parent_name)))
        if r is not None:
            return r
        if student_name:
            r = special_rates.get((tn, "student", norm(student_name)))
            if r is not None:
                return r
        return None

    # Compute
    teacher_totals = defaultdict(lambda: {
        "chf": 0.0, "eur": 0.0, "chf_as_eur": 0.0,
        "nb_lessons": 0, "total_hours": 0.0, "details": []
    })

    families_fully_paid = 0
    families_with_balance = 0

    for fam_id, fam in data.items():
        parent = fam.get("parent_name") or ""

        # ⚡ Sélectionner uniquement les cours impayés
        unpaid_lessons = _select_unpaid_lessons(fam)

        if not unpaid_lessons:
            # Famille à jour ou pas de cours facturables
            solde = float(fam.get("solde_final_reel") or 0)
            if solde <= 0 and fam.get("lessons"):
                families_fully_paid += 1
            continue

        families_with_balance += 1

        # Créer un set des cours impayés pour matching rapide
        # On identifie chaque cours par (date, student, teacher, duration)
        unpaid_keys = set()
        for L in unpaid_lessons:
            key = (
                L.get("date", ""),
                L.get("student", ""),
                L.get("teacher", ""),
                L.get("duration_min") or 0,
            )
            unpaid_keys.add(key)

        for lesson in fam.get("lessons", []):
            status = lesson.get("attendance_status", "")
            if status not in PAYABLE_STATUSES:
                continue

            # Vérifier si ce cours fait partie des impayés
            lesson_key = (
                lesson.get("date", ""),
                lesson.get("student", ""),
                lesson.get("teacher", ""),
                lesson.get("duration_min") or 0,
            )
            if lesson_key not in unpaid_keys:
                continue

            # Retirer la clé pour éviter les doublons si plusieurs cours identiques
            unpaid_keys.discard(lesson_key)

            t_name = lesson.get("teacher") or ""
            duration = lesson.get("duration_min") or 0
            hours = duration / 60.0

            cfg_key = teacher_lookup.get(norm(t_name))
            if not cfg_key:
                continue

            t_cfg = teachers_cfg[cfg_key]
            pay = t_cfg.get("pay_rate", {})

            special = get_special_rate(t_name, parent, lesson.get("student"))

            if special is not None:
                rate = special
                amount = rate * hours
                currency_label = "CHF★"
            else:
                rate = pay.get("chf", 0)
                amount = rate * hours
                currency_label = "CHF"

            teacher_totals[cfg_key]["chf"] += amount
            teacher_totals[cfg_key]["nb_lessons"] += 1
            teacher_totals[cfg_key]["total_hours"] += hours
            teacher_totals[cfg_key]["details"].append({
                "date": lesson.get("date", ""),
                "student": lesson.get("student", ""),
                "family_parent": parent,
                "currency": currency_label,
                "duration_min": duration,
                "rate": rate,
                "amount_eur": round(amount, 2),  # Clé gardée pour compatibilité PDF
            })

    grand_total = sum(d["chf"] for d in teacher_totals.values())
    total_lessons = sum(d["nb_lessons"] for d in teacher_totals.values())

    return {
        "teachers": dict(teacher_totals),
        "grand_total": round(grand_total, 2),
        "total_lessons": total_lessons,
        "currency": "CHF",
        "families_fully_paid": families_fully_paid,
        "families_with_balance": families_with_balance,
    }