"""
👨‍🏫 Recap Profs - VERSION FARES
Calcul des montants à payer aux professeurs en CHF
Tout est en CHF — pas de conversion EUR nécessaire.
"""

import unicodedata
from collections import defaultdict


PAYABLE_STATUSES = {"Present", "Unrecorded", "AbsentNoMakeup"}


def norm(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def compute_teacher_recap(data, secrets, familles_euros=None, tarifs_speciaux=None, **kwargs):
    """
    Calcule le récap des montants à payer à chaque prof en CHF.
    
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

    for fam in data.values():
        parent = fam.get("parent_name") or ""

        for lesson in fam.get("lessons", []):
            status = lesson.get("attendance_status", "")
            if status not in PAYABLE_STATUSES:
                continue

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
    }