"""
🎓 Professor+ Admin
Interface Streamlit - Gestion de l'activité de soutien scolaire
VERSION 2.0 - Restructurée
"""

import streamlit as st
import os
import json
import yaml
from scripts.config_loader import load_secrets, load_secrets_no_prof
from datetime import datetime, time, timedelta
import calendar

# Import des scripts backend
from scripts.extract_tutorbird import run_extraction
from scripts.create_payment_links import run_create_payment_links
from scripts.generate_invoices import run_generate_invoices
from scripts.send_invoices_email import run_send_invoices, get_default_email_template, get_families_from_folder
from scripts.sync_stripe_notion import run_sync_stripe_notion
from scripts.update_notion import run_update_notion
from scripts.activate_twint import get_twint_status, activate_twint_for_accounts
from scripts.cleanup_notion import run_cleanup_duplicates, run_scan_notion_dates, run_delete_old_rows
from scripts.send_payment_reminders import run_send_reminders, get_default_reminder_template, get_unpaid_families_from_notion, should_send_automatic_reminder

MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
             "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

# ===========================
# CONFIG STREAMLIT
# ===========================
st.set_page_config(
    page_title="Professor+ Admin",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===========================
# CHEMINS
# ===========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ===========================
# CSS PERSONNALISÉ
# ===========================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    .stApp { font-family: 'Inter', sans-serif; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1f2e 0%, #151922 100%) !important;
    }
    
    [data-testid="stSidebar"] .stButton > button {
        background: transparent !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        color: rgba(255,255,255,0.8) !important;
        width: 100%;
        text-align: left;
        padding: 0.75rem 1rem;
        margin: 2px 0;
    }
    
    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(255,255,255,0.05) !important;
        border-color: rgba(255,255,255,0.2) !important;
    }
    
    .section-label {
        font-size: 0.7rem;
        font-weight: 600;
        color: rgba(255,255,255,0.35);
        text-transform: uppercase;
        letter-spacing: 1px;
        padding: 1rem 0 0.5rem 0;
    }
    
    [data-testid="stAppViewContainer"], .main { background: #ffffff !important; }
    .main .block-container { padding: 2rem 2.5rem; max-width: 1200px; }
    
    .header-card {
        background: #1F3A67;
        border-radius: 16px;
        padding: 2rem;
        margin-bottom: 1.5rem;
        color: white;
    }
    .header-card h1 { margin: 0; font-size: 2rem; color: white; }
    .header-card p { margin: 0.5rem 0 0 0; opacity: 0.8; color: white; }
    
    .stat-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.25rem;
        border: 1px solid #e2e8f0;
    }
    .stat-label { font-size: 0.85rem; color: #64748b; margin-bottom: 0.5rem; }
    .stat-value { font-size: 1.75rem; font-weight: 700; color: #1F3A67; }
    
    .section-title {
        font-size: 1.25rem;
        font-weight: 600;
        color: #1F3A67;
        margin: 1.5rem 0 1rem 0;
    }
    
    [data-testid="stAppViewContainer"] .stButton > button {
        background: #1F3A67 !important;
        border: none !important;
        color: #ffffff !important;
        border-radius: 10px;
    }
    [data-testid="stAppViewContainer"] .stButton > button:hover {
        background: #274A85 !important;
    }
    
    .sidebar-info-fixed {
        position: fixed;
        bottom: 0;
        left: 0;
        width: 300px;
        padding: 1rem 1.25rem;
        background: linear-gradient(180deg, #1a1f2e 0%, #151922 100%);
        border-top: 1px solid rgba(255,255,255,0.08);
        z-index: 1000;
    }
    .sidebar-info-label { font-size: 0.75rem; color: rgba(255,255,255,0.4); }
    .sidebar-info-value { font-size: 0.9rem; color: #4ade80; font-weight: 500; }
    
    [data-testid="stSidebar"] > div:first-child { padding-bottom: 80px !important; }
</style>
""", unsafe_allow_html=True)


def save_secrets(secrets):
    path = os.path.join(CONFIG_DIR, "secrets.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(secrets, f, default_flow_style=False, allow_unicode=True)

def load_familles_euros():
    paths = [
        os.path.join(CONFIG_DIR, "familles_euros.yaml"),
        os.path.join(BASE_DIR, "familles_euros.yaml"),
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("euros", []) if data else []
    return []

def save_familles_euros(familles):
    path = os.path.join(CONFIG_DIR, "familles_euros.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"euros": familles}, f, allow_unicode=True)

def load_tarifs_speciaux():
    paths = [
        os.path.join(CONFIG_DIR, "tarifs_speciaux.yaml"),
        os.path.join(BASE_DIR, "tarifs_speciaux.yaml"),
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("tarifs_speciaux", []) if data else []
    return []

def save_tarifs_speciaux(tarifs):
    path = os.path.join(CONFIG_DIR, "tarifs_speciaux.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"tarifs_speciaux": tarifs}, f, allow_unicode=True)

def load_extracted_data():
    path = os.path.join(DATA_DIR, "full_output_tb_SIMPLE.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_latest_invoice_folder():
    invoice_dir = os.path.join(BASE_DIR, "Factures")
    if not os.path.exists(invoice_dir):
        return None
    
    folders = []
    for year in os.listdir(invoice_dir):
        year_path = os.path.join(invoice_dir, year)
        if os.path.isdir(year_path):
            for month_folder in os.listdir(year_path):
                month_path = os.path.join(year_path, month_folder)
                if os.path.isdir(month_path):
                    try:
                        date_part = month_folder.split(" - ")[-1]
                        dt = datetime.strptime(date_part, "%d-%m-%Y")
                        folders.append({"path": month_path, "date": dt, "name": month_folder})
                    except:
                        pass
    
    if folders:
        folders.sort(key=lambda x: x["date"], reverse=True)
        return folders[0]
    return None

def get_month_year_from_folder(folder):
    """Extrait le mois et l'année du dossier de factures."""
    if not folder:
        return MONTHS_FR[datetime.now().month - 1], datetime.now().year
    try:
        month_name = folder["name"].split(" - ")[0].split()[0]
        year = folder["date"].year
        return month_name, year
    except:
        return MONTHS_FR[datetime.now().month - 1], datetime.now().year

# ===========================
# SESSION STATE
# ===========================
if 'current_page' not in st.session_state:
    st.session_state.current_page = "accueil"
if 'has_extracted' not in st.session_state:
    st.session_state.has_extracted = os.path.exists(os.path.join(DATA_DIR, "full_output_tb_SIMPLE.json"))
if 'extract_dates' not in st.session_state:
    st.session_state.extract_dates = None
if "prefill_new_teacher_name" not in st.session_state:
    st.session_state.prefill_new_teacher_name = ""
if "return_to_page" not in st.session_state:
    st.session_state.return_to_page = ""
if "config_tab" not in st.session_state:
    st.session_state.config_tab = "edit_teacher"
if "prefill_edit_teacher_name" not in st.session_state:
    st.session_state.prefill_edit_teacher_name = ""
if "notion_dates_scan" not in st.session_state:
    st.session_state.notion_dates_scan = None

# ===========================
# SIDEBAR
# ===========================
with st.sidebar:
    st.markdown("""
    <div style="padding: 1rem; border-bottom: 1px solid rgba(255,255,255,0.08); margin-bottom: 1rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem;">
            <div style="width: 40px; height: 40px; background: linear-gradient(135deg, #0d9488, #14b8a6); border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem;">🎓</div>
            <span style="font-size: 1.25rem; font-weight: 700; color: white;">Professor+</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown('<p class="section-label">ACTIONS</p>', unsafe_allow_html=True)
    
    if st.button("🏠 Accueil", key="nav_accueil", width="stretch"):
        st.session_state.current_page = "accueil"
        st.rerun()
    
    if st.button("👨‍🏫 Professeurs", key="nav_profs", width="stretch"):
        st.session_state.current_page = "profs"
        st.rerun()
    
    st.markdown('<p class="section-label">📥 EXTRACTION</p>', unsafe_allow_html=True)
    
    if st.button("🗓️ Extraire les leçons", key="nav_extract", width="stretch"):
        st.session_state.current_page = "extract"
        st.rerun()
    
    if st.button("⚡ Activer Twint", key="nav_twint", width="stretch"):
        st.session_state.current_page = "twint"
        st.rerun()
    
    if st.button("🧹 Nettoyage Notion", key="nav_cleanup", width="stretch"):
        st.session_state.current_page = "cleanup"
        st.rerun()
    
    st.markdown('<p class="section-label">💳 PAIEMENTS & FACTURES</p>', unsafe_allow_html=True)
    
    if st.button("💳 Créer liens paiement", key="nav_payment", width="stretch"):
        st.session_state.current_page = "payment"
        st.rerun()
    
    if st.button("📄 Générer factures", key="nav_invoices", width="stretch"):
        st.session_state.current_page = "invoices"
        st.rerun()
    
    st.markdown('<p class="section-label">📧 COMMUNICATION</p>', unsafe_allow_html=True)
    
    if st.button("📧 Envoyer factures", key="nav_send", width="stretch"):
        st.session_state.current_page = "send"
        st.rerun()
    
    if st.button("🔔 Rappels paiement", key="nav_reminders", width="stretch"):
        st.session_state.current_page = "reminders"
        st.rerun()
    
    st.markdown('<p class="section-label">🔄 SYNCHRONISATION</p>', unsafe_allow_html=True)
    
    if st.button("🔄 Sync Stripe→Notion", key="nav_sync", width="stretch"):
        st.session_state.current_page = "sync"
        st.rerun()
    
    if st.button("📤 Ajouter lignes Notion", key="nav_update", width="stretch"):
        st.session_state.current_page = "update"
        st.rerun()
    
    st.markdown('<p class="section-label">⚙️ CONFIGURATION</p>', unsafe_allow_html=True)
    
    if st.button("⚙️ Paramètres", key="nav_config", width="stretch"):
        st.session_state.current_page = "config"
        st.rerun()
    
    latest = get_latest_invoice_folder()
    folder_date = latest["date"].strftime("%d %b. %Y") if latest else "—"
    
    st.markdown(f"""
    <div class="sidebar-info-fixed">
        <div class="sidebar-info-label">Dernier dossier</div>
        <div class="sidebar-info-value">📅 {folder_date}</div>
    </div>
    """, unsafe_allow_html=True)

# Import des pages depuis le module pages
from pages import (
    page_accueil, page_extract, page_twint, page_cleanup,
    page_payment, page_invoices, page_send, page_reminders,
    page_sync, page_update, page_config, page_profs
)

# ===========================
# ROUTING
# ===========================
page = st.session_state.current_page

# Passer les fonctions utilitaires aux pages
ctx = {
    "load_secrets": load_secrets,
    "save_secrets": save_secrets,
    "load_familles_euros": load_familles_euros,
    "save_familles_euros": save_familles_euros,
    "load_tarifs_speciaux": load_tarifs_speciaux,
    "save_tarifs_speciaux": save_tarifs_speciaux,
    "load_secrets_no_prof": load_secrets_no_prof,
    "load_extracted_data": load_extracted_data,
    "get_latest_invoice_folder": get_latest_invoice_folder,
    "get_month_year_from_folder": get_month_year_from_folder,
    "BASE_DIR": BASE_DIR,
    "CONFIG_DIR": CONFIG_DIR,
    "DATA_DIR": DATA_DIR,
    "MONTHS_FR": MONTHS_FR,
}

if page == "accueil":
    page_accueil(ctx)
elif page == "extract":
    page_extract(ctx)
elif page == "twint":
    page_twint(ctx)
elif page == "cleanup":
    page_cleanup(ctx)
elif page == "payment":
    page_payment(ctx)
elif page == "invoices":
    page_invoices(ctx)
elif page == "send":
    page_send(ctx)
elif page == "reminders":
    page_reminders(ctx)
elif page == "sync":
    page_sync(ctx)
elif page == "update":
    page_update(ctx)
elif page == "config":
    page_config(ctx)
elif page == "profs":
    page_profs(ctx)
else:
    page_accueil(ctx)