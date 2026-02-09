"""
📚 Update Notion Prof Pages
Met à jour les pages des professeurs dans Notion :
- Tableaux élèves avec détails des paiements
- Récapitulatifs par date
- Dashboard global

Basé sur update_notion_prof_pages_incremental_O2.py qui fonctionne.
Adapté pour être appelé depuis l'interface Streamlit.
"""

import time
import requests
from datetime import datetime
from collections import defaultdict

REQUEST_DELAY = 0.15

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def normalize_name(n):
    if not n:
        return ""
    return " ".join(n.lower().strip().replace(",", " ").replace("&", " ").split())


def names_match(n1, n2):
    w1, w2 = set(normalize_name(n1).split()), set(normalize_name(n2).split())
    if not w1 or not w2:
        return False
    return w1 == w2 or len(w1 & w2) >= 2 or (len(w1) == 2 and w1.issubset(w2)) or (len(w2) == 2 and w2.issubset(w1))


def format_date_title(date_str):
    if not date_str:
        return "Date inconnue"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_FR[dt.month - 1]} {dt.year}"
    except:
        return date_str


def run_update_notion_prof_pages(secrets, callback=None, force=False, latest_only=False):
    """
    Met à jour les pages des professeurs dans Notion.
    
    Args:
        secrets: Configuration YAML
        callback: Fonction callback(progress, message)
        force: Forcer la mise à jour même si pas de changement
        latest_only: Uniquement la date la plus récente par prof
    
    Returns:
        dict avec updated, skipped, recaps_updated, etc.
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        ROOT_PAGE = secrets["notion"]["root_page_paiements"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        def safe_request(method, url, json_data=None):
            for attempt in range(3):
                try:
                    time.sleep(REQUEST_DELAY)
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
                        time.sleep(int(r.headers.get("Retry-After", 2)))
                        continue
                    
                    if r.status_code in [200, 201]:
                        return r.json() if r.text else {"status": "ok"}
                except:
                    time.sleep(1)
            return None
        
        def notion_query_database(db_id):
            results = []
            cursor = None
            while True:
                payload = {"start_cursor": cursor} if cursor else {}
                data = safe_request("POST", f"https://api.notion.com/v1/databases/{db_id}/query", payload)
                if not data:
                    break
                results.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
            return results
        
        def notion_get_children(block_id):
            results = []
            cursor = None
            while True:
                url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
                if cursor:
                    url += f"&start_cursor={cursor}"
                data = safe_request("GET", url)
                if not data:
                    break
                results.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
            return results
        
        # ===========================
        # ÉTAPE 1: Charger les paiements
        # ===========================
        update(5, "📥 Chargement des paiements...")
        
        rows = notion_query_database(DB_PAIEMENTS)
        payments = []
        
        for r in rows:
            p = r["properties"]
            try:
                pid = p.get("id paiements", {}).get("number")
                if not pid:
                    continue
                
                prof = p.get("Professeur", {}).get("rich_text", [])
                eleve = p.get("Élève", {}).get("rich_text", [])
                
                if not prof or not eleve:
                    continue
                
                payments.append({
                    "id": pid,
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
        
        payments = sorted(payments, key=lambda x: x["id"])
        update(15, f"📊 {len(payments)} paiements chargés")
        
        # ===========================
        # ÉTAPE 2: Grouper par prof/date/élève
        # ===========================
        grouped = defaultdict(list)
        canonical = {}
        by_prof_date = defaultdict(list)
        
        for p in payments:
            dc = p.get("date_cours") or "unknown"
            norm = normalize_name(p["student"])
            key = (p["prof"], dc, norm)
            grouped[key].append(p)
            if key not in canonical:
                canonical[key] = p["student"]
            by_prof_date[(p["prof"], dc)].append(p)
        
        # Filtrer à la date la plus récente si demandé
        if latest_only:
            latest_dates = {}
            for prof, dc in by_prof_date.keys():
                if prof not in latest_dates or dc > latest_dates[prof]:
                    latest_dates[prof] = dc
            
            grouped = {k: v for k, v in grouped.items() if k[1] == latest_dates.get(k[0])}
            by_prof_date = {k: v for k, v in by_prof_date.items() if k[1] == latest_dates.get(k[0])}
        
        update(20, f"📚 {len(grouped)} combinaisons prof/date/élève")
        
        # ===========================
        # ÉTAPE 3: Charger les caches
        # ===========================
        update(25, "📂 Chargement de la structure Notion...")
        
        PROF_CACHE = {}
        DATE_CACHE = {}
        STUDENT_CACHE = {}
        
        # Charger les pages profs
        for b in notion_get_children(ROOT_PAGE):
            if b["type"] == "child_page":
                PROF_CACHE[b["child_page"]["title"].strip()] = b["id"]
        
        def load_dates_for_prof(prof_id):
            if any(k[0] == prof_id for k in DATE_CACHE):
                return
            for b in notion_get_children(prof_id):
                if b["type"] == "child_page":
                    DATE_CACHE[(prof_id, b["child_page"]["title"].strip())] = b["id"]
        
        def load_students_for_date(date_id):
            if date_id in STUDENT_CACHE:
                return
            STUDENT_CACHE[date_id] = {}
            for b in notion_get_children(date_id):
                if b["type"] == "child_page":
                    full = b["child_page"]["title"].strip()
                    name = full.split(" – ")[0].strip() if " – " in full else full
                    STUDENT_CACHE[date_id][normalize_name(name)] = {"id": b["id"], "title": full, "name": name}
        
        def get_or_create_prof(name):
            if name in PROF_CACHE:
                return PROF_CACHE[name]
            data = safe_request("POST", "https://api.notion.com/v1/pages", {
                "parent": {"page_id": ROOT_PAGE},
                "properties": {"title": [{"text": {"content": name}}]}
            })
            if data and "id" in data:
                PROF_CACHE[name] = data["id"]
                return data["id"]
            return None
        
        def get_or_create_date(prof_id, date_cours):
            title = format_date_title(date_cours)
            load_dates_for_prof(prof_id)
            key = (prof_id, title)
            if key in DATE_CACHE:
                return DATE_CACHE[key], title
            data = safe_request("POST", "https://api.notion.com/v1/pages", {
                "parent": {"page_id": prof_id},
                "properties": {"title": [{"text": {"content": title}}]}
            })
            if data and "id" in data:
                DATE_CACHE[key] = data["id"]
                return data["id"], title
            return None, title
        
        def get_or_create_student(date_id, student_name):
            load_students_for_date(date_id)
            norm = normalize_name(student_name)
            
            # Exact match
            if norm in STUDENT_CACHE[date_id]:
                s = STUDENT_CACHE[date_id][norm]
                return s["id"], s["title"]
            
            # Fuzzy match
            for n, s in STUDENT_CACHE[date_id].items():
                if names_match(student_name, s["name"]):
                    return s["id"], s["title"]
            
            # Create
            data = safe_request("POST", "https://api.notion.com/v1/pages", {
                "parent": {"page_id": date_id},
                "properties": {"title": [{"text": {"content": student_name}}]}
            })
            if data and "id" in data:
                STUDENT_CACHE[date_id][norm] = {"id": data["id"], "title": student_name, "name": student_name}
                return data["id"], None
            return None, None
        
        def needs_update(current_title, name, plist):
            if not current_title:
                return True
            total = len(plist)
            paid = sum(1 for p in plist if p["paid"])
            expected = f"{name} – Paie [{paid} / {total}]{' ✅' if paid == total else ''}"
            return current_title != expected
        
        def update_student(student_id, name, plist):
            # Delete old tables
            for b in notion_get_children(student_id):
                if b["type"] == "table":
                    safe_request("DELETE", f"https://api.notion.com/v1/blocks/{b['id']}")
            
            # Create table
            rows_data = [{"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "Mois / Date"}}],
                [{"type": "text", "text": {"content": "Heures"}}],
                [{"type": "text", "text": {"content": "Montant"}}],
                [{"type": "text", "text": {"content": "Date paie"}}],
                [{"type": "text", "text": {"content": "Payé ?"}}],
                [{"type": "text", "text": {"content": "id"}}],
            ]}}]
            
            for p in plist:
                rows_data.append({"type": "table_row", "table_row": {"cells": [
                    [{"type": "text", "text": {"content": p["date"]}}],
                    [{"type": "text", "text": {"content": p.get("heures", "")}}],
                    [{"type": "text", "text": {"content": str(p["real_paid"])}}],
                    [{"type": "text", "text": {"content": p.get("date_paiement", "")}}],
                    [{"type": "text", "text": {"content": "✅" if p["paid"] else "☐"}}],
                    [{"type": "text", "text": {"content": str(p["id"])}}],
                ]}})
            
            safe_request("PATCH", f"https://api.notion.com/v1/blocks/{student_id}/children", {
                "children": [{"type": "table", "table": {"table_width": 6, "has_column_header": True, "children": rows_data}}]
            })
            
            # Update title
            total = len(plist)
            paid = sum(1 for p in plist if p["paid"])
            title = f"{name} – Paie [{paid} / {total}]{' ✅' if paid == total else ''}"
            safe_request("PATCH", f"https://api.notion.com/v1/pages/{student_id}", {
                "properties": {"title": [{"text": {"content": title}}]}
            })
            return title
        
        def update_recap(date_id, plist):
            # Delete old recap
            for b in notion_get_children(date_id):
                if b["type"] in ["divider", "table"]:
                    safe_request("DELETE", f"https://api.notion.com/v1/blocks/{b['id']}")
                elif b["type"] == "callout":
                    rt = b.get("callout", {}).get("rich_text", [])
                    if rt and "Récapitulatif" in rt[0].get("plain_text", ""):
                        safe_request("DELETE", f"https://api.notion.com/v1/blocks/{b['id']}")
            
            completed = [p for p in plist if p["paid"] and p["real_paid"] > 0 and p.get("date_paiement")]
            if not completed:
                return 0
            
            total_amount = sum(p["real_paid"] for p in completed)
            rows_data = [{"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "👤 Élève"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": "⏱️ Heures"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": "💰 Montant"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": "📅 Date"}, "annotations": {"bold": True}}],
            ]}}]
            
            for p in completed:
                rows_data.append({"type": "table_row", "table_row": {"cells": [
                    [{"type": "text", "text": {"content": p["student"]}}],
                    [{"type": "text", "text": {"content": p.get("heures", "")}}],
                    [{"type": "text", "text": {"content": f"{p['real_paid']:.2f} EUR"}}],
                    [{"type": "text", "text": {"content": p["date_paiement"]}}],
                ]}})
            
            rows_data.append({"type": "table_row", "table_row": {"cells": [
                [{"type": "text", "text": {"content": "TOTAL"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": f"{len(completed)} paie"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": f"{total_amount:.2f} EUR"}, "annotations": {"bold": True}}],
                [{"type": "text", "text": {"content": ""}}],
            ]}})
            
            safe_request("PATCH", f"https://api.notion.com/v1/blocks/{date_id}/children", {
                "children": [
                    {"type": "divider", "divider": {}},
                    {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "📊 Récapitulatif"}}], "icon": {"emoji": "💵"}, "color": "green_background"}},
                    {"type": "table", "table": {"table_width": 4, "has_column_header": True, "children": rows_data}}
                ]
            })
            return len(completed)
        
        # ===========================
        # ÉTAPE 4: Traiter les combinaisons
        # ===========================
        updated = 0
        skipped = 0
        dates_updated = set()
        
        total_items = len(grouped)
        current = 0
        
        for (prof, dc, norm), plist in grouped.items():
            current += 1
            progress = int(30 + (current / total_items * 50))
            
            student = canonical[(prof, dc, norm)]
            
            prof_id = get_or_create_prof(prof)
            if not prof_id:
                continue
            
            date_id, date_title = get_or_create_date(prof_id, dc)
            if not date_id:
                continue
            
            student_id, current_title = get_or_create_student(date_id, student)
            if not student_id:
                continue
            
            if not force and not needs_update(current_title, student, plist):
                skipped += 1
                continue
            
            update(progress, f"📝 {prof} → {student}")
            update_student(student_id, student, plist)
            updated += 1
            dates_updated.add((prof, dc, date_id))
        
        # ===========================
        # ÉTAPE 5: Vérifier et mettre à jour les récaps
        # ===========================
        update(85, "📊 Vérification des récapitulatifs...")
        
        recaps_to_fix = set()
        
        for (prof, dc), plist in by_prof_date.items():
            expected = len([p for p in plist if p["paid"] and p["real_paid"] > 0 and p.get("date_paiement")])
            if expected == 0:
                continue
            
            prof_id = PROF_CACHE.get(prof)
            date_id = DATE_CACHE.get((prof_id, format_date_title(dc))) if prof_id else None
            if not date_id:
                continue
            
            if (prof, dc, date_id) in dates_updated:
                continue
            
            # Count current recap lines
            current_count = 0
            found_callout = False
            for b in notion_get_children(date_id):
                if b["type"] == "callout":
                    rt = b.get("callout", {}).get("rich_text", [])
                    if rt and "Récapitulatif" in rt[0].get("plain_text", ""):
                        found_callout = True
                elif b["type"] == "table" and found_callout:
                    current_count = max(0, len(notion_get_children(b["id"])) - 2)
                    break
            
            if current_count != expected:
                recaps_to_fix.add((prof, dc, date_id))
        
        # Mettre à jour les récaps
        all_recaps = dates_updated | recaps_to_fix
        recaps_updated = 0
        
        if all_recaps:
            update(90, f"📊 Mise à jour de {len(all_recaps)} récap(s)...")
            for prof, dc, date_id in all_recaps:
                update_recap(date_id, by_prof_date[(prof, dc)])
                recaps_updated += 1
        
        # ===========================
        # ÉTAPE 6: Dashboard
        # ===========================
        update(95, "📊 Mise à jour du dashboard...")
        
        total_rows = len(rows)
        paid_rows = sum(1 for r in rows if r["properties"].get("Payé ?", {}).get("checkbox", False))
        
        text = f"Bilan – paiements effectués : {paid_rows} / {total_rows} paiements totaux{' ✅' if paid_rows == total_rows else ''}"
        
        for b in notion_get_children(ROOT_PAGE):
            if b["type"] == "paragraph":
                rt = b.get("paragraph", {}).get("rich_text", [])
                if rt and "Bilan" in rt[0].get("plain_text", ""):
                    safe_request("DELETE", f"https://api.notion.com/v1/blocks/{b['id']}")
        
        safe_request("PATCH", f"https://api.notion.com/v1/blocks/{ROOT_PAGE}/children", {
            "children": [{"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}, "annotations": {"bold": True}}]}}]
        })
        
        update(100, "✅ Pages profs mises à jour !")
        
        return {
            "success": True,
            "updated": updated,
            "skipped": skipped,
            "recaps_updated": recaps_updated,
            "dashboard": text,
        }
        
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{str(e)}\n{traceback.format_exc()}"}