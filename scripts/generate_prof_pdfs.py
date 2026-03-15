"""
📄 Generate Prof PDFs - VERSION FARES
Génère un PDF par professeur avec le détail des leçons en CHF.
Pas de conversion EUR — tout est en CHF.
"""

import os
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    Image, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT


HEADER_BG = colors.HexColor("#1F3A67")
ROW_ALT = colors.HexColor("#f5f5f5")
BORDER_COLOR = colors.HexColor("#bdbdbd")
ACCENT = colors.HexColor("#1F3A67")


def _build_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("CustomTitle", parent=styles["Title"], fontSize=20, spaceAfter=4, textColor=ACCENT),
        "subtitle": ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11, spaceAfter=4, textColor=colors.HexColor("#424242")),
        "header": ParagraphStyle("TableHeader", parent=styles["Normal"], fontSize=9, textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold"),
        "cell": ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8.5, alignment=TA_CENTER),
        "cell_left": ParagraphStyle("CellLeft", parent=styles["Normal"], fontSize=8.5, alignment=TA_LEFT),
        "cell_right": ParagraphStyle("CellRight", parent=styles["Normal"], fontSize=8.5, alignment=TA_RIGHT),
        "total": ParagraphStyle("TotalCell", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=ACCENT),
        "footer": ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#9e9e9e")),
    }


def _build_teacher_story(teacher_name, data, mois_label, logo_path, styles):
    story = []

    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=35*mm, height=35*mm)
            logo.hAlign = "LEFT"
            header_data = [[logo, Paragraph("Professor+<br/><font size=10>Détail de paie</font>", styles["title"])]]
            header_table = Table(header_data, colWidths=[40*mm, 120*mm])
            header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(header_table)
        except Exception:
            story.append(Paragraph("Professor+", styles["title"]))
    else:
        story.append(Paragraph("Professor+", styles["title"]))

    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(f"Période : {mois_label}", styles["subtitle"]))
    story.append(Spacer(1, 6*mm))

    total_chf = data["chf"]
    total_hours = data.get("total_hours", 0)

    info_data = [
        [Paragraph("<b>Professeur</b>", styles["cell_left"]), Paragraph(teacher_name, styles["cell_left"])],
        [Paragraph("<b>Nombre de leçons</b>", styles["cell_left"]), Paragraph(str(data["nb_lessons"]), styles["cell_left"])],
        [Paragraph("<b>Heures totales</b>", styles["cell_left"]), Paragraph(f"{total_hours:.1f}h", styles["cell_left"])],
        [Paragraph("<b>TOTAL À PAYER</b>", styles["cell_left"]),
         Paragraph(f"<b>{total_chf:.2f} CHF</b>", ParagraphStyle("TI", parent=styles["cell_left"], fontSize=11, textColor=ACCENT, fontName="Helvetica-Bold"))],
    ]
    info_table = Table(info_data, colWidths=[55*mm, 80*mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8eaf6")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER_COLOR),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8*mm))

    headers = ["Date", "Élève", "Durée", "Taux", "Montant CHF"]
    header_row = [Paragraph(h, styles["header"]) for h in headers]

    sorted_details = sorted(data["details"], key=lambda x: x["date"])
    rows = [header_row]
    for d in sorted_details:
        rows.append([
            Paragraph(d["date"], styles["cell"]),
            Paragraph(d["student"], styles["cell_left"]),
            Paragraph(f"{d['duration_min']} min", styles["cell"]),
            Paragraph(f"{d['rate']}", styles["cell"]),
            Paragraph(f"{d['amount_eur']:.2f} CHF", styles["cell_right"]),
        ])

    rows.append([
        Paragraph("", styles["cell"]), Paragraph("", styles["cell"]), Paragraph("", styles["cell"]),
        Paragraph("<b>TOTAL</b>", ParagraphStyle("t", parent=styles["cell"], fontName="Helvetica-Bold")),
        Paragraph(f"<b>{total_chf:.2f} CHF</b>", styles["total"]),
    ])

    col_widths = [22*mm, 58*mm, 18*mm, 18*mm, 25*mm]
    lesson_table = Table(rows, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8eaf6")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, HEADER_BG),
    ]
    for i in range(1, len(rows) - 1):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    lesson_table.setStyle(TableStyle(style_cmds))
    story.append(lesson_table)

    story.append(Spacer(1, 10*mm))
    story.append(Paragraph("★ = tarif spécial  |  Généré automatiquement — Professor+", styles["footer"]))
    return story


def generate_single_pdf_to_bytes(teacher_name, data, mois_label, logo_path=None, **kwargs):
    styles = _build_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = _build_teacher_story(teacher_name, data, mois_label, logo_path, styles)
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def generate_all_pdfs_as_zip(teacher_recaps, mois_label, logo_path=None, exclude_owner="Fares Chouchene", **kwargs):
    import zipfile
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for tname in sorted(teacher_recaps.keys()):
            if tname == exclude_owner:
                continue
            data = teacher_recaps[tname]
            if data["nb_lessons"] == 0:
                continue
            pdf_bytes = generate_single_pdf_to_bytes(tname, data, mois_label, logo_path)
            safe_name = tname.replace(" ", "_")
            zf.writestr(f"Paie_{safe_name}_{mois_label.replace(' ', '_')}.pdf", pdf_bytes)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def generate_all_pdfs_to_bytes(teacher_recaps, mois_label, logo_path=None, exclude_owner="Fares Chouchene", **kwargs):
    styles = _build_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=20*mm, bottomMargin=20*mm)
    combined = []
    first = True
    for tname in sorted(teacher_recaps.keys()):
        if tname == exclude_owner:
            continue
        data = teacher_recaps[tname]
        if data["nb_lessons"] == 0:
            continue
        if not first:
            combined.append(PageBreak())
        first = False
        combined.extend(_build_teacher_story(tname, data, mois_label, logo_path, styles))
    if combined:
        doc.build(combined)
        buffer.seek(0)
        return buffer.getvalue()
    return None