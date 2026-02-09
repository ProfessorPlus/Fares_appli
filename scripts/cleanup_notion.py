"""
🧹 Cleanup Notion
Nettoie les doublons ET supprime les anciennes lignes Notion
"""

import time
import requests
from collections import defaultdict
from datetime import datetime


MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


def normalize_name(n):
    """Normalise un nom pour comparaison."""
    if not n:
        return ""
    n = n.lower().strip()
    n = n.replace(",", " ")
    n = n.replace("&", " ")
    n = " ".join(n.split())
    return n


def format_date_title(date_str):
    """Convertit 2026-01-03 en '3 Janvier 2026'."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {MONTHS_FR[dt.month - 1]} {dt.year}"
    except:
        return None


def parse_date_title(title):
    """Convertit '3 Janvier 2026' en datetime."""
    if not title:
        return None
    try:
        parts = title.strip().split()
        if len(parts) != 3:
            return None
        day = int(parts[0])
        month_name = parts[1]
        year = int(parts[2])
        month = MONTHS_FR.index(month_name) + 1
        return datetime(year, month, day)
    except:
        return None


def run_scan_notion_dates(secrets, callback=None):
    """
    Scanne Notion pour lister toutes les dates de factures présentes.
    
    Returns:
        dict: {"success": bool, "dates": list, "count": int, "latest_date": str, "error": str}
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
            time.sleep(0.35)
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
                return r.json()
            return None
        
        update(10, "📥 Chargement des lignes Notion...")
        
        # Récupérer toutes les lignes
        all_rows = []
        cursor = None
        
        while True:
            payload = {}
            if cursor:
                payload["start_cursor"] = cursor
            
            data = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", payload)
            if not data:
                break
            
            all_rows.extend(data.get("results", []))
            
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        
        update(50, f"📊 {len(all_rows)} lignes trouvées")
        
        # Extraire les dates uniques
        dates_set = set()
        
        for row in all_rows:
            props = row["properties"]
            
            # Date cours factures
            date_cours = None
            if props.get("Date cours factures", {}).get("date"):
                date_cours = props["Date cours factures"]["date"].get("start")
            
            if date_cours:
                dates_set.add(date_cours)
        
        # Trier les dates
        dates_list = sorted(list(dates_set), reverse=True)
        
        # Trouver la plus récente
        latest_date = dates_list[0] if dates_list else None
        
        # Convertir en format lisible
        dates_readable = []
        for d in dates_list:
            dt = datetime.strptime(d, "%Y-%m-%d")
            readable = f"{dt.day} {MONTHS_FR[dt.month - 1]} {dt.year}"
            dates_readable.append({
                "iso": d,
                "readable": readable,
                "datetime": dt
            })
        
        update(100, "✅ Scan terminé")
        
        return {
            "success": True,
            "dates": dates_readable,
            "count": len(dates_readable),
            "total_rows": len(all_rows),
            "latest_date": latest_date,
            "latest_readable": format_date_title(latest_date) if latest_date else None
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_delete_old_rows(secrets, keep_from_date, dry_run=True, callback=None):
    """
    Supprime les lignes Notion antérieures à une date donnée.
    
    Args:
        secrets: Configuration YAML
        keep_from_date: Date ISO (YYYY-MM-DD) à partir de laquelle garder les lignes
        dry_run: Si True, ne supprime pas vraiment
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "deleted": int, "kept": int, "error": str}
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
            time.sleep(0.35)
            url = f"https://api.notion.com/v1/{endpoint}"
            
            if method == "GET":
                r = requests.get(url, headers=HEADERS, timeout=30)
            elif method == "POST":
                r = requests.post(url, headers=HEADERS, json=json_data, timeout=30)
            elif method == "PATCH":
                r = requests.patch(url, headers=HEADERS, json=json_data, timeout=30)
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
        
        keep_date = datetime.strptime(keep_from_date, "%Y-%m-%d")
        
        update(10, "📥 Chargement des lignes Notion...")
        
        # Récupérer toutes les lignes
        all_rows = []
        cursor = None
        
        while True:
            payload = {}
            if cursor:
                payload["start_cursor"] = cursor
            
            data = notion_request("POST", f"databases/{DB_PAIEMENTS}/query", payload)
            if not data:
                break
            
            all_rows.extend(data.get("results", []))
            
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        
        update(30, f"📊 {len(all_rows)} lignes trouvées")
        
        # Identifier les lignes à supprimer
        rows_to_delete = []
        rows_to_keep = []
        dates_to_keep = set()
        
        for row in all_rows:
            props = row["properties"]
            
            date_cours = None
            if props.get("Date cours factures", {}).get("date"):
                date_cours = props["Date cours factures"]["date"].get("start")
            
            if date_cours:
                row_date = datetime.strptime(date_cours, "%Y-%m-%d")
                
                if row_date < keep_date:
                    rows_to_delete.append({
                        "page_id": row["id"],
                        "date": date_cours
                    })
                else:
                    rows_to_keep.append(row)
                    dates_to_keep.add(format_date_title(date_cours))
            else:
                # Pas de date = à supprimer
                rows_to_delete.append({
                    "page_id": row["id"],
                    "date": "N/A"
                })
        
        update(50, f"🗑️ {len(rows_to_delete)} lignes à supprimer, {len(rows_to_keep)} à garder")
        
        # Supprimer les lignes de la DB
        deleted_db = 0
        if rows_to_delete:
            total = len(rows_to_delete)
            for i, row in enumerate(rows_to_delete):
                progress = int(50 + (i / total * 20))
                update(progress, f"🗑️ Suppression ligne {i+1}/{total}...")
                
                if not dry_run:
                    result = notion_request("PATCH", f"pages/{row['page_id']}", {"archived": True})
                    if result:
                        deleted_db += 1
                else:
                    deleted_db += 1
        
        # Nettoyer les sous-pages profs (dates qui n'existent plus)
        update(75, "🧹 Nettoyage des sous-pages profs...")
        
        prof_children = get_children(ROOT_PAGE)
        profs = []
        for b in prof_children:
            if b["type"] == "child_page":
                profs.append({
                    "id": b["id"],
                    "name": b["child_page"]["title"].strip()
                })
        
        pages_to_delete = []
        
        for prof in profs:
            date_children = get_children(prof["id"])
            
            for b in date_children:
                if b["type"] == "child_page":
                    date_title = b["child_page"]["title"].strip()
                    
                    # Vérifier si cette date est dans les dates à garder
                    if date_title not in dates_to_keep:
                        pages_to_delete.append({
                            "id": b["id"],
                            "prof": prof["name"],
                            "date_title": date_title,
                        })
        
        # Supprimer les sous-pages
        deleted_pages = 0
        if pages_to_delete:
            total = len(pages_to_delete)
            for i, page in enumerate(pages_to_delete):
                progress = int(75 + (i / total * 20))
                update(progress, f"🗑️ Suppression sous-page {i+1}/{total}...")
                
                if not dry_run:
                    result = notion_request("PATCH", f"pages/{page['id']}", {"archived": True})
                    if result:
                        deleted_pages += 1
                else:
                    deleted_pages += 1
        
        update(100, "✅ Terminé")
        
        return {
            "success": True,
            "deleted_rows": deleted_db,
            "deleted_pages": deleted_pages,
            "kept_rows": len(rows_to_keep),
            "dry_run": dry_run,
            "details_pages": pages_to_delete[:20]
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_cleanup_duplicates(secrets, dry_run=True, callback=None):
    """
    Nettoie les doublons de pages élèves dans Notion.
    
    Args:
        secrets: Configuration YAML
        dry_run: Si True, ne supprime pas vraiment
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "duplicates_found": int, "deleted": int, "error": str}
    """
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        NOTION_TOKEN = secrets["notion"]["token"]
        ROOT_PAGE = secrets["notion"]["root_page_paiements"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        def notion_request(method, url):
            time.sleep(0.35)
            full_url = f"https://api.notion.com/v1/{url}"
            
            if method == "GET":
                r = requests.get(full_url, headers=HEADERS, timeout=30)
            elif method == "DELETE":
                r = requests.delete(full_url, headers=HEADERS, timeout=30)
            else:
                return None
            
            if r.status_code == 429:
                retry = int(r.headers.get("Retry-After", 2))
                time.sleep(retry)
                return notion_request(method, url)
            
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
        
        # Récupérer les pages profs
        update(10, "📚 Lecture des pages professeurs...")
        
        prof_pages = get_children(ROOT_PAGE)
        profs = []
        for block in prof_pages:
            if block["type"] == "child_page":
                profs.append({
                    "id": block["id"],
                    "name": block["child_page"]["title"].strip(),
                })
        
        update(20, f"👨‍🏫 {len(profs)} professeurs trouvés")
        
        total_duplicates = 0
        total_deleted = 0
        duplicates_list = []
        
        total_profs = len(profs)
        
        for idx, prof in enumerate(profs):
            progress = int(20 + (idx / total_profs * 70))
            update(progress, f"🔍 Analyse {prof['name']}...")
            
            # Parcourir les pages date
            date_pages = get_children(prof["id"])
            
            for date_block in date_pages:
                if date_block["type"] != "child_page":
                    continue
                
                date_title = date_block["child_page"]["title"].strip()
                
                # Récupérer les sous-pages élèves
                student_pages = get_children(date_block["id"])
                
                # Grouper par nom normalisé
                grouped = defaultdict(list)
                for block in student_pages:
                    if block["type"] == "child_page":
                        title = block["child_page"]["title"].strip()
                        # Extraire le nom (avant " – ")
                        student_name = title.split(" – ")[0].strip() if " – " in title else title
                        normalized = normalize_name(student_name)
                        grouped[normalized].append({
                            "id": block["id"],
                            "title": title
                        })
                
                # Trouver les doublons
                for normalized, pages in grouped.items():
                    if len(pages) > 1:
                        total_duplicates += len(pages) - 1
                        
                        # Garder le premier, supprimer les autres
                        keep = pages[0]
                        to_delete = pages[1:]
                        
                        for page in to_delete:
                            duplicates_list.append({
                                "prof": prof["name"],
                                "date": date_title,
                                "keep": keep["title"],
                                "delete": page["title"]
                            })
                            
                            if not dry_run:
                                result = notion_request("DELETE", f"blocks/{page['id']}")
                                if result:
                                    total_deleted += 1
                            else:
                                total_deleted += 1
        
        update(100, "✅ Terminé !")
        
        return {
            "success": True,
            "duplicates_found": total_duplicates,
            "deleted": total_deleted,
            "dry_run": dry_run,
            "details": duplicates_list[:20]
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
