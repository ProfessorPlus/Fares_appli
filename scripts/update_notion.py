"""
📤 Ajouter Lignes Notion
Ajoute les nouvelles lignes dans la database paiements Notion
ET crée les sous-pages dans les pages des profs
"""

import os
import json
import time
import re
import unicodedata
import requests
from datetime import datetime
from collections import defaultdict
from difflib import SequenceMatcher


MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

REQUEST_DELAY = 0.20


def normalize_name(n):
    if not n:
        return ""
    return " ".join(n.lower().strip().replace(",", " ").replace("&", " ").split())


def names_match(n1, n2):
    w1, w2 = set(normalize_name(n1).split()), set(normalize_name(n2).split())
    if not w1 or not w2:
        return False
    return w1 == w2 or len(w1 & w2) >= 2 or (len(w1) == 2 and w1.issubset(w2)) or (len(w2) == 2 and w2.issubset(w1))


def normalize_for_match(s):
    """Normalise un nom pour comparaison."""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.replace("-", " ").replace("_", " ").replace(",", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def format_date_title(date_str):
    """Convertit 2026-01-03 en '3 Janvier 2026'."""
    if not date_str:
        return "Date inconnue"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_FR[dt.month - 1]} {dt.year}"
    except:
        return date_str


def run_update_notion(secrets, data, base_dir, callback=None):
    """
    Ajoute les nouvelles lignes dans Notion ET crée les sous-pages profs.
    
    Args:
        secrets: Configuration YAML
        data: Données extraites de TutorBird
        base_dir: Dossier racine
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "added": int, "skipped": int, "pages_created": int, "error": str}
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        ROOT_PAGE = secrets["notion"]["root_page_paiements"]
        TEACHERS = secrets.get("teachers", {})
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        def notion_request(method, endpoint, json_data=None):
            time.sleep(REQUEST_DELAY)
            url = f"https://api.notion.com/v1/{endpoint}"
            
            if method == "GET":
                r = requests.get(url, headers=HEADERS, timeout=30)
            elif method == "POST":
                r = requests.post(url, headers=HEADERS, json=json_data, timeout=30)
            elif method == "PATCH":
                r = requests.patch(url, headers=HEADERS, json=json_data, timeout=30)
            elif method == "DELETE":
                r = requests.delete(url, headers=HEADERS, timeout=30)
            else:
                return None
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 2))
                time.sleep(retry)
                return notion_request(method, endpoint, json_data)
            
            if r.status_code in [200, 201]:
                return r.json() if r.text else {"ok": True}
            return None
        
        def get_children(block_id):
            results = []
            cursor = None
            while True:
                url = f"blocks/{block_id}/children?page_size=100"
                if cursor:
                    url += f"&start_cursor={cursor}"
                data = notion_request("GET", url)
                if not data:
                    break
                results.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
            return results
        
        # ===========================
        # CACHES pour les pages profs
        # ===========================
        PROF_CACHE = {}  # {name: id}
        DATE_CACHE = {}  # {(prof_id, title): id}
        STUDENT_CACHE = {}  # {date_id: {normalized: {id, title, name}}}
        
        def load_profs():
            for b in get_children(ROOT_PAGE):
                if b["type"] == "child_page":
                    PROF_CACHE[b["child_page"]["title"].strip()] = b["id"]
        
        def get_or_create_prof(name):
            if name in PROF_CACHE:
                return PROF_CACHE[name]
            
            # Créer la page prof
            data = notion_request("POST", "pages", {
                "parent": {"page_id": ROOT_PAGE},
                "properties": {"title": [{"text": {"content": name}}]}
            })
            if data and "id" in data:
                PROF_CACHE[name] = data["id"]
                return data["id"]
            return None
        
        def load_dates_for_prof(prof_id):
            if any(k[0] == prof_id for k in DATE_CACHE):
                return
            for b in get_children(prof_id):
                if b["type"] == "child_page":
                    DATE_CACHE[(prof_id, b["child_page"]["title"].strip())] = b["id"]
        
        def get_or_create_date(prof_id, date_cours):
            title = format_date_title(date_cours)
            load_dates_for_prof(prof_id)
            key = (prof_id, title)
            if key in DATE_CACHE:
                return DATE_CACHE[key], title
            
            # Créer la page date
            data = notion_request("POST", "pages", {
                "parent": {"page_id": prof_id},
                "properties": {"title": [{"text": {"content": title}}]}
            })
            if data and "id" in data:
                DATE_CACHE[key] = data["id"]
                return data["id"], title
            return None, title
        
        def load_students_for_date(date_id):
            if date_id in STUDENT_CACHE:
                return
            STUDENT_CACHE[date_id] = {}
            for b in get_children(date_id):
                if b["type"] == "child_page":
                    full = b["child_page"]["title"].strip()
                    name = full.split(" – ")[0].strip() if " – " in full else full
                    STUDENT_CACHE[date_id][normalize_name(name)] = {"id": b["id"], "title": full, "name": name}
        
        def get_or_create_student(date_id, name):
            load_students_for_date(date_id)
            norm = normalize_name(name)
            
            # Exact match
            if norm in STUDENT_CACHE[date_id]:
                s = STUDENT_CACHE[date_id][norm]
                return s["id"], s["title"]
            
            # Fuzzy match
            for n, s in STUDENT_CACHE[date_id].items():
                if names_match(name, s["name"]):
                    return s["id"], s["title"]
            
            # Create
            data = notion_request("POST", "pages", {
                "parent": {"page_id": date_id},
                "properties": {"title": [{"text": {"content": name}}]}
            })
            if data and "id" in data:
                STUDENT_CACHE[date_id][norm] = {"id": data["id"], "title": name, "name": name}
                return data["id"], None
            return None, None
        
        def update_student_page(student_id, name, payments):
            """Met à jour le contenu d'une page élève avec un tableau."""
            # Supprimer les anciens tableaux
            for b in get_children(student_id):
                if b["type"] == "table":
                    notion_request("DELETE", f"blocks/{b['id']}")
            
            # Créer le tableau
            rows = [{"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "Mois / Date"}}],
                [{"type": "text", "text": {"content": "Heures"}}],
                [{"type": "text", "text": {"content": "Montant"}}],
                [{"type": "text", "text": {"content": "Payé ?"}}],
            ]}}]
            
            for p in payments:
                rows.append({"type": "table_row", "table_row": {"cells": [
                    [{"type": "text", "text": {"content": p.get("date", "")}}],
                    [{"type": "text", "text": {"content": f"{p.get('hours', 0):.1f}h"}}],
                    [{"type": "text", "text": {"content": f"{p.get('amount', 0):.2f} {p.get('currency', 'CHF')}"}}],
                    [{"type": "text", "text": {"content": "☐"}}],
                ]}})
            
            notion_request("PATCH", f"blocks/{student_id}/children", {
                "children": [{"type": "table", "table": {"table_width": 4, "has_column_header": True, "children": rows}}]
            })
            
            # Update title
            total = len(payments)
            title = f"{name} – Paie [0 / {total}]"
            notion_request("PATCH", f"pages/{student_id}", {
                "properties": {"title": [{"text": {"content": title}}]}
            })
            return title
        
        # ===========================
        # ÉTAPE 1: Vérifier les doublons dans la DB
        # ===========================
        update(5, "🔍 Vérification des doublons...")
        
        existing = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", {
            "sorts": [{"property": "id paiements", "direction": "descending"}],
            "page_size": 100
        })
        
        existing_keys = set()
        if existing:
            for row in existing.get("results", []):
                props = row["properties"]
                
                famille = ""
                montant = 0
                
                famille_prop = props.get("Famille", {})
                if famille_prop.get("title"):
                    famille = famille_prop["title"][0]["plain_text"] if famille_prop["title"] else ""
                
                montant = props.get("Montant total dû", {}).get("number", 0)
                
                if famille and montant:
                    existing_keys.add((famille.lower(), round(montant, 2)))
        
        # ===========================
        # ÉTAPE 2: Obtenir le prochain ID
        # ===========================
        update(10, "📊 Récupération du dernier ID...")
        
        metadata_db = secrets["notion"].get("metadata_database_id")
        next_id = 1
        
        if metadata_db:
            meta = notion_request("POST", f"databases/{metadata_db}/query", {})
            if meta:
                for row in meta.get("results", []):
                    props = row["properties"]
                    cle = props.get("Clé", {}).get("title", [])
                    if cle and cle[0].get("plain_text", "").strip() == "last_payment_id":
                        next_id = props.get("Valeur", {}).get("number", 0) + 1
                        break
        
        # ===========================
        # ÉTAPE 3: Charger les pages profs existantes
        # ===========================
        update(15, "📚 Chargement des pages profs...")
        load_profs()
        
        # ===========================
        # ÉTAPE 4: Ajouter les lignes et créer les sous-pages
        # ===========================
        update(20, "➕ Ajout des lignes...")
        
        added = 0
        skipped = 0
        pages_created = 0
        total = len(data)
        current = 0
        
        for fam_id, fam in data.items():
            current += 1
            progress = int(20 + (current / total * 60))
            
            parent_name = fam.get("parent_name") or fam.get("family_name") or ""
            parent_email = fam.get("parent_email") or ""
            total_amount = fam.get("total_courses", 0)
            
            # Vérifier doublon
            key = (parent_name.lower(), round(total_amount, 2))
            if key in existing_keys:
                skipped += 1
                continue
            
            update(progress, f"➕ {parent_name}")
            
            lessons = fam.get("lessons", [])
            
            # Filtrer les absences
            lessons_filtered = [L for L in lessons if L.get("attendance_status") != "AbsentNotice"]
            
            if not lessons_filtered:
                continue
            
            # Calculer le total des heures
            total_hours = sum((L.get("duration_min") or 0) / 60 for L in lessons_filtered)
            
            # Trouver la date du premier cours
            dates = [L.get("date") for L in lessons_filtered if L.get("date")]
            first_date = min(dates) if dates else ""
            
            # Convertir la date
            date_iso = None
            if first_date:
                try:
                    dt = datetime.strptime(first_date, "%d.%m.%Y")
                    date_iso = dt.strftime("%Y-%m-%d")
                except:
                    pass
            
            # Créer la page dans la DB Paiements
            properties = {
                "Famille": {"title": [{"text": {"content": parent_name}}]},
                "Email parent": {"email": parent_email} if parent_email else {"rich_text": []},
                "Montant total dû": {"number": round(total_amount, 2)},
                "Heures": {"number": round(total_hours, 2)},
                "Payé": {"checkbox": False},
                "id paiements": {"number": next_id},
            }
            
            if date_iso:
                properties["Date cours factures"] = {"date": {"start": date_iso}}
            
            result = notion_request("POST", "pages", {
                "parent": {"database_id": DB_PAIEMENTS},
                "properties": properties
            })
            
            if result:
                added += 1
                next_id += 1
                existing_keys.add(key)
                
                # ===========================
                # CRÉER LES SOUS-PAGES PROFS
                # ===========================
                # Grouper les leçons par prof
                lessons_by_prof = defaultdict(list)
                for L in lessons_filtered:
                    teacher = L.get("teacher", "")
                    if teacher:
                        lessons_by_prof[teacher].append(L)
                
                for teacher_name, teacher_lessons in lessons_by_prof.items():
                    # Trouver/créer la page prof
                    prof_id = get_or_create_prof(teacher_name)
                    if not prof_id:
                        continue
                    
                    # Grouper par élève
                    lessons_by_student = defaultdict(list)
                    for L in teacher_lessons:
                        student = L.get("student", "")
                        if student:
                            lessons_by_student[student].append(L)
                    
                    for student_name, student_lessons in lessons_by_student.items():
                        # Trouver la date du cours
                        lesson_dates = [L.get("date") for L in student_lessons if L.get("date")]
                        if lesson_dates:
                            try:
                                dt = datetime.strptime(lesson_dates[0], "%d.%m.%Y")
                                date_cours_iso = dt.strftime("%Y-%m-%d")
                            except:
                                date_cours_iso = None
                        else:
                            date_cours_iso = None
                        
                        if not date_cours_iso:
                            continue
                        
                        # Trouver/créer la page date
                        date_id, date_title = get_or_create_date(prof_id, date_cours_iso)
                        if not date_id:
                            continue
                        
                        # Trouver/créer la page élève
                        student_id, current_title = get_or_create_student(date_id, student_name)
                        if not student_id:
                            continue
                        
                        # Préparer les données de paiement
                        payments = []
                        for L in student_lessons:
                            payments.append({
                                "date": L.get("date", ""),
                                "hours": (L.get("duration_min") or 0) / 60,
                                "amount": L.get("amount", 0),
                                "currency": "CHF",
                            })
                        
                        # Mettre à jour la page élève
                        if current_title is None:  # Page nouvellement créée
                            update_student_page(student_id, student_name, payments)
                            pages_created += 1
        
        # ===========================
        # ÉTAPE 5: Mettre à jour le dashboard
        # ===========================
        update(90, "📊 Mise à jour du dashboard...")
        
        # Compter les paiements
        all_rows = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", {})
        if all_rows:
            total_rows = len(all_rows.get("results", []))
            paid_rows = sum(1 for r in all_rows.get("results", []) if r["properties"].get("Payé", {}).get("checkbox", False))
            
            # Supprimer l'ancien dashboard
            for b in get_children(ROOT_PAGE):
                if b["type"] == "paragraph":
                    rt = b.get("paragraph", {}).get("rich_text", [])
                    if rt and "Bilan" in rt[0].get("plain_text", ""):
                        notion_request("DELETE", f"blocks/{b['id']}")
            
            # Créer le nouveau
            text = f"Bilan – paiements effectués : {paid_rows} / {total_rows} paiements totaux{' ✅' if paid_rows == total_rows else ''}"
            notion_request("PATCH", f"blocks/{ROOT_PAGE}/children", {
                "children": [{"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}, "annotations": {"bold": True}}]}}]
            })
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "added": added,
            "skipped": skipped,
            "pages_created": pages_created,
            "next_id": next_id
        }
        
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{str(e)}\n{traceback.format_exc()}"}


def run_update_notion_selective(secrets, data, invoice_folder_path, selected_family_ids, selected_teachers, callback=None):
    """
    Met à jour les lignes Notion pour certaines familles et certains profs.
    Utilise la même logique que update_notion_prof_pages pour mettre à jour les sous-pages.
    
    Args:
        secrets: Configuration YAML
        data: Données extraites de TutorBird
        invoice_folder_path: Chemin vers le dossier de factures
        selected_family_ids: Liste des family_id à mettre à jour
        selected_teachers: Liste des noms de profs à mettre à jour
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "rows_updated": int, "subpages_updated": int, ...}
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        ROOT_PAGE = secrets["notion"]["root_page_paiements"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        def notion_request(method, endpoint, json_data=None):
            time.sleep(REQUEST_DELAY)
            url = f"https://api.notion.com/v1/{endpoint}"
            
            if method == "GET":
                r = requests.get(url, headers=HEADERS, timeout=30)
            elif method == "POST":
                r = requests.post(url, headers=HEADERS, json=json_data, timeout=30)
            elif method == "PATCH":
                r = requests.patch(url, headers=HEADERS, json=json_data, timeout=30)
            elif method == "DELETE":
                r = requests.delete(url, headers=HEADERS, timeout=30)
            else:
                return None
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 2))
                time.sleep(retry)
                return notion_request(method, endpoint, json_data)
            
            if r.status_code in [200, 201]:
                return r.json() if r.text else {"ok": True}
            return None
        
        def get_children(block_id):
            results = []
            cursor = None
            while True:
                url = f"blocks/{block_id}/children?page_size=100"
                if cursor:
                    url += f"&start_cursor={cursor}"
                resp = notion_request("GET", url)
                if not resp:
                    break
                results.extend(resp.get("results", []))
                if not resp.get("has_more"):
                    break
                cursor = resp.get("next_cursor")
            return results
        
        # ===========================
        # CACHES pour les pages profs (comme dans update_notion_prof_pages)
        # ===========================
        PROF_CACHE = {}
        DATE_CACHE = {}
        STUDENT_CACHE = {}
        
        def load_profs():
            for b in get_children(ROOT_PAGE):
                if b["type"] == "child_page":
                    PROF_CACHE[b["child_page"]["title"].strip()] = b["id"]
        
        def get_or_create_prof(name):
            if name in PROF_CACHE:
                return PROF_CACHE[name]
            
            result = notion_request("POST", "pages", {
                "parent": {"page_id": ROOT_PAGE},
                "properties": {"title": [{"text": {"content": name}}]}
            })
            if result and "id" in result:
                PROF_CACHE[name] = result["id"]
                return result["id"]
            return None
        
        def load_dates_for_prof(prof_id):
            if any(k[0] == prof_id for k in DATE_CACHE):
                return
            for b in get_children(prof_id):
                if b["type"] == "child_page":
                    DATE_CACHE[(prof_id, b["child_page"]["title"].strip())] = b["id"]
        
        def get_or_create_date(prof_id, date_cours):
            title = format_date_title(date_cours)
            load_dates_for_prof(prof_id)
            key = (prof_id, title)
            if key in DATE_CACHE:
                return DATE_CACHE[key], title
            
            result = notion_request("POST", "pages", {
                "parent": {"page_id": prof_id},
                "properties": {"title": [{"text": {"content": title}}]}
            })
            if result and "id" in result:
                DATE_CACHE[key] = result["id"]
                return result["id"], title
            return None, title
        
        def load_students_for_date(date_id):
            if date_id in STUDENT_CACHE:
                return
            STUDENT_CACHE[date_id] = {}
            for b in get_children(date_id):
                if b["type"] == "child_page":
                    full = b["child_page"]["title"].strip()
                    name = full.split(" – ")[0].strip() if " – " in full else full
                    STUDENT_CACHE[date_id][normalize_name(name)] = {"id": b["id"], "title": full, "name": name}
        
        def get_or_create_student(date_id, name):
            load_students_for_date(date_id)
            norm = normalize_name(name)
            
            if norm in STUDENT_CACHE[date_id]:
                s = STUDENT_CACHE[date_id][norm]
                return s["id"], s["title"]
            
            for n, s in STUDENT_CACHE[date_id].items():
                if names_match(name, s["name"]):
                    return s["id"], s["title"]
            
            result = notion_request("POST", "pages", {
                "parent": {"page_id": date_id},
                "properties": {"title": [{"text": {"content": name}}]}
            })
            if result and "id" in result:
                STUDENT_CACHE[date_id][norm] = {"id": result["id"], "title": name, "name": name}
                return result["id"], None
            return None, None
        
        def update_student_page(student_id, name, payments, paid_count=0):
            """Met à jour la page élève avec le tableau des paiements."""
            # Supprimer les anciens tableaux
            for b in get_children(student_id):
                if b["type"] == "table":
                    notion_request("DELETE", f"blocks/{b['id']}")
            
            # Créer le tableau (même format que update_notion_prof_pages)
            rows = [{"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "Mois / Date"}}],
                [{"type": "text", "text": {"content": "Heures"}}],
                [{"type": "text", "text": {"content": "Montant"}}],
                [{"type": "text", "text": {"content": "Date paie"}}],
                [{"type": "text", "text": {"content": "Payé ?"}}],
                [{"type": "text", "text": {"content": "id"}}],
            ]}}]
            
            for p in payments:
                rows.append({"type": "table_row", "table_row": {"cells": [
                    [{"type": "text", "text": {"content": p.get("date", "")}}],
                    [{"type": "text", "text": {"content": p.get("heures", "")}}],
                    [{"type": "text", "text": {"content": str(p.get("real_paid", 0))}}],
                    [{"type": "text", "text": {"content": p.get("date_paiement", "")}}],
                    [{"type": "text", "text": {"content": "✅" if p.get("paid") else "☐"}}],
                    [{"type": "text", "text": {"content": str(p.get("id", ""))}}],
                ]}})
            
            notion_request("PATCH", f"blocks/{student_id}/children", {
                "children": [{"type": "table", "table": {"table_width": 6, "has_column_header": True, "children": rows}}]
            })
            
            # Update title
            total = len(payments)
            paid = paid_count
            title = f"{name} – Paie [{paid} / {total}]{' ✅' if paid == total else ''}"
            notion_request("PATCH", f"pages/{student_id}", {
                "properties": {"title": [{"text": {"content": title}}]}
            })
            return title
        
        def update_recap(date_id, payments):
            """Met à jour le récapitulatif d'une page date."""
            # Supprimer ancien récap
            for b in get_children(date_id):
                if b["type"] in ["divider", "table"]:
                    notion_request("DELETE", f"blocks/{b['id']}")
                elif b["type"] == "callout":
                    rt = b.get("callout", {}).get("rich_text", [])
                    if rt and "Récapitulatif" in rt[0].get("plain_text", ""):
                        notion_request("DELETE", f"blocks/{b['id']}")
            
            completed = [p for p in payments if p.get("paid") and p.get("real_paid", 0) > 0 and p.get("date_paiement")]
            if not completed:
                return 0
            
            total_amount = sum(p["real_paid"] for p in completed)
            rows = [{"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "👤 Élève"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": "⏱️ Heures"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": "💰 Montant"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": "📅 Date"}, "annotations": {"bold": True}}],
            ]}}]
            
            for p in completed:
                rows.append({"type": "table_row", "table_row": {"cells": [
                    [{"type": "text", "text": {"content": p.get("student", "")}}],
                    [{"type": "text", "text": {"content": p.get("heures", "")}}],
                    [{"type": "text", "text": {"content": f"{p['real_paid']:.2f} EUR"}}],
                    [{"type": "text", "text": {"content": p["date_paiement"]}}],
                ]}})
            
            rows.append({"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "TOTAL"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": f"{len(completed)} paie"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": f"{total_amount:.2f} EUR"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": ""}}],
            ]}})
            
            notion_request("PATCH", f"blocks/{date_id}/children", {
                "children": [
                    {"type": "divider", "divider": {}},
                    {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "📊 Récapitulatif"}}], "icon": {"emoji": "💵"}, "color": "green_background"}},
                    {"type": "table", "table": {"table_width": 4, "has_column_header": True, "children": rows}}
                ]
            })
            return len(completed)
        
        update(5, "📁 Analyse du dossier de factures...")
        
        # ===========================
        # ÉTAPE 1: Scanner les factures du dossier
        # ===========================
        invoices_found = []
        
        selected_teachers_norm = [normalize_for_match(t) for t in selected_teachers]
        
        # Récupérer les noms des familles sélectionnées
        selected_families_names = {}
        for fam_id in selected_family_ids:
            fam = data.get(fam_id, {})
            parent_name = fam.get("parent_name") or fam.get("family_name") or ""
            if parent_name:
                selected_families_names[fam_id] = parent_name
        
        # Scanner les sous-dossiers du dossier de factures
        if os.path.exists(invoice_folder_path):
            for folder_name in os.listdir(invoice_folder_path):
                folder_path = os.path.join(invoice_folder_path, folder_name)
                
                if os.path.isdir(folder_path):
                    folder_norm = normalize_for_match(folder_name)
                    
                    # Chercher si ce dossier correspond à une famille sélectionnée
                    matched_family_id = None
                    matched_family_name = None
                    
                    for fam_id, fam_name in selected_families_names.items():
                        fam_norm = normalize_for_match(fam_name)
                        score = SequenceMatcher(None, folder_norm, fam_norm).ratio()
                        if score > 0.7 or folder_norm == fam_norm:
                            matched_family_id = fam_id
                            matched_family_name = fam_name
                            break
                    
                    if matched_family_id:
                        # Scanner les PDFs dans ce dossier
                        for pdf_file in os.listdir(folder_path):
                            if pdf_file.lower().endswith(".pdf"):
                                # Extraire le nom du prof du fichier
                                # Format: Facture_2026-02-02_Prof_Name.pdf
                                parts = pdf_file.replace(".pdf", "").split("_")
                                if len(parts) >= 3:
                                    teacher_from_file = " ".join(parts[2:])
                                    teacher_norm = normalize_for_match(teacher_from_file)
                                    
                                    # Vérifier si ce prof est dans la sélection
                                    is_selected = False
                                    matched_teacher = None
                                    for sel_teacher, sel_norm in zip(selected_teachers, selected_teachers_norm):
                                        score = SequenceMatcher(None, teacher_norm, sel_norm).ratio()
                                        if score > 0.7:
                                            is_selected = True
                                            matched_teacher = sel_teacher
                                            break
                                    
                                    if is_selected:
                                        # Extraire la date du fichier
                                        try:
                                            date_part = parts[1]
                                            file_date = datetime.strptime(date_part, "%Y-%m-%d")
                                        except:
                                            file_date = datetime.min
                                        
                                        invoices_found.append({
                                            "family_id": matched_family_id,
                                            "family_name": matched_family_name,
                                            "teacher": matched_teacher,
                                            "file_date": file_date,
                                        })
        
        update(15, f"📄 {len(invoices_found)} facture(s) trouvée(s)")
        
        if not invoices_found:
            return {
                "success": True,
                "invoices_found": 0,
                "rows_updated": 0,
                "subpages_updated": 0,
                "not_found": [f"{name} (aucune facture)" for name in selected_families_names.values()]
            }
        
        # ===========================
        # ÉTAPE 2: Garder uniquement la facture la plus récente par famille/prof
        # ===========================
        latest_invoices = {}
        
        for inv in invoices_found:
            key = (inv["family_id"], inv["teacher"])
            if key not in latest_invoices or inv["file_date"] > latest_invoices[key]["file_date"]:
                latest_invoices[key] = inv
        
        update(20, f"📊 {len(latest_invoices)} facture(s) à traiter")
        
        # ===========================
        # ÉTAPE 3: Charger les pages profs
        # ===========================
        update(25, "📚 Chargement des pages profs...")
        load_profs()
        
        # ===========================
        # ÉTAPE 4: Récupérer les données de la DB Notion
        # ===========================
        update(30, "📥 Récupération des données Notion...")
        
        all_rows = []
        cursor = None
        
        while True:
            payload = {}
            if cursor:
                payload["start_cursor"] = cursor
            
            result = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", payload)
            if not result:
                break
            
            all_rows.extend(result.get("results", []))
            
            if not result.get("has_more"):
                break
            cursor = result.get("next_cursor")
        
        # Parser les paiements de la DB (même format que update_notion_prof_pages)
        payments_db = []
        for row in all_rows:
            p = row["properties"]
            try:
                pid = p.get("id paiements", {}).get("number")
                if not pid:
                    continue
                
                prof = p.get("Professeur", {}).get("rich_text", [])
                eleve = p.get("Élève", {}).get("rich_text", [])
                
                if not prof or not eleve:
                    continue
                
                payments_db.append({
                    "id": pid,
                    "page_id": row["id"],
                    "prof": prof[0]["plain_text"].strip(),
                    "student": eleve[0]["plain_text"].strip(),
                    "date": p.get("Mois / Date", {}).get("rich_text", [{}])[0].get("plain_text", "").strip() if p.get("Mois / Date", {}).get("rich_text") else "",
                    "heures": p.get("Heures", {}).get("rich_text", [{}])[0].get("plain_text", "").strip() if p.get("Heures", {}).get("rich_text") else "",
                    "paid": p.get("Payé ?", {}).get("checkbox", False),
                    "real_paid": p.get("Montant réel versé par Stripe", {}).get("number") or 0,
                    "date_paiement": p.get("Date des paiements", {}).get("date", {}).get("start", "") if p.get("Date des paiements", {}).get("date") else "",
                    "date_cours": p.get("Date cours factures", {}).get("date", {}).get("start", "") if p.get("Date cours factures", {}).get("date") else "",
                })
            except:
                continue
        
        update(40, f"📊 {len(payments_db)} lignes dans la DB")
        
        # ===========================
        # ÉTAPE 5: Calculer les montants depuis TutorBird et mettre à jour
        # ===========================
        update(45, "💰 Calcul des montants et mise à jour...")
        
        rows_updated = 0
        subpages_updated = 0
        details = []
        not_found = []
        dates_to_update_recap = set()
        
        # Créer un index par famille pour la DB Notion
        notion_family_index = {}
        for row in all_rows:
            props = row["properties"]
            famille = ""
            famille_prop = props.get("Famille", {})
            if famille_prop.get("title"):
                famille = famille_prop["title"][0]["plain_text"] if famille_prop["title"] else ""
            if famille:
                notion_family_index[normalize_for_match(famille)] = row
        
        # Grouper les factures par famille
        family_totals = defaultdict(lambda: {"amount": 0, "hours": 0, "teachers": []})
        
        for key, inv in latest_invoices.items():
            fam_id, teacher = key
            fam = data.get(fam_id, {})
            lessons = fam.get("lessons", [])
            
            # Filtrer les absences
            lessons_filtered = [L for L in lessons if L.get("attendance_status") != "AbsentNotice"]
            
            # Calculer le montant pour ce prof
            teacher_norm = normalize_for_match(teacher)
            teacher_total = 0
            teacher_hours = 0
            
            for L in lessons_filtered:
                if SequenceMatcher(None, normalize_for_match(L.get("teacher", "")), teacher_norm).ratio() > 0.7:
                    teacher_total += float(L.get("amount", 0) or 0)
                    teacher_hours += (L.get("duration_min") or 0) / 60
            
            if teacher_total > 0:
                family_totals[fam_id]["amount"] += teacher_total
                family_totals[fam_id]["hours"] += teacher_hours
                family_totals[fam_id]["family_name"] = inv["family_name"]
                family_totals[fam_id]["teachers"].append({
                    "teacher": teacher,
                    "amount": teacher_total,
                    "hours": teacher_hours,
                    "date_cours": inv["file_date"].strftime("%Y-%m-%d") if inv["file_date"] != datetime.min else None
                })
        
        total_families = len(family_totals)
        current = 0
        
        for fam_id, totals in family_totals.items():
            current += 1
            progress_val = int(45 + (current / total_families * 40))
            
            family_name = totals["family_name"]
            family_norm = normalize_for_match(family_name)
            
            update(progress_val, f"✏️ {family_name}...")
            
            # Trouver la ligne Notion de la famille
            row = notion_family_index.get(family_norm)
            
            if not row:
                for row_norm, row_data in notion_family_index.items():
                    if SequenceMatcher(None, family_norm, row_norm).ratio() > 0.8:
                        row = row_data
                        break
            
            if row:
                page_id = row["id"]
                
                # Mettre à jour la ligne famille
                properties = {
                    "Montant total dû": {"number": round(totals["amount"], 2)},
                    "Heures": {"number": round(totals["hours"], 2)},
                }
                
                result = notion_request("PATCH", f"pages/{page_id}", {"properties": properties})
                
                if result:
                    rows_updated += 1
                    
                    # ===========================
                    # METTRE À JOUR LES SOUS-PAGES PROFS
                    # ===========================
                    for teacher_info in totals["teachers"]:
                        teacher = teacher_info["teacher"]
                        date_cours = teacher_info.get("date_cours")
                        
                        if not date_cours:
                            continue
                        
                        # Trouver/créer la page prof
                        prof_id = get_or_create_prof(teacher)
                        if not prof_id:
                            continue
                        
                        # Trouver/créer la page date
                        date_id, date_title = get_or_create_date(prof_id, date_cours)
                        if not date_id:
                            continue
                        
                        # Trouver les élèves concernés dans la famille
                        fam = data.get(fam_id, {})
                        lessons = fam.get("lessons", [])
                        lessons_filtered = [L for L in lessons if L.get("attendance_status") != "AbsentNotice"]
                        
                        # Grouper par élève pour ce prof
                        teacher_norm = normalize_for_match(teacher)
                        students_lessons = defaultdict(list)
                        
                        for L in lessons_filtered:
                            if SequenceMatcher(None, normalize_for_match(L.get("teacher", "")), teacher_norm).ratio() > 0.7:
                                student = L.get("student", "")
                                if student:
                                    students_lessons[student].append(L)
                        
                        for student_name, student_lessons in students_lessons.items():
                            # Trouver/créer la page élève
                            student_id, current_title = get_or_create_student(date_id, student_name)
                            if not student_id:
                                continue
                            
                            # Chercher les paiements existants pour cet élève dans la DB
                            student_payments = []
                            for pdb in payments_db:
                                if pdb["prof"].lower() == teacher.lower() and names_match(pdb["student"], student_name):
                                    student_payments.append(pdb)
                            
                            # Si pas de paiements existants, créer depuis les leçons
                            if not student_payments:
                                for L in student_lessons:
                                    student_payments.append({
                                        "id": "",
                                        "date": L.get("date", ""),
                                        "heures": f"{(L.get('duration_min') or 0) / 60:.1f}h",
                                        "real_paid": 0,
                                        "date_paiement": "",
                                        "paid": False,
                                        "student": student_name,
                                    })
                            
                            # Mettre à jour la page élève
                            paid_count = sum(1 for p in student_payments if p.get("paid"))
                            update_student_page(student_id, student_name, student_payments, paid_count)
                            subpages_updated += 1
                            
                            # Marquer la date pour mise à jour du récap
                            dates_to_update_recap.add((prof_id, date_id, teacher, date_cours))
                        
                        details.append({
                            "family": family_name,
                            "teacher": teacher,
                            "amount": teacher_info["amount"],
                            "currency": "CHF"
                        })
            else:
                not_found.append(f"{family_name} (non trouvé dans Notion)")
        
        # ===========================
        # ÉTAPE 6: Mettre à jour les récaps
        # ===========================
        if dates_to_update_recap:
            update(90, f"📊 Mise à jour de {len(dates_to_update_recap)} récap(s)...")
            
            for prof_id, date_id, teacher, date_cours in dates_to_update_recap:
                # Récupérer tous les paiements pour cette date/prof
                date_payments = [p for p in payments_db if p["prof"].lower() == teacher.lower() and p.get("date_cours") == date_cours]
                if date_payments:
                    update_recap(date_id, date_payments)
        
        # ===========================
        # ÉTAPE 7: Mettre à jour le dashboard
        # ===========================
        update(95, "📊 Mise à jour du dashboard...")
        
        total_rows = len(all_rows)
        paid_rows = sum(1 for r in all_rows if r["properties"].get("Payé ?", {}).get("checkbox", False))
        
        for b in get_children(ROOT_PAGE):
            if b["type"] == "paragraph":
                rt = b.get("paragraph", {}).get("rich_text", [])
                if rt and "Bilan" in rt[0].get("plain_text", ""):
                    notion_request("DELETE", f"blocks/{b['id']}")
        
        text = f"Bilan – paiements effectués : {paid_rows} / {total_rows} paiements totaux{' ✅' if paid_rows == total_rows else ''}"
        notion_request("PATCH", f"blocks/{ROOT_PAGE}/children", {
            "children": [{"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}, "annotations": {"bold": True}}]}}]
        })
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "invoices_found": len(invoices_found),
            "rows_updated": rows_updated,
            "subpages_updated": subpages_updated,
            "details": details,
            "not_found": not_found
        }
        
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{str(e)}\n{traceback.format_exc()}"}


def run_scan_and_compare(secrets, data, invoice_folder_path, callback=None):
    """
    Compare les lignes de payment_links_output.json avec Notion pour trouver les lignes manquantes.
    
    Args:
        secrets: Configuration YAML
        data: Données extraites de TutorBird (utilisé pour le chemin du fichier)
        invoice_folder_path: Chemin vers le dossier de factures
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {
            "success": bool,
            "invoices_scanned": int,
            "notion_rows": int,
            "missing": list of {family_name, teacher, amount, ...},
            "already_exists": list,
            "error": str
        }
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        def notion_request(method, endpoint, json_data=None):
            time.sleep(REQUEST_DELAY)
            url = f"https://api.notion.com/v1/{endpoint}"
            
            if method == "POST":
                r = requests.post(url, headers=HEADERS, json=json_data, timeout=30)
            else:
                return None
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 2))
                time.sleep(retry)
                return notion_request(method, endpoint, json_data)
            
            if r.status_code in [200, 201]:
                return r.json() if r.text else {"ok": True}
            return None
        
        update(5, "📁 Chargement de payment_links_output.json...")
        
        # ===========================
        # ÉTAPE 1: Charger payment_links_output.json
        # ===========================
        payment_links_data = []
        
        # invoice_folder_path = .../professor_plus_V9/Factures/2026/Février 2026 - 02-02-2026
        # On doit aller vers .../professor_plus_V9/data/payment_links_output.json
        
        # Essayer plusieurs chemins possibles
        possible_paths = []
        
        # Remonter de 1, 2, 3, 4 niveaux et chercher data/payment_links_output.json
        current = invoice_folder_path
        for _ in range(5):
            current = os.path.dirname(current)
            possible_paths.append(os.path.join(current, "data", "payment_links_output.json"))
        
        # Aussi chercher directement à côté du dossier Factures
        possible_paths.append(os.path.join(os.path.dirname(invoice_folder_path), "data", "payment_links_output.json"))
        
        found_path = None
        for path in possible_paths:
            if os.path.exists(path):
                found_path = path
                break
        
        if found_path:
            try:
                with open(found_path, "r", encoding="utf-8") as f:
                    payment_links_data = json.load(f)
            except Exception as e:
                return {"success": False, "error": f"Erreur lecture {found_path}: {str(e)}"}
        
        if not payment_links_data:
            return {"success": False, "error": f"Fichier payment_links_output.json non trouvé. Chemins testés: {possible_paths[:3]}"}
        
        update(20, f"📄 {len(payment_links_data)} entrée(s) trouvée(s)")
        
        # ===========================
        # ÉTAPE 2: Préparer les données depuis payment_links_output.json
        # ===========================
        invoices_with_amounts = []
        
        for item in payment_links_data:
            # Extraire le nom des élèves depuis students_label
            # Format: "Soutien scolaire | Blanchoud Chelsy & Kristy"
            students_label = item.get("students_label", "")
            if " | " in students_label:
                students_formatted = students_label.split(" | ")[1].strip()
            else:
                students_formatted = students_label
            
            # Extraire l'année et le mois/date depuis invoice_date
            invoice_date = item.get("invoice_date", "")
            year = ""
            mois_date = ""
            if invoice_date:
                try:
                    dt = datetime.strptime(invoice_date, "%Y-%m-%d")
                    year = str(dt.year)
                    months_short = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
                    mois_date = f"{dt.day:02d} {months_short[dt.month-1]} {dt.year}"
                except:
                    pass
            
            # Calculer les heures depuis les données TutorBird si disponible
            hours = 0
            family_id = item.get("family_id", "")
            teacher = item.get("teacher", "")
            
            if family_id and family_id in data:
                fam = data[family_id]
                lessons = fam.get("lessons", [])
                for L in lessons:
                    if L.get("attendance_status") != "AbsentNotice":
                        lesson_teacher_norm = normalize_for_match(L.get("teacher", ""))
                        if SequenceMatcher(None, lesson_teacher_norm, normalize_for_match(teacher)).ratio() > 0.7:
                            hours += (L.get("duration_min") or 0) / 60
            
            invoices_with_amounts.append({
                "family_id": family_id,
                "family_name": item.get("parent", ""),
                "teacher": teacher,
                "amount": round(float(item.get("amount", 0)), 2),
                "hours": round(hours, 2),
                "students_formatted": students_formatted,
                "date_cours": invoice_date,
                "currency": (item.get("currency") or "CHF").upper(),
                "year": year,
                "mois_date": mois_date,
                "stripe_link": item.get("payment_link", ""),
            })
        
        update(50, f"📊 {len(invoices_with_amounts)} facture(s) à vérifier")
        
        # ===========================
        # ÉTAPE 3: Récupérer les lignes Notion existantes
        # ===========================
        update(60, "📥 Récupération des lignes Notion...")
        
        all_notion_rows = []
        cursor = None
        
        while True:
            payload = {}
            if cursor:
                payload["start_cursor"] = cursor
            
            result = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", payload)
            if not result:
                break
            
            all_notion_rows.extend(result.get("results", []))
            
            if not result.get("has_more"):
                break
            cursor = result.get("next_cursor")
        
        # Parser les lignes Notion
        notion_rows = []
        for row in all_notion_rows:
            p = row["properties"]
            
            famille = ""
            famille_prop = p.get("Famille", {})
            if famille_prop.get("title"):
                famille = famille_prop["title"][0]["plain_text"] if famille_prop["title"] else ""
            
            prof = ""
            prof_prop = p.get("Professeur", {}).get("rich_text", [])
            if prof_prop:
                prof = prof_prop[0]["plain_text"].strip()
            
            montant = p.get("Montant dû Famille/Prof", {}).get("number", 0) or 0
            
            if famille and montant:
                notion_rows.append({
                    "famille": famille,
                    "famille_norm": normalize_for_match(famille),
                    "prof": prof,
                    "prof_norm": normalize_for_match(prof),
                    "montant": round(montant, 2),
                })
        
        update(80, f"📋 {len(notion_rows)} lignes Notion trouvées")
        
        # ===========================
        # ÉTAPE 4: Comparer et trouver les manquantes
        # ===========================
        update(90, "🔍 Comparaison...")
        
        missing = []
        already_exists = []
        
        for inv in invoices_with_amounts:
            inv_family_norm = normalize_for_match(inv["family_name"])
            inv_teacher_norm = normalize_for_match(inv["teacher"])
            inv_amount = inv["amount"]
            
            found = False
            
            for nr in notion_rows:
                # Matcher par famille + prof + montant (avec tolérance)
                family_match = SequenceMatcher(None, inv_family_norm, nr["famille_norm"]).ratio() > 0.7
                prof_match = SequenceMatcher(None, inv_teacher_norm, nr["prof_norm"]).ratio() > 0.7
                amount_match = abs(nr["montant"] - inv_amount) < 0.01
                
                if family_match and prof_match and amount_match:
                    found = True
                    already_exists.append({
                        "family_name": inv["family_name"],
                        "teacher": inv["teacher"],
                        "amount": inv_amount,
                    })
                    break
            
            if not found:
                missing.append(inv)
        
        update(100, "✅ Comparaison terminée")
        
        return {
            "success": True,
            "invoices_scanned": len(invoices_with_amounts),
            "notion_rows": len(notion_rows),
            "missing": missing,
            "already_exists": already_exists,
        }
        
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{str(e)}\n{traceback.format_exc()}"}


def run_add_missing_rows(secrets, data, missing_rows, callback=None):
    """
    Ajoute les lignes manquantes dans la DB Notion (sans créer les sous-pages profs).
    
    Args:
        secrets: Configuration YAML
        data: Données extraites de TutorBird
        missing_rows: Liste des lignes manquantes (retournées par run_scan_and_compare)
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "added": int, "errors": list}
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        # ===========================
        # ÉTAPE 1: Obtenir le prochain ID
        # ===========================
        update(5, "📊 Récupération du dernier ID...")
        
        metadata_db = secrets["notion"].get("metadata_database_id")
        next_id = 1
        
        if metadata_db:
            time.sleep(REQUEST_DELAY)
            r = requests.post(
                f"https://api.notion.com/v1/databases/{metadata_db}/query",
                headers=HEADERS,
                json={},
                timeout=30
            )
            if r.status_code == 200:
                meta = r.json()
                for row in meta.get("results", []):
                    props = row["properties"]
                    cle = props.get("Clé", {}).get("title", [])
                    if cle and cle[0].get("plain_text", "").strip() == "last_payment_id":
                        next_id = props.get("Valeur", {}).get("number", 0) + 1
                        break
        
        # ===========================
        # ÉTAPE 2: Ajouter les lignes manquantes
        # ===========================
        added = 0
        errors = []
        total = len(missing_rows)
        
        for i, row in enumerate(missing_rows):
            progress_val = int(10 + (i / total * 85))
            update(progress_val, f"➕ {row['family_name']} / {row['teacher']}")
            
            fam_id = row.get("family_id")
            
            # Si family_id pas trouvé ou pas dans data, chercher par nom
            if not fam_id or fam_id not in data:
                family_name_norm = normalize_for_match(row["family_name"])
                for fid, fam_data in data.items():
                    fam_name = fam_data.get("parent_name") or fam_data.get("family_name") or ""
                    if SequenceMatcher(None, normalize_for_match(fam_name), family_name_norm).ratio() > 0.7:
                        fam_id = fid
                        break
            
            # Utiliser le nom d'élève formaté (Nom, Prénom1 & Prénom2)
            eleve_formatted = row.get("students_formatted", "") or ", ".join(row.get("students", []))
            
            # Créer la ligne dans la DB Paiements avec TOUTES les colonnes
            properties = {
                "Famille": {"title": [{"text": {"content": row["family_name"]}}]},
                "Professeur": {"rich_text": [{"text": {"content": row["teacher"]}}]},
                "Élève": {"rich_text": [{"text": {"content": eleve_formatted}}]},
                "Montant dû Famille/Prof": {"number": row["amount"]},
                "Payé ?": {"checkbox": False},
                "id paiements": {"number": next_id},
            }
            
            # Année (number)
            if row.get("year"):
                try:
                    properties["Année"] = {"number": int(row["year"])}
                except:
                    pass
            
            # Mois / Date (rich_text)
            if row.get("mois_date"):
                properties["Mois / Date"] = {"rich_text": [{"text": {"content": row["mois_date"]}}]}
            
            # Devise (rich_text)
            if row.get("currency"):
                properties["Devise"] = {"rich_text": [{"text": {"content": row["currency"]}}]}
            
            # Heures (rich_text) - format "5h" sans décimale si entier
            if row.get("hours"):
                hours = row["hours"]
                if hours == int(hours):
                    hours_str = f"{int(hours)}h"
                else:
                    hours_str = f"{hours:.1f}h".replace(".0h", "h")
                properties["Heures"] = {"rich_text": [{"text": {"content": hours_str}}]}
            
            # Lien payment link Stripe (url)
            if row.get("stripe_link"):
                properties["Lien payment link Stripe"] = {"url": row["stripe_link"]}
            
            # Date cours factures (date)
            if row.get("date_cours"):
                properties["Date cours factures"] = {"date": {"start": row["date_cours"]}}
            
            # Ajouter la ligne
            time.sleep(REQUEST_DELAY)
            try:
                r = requests.post(
                    f"https://api.notion.com/v1/pages",
                    headers=HEADERS,
                    json={
                        "parent": {"database_id": DB_PAIEMENTS},
                        "properties": properties
                    },
                    timeout=30
                )
                
                if r.status_code in [200, 201]:
                    added += 1
                    next_id += 1
                else:
                    errors.append(f"{row['family_name']}: {r.status_code} - {r.text[:200]}")
            except Exception as e:
                errors.append(f"{row['family_name']}: {str(e)}")
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "added": added,
            "errors": errors,
        }
        
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{str(e)}\n{traceback.format_exc()}"}