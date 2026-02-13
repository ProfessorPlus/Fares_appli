"""
📄 Generate Invoices
Génération des factures PDF (basé sur generate_invoice_auto.py)
VERSION CLOUD - Compatible Streamlit Cloud avec Google Drive
"""

import os
import json
import re
import traceback
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from reportlab.lib.utils import ImageReader
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# Import du storage manager pour compatibilité cloud
try:
    from scripts.storage_manager import save_invoice_folder, load_json
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False

# ---------- CONSTANTES PDF ----------
BRAND_BLUE = colors.Color(0.121, 0.227, 0.404)
FONT_SANS, FONT_BOLD = "Helvetica", "Helvetica-Bold"
LEFT = RIGHT = 20 * mm
TOP = 48 * mm
BOTTOM = 24 * mm
TAGLINE_LEFT = "Soutien scolaire\nsur-mesure"

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]

STATUTS_NON_FACTURES = ["AbsentNotice"]


# ---------- NORMALISATION ----------
def normalize(s):
    """Normalise un nom : minuscules, sans accents, espaces propres"""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    if "," in s:
        p = [x.strip() for x in s.split(",", 1)]
        if len(p) == 2:
            s = f"{p[1]} {p[0]}"
    return s.strip()


def clean_str(s):
    """Nettoie une chaîne pour nom de fichier"""
    if not isinstance(s, str):
        return ""
    return re.sub(r"[^a-zA-Z0-9_\- ]", "", s).strip()


def parse_dt(date_str):
    """Parse une date DD.MM.YYYY"""
    try:
        return datetime.strptime(date_str, "%d.%m.%Y")
    except:
        return datetime.min


# ---------- TOTAL COMPACT (comme l'original) ----------
class TotalTight(Flowable):
    def __init__(self, text, fontName=FONT_BOLD, fontSize=16, color=BRAND_BLUE, spacing=-1.0):
        Flowable.__init__(self)
        self.text = text
        self.fontName = fontName
        self.fontSize = fontSize
        self.color = color
        self.spacing = spacing
        self.width = sum(pdfmetrics.stringWidth(ch, fontName, fontSize) + spacing for ch in text)
        self.height = fontSize + 2

    def wrap(self, *args):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFont(self.fontName, self.fontSize)
        c.setFillColor(self.color)
        x = 0
        for ch in self.text:
            c.drawString(x, 0, ch)
            x += pdfmetrics.stringWidth(ch, self.fontName, self.fontSize) + self.spacing
        c.restoreState()


# ---------- BOUTON (comme l'original) ----------
class PayButton(Flowable):
    def __init__(self, label="Cliquez ici pour payer en ligne", url="https://example.com"):
        Flowable.__init__(self)
        self.label = label
        self.url = url
        self.w = 55 * mm
        self.h = 11 * mm

    def wrap(self, *args):
        return (self.w, self.h)

    def draw(self):
        c = self.canv
        c.saveState()

        c.setFillColor(BRAND_BLUE)
        c.roundRect(0, 0, self.w, self.h, 5 * mm, fill=1, stroke=0)

        full = self.label
        before = "Cliquez "
        word = "ici"

        c.setFillColor(colors.white)
        c.setFont(FONT_SANS, 8.7)

        w_before = c.stringWidth(before, FONT_SANS, 8.7)
        w_word = c.stringWidth(word, FONT_SANS, 8.7)
        w_full = c.stringWidth(full, FONT_SANS, 8.7)

        x = (self.w - w_full) / 2
        y = (self.h - 9) / 2 + 2

        c.drawString(x, y, full)

        # Souligner "ici"
        underline_y = y - 1.2
        c.saveState()
        c.setStrokeColor(colors.white)
        c.setLineWidth(1.0)
        c.line(x + w_before, underline_y, x + w_before + w_word, underline_y)
        c.restoreState()

        c.linkURL(self.url, (0, 0, self.w, self.h), relative=1)
        c.restoreState()


# ---------- COMPTEUR FACTURES ----------
def _next_invoice_number(counter_root, invoice_date):
    os.makedirs(counter_root, exist_ok=True)
    month_dir = os.path.join(counter_root, f"invoice_counters_{invoice_date:%y_%m}")
    os.makedirs(month_dir, exist_ok=True)
    counter_file = os.path.join(month_dir, "invoice_counter.txt")

    if os.path.exists(counter_file):
        try:
            counter = int(open(counter_file, "r", encoding="utf-8").read().strip())
        except:
            counter = 0
    else:
        counter = 0

    counter += 1
    with open(counter_file, "w", encoding="utf-8") as f:
        f.write(str(counter))

    seq_number = 10000 + (counter - 1)
    return f"{invoice_date:%y-%m}-{seq_number}"


def run_generate_invoices(data, secrets, familles_euros, data_dir, base_dir, logo_path=None, callback=None, target_folder_path=None):
    """
    Génère les factures PDF.
    
    Args:
        data: Données extraites de TutorBird
        secrets: Configuration YAML
        familles_euros: Liste des familles en EUR
        data_dir: Dossier des données (pour payment_links_output.json)
        base_dir: Dossier racine du projet
        logo_path: Chemin vers le logo (optionnel)
        callback: Fonction callback(progress, message)
        target_folder_path: Chemin vers le dossier cible (optionnel, pour régénération)
    
    Returns:
        dict: {"success": bool, "invoices": int, "links_found": int, "generated_files": list, ...}
    """
    
    if not REPORTLAB_AVAILABLE:
        return {"success": False, "error": "Module reportlab non installé. pip install reportlab"}
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        TEACHERS = secrets.get("teachers", {})
        TEACHER_MAP = {normalize(tid): tid for tid in TEACHERS.keys()}
        
        # Règles spéciales de mapping
        if "Ricardo Hounsinou" in TEACHERS:
            TEACHER_MAP[normalize("Ricardo H")] = "Ricardo Hounsinou"
        if "Ricardo HOUNSINOU" in TEACHERS:
            TEACHER_MAP[normalize("Ricardo H")] = "Ricardo HOUNSINOU"
        
        # Table de correspondance teacher names
        TEACHER_ALIAS = {
            normalize("Ricardo H"): normalize("Ricardo Hounsinou"),
            normalize("Bruno Lamaison"): normalize("Bruno Lamaison"),
            normalize("lamaison bruno"): normalize("Bruno Lamaison"),
        }
        
        # Matching EUR
        manual_names = [normalize(n) for n in familles_euros]
        families_in_euros = set()
        
        for fam_id, fam in data.items():
            parent_name = fam.get("parent_name") or fam.get("family_name") or ""
            norm_parent = normalize(parent_name)
            
            for eur_name in manual_names:
                ratio = SequenceMatcher(None, norm_parent, eur_name).ratio()
                if ratio > 0.70:
                    families_in_euros.add(fam_id)
                    break
        
        # Charger liens Stripe (local ou Drive)
        links_map = {}
        links_list = None
        
        # Essayer storage_manager d'abord (supporte Drive)
        if STORAGE_AVAILABLE:
            links_list = load_json("payment_links_output.json", "data", default=None)
        
        # Fallback fichier local
        if links_list is None:
            links_path = os.path.join(data_dir, "payment_links_output.json")
            if os.path.exists(links_path):
                with open(links_path, "r", encoding="utf-8") as f:
                    links_list = json.load(f)
        
        if links_list:
            for e in links_list:
                key = (e["family_id"], normalize(e["teacher"]))
                links_map[key] = e["payment_link"]
        
        today = datetime.today()
        year_str = today.strftime("%Y")
        month_str = MONTHS_FR[today.month - 1]
        
        # Dossiers
        invoice_root = os.path.join(base_dir, "Factures")
        counter_root = os.path.join(base_dir, "invoice_counters")
        
        # Utiliser le dossier cible si spécifié
        if target_folder_path and os.path.exists(target_folder_path):
            month_folder_path = target_folder_path
            update(5, f"📁 Régénération dans : {os.path.basename(target_folder_path)}")
        else:
            month_folder_name = f"{month_str} {year_str} - {today.strftime('%d-%m-%Y')}"
            month_folder_path = os.path.join(invoice_root, year_str, month_folder_name)
            os.makedirs(month_folder_path, exist_ok=True)
        
        # Stats
        factures_generees = 0
        liens_trouves = 0
        liens_manquants = []
        cours_non_factures = 0
        generated_files = []
        
        total_families = len(data)
        current = 0
        
        for fam_id, fam in data.items():
            current += 1
            progress = int(current / total_families * 90)
            
            lessons = fam.get("lessons", [])
            if not lessons:
                continue
            
            parent_name = fam.get("parent_name") or fam.get("family_name") or "Parent"
            update(progress, f"📄 {parent_name} ({current}/{total_families})")
            
            currency = "EUR" if fam_id in families_in_euros else "CHF"
            
            # Filtrer les absences
            lessons_filtered = []
            for L in lessons:
                attendance = L.get("attendance_status", "")
                if attendance in STATUTS_NON_FACTURES:
                    cours_non_factures += 1
                    continue
                lessons_filtered.append(L)
            
            if not lessons_filtered:
                continue
            
            # Regrouper par prof
            by_teacher = {}
            for L in lessons_filtered:
                prof_tb = L.get("teacher") or "Professeur"
                prof_normalized = normalize(prof_tb)
                yaml_name = TEACHER_MAP.get(prof_normalized, prof_tb)
                by_teacher.setdefault((prof_tb, yaml_name), []).append(L)
            
            fam_folder = clean_str(parent_name.replace(" ", "_"))
            fam_base_dir = os.path.join(month_folder_path, fam_folder)
            os.makedirs(fam_base_dir, exist_ok=True)
            
            for (teacher_display, teacher_yaml), lessons_list in by_teacher.items():
                lessons_sorted = sorted(lessons_list, key=lambda x: parse_dt(x.get("date", "")))
                
                items = []
                total_due = 0.0
                
                for L in lessons_sorted:
                    d = parse_dt(L.get("date", ""))
                    student = L.get("student", "")
                    duration = L.get("duration_min", "")
                    desc = f"Cours avec {teacher_display} pour {student} ({duration} min)"
                    amt = float(L.get("amount", 0) or 0)
                    total_due += amt
                    items.append({"date": d, "description": desc, "amount": amt})
                
                if total_due <= 0:
                    continue
                
                total_due_display = f"{total_due:.2f} {currency}"
                
                # Chercher lien paiement
                pay_link_url = None
                teacher_norm = normalize(teacher_display)
                teacher_search = TEACHER_ALIAS.get(teacher_norm, teacher_norm)
                
                # Essai 1
                key1 = (fam_id, teacher_search)
                if key1 in links_map:
                    pay_link_url = links_map[key1]
                
                # Essai 2
                if not pay_link_url:
                    key2 = (fam_id, normalize(teacher_yaml))
                    if key2 in links_map:
                        pay_link_url = links_map[key2]
                
                # Essai 3
                if not pay_link_url:
                    key3 = (fam_id, teacher_norm)
                    if key3 in links_map:
                        pay_link_url = links_map[key3]
                
                # Essai 4: recherche approximative
                if not pay_link_url:
                    for (link_fam, link_teacher), link_url in links_map.items():
                        if link_fam == fam_id:
                            if SequenceMatcher(None, teacher_search, link_teacher).ratio() > 0.8:
                                pay_link_url = link_url
                                break
                            if SequenceMatcher(None, teacher_norm, link_teacher).ratio() > 0.8:
                                pay_link_url = link_url
                                break
                
                if pay_link_url:
                    liens_trouves += 1
                else:
                    pay_link_url = "https://example.com"
                    liens_manquants.append(f"{parent_name} / {teacher_display}")
                
                teacher_clean = clean_str(teacher_display.replace(" ", "_"))
                filename = f"Facture_{year_str}-{today.strftime('%m-%d')}_{teacher_clean}.pdf"
                output_path = os.path.join(fam_base_dir, filename)
                
                # ---------- GENERATION PDF ----------
                def draw_header(canvas, doc_inner):
                    w, h = A4
                    x_left = LEFT
                    x_right = w - RIGHT
                    y_top = h - TOP + 16 * mm

                    if logo_path and os.path.exists(logo_path):
                        img = ImageReader(logo_path)
                        canvas.drawImage(img, x_left, y_top - 26*mm, width=36*mm, height=36*mm, preserveAspectRatio=True)

                    canvas.setFillColor(BRAND_BLUE)
                    canvas.setFont(FONT_BOLD, 27)
                    title = "FACTURE"
                    tw = canvas.stringWidth(title, FONT_BOLD, 27)
                    canvas.drawString(x_right - tw, y_top - 6 * mm, title)

                def draw_footer(canvas, doc):
                    w, h = A4
                    bar_h = 12 * mm
                    y = 12 * mm

                    canvas.setFillColor(BRAND_BLUE)
                    canvas.rect(LEFT, y, w - LEFT - RIGHT, bar_h, fill=1, stroke=0)

                    canvas.setFillColor(colors.white)
                    canvas.setFont(FONT_BOLD, 11)
                    canvas.drawString(LEFT + 5 * mm, y + bar_h/2 - 4, "Soutien scolaire sur-mesure")

                    canvas.setFont(FONT_SANS, 10)
                    txt = "Facture"
                    tw = canvas.stringWidth(txt, FONT_SANS, 10)
                    canvas.drawString(w - RIGHT - tw - 5*mm, y + bar_h/2 - 4, txt)

                def on_page(canvas, d):
                    draw_header(canvas, d)
                    draw_footer(canvas, d)

                doc = SimpleDocTemplate(
                    output_path,
                    pagesize=A4,
                    leftMargin=LEFT,
                    rightMargin=RIGHT,
                    topMargin=TOP,
                    bottomMargin=BOTTOM,
                )

                flow = []

                # Styles
                st_sub = ParagraphStyle(name="sub", fontName=FONT_BOLD, fontSize=11, leading=13)
                st_facturer = ParagraphStyle(name="facturer", fontName=FONT_SANS, fontSize=12, leading=14)
                st_label = ParagraphStyle(name="label", fontName=FONT_BOLD, fontSize=10, alignment=TA_RIGHT)
                st_value = ParagraphStyle(name="value", fontName=FONT_SANS, fontSize=10, alignment=TA_RIGHT)
                st_header = ParagraphStyle(name="th", fontName=FONT_BOLD, fontSize=12, alignment=TA_CENTER, textColor=colors.white)

                date_str = today.strftime("%d.%m.%Y")
                inv_number = _next_invoice_number(counter_root, today)

                # BANDEAU HAUT
                left_band = Paragraph(TAGLINE_LEFT.replace("\n", "<br/>"), st_sub)
                middle_band = Paragraph(f"<b>Facturer à :</b><br/>{parent_name}", st_facturer)

                avail = A4[0] - LEFT - RIGHT
                left_w = 58 * mm
                mid_w = 54 * mm
                right_w = avail - left_w - mid_w

                right_band = Table(
                    [
                        [Paragraph("Date :", st_label), "", Paragraph(date_str, st_value)],
                        [Paragraph("Facture n°:", st_label), "", Paragraph(inv_number, st_value)],
                    ],
                    colWidths=[26*mm, 4*mm, right_w - 30*mm],
                )

                header_row = Table([[left_band, middle_band, right_band]],
                                   colWidths=[left_w, mid_w, right_w])
                flow.append(header_row)
                flow.append(Spacer(1, 10 * mm))

                # TABLEAU
                data_tbl = [
                    [
                        Paragraph("Date", st_header),
                        Paragraph("Description", st_header),
                        Paragraph("Frais", st_header),
                    ]
                ]

                for item in items:
                    date_cell = item["date"].strftime("%d.%m.%Y") if item["date"] != datetime.min else ""
                    desc_cell = item["description"]
                    amt = float(item["amount"])
                    amount_cell = f"{amt:.2f} {currency}"
                    data_tbl.append([date_cell, desc_cell, amount_cell])

                tbl = Table(
                    data_tbl,
                    colWidths=[30*mm, avail - 60*mm, 30*mm],
                    repeatRows=1,
                )

                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),

                    ("TOPPADDING", (0, 0), (-1, 0), 14),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 14),

                    ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("ALIGN", (1, 1), (1, -1), "CENTER"),
                    ("ALIGN", (2, 1), (2, -1), "CENTER"),

                    ("TOPPADDING", (0, 1), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 8),

                    ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.lightgrey),
                ]))

                flow.append(tbl)
                flow.append(Spacer(1, 18 * mm))

                # TOTAL + BOUTON
                total_para = TotalTight(f"Total dû : {total_due_display}", spacing=-1.0)

                stack = Table(
                    [
                        [total_para],
                        [PayButton(label="Cliquez ici pour payer en ligne", url=pay_link_url)],
                    ],
                    colWidths=[55 * mm],
                    hAlign="RIGHT",
                )

                stack.setStyle(TableStyle([
                    ("ALIGN", (0, 0), (0, 0), "CENTER"),
                    ("ALIGN", (0, 1), (0, 1), "CENTER"),
                    ("TOPPADDING", (0, 0), (0, 0), 6),
                ]))

                flow.append(stack)

                # BUILD PDF
                try:
                    doc.build(flow, onFirstPage=on_page, onLaterPages=on_page)
                    factures_generees += 1
                    generated_files.append(output_path)
                except:
                    traceback.print_exc()
        
        # ===============================
        # UPLOAD VERS GOOGLE DRIVE (si cloud)
        # ===============================
        drive_saved = False
        if STORAGE_AVAILABLE and factures_generees > 0:
            update(95, "☁️ Upload vers Google Drive...")
            try:
                result = save_invoice_folder(month_folder_path)
                if result.get("success"):
                    drive_saved = True
                    uploaded_count = result.get("uploaded", 0)
                    update(98, f"☁️ {uploaded_count} fichiers uploadés sur Drive")
            except Exception as e:
                print(f"⚠️ Erreur upload Drive: {e}")
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "invoices": factures_generees,
            "links_found": liens_trouves,
            "links_missing": liens_manquants,
            "absences": cours_non_factures,
            "folder": month_folder_path,
            "generated_files": generated_files,
            "drive_saved": drive_saved
        }
        
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}