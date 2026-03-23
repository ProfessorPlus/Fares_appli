"""
📄 Generate Prof PDFs - Design Lovable (VERSION FARES)
Tout en CHF — pas de conversion EUR.
"""

import os
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ===========================
# FONTS
# ===========================
def _init_fonts():
    paths = [
        ("Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("SansBd", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for name, path in paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:
                pass
    try:
        pdfmetrics.getFont("Sans")
        return "Sans", "SansBd"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


F, FB = _init_fonts()

# ===========================
# COLORS (matching Lovable)
# ===========================
NAVY = colors.HexColor("#1F3A67")
GREEN = colors.HexColor("#059669")
CARD_BG = colors.HexColor("#F7F8FA")
CARD_BORDER = colors.HexColor("#E5E7EB")
ROW_ALT = colors.HexColor("#F9FAFB")
ROW_BORDER = colors.HexColor("#E5E7EB")
TXT = colors.HexColor("#1F2937")
TXT_MID = colors.HexColor("#6B7280")
TXT_LIGHT = colors.HexColor("#9CA3AF")
WHITE = colors.white

PW, PH = A4
MX = 50
MY_TOP = 45
MY_BOT = 35
CW = PW - 2 * MX


def _rrect(c, x, y, w, h, r=6, fill=None, stroke=None, sw=0.75):
    p = c.beginPath()
    p.roundRect(x, y, w, h, r)
    if fill:
        c.setFillColor(fill)
    if stroke:
        c.setStrokeColor(stroke)
        c.setLineWidth(sw)
    else:
        c.setStrokeColor(fill or WHITE)
        c.setLineWidth(0)
    c.drawPath(p, fill=1 if fill else 0, stroke=1 if stroke else 0)


def _circle(c, cx, cy, r, fill):
    c.setFillColor(fill)
    c.circle(cx, cy, r, fill=1, stroke=0)


def _build_page(c, teacher_name, data, mois_label, logo_path):
    total_chf = data.get("chf", 0)
    total_hours = data.get("total_hours", 0)
    nb_lessons = data.get("nb_lessons", 0)
    details = data.get("details", [])

    y = PH - MY_TOP

    # ─── HEADER ───
    logo_size = 44
    if logo_path and os.path.exists(logo_path):
        try:
            c.drawImage(logo_path, MX, y - logo_size, width=logo_size, height=logo_size, preserveAspectRatio=True, mask='auto')
        except Exception:
            _circle(c, MX + 22, y - 22, 22, NAVY)
            c.setFillColor(WHITE)
            c.setFont(FB, 16)
            c.drawCentredString(MX + 22, y - 28, "P+")
    else:
        _circle(c, MX + 22, y - 22, 22, NAVY)
        c.setFillColor(WHITE)
        c.setFont(FB, 16)
        c.drawCentredString(MX + 22, y - 28, "P+")

    tx = MX + logo_size + 14
    c.setFillColor(TXT)
    c.setFont(FB, 20)
    c.drawString(tx, y - 18, "Professor+")
    c.setFillColor(TXT_LIGHT)
    c.setFont(F, 9)
    c.drawString(tx, y - 34, "Soutien scolaire personnalisé")

    c.setFillColor(NAVY)
    c.setFont(FB, 24)
    c.drawRightString(PW - MX, y - 16, "Détail de paie")
    c.setFillColor(TXT_MID)
    c.setFont(F, 10)
    c.drawRightString(PW - MX, y - 36, f"Période : {mois_label}")

    y -= 58
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.75)
    c.line(MX, y, PW - MX, y)
    y -= 30

    # ─── METRIC CARDS ───
    gap = 10
    card1_w = CW * 0.34
    card4_w = CW * 0.24
    remaining = CW - card1_w - card4_w - 3 * gap
    card_sm = remaining / 2
    card_h = 62

    cards = [
        (card1_w, "PROFESSEUR", teacher_name, TXT, 13),
        (card_sm, "LEÇONS", str(nb_lessons), NAVY, 22),
        (card_sm, "HEURES", f"{total_hours:.1f}h", NAVY, 22),
        (card4_w, "TOTAL À PAYER", f"{total_chf:,.2f} CHF", GREEN, 16),
    ]

    cx = MX
    for w, label, val, vc, fs in cards:
        _rrect(c, cx, y - card_h, w, card_h, r=8, fill=CARD_BG, stroke=CARD_BORDER)
        c.setFillColor(TXT_LIGHT)
        c.setFont(FB, 7)
        c.drawString(cx + 14, y - 18, label)
        c.setFillColor(vc)
        actual_fs = fs
        if len(val) > 20 and fs > 11:
            actual_fs = 11

        # Wrap PROFESSEUR name on 2 lines if needed
        if label == "PROFESSEUR":
            max_text_w = w - 28
            text_w = c.stringWidth(val, FB, actual_fs)
            if text_w > max_text_w:
                words = val.split()
                line1 = ""
                line2 = ""
                for word in words:
                    test = (line1 + " " + word).strip()
                    if c.stringWidth(test, FB, actual_fs) <= max_text_w:
                        line1 = test
                    else:
                        line2 = (line2 + " " + word).strip()
                c.setFont(FB, actual_fs)
                c.drawString(cx + 14, y - card_h + 28, line1)
                c.drawString(cx + 14, y - card_h + 12, line2)
            else:
                c.setFont(FB, actual_fs)
                c.drawString(cx + 14, y - card_h + 18, val)
        else:
            c.setFont(FB, actual_fs)
            c.drawString(cx + 14, y - card_h + 18, val)

        cx += w + gap

    y -= card_h + 30

    # ─── SECTION TITLE ───
    c.setFillColor(NAVY)
    c.setFont(FB, 14)
    c.drawString(MX, y, "Détail des leçons")
    title_w = c.stringWidth("Détail des leçons", FB, 14)
    c.setStrokeColor(NAVY)
    c.setLineWidth(2)
    c.line(MX, y - 5, MX + title_w, y - 5)
    y -= 28

    # ─── TABLE ───
    cols = [90, 150, 70, 100, 85]
    tw = sum(cols)
    tx0 = MX + (CW - tw) / 2
    rh = 36

    # Header
    _rrect(c, tx0, y - rh, tw, rh, r=5, fill=NAVY)
    hdrs = ["Date", "Élève", "Durée", "Taux horaire", "Montant"]
    c.setFillColor(WHITE)
    c.setFont(FB, 9)
    hx = tx0
    for i, h in enumerate(hdrs):
        if i == len(hdrs) - 1:
            c.drawRightString(hx + cols[i] - 12, y - rh + 13, h)
        else:
            c.drawString(hx + 12, y - rh + 13, h)
        hx += cols[i]
    y -= rh

    sorted_d = sorted(details, key=lambda d: d["date"])
    tot_min = 0
    tot_amt = 0.0

    for idx, d in enumerate(sorted_d):
        bg = ROW_ALT if idx % 2 == 0 else WHITE
        c.setFillColor(bg)
        c.rect(tx0, y - rh, tw, rh, fill=1, stroke=0)
        c.setStrokeColor(ROW_BORDER)
        c.setLineWidth(0.5)
        c.line(tx0, y - rh, tx0 + tw, y - rh)

        rx = tx0
        ry = y - rh + 13
        c.setFillColor(TXT)
        c.setFont(F, 9)

        c.drawString(rx + 12, ry, d["date"])
        rx += cols[0]

        student = d.get("student", "")
        if "," in student:
            parts = [p.strip() for p in student.split(",")]
            student = " ".join(parts)
        if len(student) > 22:
            student = student[:20] + "…"
        c.drawString(rx + 12, ry, student)
        rx += cols[1]

        dur = d.get("duration_min", 0)
        tot_min += dur
        c.drawString(rx + 12, ry, f"{dur} min")
        rx += cols[2]

        rate = d.get("rate", 0)
        cur = d.get("currency", "CHF")
        is_special = "★" in cur
        taux = f"{rate:,.2f} CHF/h" + ("★" if is_special else "")
        c.drawString(rx + 12, ry, taux)
        rx += cols[3]

        amt = d.get("amount_eur", 0)  # Key is amount_eur for compat but it's CHF
        tot_amt += amt
        c.setFont(FB, 9)
        c.drawRightString(rx + cols[4] - 12, ry, f"{amt:,.2f} CHF")
        y -= rh

    # ─── TOTAL ROW ───
    trh = 40
    left_w = cols[0] + cols[1] + cols[2]
    _rrect(c, tx0, y - trh, left_w, trh, r=0, fill=NAVY)
    right_w = tw - left_w
    c.setFillColor(CARD_BG)
    c.rect(tx0 + left_w, y - trh, right_w, trh, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.setFont(FB, 11)
    c.drawString(tx0 + 12, y - trh + 14, "TOTAL")
    h, m = divmod(tot_min, 60)
    c.drawString(tx0 + cols[0] + cols[1] + 12, y - trh + 14, f"{h}h{m:02d}" if m else f"{h}h")

    c.setFillColor(GREEN)
    c.setFont(FB, 15)
    c.drawRightString(tx0 + tw - 12, y - trh + 12, f"{tot_amt:,.2f} CHF")

    # ─── FOOTER ───
    fy = MY_BOT + 8
    c.setStrokeColor(CARD_BORDER)
    c.setLineWidth(0.5)
    c.line(MX, fy + 12, PW - MX, fy + 12)
    c.setFillColor(TXT_LIGHT)
    c.setFont(F, 7)
    c.drawString(MX, fy, "★ = tarif spécial")
    c.drawRightString(PW - MX, fy, "Généré automatiquement — Professor+")


# ===========================
# PUBLIC API
# ===========================

def generate_single_pdf_to_bytes(teacher_name, data, mois_label, logo_path=None, extraction_end_date=None):
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    _build_page(cv, teacher_name, data, mois_label, logo_path)
    cv.save()
    buf.seek(0)
    return buf.getvalue()


def generate_all_pdfs_as_zip(teacher_recaps, mois_label, logo_path=None, exclude_owner="Fares Chouchenne", extraction_end_date=None):
    import zipfile
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        for tname in sorted(teacher_recaps.keys()):
            if tname == exclude_owner:
                continue
            d = teacher_recaps[tname]
            if d["nb_lessons"] == 0:
                continue
            buf = io.BytesIO()
            cv = canvas.Canvas(buf, pagesize=A4)
            _build_page(cv, tname, d, mois_label, logo_path)
            cv.save()
            buf.seek(0)
            safe = tname.replace(" ", "_")
            zf.writestr(f"Paie_{safe}_{mois_label.replace(' ', '_')}.pdf", buf.getvalue())
    zbuf.seek(0)
    return zbuf.getvalue()


def generate_all_pdfs_to_bytes(teacher_recaps, mois_label, logo_path=None, exclude_owner="Fares Chouchenne", extraction_end_date=None):
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    first = True
    for tname in sorted(teacher_recaps.keys()):
        if tname == exclude_owner:
            continue
        d = teacher_recaps[tname]
        if d["nb_lessons"] == 0:
            continue
        if not first:
            cv.showPage()
        first = False
        _build_page(cv, tname, d, mois_label, logo_path)
    if not first:
        cv.save()
        buf.seek(0)
        return buf.getvalue()
    return None