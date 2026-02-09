"""
⚡ Activate Twint
Active la capability twint_payments sur les comptes Connect
"""

try:
    import stripe
except ImportError:
    stripe = None


def get_twint_status(secrets, callback=None):
    """
    Vérifie le statut Twint de tous les comptes Connect.
    
    Returns:
        dict: {"success": bool, "accounts": list, "error": str}
    """
    
    if stripe is None:
        return {"success": False, "error": "Module stripe non installé"}
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        stripe.api_key = secrets["stripe"]["platform_secret_key"]
        TEACHERS = secrets.get("teachers", {})
        
        accounts = []
        total = len(TEACHERS)
        current = 0
        
        for name, info in TEACHERS.items():
            current += 1
            progress = int(current / total * 100)
            
            connect_id = info.get("connect_account_id")
            
            if not connect_id:
                accounts.append({
                    "name": name,
                    "connect_id": None,
                    "twint_status": "Pas de compte Connect",
                    "has_connect": False
                })
                continue
            
            update(progress, f"🔍 Vérification {name}...")
            
            try:
                account = stripe.Account.retrieve(connect_id)
                twint_status = account.capabilities.get("twint_payments", "non configuré")
                
                accounts.append({
                    "name": name,
                    "connect_id": connect_id,
                    "twint_status": twint_status,
                    "has_connect": True,
                    "country": account.country,
                    "type": account.type
                })
            except Exception as e:
                accounts.append({
                    "name": name,
                    "connect_id": connect_id,
                    "twint_status": f"Erreur: {str(e)}",
                    "has_connect": True
                })
        
        return {
            "success": True,
            "accounts": accounts
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def activate_twint_for_accounts(secrets, account_ids, callback=None):
    """
    Active Twint pour les comptes spécifiés.
    
    Args:
        secrets: Configuration YAML
        account_ids: Liste des connect_account_id à activer
        callback: Fonction callback(progress, message)
    
    Returns:
        dict: {"success": bool, "activated": int, "errors": list}
    """
    
    if stripe is None:
        return {"success": False, "error": "Module stripe non installé"}
    
    def update(progress, message):
        if callback:
            callback(progress, message)
    
    try:
        stripe.api_key = secrets["stripe"]["platform_secret_key"]
        
        activated = 0
        errors = []
        total = len(account_ids)
        
        for i, account_id in enumerate(account_ids):
            progress = int((i + 1) / total * 100)
            update(progress, f"⚡ Activation {account_id}...")
            
            try:
                account = stripe.Account.modify(
                    account_id,
                    capabilities={
                        "twint_payments": {"requested": True}
                    }
                )
                
                twint_status = account.capabilities.get("twint_payments", "unknown")
                activated += 1
                
            except stripe.error.InvalidRequestError as e:
                errors.append(f"{account_id}: {e.user_message}")
            except Exception as e:
                errors.append(f"{account_id}: {str(e)}")
        
        return {
            "success": True,
            "activated": activated,
            "errors": errors
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
