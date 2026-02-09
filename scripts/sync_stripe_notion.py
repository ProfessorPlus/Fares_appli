"""
🔄 Sync Stripe to Notion
Synchronise les paiements Stripe vers Notion (marque Payé)

Basé sur Sync_stripe_to_notion.py qui fonctionne.
Adapté pour être appelé depuis l'interface Streamlit.
"""

import time
import requests
from datetime import datetime

try:
    import stripe
except ImportError:
    stripe = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

REQUEST_DELAY = 0.20


def extract_student_from_receipt(receipt_url):
    """Extrait le nom de l'élève depuis le reçu Stripe."""
    if not receipt_url or BeautifulSoup is None:
        return None
    try:
        r = requests.get(receipt_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.find_all(string=lambda t: t and "Soutien scolaire" in t):
            text = item.strip()
            if "|" in text and "×" in text:
                return text.split("|")[1].split("×")[0].strip()
    except:
        pass
    return None


def names_match(name1, name2):
    """
    Compare les noms Stripe ↔ Notion en gérant :
    - Nom, Prénom / Prénom Nom
    - Noms composés
    - Familles avec plusieurs enfants (ex: "Blanchoud, Chelsy & Kristy" match "Chelsy Blanchoud")
    
    RÈGLE: Si au moins 2 mots sont en commun → MATCH
    """
    def normalize(n):
        if not n:
            return ""
        n = n.lower().strip()
        n = n.replace(",", " ")
        n = n.replace("&", " ")
        n = " ".join(n.split())
        return n

    n1 = normalize(name1)
    n2 = normalize(name2)

    if not n1 or not n2:
        return False

    words1 = set(n1.split())
    words2 = set(n2.split())

    if words1 == words2:
        return True
    
    common_words = words1 & words2
    if len(common_words) >= 2:
        return True
    
    if len(words1) == 2 and words1.issubset(words2):
        return True
    if len(words2) == 2 and words2.issubset(words1):
        return True
    
    return False


def run_sync_stripe_notion(secrets, since_date=None, callback=None):
    """
    Synchronise les paiements Stripe vers Notion.
    
    Args:
        secrets: Configuration YAML (contient stripe, notion, teachers)
        since_date: Date depuis laquelle synchroniser
        callback: Fonction callback(progress, message)
    
    Returns:
        dict avec synced, already_paid, no_match, student_unknown, etc.
    """
    
    if stripe is None:
        return {"success": False, "error": "Module stripe non installé. pip install stripe"}
    
    if BeautifulSoup is None:
        return {"success": False, "error": "Module beautifulsoup4 non installé. pip install beautifulsoup4"}
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        # Config
        stripe.api_key = secrets["stripe"]["platform_secret_key"]
        
        NOTION_TOKEN = secrets["notion"]["token"]
        DB_PAIEMENTS = secrets["notion"]["paiements_database_id"]
        
        HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        
        # Mapping compte connecté → prof
        ACCOUNT_TO_TEACHER = {}
        for teacher_name, data in secrets.get("teachers", {}).items():
            if data.get("connect_account_id"):
                ACCOUNT_TO_TEACHER[data["connect_account_id"]] = teacher_name
        
        # ===========================
        # ÉTAPE 1: Récupérer les paiements Stripe
        # ===========================
        update(5, "💳 Récupération des paiements Stripe...")
        
        params = {"limit": 100}
        if since_date:
            params["created"] = {"gte": int(since_date.timestamp())}
        
        charges = stripe.Charge.list(**params)
        stripe_payments = []
        
        for ch in charges.data:
            if ch.status != "succeeded" or not ch.balance_transaction:
                continue
            
            # Déterminer le prof via transfer_data
            transfer_data = getattr(ch, "transfer_data", None)
            if transfer_data and transfer_data.destination:
                teacher = ACCOUNT_TO_TEACHER.get(transfer_data.destination, "Inconnu")
                dest_acct = transfer_data.destination
            else:
                teacher = "Parisi Lucas"
                dest_acct = None
            
            # Extraire le nom de l'élève depuis le reçu
            student = extract_student_from_receipt(ch.receipt_url)
            
            # Calculer le montant versé au prof
            if dest_acct:
                try:
                    transfers = stripe.Transfer.list(limit=50)
                    montant_verse = None
                    for t in transfers.data:
                        if t.get("source_transaction") == ch.id:
                            dest_pay = stripe.Charge.retrieve(t["destination_payment"], stripe_account=dest_acct)
                            bt_prof = stripe.BalanceTransaction.retrieve(dest_pay["balance_transaction"], stripe_account=dest_acct)
                            montant_verse = bt_prof["net"] / 100
                            break
                    
                    if montant_verse is None:
                        montant_verse = (ch.amount - (ch.application_fee_amount or 0)) / 100
                except:
                    montant_verse = (ch.amount - (ch.application_fee_amount or 0)) / 100
            else:
                bt = stripe.BalanceTransaction.retrieve(ch.balance_transaction)
                montant_verse = bt.net / 100
            
            stripe_payments.append({
                "charge_id": ch.id,
                "teacher": teacher,
                "student": student,
                "amount": ch.amount / 100,
                "montant_verse": montant_verse,
                "date_payment": datetime.fromtimestamp(ch.created).strftime("%Y-%m-%d"),
            })
        
        update(30, f"📊 {len(stripe_payments)} paiements Stripe trouvés")
        
        # ===========================
        # ÉTAPE 2: Récupérer toutes les lignes Notion
        # ===========================
        update(40, "📥 Récupération des données Notion...")
        
        all_notion_rows = []
        cursor = None
        
        while True:
            payload = {}
            if cursor:
                payload["start_cursor"] = cursor
            
            time.sleep(REQUEST_DELAY)
            r = requests.post(
                f"https://api.notion.com/v1/databases/{DB_PAIEMENTS}/query",
                headers=HEADERS,
                json=payload,
                timeout=30
            )
            
            if r.status_code != 200:
                break
            
            data = r.json()
            all_notion_rows.extend(data.get("results", []))
            
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        
        # Parser les lignes Notion
        notion_rows = []
        for row in all_notion_rows:
            p = row["properties"]
            
            prof_prop = p.get("Professeur", {}).get("rich_text", [])
            eleve_prop = p.get("Élève", {}).get("rich_text", [])
            montant = p.get("Montant dû Famille/Prof", {}).get("number", 0)
            paid = p.get("Payé ?", {}).get("checkbox", False)
            
            if prof_prop and eleve_prop and montant:
                notion_rows.append({
                    "page_id": row["id"],
                    "prof": prof_prop[0]["plain_text"].strip(),
                    "eleve": eleve_prop[0]["plain_text"].strip(),
                    "montant": montant,
                    "paid": paid,
                })
        
        update(55, f"📊 {len(notion_rows)} lignes Notion trouvées")
        
        # ===========================
        # ÉTAPE 3: Matching et mise à jour
        # ===========================
        update(60, "🔄 Matching Stripe ↔ Notion...")
        
        synced = 0
        already_paid = 0
        no_match = []
        student_unknown = 0
        matched_ids = set()
        
        total = len(stripe_payments)
        
        for i, sp in enumerate(stripe_payments):
            progress = int(60 + (i / max(total, 1) * 35))
            
            # Cas 1: Élève non trouvé dans le reçu
            if not sp["student"]:
                student_unknown += 1
                no_match.append(f"⚠️ {sp['teacher']} - {sp['amount']} CHF (élève inconnu)")
                continue
            
            found_unpaid = None
            found_paid = None
            
            for nr in notion_rows:
                # Vérifier si prof + montant + élève correspondent
                # IMPORTANT: Comparaison avec tolérance sur le montant (arrondi à 2 décimales)
                prof_match = nr["prof"].lower() == sp["teacher"].lower()
                amount_match = abs(round(nr["montant"], 2) - round(sp["amount"], 2)) < 0.01
                name_match = names_match(nr["eleve"], sp["student"])
                
                if prof_match and amount_match and name_match:
                    if not nr["paid"] and nr["page_id"] not in matched_ids:
                        found_unpaid = nr
                        break
                    elif nr["paid"]:
                        found_paid = nr
            
            # Cas 2: Match trouvé avec ligne non payée → mise à jour
            if found_unpaid:
                update(progress, f"✅ {sp['student']}")
                
                # Mettre à jour Notion
                time.sleep(REQUEST_DELAY)
                result = requests.patch(
                    f"https://api.notion.com/v1/pages/{found_unpaid['page_id']}",
                    headers=HEADERS,
                    json={
                        "properties": {
                            "Payé ?": {"checkbox": True},
                            "Montant réel versé par Stripe": {"number": round(sp["montant_verse"], 2)},
                            "Date des paiements": {"date": {"start": sp["date_payment"]}},
                        }
                    },
                    timeout=30
                )
                
                if result.status_code in [200, 201]:
                    synced += 1
                    matched_ids.add(found_unpaid["page_id"])
            
            # Cas 3: Ligne existe mais déjà payée
            elif found_paid:
                already_paid += 1
            
            # Cas 4: Aucune correspondance
            else:
                no_match.append(f"{sp['teacher']} | {sp['student']} | {sp['amount']} CHF")
        
        update(100, "✅ Sync Stripe terminé !")
        
        return {
            "success": True,
            "synced": synced,
            "already_paid": already_paid,
            "not_found": no_match[:20],
            "total_not_found": len(no_match),
            "student_unknown": student_unknown,
            "total_charges": len(stripe_payments),
        }
        
    except stripe.error.AuthenticationError:
        return {"success": False, "error": "Erreur d'authentification Stripe - Vérifiez votre clé API"}
    except Exception as e:
        import traceback
        return {"success": False, "error": f"{str(e)}\n{traceback.format_exc()}"}