"""
Pages de l'application Professor+ Admin
VERSION 2.1 - Avec onglets régénération
"""

import streamlit as st
import os
import json
from datetime import datetime, time
import calendar

# Import des scripts
from scripts.extract_tutorbird import run_extraction
from scripts.update_notion import run_update_notion, run_update_notion_selective, run_scan_and_compare, run_add_missing_rows
from scripts.create_payment_links import run_create_payment_links
from scripts.generate_invoices import run_generate_invoices
from scripts.send_invoices_email import run_send_invoices, get_default_email_template, get_families_from_folder
from scripts.sync_stripe_notion import run_sync_stripe_notion
from scripts.activate_twint import get_twint_status, activate_twint_for_accounts
from scripts.cleanup_notion import run_cleanup_duplicates, run_scan_notion_dates, run_delete_old_rows
from scripts.send_payment_reminders import run_send_reminders, get_default_reminder_template, get_unpaid_families_from_notion, should_send_automatic_reminder


def page_accueil(ctx):
    st.markdown("""
    <div class="header-card">
        <h1>🎓 Professor+ Admin</h1>
        <p>Gestion complète de votre activité de soutien scolaire</p>
    </div>
    """, unsafe_allow_html=True)
    
    secrets = ctx["load_secrets"]()
    data = ctx["load_extracted_data"]()
    latest = ctx["get_latest_invoice_folder"]()
    
    nb_profs = len(secrets.get("teachers", {})) if secrets else 0
    nb_families = len(data) if data else 0
    total_amount = sum(f.get("total_courses", 0) for f in data.values()) if data else 0
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">👨‍🏫 Professeurs</div>
            <div class="stat-value">{nb_profs}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">👨‍👩‍👧 Familles</div>
            <div class="stat-value">{nb_families}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">💰 À facturer</div>
            <div class="stat-value">{total_amount:,.0f} CHF</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        folder_date = latest["date"].strftime("%d/%m/%Y") if latest else "—"
        st.markdown(f"""
        <div class="stat-card">
            <div class="stat-label">📁 Dernier dossier</div>
            <div class="stat-value" style="font-size: 1.2rem;">{folder_date}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Alerte rappel automatique le 11
    if should_send_automatic_reminder():
        st.warning("🔔 **C'est le 11 du mois !** Pensez à envoyer les rappels de paiement aux familles qui n'ont pas encore payé.")
    
    st.markdown('<div class="section-title">⚡ Actions rapides</div>', unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📥 Extraction TutorBird", width="stretch", key="home_extract"):
            st.session_state.current_page = "extract"
            st.rerun()
    with col2:
        if st.button("💳 Créer liens paiement", width="stretch", key="home_payment"):
            st.session_state.current_page = "payment"
            st.rerun()
    with col3:
        if st.button("📄 Générer Factures", width="stretch", key="home_invoices"):
            st.session_state.current_page = "invoices"
            st.rerun()
    
    st.markdown('<div class="section-title">📋 Workflow recommandé</div>', unsafe_allow_html=True)
    
    st.info("""
    **📌 Ordre recommandé pour la facturation :**
    1. **Extraire TutorBird** - Récupérer les leçons du mois
    2. **Créer liens paiement** - Générer les liens Stripe
    3. **Générer Factures** - Créer les PDFs
    4. **Envoyer Factures** - Envoyer par email
    5. **Ajouter lignes Notion** - Ajouter dans la DB paiements + sous-pages profs
    6. **Sync Stripe→Notion** - Marquer les paiements reçus
    """)


def page_extract(ctx):
    st.markdown('<div class="section-title">📥 Extraction TutorBird</div>', unsafe_allow_html=True)
    
    st.info("Sélectionnez la période pour extraire les leçons depuis TutorBird.")
    
    today = datetime.today()
    first_day = today.replace(day=1)
    last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("📅 Date de début", value=first_day, format="DD/MM/YYYY")
    with col2:
        end_date = st.date_input("📅 Date de fin", value=last_day, format="DD/MM/YYYY")
    
    full_day = st.checkbox("🗓️ Journée entière (00:00 → 23:59)", value=True)
    
    if full_day:
        start_time = time(0, 0)
        end_time = time(23, 59)
    else:
        col1, col2 = st.columns(2)
        with col1:
            start_time = st.time_input("Heure de début", value=time(0, 0))
        with col2:
            end_time = st.time_input("Heure de fin", value=time(23, 59))
    
    st.markdown("---")
    
    # Info pour modification de factures
    st.info("💡 **Besoin de modifier des factures ?** Utilisez l'onglet *« Régénérer certaines familles »* dans **Créer liens paiement**, puis *« Régénérer certaines factures »* dans **Générer factures**.")
    
    if st.button("🚀 Lancer l'extraction", type="primary", width="stretch"):
        secrets = ctx["load_secrets"]()
        
        if not secrets:
            st.error("❌ Fichier secrets.yaml non trouvé !")
            return
        
        progress_bar = st.progress(0)
        status = st.empty()
        
        def callback(progress, message):
            progress_bar.progress(progress)
            status.info(message)
        
        result = run_extraction(secrets, start_date, end_date, start_time, end_time, ctx["DATA_DIR"], callback)
        
        if result["success"]:
            st.session_state.has_extracted = True
            st.session_state.extract_dates = {"start": start_date, "end": end_date}

            report_path = os.path.join(ctx["DATA_DIR"], "payment_links_report.json")
            if os.path.exists(report_path):
                os.remove(report_path)

            links_path = os.path.join(ctx["DATA_DIR"], "payment_links_output.json")
            if os.path.exists(links_path):
                os.remove(links_path)
            
            st.success(f"""
            ✅ **Extraction terminée !**
            - 📁 **{result['families']}** familles
            - 📚 **{result['lessons']}** leçons
            - 💰 **{result['amount']:,.2f} CHF** total
            """)
        else:
            st.error(f"❌ Erreur : {result['error']}")


def page_twint(ctx):
    st.markdown('<div class="section-title">⚡ Activation Twint</div>', unsafe_allow_html=True)
    
    secrets = ctx["load_secrets"]()
    if not secrets:
        st.error("❌ Fichier secrets.yaml non trouvé !")
        return
    
    if st.button("🔍 Vérifier le statut Twint", width="stretch"):
        progress = st.progress(0)
        status = st.empty()
        
        def callback(progress_val, message):
            progress.progress(progress_val)
            status.info(message)
        
        result = get_twint_status(secrets, callback)
        
        if result["success"]:
            st.markdown("### 📊 Statut des comptes")
            
            for acc in result["accounts"]:
                if acc["has_connect"]:
                    emoji = "✅" if acc["twint_status"] == "active" else "⏳" if acc["twint_status"] == "pending" else "❌"
                    st.write(f"{emoji} **{acc['name']}** : {acc['twint_status']}")
                else:
                    st.write(f"⚪ **{acc['name']}** : Pas de compte Connect")
        else:
            st.error(f"❌ Erreur : {result['error']}")
    
    st.markdown("---")
    
    st.markdown("### ⚡ Activer Twint")
    
    teachers = secrets.get("teachers", {})
    accounts_to_activate = []
    
    for name, info in teachers.items():
        connect_id = info.get("connect_account_id")
        if connect_id:
            accounts_to_activate.append({"name": name, "id": connect_id})
    
    if accounts_to_activate:
        selected = st.multiselect(
            "Sélectionner les comptes à activer",
            [a["name"] for a in accounts_to_activate],
            default=[a["name"] for a in accounts_to_activate]
        )
        
        if st.button("⚡ Activer Twint", type="primary", width="stretch"):
            ids = [a["id"] for a in accounts_to_activate if a["name"] in selected]
            
            result = activate_twint_for_accounts(secrets, ids)
            
            if result["success"]:
                st.success(f"✅ {result['activated']} compte(s) activé(s)")
                if result["errors"]:
                    for err in result["errors"]:
                        st.warning(f"⚠️ {err}")
            else:
                st.error(f"❌ Erreur : {result['error']}")
    else:
        st.warning("⚠️ Aucun compte Connect configuré")


def page_cleanup(ctx):
    st.markdown('<div class="section-title">🧹 Nettoyage Notion</div>', unsafe_allow_html=True)
    
    st.info("""
    Cette page regroupe tous les outils de nettoyage Notion :
    - **Scanner les dates** : voir quelles dates de factures sont présentes
    - **Supprimer les anciennes lignes** : nettoyer les données obsolètes
    - **Nettoyer les doublons** : supprimer les pages élèves en double
    """)
    
    secrets = ctx["load_secrets"]()
    if not secrets:
        st.error("❌ Fichier secrets.yaml non trouvé !")
        return
    
    tab1, tab2, tab3 = st.tabs(["📅 Scanner les dates", "🗑️ Supprimer anciennes lignes", "🔍 Nettoyer doublons"])
    
    # ===========================
    # TAB 1: Scanner les dates
    # ===========================
    with tab1:
        st.markdown("### 📅 Dates de factures présentes dans Notion")
        
        if st.button("🔍 Scanner les dates", width="stretch", key="scan_dates"):
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_scan_notion_dates(secrets, callback)
            
            if result["success"]:
                st.session_state.notion_dates_scan = result
                st.success(f"✅ Scan terminé : **{result['count']}** date(s) trouvée(s)")
            else:
                st.error(f"❌ Erreur : {result['error']}")
        
        # Afficher les résultats du scan
        if st.session_state.get("notion_dates_scan"):
            scan = st.session_state.notion_dates_scan
            
            st.markdown(f"**📊 {scan['total_rows']} lignes** dans la base Notion")
            st.markdown(f"**📅 Date la plus récente** : {scan['latest_readable']}")
            
            with st.expander("📋 Toutes les dates", expanded=True):
                for d in scan["dates"]:
                    st.write(f"• {d['readable']} ({d['iso']})")
    
    # ===========================
    # TAB 2: Supprimer anciennes lignes
    # ===========================
    with tab2:
        st.markdown("### 🗑️ Supprimer les anciennes lignes")
        
        st.warning("""
        ⚠️ **Attention** : Cette action supprime définitivement les lignes Notion ET les sous-pages des professeurs correspondantes.
        
        **Recommandation** : Supprimez les lignes antérieures à la date de facture la plus récente.
        """)
        
        # Récupérer la date la plus récente si scan effectué
        latest_date = None
        if st.session_state.get("notion_dates_scan"):
            latest_date = st.session_state.notion_dates_scan.get("latest_date")
        
        if latest_date:
            st.info(f"💡 Date la plus récente détectée : **{st.session_state.notion_dates_scan['latest_readable']}**")
            use_latest = st.checkbox("Garder uniquement à partir de cette date (recommandé)", value=True)
            
            if use_latest:
                keep_from = latest_date
            else:
                keep_from = st.date_input("📅 Garder à partir de", value=datetime.strptime(latest_date, "%Y-%m-%d"))
                keep_from = keep_from.strftime("%Y-%m-%d")
        else:
            st.warning("⚠️ Scannez d'abord les dates pour voir les options disponibles.")
            keep_from = st.date_input("📅 Garder à partir de", value=datetime.today())
            keep_from = keep_from.strftime("%Y-%m-%d")
        
        dry_run = st.checkbox("🔍 Mode aperçu (ne supprime rien)", value=True, key="delete_dry_run")
        
        if st.button("🗑️ Lancer la suppression", type="primary", width="stretch", key="delete_old"):
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_delete_old_rows(secrets, keep_from, dry_run=dry_run, callback=callback)
            
            if result["success"]:
                if dry_run:
                    st.warning(f"""
                    🔍 **Aperçu** :
                    - {result['deleted_rows']} ligne(s) DB à supprimer
                    - {result['deleted_pages']} sous-page(s) prof à supprimer
                    - {result['kept_rows']} ligne(s) conservées
                    """)
                else:
                    st.success(f"""
                    ✅ **Suppression terminée** :
                    - {result['deleted_rows']} ligne(s) DB supprimées
                    - {result['deleted_pages']} sous-page(s) prof supprimées
                    """)
                
                if result.get("details_pages"):
                    with st.expander("📋 Détails des sous-pages supprimées"):
                        for p in result["details_pages"]:
                            st.write(f"• {p['prof']} → {p['date_title']}")
            else:
                st.error(f"❌ Erreur : {result['error']}")
    
    # ===========================
    # TAB 3: Nettoyer doublons
    # ===========================
    with tab3:
        st.markdown("### 🔍 Nettoyer les doublons de pages élèves")
        
        st.info("Détecte et supprime les pages élèves en doublon (ex: 'Louis Clémence' et 'Louis, Clémence')")
        
        dry_run = st.checkbox("🔍 Mode aperçu (ne supprime rien)", value=True, key="dup_dry_run")
        
        if st.button("🧹 Lancer le nettoyage", type="primary", width="stretch", key="cleanup_dup"):
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_cleanup_duplicates(secrets, dry_run=dry_run, callback=callback)
            
            if result["success"]:
                if dry_run:
                    st.warning(f"🔍 **Aperçu** : {result['duplicates_found']} doublons trouvés")
                else:
                    st.success(f"✅ {result['deleted']} doublons supprimés")
                
                if result.get("details"):
                    with st.expander("📋 Détails"):
                        for d in result["details"]:
                            st.write(f"- {d['prof']} / {d['date']} : garder '{d['keep']}', supprimer '{d['delete']}'")
            else:
                st.error(f"❌ Erreur : {result['error']}")

def page_payment(ctx):
    st.markdown('<div class="section-title">💳 Créer les liens de paiement</div>', unsafe_allow_html=True)
    
    # Chargement des données EN PREMIER
    if not st.session_state.has_extracted:
        st.warning("⚠️ Vous devez d'abord extraire les données TutorBird.")
        return
    
    data = ctx["load_extracted_data"]()
    secrets = ctx["load_secrets"]()
    
    if not secrets:
        st.error("❌ Fichier secrets.yaml non trouvé !")
        return
    
    if not data:
        st.error("❌ Aucune donnée extraite trouvée")
        return
    
    configured_teachers = set(secrets.get("teachers", {}).keys())
    
    # ===========================
    # VÉRIFICATION DES PROFS AVANT TOUT
    # ===========================
    # Récupérer tous les profs de TutorBird
    tutorbird_teachers = set()
    for fam_id, fam in data.items():
        for L in fam.get("lessons", []):
            teacher = L.get("teacher", "")
            if teacher:
                tutorbird_teachers.add(teacher)
    
    # Fonction de normalisation pour comparaison
    def normalize_for_compare(s):
        if not s:
            return ""
        import unicodedata
        s = s.lower().strip()
        s = unicodedata.normalize('NFD', s)
        s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
        s = s.replace("-", " ").replace("_", " ").replace(",", " ")
        return " ".join(s.split())
    
    # Créer un mapping normalisé des profs configurés
    configured_normalized = {normalize_for_compare(t): t for t in configured_teachers}
    
    # Trouver les profs non configurés
    missing_teachers = []
    matched_teachers = []
    
    for tb_teacher in tutorbird_teachers:
        tb_norm = normalize_for_compare(tb_teacher)
        
        # Vérifier match exact ou similaire
        found = False
        for cfg_norm, cfg_original in configured_normalized.items():
            # Match exact normalisé
            if tb_norm == cfg_norm:
                found = True
                matched_teachers.append({"tutorbird": tb_teacher, "config": cfg_original})
                break
            # Match partiel (ex: "Ricardo H" vs "Ricardo Hounsinou")
            if tb_norm in cfg_norm or cfg_norm in tb_norm:
                found = True
                matched_teachers.append({"tutorbird": tb_teacher, "config": cfg_original})
                break
        
        if not found:
            missing_teachers.append(tb_teacher)
    
    # ===========================
    # AFFICHAGE STATUT DES PROFS
    # ===========================
    if missing_teachers:
        st.error(f"❌ **{len(missing_teachers)} professeur(s) non configuré(s)** - Vous devez les ajouter avant de générer les liens")
        
        for teacher in missing_teachers:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"• **{teacher}**")
            with col2:
                if st.button(f"➕ Ajouter", key=f"add_missing_{teacher}"):
                    st.session_state.prefill_new_teacher_name = teacher
                    st.session_state.return_to_page = "payment"
                    st.session_state.current_page = "config"
                    st.rerun()
        
        st.markdown("---")
    else:
        st.success(f"✅ **{len(matched_teachers)} professeur(s)** - Tous les profs TutorBird sont configurés")
    
    # ===========================
    # ONGLETS
    # ===========================
    tab1, tab2 = st.tabs(["🚀 Générer tous les liens", "🔄 Régénérer pour certaines familles"])
    
    # ===========================
    # TAB 1: Générer tous les liens
    # ===========================
    with tab1:
        # RAPPORT - SEULEMENT si on vient de générer (pas à chaque visite)
        report_path = os.path.join(ctx["DATA_DIR"], "payment_links_report.json")
        
        # Afficher le rapport SEULEMENT si flag actif
        if st.session_state.get("show_payment_report") and os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            
            nb_expected = report.get("expected_families_count", 0)
            nb_created = report.get("created_families_count", 0)
            nb_links = report.get("links_count", 0)
            profs_inconnus_raw = report.get("profs_inconnus", [])
            missing_families = report.get("missing_families", [])
            
            # Filtrer les profs inconnus
            profs_inconnus = [p for p in profs_inconnus_raw if p not in configured_teachers]
            
            all_ok = (len(missing_families) == 0 and len(profs_inconnus) == 0)
            
            if all_ok:
                st.success(f"✅ **{nb_created}/{nb_expected} familles** — {nb_links} liens créés")
            else:
                st.warning(f"⚠️ **{nb_created}/{nb_expected} familles** — {nb_links} liens créés")
            
            if profs_inconnus:
                st.error("❌ **Profs inconnus détectés**")
                for p in profs_inconnus:
                    if st.button(f"➕ Ajouter : {p}", key=f"add_unknown_{p}"):
                        st.session_state.prefill_new_teacher_name = p
                        st.session_state.return_to_page = "payment"
                        st.session_state.current_page = "config"
                        st.rerun()
            
            if missing_families:
                with st.expander(f"❌ {len(missing_families)} famille(s) sans lien", expanded=True):
                    for fam in missing_families:
                        st.write(f"• **{fam['parent_name']}** — {fam['billable_amount']} {fam['currency']}")
            
            # Bouton pour fermer le rapport
            if st.button("✖️ Fermer ce rapport", key="close_report"):
                st.session_state.show_payment_report = False
                st.rerun()
            
            st.markdown("---")
        
        # Info
        st.info(f"📊 **{len(data)}** familles dans l'extraction")
        
        # Bloquer si profs manquants
        if missing_teachers:
            st.error("⛔ Vous devez d'abord configurer tous les professeurs ci-dessus avant de générer les liens.")
            return
        
        # Options communes (On Behalf Of + Méthodes paiement)
        use_on_behalf, selected_teachers, payment_method_types = _render_payment_options(ctx, secrets, "tab1")
        
        # Bouton Relancer manquants (seulement si rapport affiché)
        if st.session_state.get("show_payment_report") and os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            missing_families = report.get("missing_families", [])
            
            if missing_families:
                st.markdown("---")
                if st.button("🔁 Relancer uniquement les liens manquants", width="stretch", key="relaunch_missing"):
                    familles_euros = ctx["load_familles_euros"]()
                    tarifs_speciaux = ctx["load_tarifs_speciaux"]()

                    progress = st.progress(0)
                    status = st.empty()

                    def callback(p, m):
                        progress.progress(p)
                        status.info(m)

                    target_family_ids = [f["family_id"] for f in missing_families]

                    result = run_create_payment_links(
                        data, secrets, familles_euros, tarifs_speciaux,
                        use_on_behalf, selected_teachers, ctx["DATA_DIR"], callback,
                        payment_method_types=payment_method_types,
                        target_family_ids=target_family_ids,
                        skip_if_exists=True,
                    )

                    if result["success"]:
                        st.session_state.regenerated_families = target_family_ids
                        st.session_state.show_goto_invoices = True
                        st.session_state.show_payment_report = True
                        st.success("✅ Relance terminée !")
                        st.rerun()
                    else:
                        st.error(f"❌ Erreur : {result['error']}")

        # Bouton principal
        if st.button("🚀 Générer les liens", type="primary", width="stretch", key="gen_all_links"):
            familles_euros = ctx["load_familles_euros"]()
            tarifs_speciaux = ctx["load_tarifs_speciaux"]()
            
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_create_payment_links(
                data, secrets, familles_euros, tarifs_speciaux,
                use_on_behalf, selected_teachers, ctx["DATA_DIR"], callback,
                payment_method_types=payment_method_types,
            )
            
            if result["success"]:
                st.session_state.show_payment_report = True  # Activer l'affichage du rapport
                st.rerun()
            else:
                st.error(f"❌ Erreur : {result['error']}")
        
        # Bouton vers génération factures (après régénération)
        if st.session_state.get("show_goto_invoices"):
            st.markdown("---")
            st.success("✅ Liens régénérés ! Vous pouvez maintenant régénérer les factures correspondantes.")
            if st.button("📄 Aller à Régénérer les factures →", type="primary", width="stretch", key="goto_invoices"):
                st.session_state.current_page = "invoices"
                st.session_state.invoices_tab = "regen"
                st.session_state.show_goto_invoices = False
                st.session_state.show_payment_report = False
                st.rerun()
    
    # ===========================
    # TAB 2: Régénérer pour certaines familles
    # ===========================
    with tab2:
        st.markdown("### 🔄 Régénérer liens pour certaines familles")
        
        st.info("""
        **Utilisez cette option pour :**
        - Corriger un lien de paiement incorrect
        - Régénérer un lien expiré
        - Modifier le montant d'une famille spécifique
        
        ⚠️ Les anciens liens seront remplacés.
        """)
        
        # Bloquer si profs manquants
        if missing_teachers:
            st.error("⛔ Vous devez d'abord configurer tous les professeurs avant de générer les liens.")
            return
        
        # Liste des familles
        family_list = [(fam_id, fam.get("parent_name", fam_id)) for fam_id, fam in data.items()]
        family_names = [f"{name} ({fam_id})" for fam_id, name in family_list]
        
        selected_families_display = st.multiselect(
            "📋 Sélectionnez les familles",
            family_names,
            key="select_families_regen"
        )
        
        # Extraire les IDs
        selected_family_ids = []
        for sel in selected_families_display:
            for fam_id, name in family_list:
                if f"{name} ({fam_id})" == sel:
                    selected_family_ids.append(fam_id)
        
        if selected_family_ids:
            st.info(f"📊 **{len(selected_family_ids)}** famille(s) sélectionnée(s)")
            
            # Options
            use_on_behalf_t2, selected_teachers_t2, payment_method_types_t2 = _render_payment_options(ctx, secrets, "tab2")
            
            if st.button("🔄 Régénérer les liens sélectionnés", type="primary", width="stretch", key="regen_selected"):
                familles_euros = ctx["load_familles_euros"]()
                tarifs_speciaux = ctx["load_tarifs_speciaux"]()
                
                progress = st.progress(0)
                status = st.empty()
                
                def callback(p, m):
                    progress.progress(p)
                    status.info(m)
                
                result = run_create_payment_links(
                    data, secrets, familles_euros, tarifs_speciaux,
                    use_on_behalf_t2, selected_teachers_t2, ctx["DATA_DIR"], callback,
                    payment_method_types=payment_method_types_t2,
                    target_family_ids=selected_family_ids,
                    skip_if_exists=False,  # Forcer la régénération
                )
                
                if result["success"]:
                    st.session_state.regenerated_families = selected_family_ids
                    st.session_state.show_goto_invoices_tab2 = True
                    st.success(f"✅ **{result['links_count']}** liens régénérés !")
                    st.rerun()
                else:
                    st.error(f"❌ Erreur : {result['error']}")
            
            # Bouton vers génération factures
            if st.session_state.get("show_goto_invoices_tab2"):
                st.markdown("---")
                st.warning("⚠️ **Étape suivante** : Régénérez les factures pour ces familles.")
                if st.button("📄 Aller à Régénérer les factures →", type="primary", width="stretch", key="goto_invoices_t2"):
                    st.session_state.current_page = "invoices"
                    st.session_state.invoices_tab = "regen"
                    st.session_state.show_goto_invoices_tab2 = False
                    st.rerun()
        else:
            st.warning("⚠️ Sélectionnez au moins une famille.")

def _render_payment_options(ctx, secrets, prefix):
    """Rend les options de paiement (On Behalf Of + Méthodes) et retourne les valeurs."""
    
    # Options On Behalf Of
    st.markdown("### 👨‍🏫 On Behalf Of")
    
    use_on_behalf = st.checkbox("🔄 Activer On Behalf Of", value=True, key=f"use_on_behalf_{prefix}")
    
    selected_teachers = []
    if use_on_behalf:
        teachers = secrets.get("teachers", {})
        teachers_with_connect = [n for n, i in teachers.items() if i.get("connect_account_id")]
        
        selected_teachers = st.multiselect(
            "Professeurs pour On Behalf Of",
            teachers_with_connect,
            default=teachers_with_connect,
            key=f"selected_teachers_{prefix}"
        )
    
    # Méthodes de paiement avec tooltip pour Revolut
    st.markdown("### 💳 Méthodes de paiement")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        pm_card = st.checkbox("💳 Carte bancaire", value=True, key=f"pm_card_{prefix}")
        pm_link = st.checkbox("🔗 Link", value=True, key=f"pm_link_{prefix}")

    with col2:
        pm_apple = st.checkbox("🍎 Apple Pay", value=True, key=f"pm_apple_{prefix}")
        pm_google = st.checkbox("🤖 Google Pay", value=True, key=f"pm_google_{prefix}")

    with col3:
        # Revolut avec tooltip
        col_rev, col_help = st.columns([4, 1])
        with col_rev:
            pm_revolut = st.checkbox("🔄 Revolut Pay", value=True, key=f"pm_revolut_{prefix}")
        with col_help:
            st.markdown("""
            <span title="Revolut Pay est géré via les réglages Stripe" style="cursor: help; color: #666;">❓</span>
            """, unsafe_allow_html=True)
        pm_klarna = st.checkbox("🟢 Klarna", value=True, key=f"pm_klarna_{prefix}")

    with col4:
        pm_twint = st.checkbox("🇨🇭 Twint", value=True, key=f"pm_twint_{prefix}")

    payment_method_types = []

    if pm_card or pm_apple or pm_google:
        payment_method_types.append("card")
    if pm_link:
        payment_method_types.append("link")
    if pm_klarna:
        payment_method_types.append("klarna")
    if pm_twint:
        payment_method_types.append("twint")

    if not payment_method_types:
        payment_method_types = ["card"]
    
    st.warning("⚠️ Vérifiez dans les paramètres Stripe que ces méthodes sont bien actives !")
    
    return use_on_behalf, selected_teachers, payment_method_types


def page_invoices(ctx):
    st.markdown('<div class="section-title">📄 Générer les Factures</div>', unsafe_allow_html=True)
    
    if not st.session_state.has_extracted:
        st.warning("⚠️ Vous devez d'abord extraire les données TutorBird.")
        return
    
    data = ctx["load_extracted_data"]()
    secrets = ctx["load_secrets"]()
    latest = ctx["get_latest_invoice_folder"]()
    
    if not data:
        st.error("❌ Aucune donnée extraite")
        return
    
    # Onglets
    default_tab = 1 if st.session_state.get("invoices_tab") == "regen" else 0
    tab1, tab2 = st.tabs(["📄 Générer toutes les factures", "🔄 Régénérer certaines factures"])
    
    # ===========================
    # TAB 1: Générer toutes les factures
    # ===========================
    with tab1:
        st.info(f"📊 **{len(data)}** familles à facturer")
        
        links_path = os.path.join(ctx["DATA_DIR"], "payment_links_output.json")
        if not os.path.exists(links_path):
            st.warning("⚠️ Les liens de paiement n'ont pas été générés.")
        
        # Logo
        candidates = [
            os.path.join(ctx["BASE_DIR"], "Professor_logo_dernier.png"),
            os.path.join(ctx["BASE_DIR"], "assets", "logo.png"),
        ]
        logo_path = next((p for p in candidates if os.path.exists(p)), None)

        if not logo_path:
            st.warning("⚠️ Logo non trouvé")
        
        if st.button("📄 Générer les factures", type="primary", width="stretch", key="gen_all_invoices"):
            familles_euros = ctx["load_familles_euros"]()
            
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_generate_invoices(
                data, secrets, familles_euros, ctx["DATA_DIR"], ctx["BASE_DIR"], logo_path, callback
            )
            
            if result["success"]:
                st.success(f"✅ **{result['invoices']}** factures créées")
            else:
                st.error(f"❌ Erreur : {result['error']}")
    
    # ===========================
    # TAB 2: Régénérer certaines factures
    # ===========================
    with tab2:
        st.markdown("### 🔄 Régénérer factures pour certaines familles")
        
        if latest:
            st.warning(f"""
            ⚠️ **Attention** : Les nouvelles factures remplaceront celles existantes dans le dossier :
            **{latest['name']}**
            """)
        else:
            st.error("❌ Aucun dossier de factures existant. Générez d'abord toutes les factures.")
            return
        
        st.info("""
        💡 **Note** : La mise à jour Notion n'est nécessaire que si le **prix** ou les **horaires** ont changé.
        Si vous corrigez uniquement une erreur de mise en page, pas besoin de mettre à jour Notion.
        """)
        
        # Pré-sélection si venant de la page paiements
        preselected = st.session_state.get("regenerated_families", [])
        
        # Liste des familles
        family_list = [(fam_id, fam.get("parent_name", fam_id)) for fam_id, fam in data.items()]
        family_names = [f"{name} ({fam_id})" for fam_id, name in family_list]
        
        # Pré-sélectionner
        default_selection = []
        for fam_id in preselected:
            for fid, name in family_list:
                if fid == fam_id:
                    default_selection.append(f"{name} ({fid})")
        
        selected_families_display = st.multiselect(
            "📋 Sélectionnez les familles",
            family_names,
            default=default_selection,
            key="select_families_invoices_regen"
        )
        
        # Extraire les IDs
        selected_family_ids = []
        for sel in selected_families_display:
            for fam_id, name in family_list:
                if f"{name} ({fam_id})" == sel:
                    selected_family_ids.append(fam_id)
        
        if selected_family_ids:
            st.info(f"📊 **{len(selected_family_ids)}** famille(s) sélectionnée(s)")
            
            if st.button("🔄 Régénérer les factures sélectionnées", type="primary", width="stretch", key="regen_invoices"):
                familles_euros = ctx["load_familles_euros"]()
                
                # Logo
                candidates = [
                    os.path.join(ctx["BASE_DIR"], "Professor_logo_dernier.png"),
                    os.path.join(ctx["BASE_DIR"], "assets", "logo.png"),
                ]
                logo_path = next((p for p in candidates if os.path.exists(p)), None)
                
                progress = st.progress(0)
                status = st.empty()
                
                def callback(p, m):
                    progress.progress(p)
                    status.info(m)
                
                # Filtrer les données pour les familles sélectionnées
                filtered_data = {fid: fam for fid, fam in data.items() if fid in selected_family_ids}
                
                # ⚠️ IMPORTANT : Passer le dossier existant pour ne pas en créer un nouveau
                result = run_generate_invoices(
                    filtered_data, secrets, familles_euros, ctx["DATA_DIR"], ctx["BASE_DIR"], logo_path, callback,
                    target_folder_path=latest["path"]  # Utiliser le dossier existant !
                )
                
                if result["success"]:
                    st.session_state.regenerated_invoices_families = selected_family_ids
                    st.session_state.regenerated_invoices_paths = result.get("generated_files", [])
                    st.session_state.show_download_invoices = True
                    st.success(f"✅ **{result['invoices']}** factures régénérées dans **{latest['name']}** !")
                    st.rerun()
                else:
                    st.error(f"❌ Erreur : {result['error']}")
            
            # Bouton téléchargement après régénération
            if st.session_state.get("show_download_invoices"):
                st.markdown("---")
                
                generated_files = st.session_state.get("regenerated_invoices_paths", [])
                
                if generated_files:
                    st.success(f"📄 **{len(generated_files)}** facture(s) régénérée(s)")
                    
                    # Créer un ZIP des factures régénérées
                    import zipfile
                    import io
                    
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                        for file_path in generated_files:
                            if os.path.exists(file_path):
                                zf.write(file_path, os.path.basename(file_path))
                    
                    zip_buffer.seek(0)
                    
                    st.download_button(
                        label="📥 Télécharger les factures régénérées (ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name="factures_regenerees.zip",
                        mime="application/zip",
                        width="stretch"
                    )
                    
                    # Afficher la liste des fichiers
                    with st.expander("📋 Fichiers régénérés"):
                        for f in generated_files:
                            st.write(f"• {os.path.basename(f)}")
                
                st.markdown("---")
                st.info("💡 **Rappel** : Mettez à jour Notion uniquement si le prix ou les horaires ont changé.")
                
                if st.button("📤 Aller à Mettre à jour Notion →", width="stretch", key="goto_notion"):
                    st.session_state.current_page = "update"
                    st.session_state.update_tab = "selective"
                    st.session_state.show_download_invoices = False
                    st.rerun()
                
                if st.button("✅ Terminé (pas besoin de Notion)", width="stretch", key="done_no_notion"):
                    st.session_state.show_download_invoices = False
                    st.session_state.regenerated_invoices_families = []
                    st.session_state.regenerated_invoices_paths = []
                    st.rerun()
        else:
            st.warning("⚠️ Sélectionnez au moins une famille.")
        
        # Clear le flag après affichage
        st.session_state.invoices_tab = None


def page_send(ctx):
    st.markdown('<div class="section-title">📧 Envoyer les Factures</div>', unsafe_allow_html=True)
    
    data = ctx["load_extracted_data"]()
    secrets = ctx["load_secrets"]()
    latest = ctx["get_latest_invoice_folder"]()
    
    if not data:
        st.warning("⚠️ Aucune donnée extraite")
        return
    
    if not latest:
        st.warning("⚠️ Aucun dossier de factures trouvé")
        return
    
    # Vérifier config email
    gmail_config = secrets.get("gmail", {}) if secrets else {}
    if not gmail_config.get("email") or not gmail_config.get("app_password"):
        st.error("❌ Configuration email manquante. Allez dans Paramètres > Email pour configurer.")
        if st.button("⚙️ Aller aux paramètres"):
            st.session_state.current_page = "config"
            st.rerun()
        return
    
    st.info(f"📁 Dossier : **{latest['name']}**")
    
    # Template avec mois automatique
    month_name, year = ctx["get_month_year_from_folder"](latest)
    template = get_default_email_template(month_name, year)
    
    subject = st.text_input("📝 Sujet", value=template["subject"])
    body = st.text_area("✉️ Message", value=template["body"], height=250)
    
    st.markdown("---")
    
    # Options d'envoi
    st.markdown("### 📬 Options d'envoi")
    
    col1, col2 = st.columns(2)
    with col1:
        send_all = st.radio(
            "Envoyer à :",
            ["Toutes les familles", "Sélection personnalisée"],
            key="send_mode"
        )
    
    with col2:
        send_test = st.checkbox("📧 Envoyer d'abord à moi-même (test)", value=True)
    
    selected_families = None
    if send_all == "Sélection personnalisée":
        families = get_families_from_folder(latest["path"], data)
        family_names = [f["parent_name"] for f in families]
        selected_names = st.multiselect("Sélectionner les familles", family_names)
        selected_families = [f["family_id"] for f in families if f["parent_name"] in selected_names]
    
    if send_test:
        if st.button("📧 Envoyer le test à moi-même", width="stretch"):
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_send_invoices(
                secrets, data, latest["path"],
                custom_subject=subject, custom_body=body,
                selected_families=selected_families,
                send_to_test=True, callback=callback
            )
            
            if result["success"]:
                st.success(f"✅ Test envoyé à {gmail_config['email']}")
            else:
                st.error(f"❌ Erreur : {result['error']}")
    
    if st.button("📧 Envoyer les factures aux clients", type="primary", width="stretch"):
        progress = st.progress(0)
        status = st.empty()
        
        def callback(p, m):
            progress.progress(p)
            status.info(m)
        
        result = run_send_invoices(
            secrets, data, latest["path"],
            custom_subject=subject, custom_body=body,
            selected_families=selected_families,
            send_to_test=False, callback=callback
        )
        
        if result["success"]:
            st.success(f"✅ **{result['sent']}/{result['total']}** emails envoyés")
            if result.get("errors"):
                for err in result["errors"]:
                    st.warning(f"⚠️ {err}")
        else:
            st.error(f"❌ Erreur : {result['error']}")


def page_reminders(ctx):
    st.markdown('<div class="section-title">🔔 Rappels de Paiement</div>', unsafe_allow_html=True)
    
    data = ctx["load_extracted_data"]()
    secrets = ctx["load_secrets"]()
    latest = ctx["get_latest_invoice_folder"]()
    
    st.info("Envoie des rappels aux familles n'ayant pas encore payé (basé sur Notion).")
    
    # Alerte le 11
    if should_send_automatic_reminder():
        st.warning("🔔 **C'est le 11 du mois !** C'est le bon moment pour envoyer les rappels.")
    
    # Template
    month_name, year = ctx["get_month_year_from_folder"](latest) if latest else (ctx["MONTHS_FR"][datetime.now().month - 1], datetime.now().year)
    template = get_default_reminder_template(month_name, year)
    
    subject = st.text_input("📝 Sujet", value=template["subject"], key="reminder_subject")
    body = st.text_area("✉️ Message", value=template["body"], height=250, key="reminder_body")
    
    st.markdown("---")
    
    # Options
    col1, col2 = st.columns(2)
    with col1:
        send_test = st.checkbox("📧 Envoyer d'abord à moi-même (test)", value=True, key="reminder_test")
    
    # Charger les impayés
    if st.button("🔍 Voir les familles non payées", width="stretch"):
        result = get_unpaid_families_from_notion(secrets)
        if result["success"]:
            unpaid = result["unpaid"]
            st.session_state.unpaid_families = unpaid
            st.info(f"📊 {len(unpaid)} famille(s) avec paiement en attente")
        else:
            st.error(f"❌ Erreur : {result['error']}")
    
    if st.session_state.get("unpaid_families"):
        unpaid = st.session_state.unpaid_families
        with st.expander(f"📋 {len(unpaid)} famille(s) non payée(s)", expanded=True):
            for f in unpaid:
                st.write(f"• **{f['parent_name']}** — {f['amount']:.2f} CHF")
    
    if send_test:
        if st.button("📧 Envoyer le test à moi-même", width="stretch", key="send_reminder_test"):
            if not latest:
                st.error("❌ Aucun dossier de factures")
                return
            
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_send_reminders(
                secrets, data, latest["path"], ctx["DATA_DIR"],
                custom_subject=subject, custom_body=body,
                send_to_test=True, callback=callback
            )
            
            if result["success"]:
                st.success(f"✅ Test envoyé")
            else:
                st.error(f"❌ Erreur : {result['error']}")
    
    if st.button("📧 Envoyer les rappels", type="primary", width="stretch"):
        if not latest:
            st.error("❌ Aucun dossier de factures")
            return
        
        progress = st.progress(0)
        status = st.empty()
        
        def callback(p, m):
            progress.progress(p)
            status.info(m)
        
        result = run_send_reminders(
            secrets, data, latest["path"], ctx["DATA_DIR"],
            custom_subject=subject, custom_body=body,
            send_to_test=False, callback=callback
        )
        
        if result["success"]:
            st.success(f"✅ **{result['sent']}** rappels envoyés")
        else:
            st.error(f"❌ Erreur : {result['error']}")

def page_sync(ctx):
    st.markdown('<div class="section-title">🔄 Sync Stripe → Notion</div>', unsafe_allow_html=True)
    
    st.info("""
    **À quoi sert cette synchronisation ?**
    
    Cette fonction récupère les paiements effectués sur Stripe et :
    1. Marque automatiquement les lignes comme "Payé" dans Notion
    2. Met à jour les tableaux dans les pages des professeurs
    3. Met à jour les récapitulatifs de paiements
    4. Met à jour le dashboard global
    
    **Matching par :** Prof + Élève + Montant (via extraction du reçu Stripe)
    """)
    
    secrets = ctx["load_secrets"]()
    latest = ctx["get_latest_invoice_folder"]()
    
    use_latest = st.checkbox("📅 Depuis le dernier dossier de factures", value=True)
    
    if use_latest and latest:
        since_date = latest["date"]
        st.info(f"📅 Depuis : {since_date.strftime('%d/%m/%Y')}")
    else:
        since_date = st.date_input("📅 Depuis la date")
        since_date = datetime.combine(since_date, time(0, 0))
    
    if st.button("🔄 Synchroniser", type="primary", width="stretch"):
        progress = st.progress(0)
        status = st.empty()
        
        # ===========================
        # ÉTAPE 1: Sync Stripe → Notion (marquer Payé)
        # ===========================
        def callback1(p, m):
            progress.progress(int(p * 0.5))
            status.info(f"[1/2] {m}")
        
        from scripts.sync_stripe_notion import run_sync_stripe_notion
        result1 = run_sync_stripe_notion(secrets, since_date, callback1)
        
        if not result1["success"]:
            st.error(f"❌ Erreur sync Stripe : {result1['error']}")
            return
        
        # ===========================
        # ÉTAPE 2: Mise à jour des pages profs
        # ===========================
        def callback2(p, m):
            progress.progress(50 + int(p * 0.5))
            status.info(f"[2/2] {m}")
        
        from scripts.update_notion_prof_pages import run_update_notion_prof_pages
        result2 = run_update_notion_prof_pages(secrets, callback2, force=False, latest_only=False)
        
        progress.progress(100)
        status.empty()
        
        # ===========================
        # Affichage des résultats
        # ===========================
        if result1["success"] and result2["success"]:
            st.success(f"""
            ✅ **Synchronisation terminée**
            
            **Stripe → Notion :**
            - {result1['synced']} paiement(s) synchronisé(s)
            - {result1['already_paid']} déjà marqué(s) payé(s)
            - {result1.get('student_unknown', 0)} élève(s) inconnu(s) (reçu vide)
            - {result1['total_not_found']} non trouvé(s) dans Notion
            
            **Pages professeurs :**
            - {result2['updated']} page(s) mise(s) à jour
            - {result2['skipped']} page(s) déjà à jour
            - {result2['recaps_updated']} récap(s) mis à jour
            """)
            
            if result1.get("not_found"):
                with st.expander("⚠️ Paiements non trouvés dans Notion"):
                    for nf in result1["not_found"]:
                        st.write(f"• {nf}")
        
        elif result2 and not result2["success"]:
            st.warning(f"""
            ⚠️ **Sync Stripe OK, mais erreur pages profs**
            
            **Stripe → Notion :**
            - {result1['synced']} paiement(s) synchronisé(s)
            
            **Erreur pages profs :**
            {result2['error']}
            """)

"""
Nouvelle version de page_update avec 3 onglets :
1. Ajouter toutes les lignes
2. Mettre à jour certaines lignes  
3. Vérifier & Compléter (NOUVEAU)
"""

def page_update(ctx):
    st.markdown('<div class="section-title">📤 Ajouter lignes Notion</div>', unsafe_allow_html=True)
    
    data = ctx["load_extracted_data"]()
    secrets = ctx["load_secrets"]()
    latest = ctx["get_latest_invoice_folder"]()
    
    if not data:
        st.warning("⚠️ Aucune donnée extraite")
        return
    
    # Onglets
    default_tab = 1 if st.session_state.get("update_tab") == "selective" else 0
    tab1, tab2, tab3 = st.tabs(["➕ Ajouter toutes les lignes", "🔄 Mettre à jour certaines lignes", "🔍 Ajouter ligne(s) manquante(s)"])
    
    # ===========================
    # TAB 1: Ajouter toutes les lignes
    # ===========================
    with tab1:
        st.info(f"""
        **Cette action va :**
        1. Ajouter **{len(data)}** lignes dans la base de données Paiements
        2. Créer les sous-pages dans les pages des professeurs (Prof → Date → Élève)
        
        📁 Basé sur le dernier dossier : **{latest['name'] if latest else 'N/A'}**
        
        ⚠️ Les lignes déjà existantes (même famille + même montant) seront ignorées.
        """)
        
        if st.button("📤 Ajouter les lignes", type="primary", width="stretch", key="add_all_notion"):
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            result = run_update_notion(secrets, data, ctx["BASE_DIR"], callback)
            
            if result["success"]:
                st.success(f"""
                ✅ **Mise à jour terminée**
                - {result['added']} ligne(s) ajoutée(s)
                - {result['skipped']} ligne(s) ignorée(s) (doublons)
                - {result['pages_created']} sous-page(s) prof créée(s)
                """)
            else:
                st.error(f"❌ Erreur : {result['error']}")
    
    # ===========================
    # TAB 2: Mettre à jour certaines lignes
    # ===========================
    with tab2:
        st.markdown("### 🔄 Mettre à jour certaines lignes Notion")
        
        st.info("""
        **Cette option permet de :**
        - Remplacer les valeurs des lignes existantes pour certaines familles
        - Mettre à jour les sous-pages des professeurs concernés
        
        ⚠️ Utilisez cette option après avoir régénéré des factures pour certains clients.
        """)
        
        if latest:
            st.warning(f"📁 Les modifications concerneront le dossier : **{latest['name']}**")
        else:
            st.error("❌ Aucun dossier de factures trouvé.")
            return
        
        # ===========================
        # CHOIX DU MODE DE SÉLECTION
        # ===========================
        mode = st.radio(
            "🔍 Mode de sélection :",
            ["👨‍👩‍👧 Par famille", "👨‍🏫 Par professeur"],
            horizontal=True,
            key="update_selection_mode"
        )
        
        st.markdown("---")
        
        selected_family_ids = []
        selected_teachers = []
        
        # ===========================
        # MODE PAR FAMILLE
        # ===========================
        if mode == "👨‍👩‍👧 Par famille":
            # Pré-sélection si venant de la page factures
            preselected = st.session_state.get("regenerated_invoices_families", [])
            
            # Liste des familles
            family_list = [(fam_id, fam.get("parent_name", fam_id)) for fam_id, fam in data.items()]
            family_names = [f"{name} ({fam_id})" for fam_id, name in family_list]
            
            # Pré-sélectionner
            default_selection = []
            for fam_id in preselected:
                for fid, name in family_list:
                    if fid == fam_id:
                        default_selection.append(f"{name} ({fid})")
            
            selected_families_display = st.multiselect(
                "📋 Sélectionnez les familles à mettre à jour",
                family_names,
                default=default_selection,
                key="select_families_notion_update_mode1"
            )
            
            # Extraire les IDs
            for sel in selected_families_display:
                for fam_id, name in family_list:
                    if f"{name} ({fam_id})" == sel:
                        selected_family_ids.append(fam_id)
            
            if selected_family_ids:
                # Récupérer TOUS les profs de ces familles automatiquement
                for fam_id in selected_family_ids:
                    fam = data.get(fam_id, {})
                    lessons = fam.get("lessons", [])
                    for L in lessons:
                        teacher = L.get("teacher", "")
                        if teacher and teacher not in selected_teachers:
                            selected_teachers.append(teacher)
                
                st.info(f"📊 **{len(selected_family_ids)}** famille(s) sélectionnée(s) → **{len(selected_teachers)}** professeur(s) concerné(s)")
        
        # ===========================
        # MODE PAR PROFESSEUR
        # ===========================
        else:
            # Récupérer tous les profs avec le nombre de familles
            all_teachers = {}
            for fam_id, fam in data.items():
                lessons = fam.get("lessons", [])
                for L in lessons:
                    teacher = L.get("teacher", "")
                    if teacher:
                        if teacher not in all_teachers:
                            all_teachers[teacher] = {"families": set(), "count": 0}
                        all_teachers[teacher]["families"].add(fam_id)
                        all_teachers[teacher]["count"] = len(all_teachers[teacher]["families"])
            
            # Liste des profs avec leur nombre de familles
            teacher_options = [f"{name} ({info['count']} famille(s))" for name, info in sorted(all_teachers.items())]
            
            selected_teachers_display = st.multiselect(
                "👨‍🏫 Sélectionnez les professeurs",
                teacher_options,
                key="select_teachers_notion_update_mode2"
            )
            
            # Extraire les noms et les familles concernées
            for sel in selected_teachers_display:
                teacher_name = sel.split(" (")[0]
                selected_teachers.append(teacher_name)
                
                # Ajouter toutes les familles de ce prof
                if teacher_name in all_teachers:
                    for fam_id in all_teachers[teacher_name]["families"]:
                        if fam_id not in selected_family_ids:
                            selected_family_ids.append(fam_id)
            
            if selected_teachers:
                st.info(f"👨‍🏫 **{len(selected_teachers)}** professeur(s) sélectionné(s) → **{len(selected_family_ids)}** famille(s) concernée(s)")
        
        # ===========================
        # BOUTON D'ACTION
        # ===========================
        if selected_family_ids and selected_teachers:
            st.markdown("---")
            
            st.warning(f"""
            ⚠️ **Cette action va :**
            1. Scanner les factures PDF du dossier **{latest['name']}**
            2. Mettre à jour **{len(selected_family_ids)}** ligne(s) Notion
            3. Professeurs concernés : {', '.join(selected_teachers)}
            """)
            
            if st.button("🔄 Mettre à jour les lignes sélectionnées", type="primary", width="stretch", key="update_selective_notion"):
                progress = st.progress(0)
                status = st.empty()
                
                def callback(p, m):
                    progress.progress(p)
                    status.info(m)
                
                # Appel de la fonction de mise à jour sélective
                result = run_update_notion_selective(
                    secrets, 
                    data, 
                    latest["path"],
                    selected_family_ids,
                    selected_teachers,
                    callback
                )
                
                if result["success"]:
                    st.success(f"""
                    ✅ **Mise à jour terminée !**
                    - 📄 {result.get('invoices_found', 0)} facture(s) trouvée(s)
                    - ✏️ {result.get('rows_updated', 0)} ligne(s) Notion mise(s) à jour
                    - 📁 {result.get('subpages_updated', 0)} sous-page(s) prof mise(s) à jour
                    """)
                    
                    if result.get("details"):
                        with st.expander("📋 Détails des mises à jour"):
                            for detail in result["details"]:
                                st.write(f"• **{detail['family']}** / {detail['teacher']} : {detail['amount']} {detail['currency']}")
                    
                    if result.get("not_found"):
                        with st.expander("⚠️ Factures non trouvées"):
                            for nf in result["not_found"]:
                                st.write(f"• {nf}")
                    
                    # Clear les flags
                    st.session_state.regenerated_invoices_families = []
                    st.session_state.update_tab = None
                else:
                    st.error(f"❌ Erreur : {result['error']}")
        else:
            st.warning("⚠️ Sélectionnez au moins une famille ou un professeur.")
        
        # Clear le flag après affichage
        st.session_state.update_tab = None
    
    # ===========================
    # TAB 3: Ajouter ligne(s) manquante(s) (NOUVEAU)
    # ===========================
    with tab3:
        st.markdown("### 🔍 Ajouter ligne(s) manquante(s)")
        
        st.info("""
        **Cette option permet de :**
        1. Scanner toutes les factures du dossier actuel
        2. Comparer avec les lignes Notion existantes
        3. Identifier les lignes manquantes
        4. Ajouter automatiquement les lignes manquantes
        
        💡 Utile pour s'assurer que toutes les factures ont bien une ligne dans Notion.
        """)
        
        if not latest:
            st.error("❌ Aucun dossier de factures trouvé.")
            return
        
        st.warning(f"📁 Dossier analysé : **{latest['name']}**")
        
        # ===========================
        # ÉTAPE 1: SCAN ET COMPARAISON
        # ===========================
        if st.button("🔍 Scanner et comparer", type="primary", width="stretch", key="scan_compare_notion"):
            progress = st.progress(0)
            status = st.empty()
            
            def callback(p, m):
                progress.progress(p)
                status.info(m)
            
            from scripts.update_notion import run_scan_and_compare
            result = run_scan_and_compare(secrets, data, latest["path"], callback)
            
            if result["success"]:
                # Stocker le résultat dans session_state pour l'utiliser après
                st.session_state.scan_compare_result = result
                
                missing = result.get("missing", [])
                already_exists = result.get("already_exists", [])
                
                st.success(f"""
                ✅ **Scan terminé !**
                - 📄 **{result['invoices_scanned']}** facture(s) scannée(s)
                - 📋 **{result['notion_rows']}** lignes Notion existantes
                - ✅ **{len(already_exists)}** déjà dans Notion
                - ⚠️ **{len(missing)}** manquante(s)
                """)
                
                if missing:
                    st.warning(f"⚠️ **{len(missing)} ligne(s) manquante(s) dans Notion :**")
                    
                    # Afficher les détails dans un tableau
                    missing_data = []
                    for m in missing:
                        missing_data.append({
                            "Famille": m["family_name"],
                            "Professeur": m["teacher"],
                            "Montant": f"{m['amount']:.2f} {m.get('currency', 'CHF')}",
                            "Élèves": m.get("students_formatted", ""),
                        })
                    
                    st.dataframe(missing_data, width="stretch", hide_index=True)
                else:
                    st.success("🎉 **Toutes les factures ont une ligne dans Notion !**")
            else:
                st.error(f"❌ Erreur : {result['error']}")
        
        # ===========================
        # ÉTAPE 2: AJOUTER LES MANQUANTES
        # ===========================
        if "scan_compare_result" in st.session_state:
            result = st.session_state.scan_compare_result
            missing = result.get("missing", [])
            
            if missing:
                st.markdown("---")
                st.markdown("### ➕ Ajouter les lignes manquantes")
                
                if st.button(f"➕ Ajouter les {len(missing)} ligne(s) manquante(s)", type="primary", width="stretch", key="add_missing_notion"):
                    progress = st.progress(0)
                    status = st.empty()
                    
                    def callback(p, m):
                        progress.progress(p)
                        status.info(m)
                    
                    from scripts.update_notion import run_add_missing_rows
                    add_result = run_add_missing_rows(secrets, data, missing, callback)
                    
                    if add_result["success"]:
                        st.success(f"""
                        ✅ **Ligne(s) ajoutée(s) !**
                        - ➕ **{add_result['added']}** ligne(s) ajoutée(s) dans Notion
                        """)
                        
                        # Afficher les erreurs s'il y en a
                        if add_result.get("errors"):
                            with st.expander("⚠️ Erreurs rencontrées"):
                                for err in add_result["errors"]:
                                    st.error(err)
                        
                        # Clear le résultat
                        del st.session_state.scan_compare_result
                        
                        # Proposer d'aller vers Sync Stripe
                        if add_result['added'] > 0:
                            st.markdown("---")
                            st.info("💡 **Prochaine étape :** Allez sur **Sync Stripe → Notion** pour synchroniser les paiements et mettre à jour les pages des professeurs.")
                            
                            if st.button("🔄 Aller vers Sync Stripe → Notion", width="stretch", key="go_to_sync"):
                                st.session_state.current_page = "sync"
                                st.rerun()
                    else:
                        st.error(f"❌ Erreur : {add_result['error']}")

def page_config(ctx):
    st.markdown('<div class="section-title">⚙️ Configuration</div>', unsafe_allow_html=True)
    
    tab1, tab2, tab3, tab4 = st.tabs(["👨‍🏫 Professeurs", "💶 Familles EUR", "🏷️ Tarifs spéciaux", "📧 Email"])
    
    # ===========================
    # TAB 1: Professeurs
    # ===========================
    with tab1:
        secrets = ctx["load_secrets"]()
        if not secrets:
            st.error("❌ secrets.yaml non trouvé")
            return

        if "teachers" not in secrets:
            secrets["teachers"] = {}

        teachers = secrets.get("teachers", {})

        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown("### 👨‍🏫 Gestion des professeurs")
        with cols[1]:
            if st.session_state.get("return_to_page"):
                if st.button("↩ Retour", width="stretch"):
                    st.session_state.current_page = st.session_state.return_to_page
                    st.session_state.return_to_page = ""
                    st.rerun()

        t_add, t_edit = st.tabs(["➕ Ajouter", "✏️ Modifier"])

        with t_add:

            # Message important sur Render
            st.warning("""
            ⚠️ **Important** : Après avoir ajouté un nouveau professeur ici, pensez à **l'ajouter également dans Render** 
            (variables d'environnement du webhook) pour que l'automatisation Stripe → Notion fonctionne correctement !
            """)
            prefill = st.session_state.get("prefill_new_teacher_name", "")

            new_name = st.text_input(
                "Nom du professeur (doit matcher TutorBird)",
                value=prefill,
                key="ui_new_teacher_name",
            )

            col1, col2 = st.columns(2)
            with col1:
                new_chf = st.number_input("💰 Tarif CHF/h", value=0.0, step=1.0, key="ui_new_teacher_chf")
            with col2:
                new_eur = st.number_input("💶 Tarif EUR/h", value=0.0, step=1.0, key="ui_new_teacher_eur")

            new_connect = st.text_input("🔗 Stripe Connect ID (optionnel)", value="", key="ui_new_teacher_connect")

            if st.button("✅ Créer le professeur", type="primary", width="stretch"):
                name = (new_name or "").strip()
                if not name:
                    st.error("❌ Nom vide")
                elif name in teachers:
                    st.warning("⚠️ Ce professeur existe déjà.")
                else:
                    teachers[name] = {
                        "connect_account_id": (new_connect or "").strip(),
                        "pay_rate": {
                            "chf": float(new_chf),
                            "eur": float(new_eur)
                        }
                    }
                    secrets["teachers"] = teachers
                    ctx["save_secrets"](secrets)

                    st.success("✅ Professeur ajouté !")
                    st.session_state.prefill_new_teacher_name = ""

                    report_path = os.path.join(ctx["DATA_DIR"], "payment_links_report.json")
                    if os.path.exists(report_path):
                        os.remove(report_path)

                    return_to = st.session_state.get("return_to_page", "")
                    if return_to:
                        st.session_state.current_page = return_to
                        st.session_state.return_to_page = ""

                    st.rerun()

        with t_edit:
            if not teachers:
                st.info("Aucun professeur configuré.")
            else:
                # Créer les données pour le tableau
                teacher_names = list(teachers.keys())
                
                # Préparer les données pour st.data_editor
                table_data = []
                for name in teacher_names:
                    t_data = teachers[name]
                    table_data.append({
                        "Professeur": name,
                        "CHF/h": float(t_data.get("pay_rate", {}).get("chf", 0)),
                        "EUR/h": float(t_data.get("pay_rate", {}).get("eur", 0)),
                        "Stripe Connect ID": t_data.get("connect_account_id") or "",
                        "Supprimer": False
                    })
                
                # Afficher le tableau éditable
                edited_df = st.data_editor(
                    table_data,
                    column_config={
                        "Professeur": st.column_config.TextColumn(
                            "👨‍🏫 Professeur",
                            disabled=True,
                            width="medium"
                        ),
                        "CHF/h": st.column_config.NumberColumn(
                            "💰 CHF/h",
                            min_value=0,
                            max_value=500,
                            step=1,
                            format="%.2f",
                            width="small"
                        ),
                        "EUR/h": st.column_config.NumberColumn(
                            "💶 EUR/h",
                            min_value=0,
                            max_value=500,
                            step=1,
                            format="%.2f",
                            width="small"
                        ),
                        "Stripe Connect ID": st.column_config.TextColumn(
                            "🔗 Stripe Connect ID",
                            width="large"
                        ),
                        "Supprimer": st.column_config.CheckboxColumn(
                            "🗑️",
                            width="small",
                            default=False
                        )
                    },
                    hide_index=True,
                    width="stretch",
                    key="teachers_table"
                )
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("💾 Sauvegarder les modifications", type="primary", width="stretch"):
                        # Mettre à jour les données
                        for row in edited_df:
                            name = row["Professeur"]
                            if name in teachers:
                                teachers[name]["pay_rate"]["chf"] = float(row["CHF/h"])
                                teachers[name]["pay_rate"]["eur"] = float(row["EUR/h"])
                                teachers[name]["connect_account_id"] = (row["Stripe Connect ID"] or "").strip()
                        
                        secrets["teachers"] = teachers
                        ctx["save_secrets"](secrets)
                        st.success("✅ Modifications sauvegardées !")
                
                with col2:
                    # Compter les suppressions cochées
                    to_delete = [row["Professeur"] for row in edited_df if row.get("Supprimer")]
                    
                    if to_delete:
                        if st.button(f"🗑️ Supprimer ({len(to_delete)})", width="stretch"):
                            for name in to_delete:
                                if name in teachers:
                                    del teachers[name]
                            secrets["teachers"] = teachers
                            ctx["save_secrets"](secrets)
                            st.success(f"✅ {len(to_delete)} professeur(s) supprimé(s)")
                            st.rerun()
                    else:
                        st.button("🗑️ Supprimer", width="stretch", disabled=True)
    
    # ===========================
    # TAB 2: Familles EUR (AMÉLIORÉ)
    # ===========================
    with tab2:
        st.markdown("### 💶 Familles facturées en EUR")
        
        familles_eur = ctx["load_familles_euros"]()
        data = ctx["load_extracted_data"]()
        
        # Récupérer toutes les familles depuis TutorBird
        all_families = []
        if data:
            for fam_id, fam_data in data.items():
                parent_name = fam_data.get("parent_name") or fam_data.get("family_name") or ""
                if parent_name and parent_name not in all_families:
                    all_families.append(parent_name)
        all_families.sort()
        
        st.info(f"📋 **{len(familles_eur)}** famille(s) configurée(s) en EUR")
        
        # Afficher les familles existantes dans un tableau
        if familles_eur:
            table_data = []
            for fam in familles_eur:
                table_data.append({
                    "Famille": fam,
                    "Supprimer": False
                })
            
            edited_fam_df = st.data_editor(
                table_data,
                column_config={
                    "Famille": st.column_config.TextColumn(
                        "👨‍👩‍👧 Famille",
                        disabled=True,
                        width="large"
                    ),
                    "Supprimer": st.column_config.CheckboxColumn(
                        "🗑️",
                        width="small",
                        default=False
                    )
                },
                hide_index=True,
                width="stretch",
                key="familles_eur_table"
            )
            
            # Bouton supprimer
            to_delete_fam = [row["Famille"] for row in edited_fam_df if row.get("Supprimer")]
            if to_delete_fam:
                if st.button(f"🗑️ Supprimer {len(to_delete_fam)} famille(s)", width="stretch"):
                    for fam in to_delete_fam:
                        if fam in familles_eur:
                            familles_eur.remove(fam)
                    ctx["save_familles_euros"](familles_eur)
                    st.success(f"✅ {len(to_delete_fam)} famille(s) supprimée(s)")
                    st.rerun()
        
        st.markdown("---")
        st.markdown("#### ➕ Ajouter une famille en EUR")
        
        # Filtrer les familles qui ne sont pas encore en EUR
        available_families = [f for f in all_families if f not in familles_eur]
        
        if available_families:
            col1, col2 = st.columns([3, 1])
            with col1:
                selected_family = st.selectbox(
                    "Sélectionner une famille",
                    options=[""] + available_families,
                    format_func=lambda x: "-- Choisir une famille --" if x == "" else x,
                    key="select_famille_eur"
                )
            with col2:
                st.write("")  # Spacer
                st.write("")  # Spacer
                add_disabled = selected_family == ""
                if st.button("➕ Ajouter", type="primary", width="stretch", disabled=add_disabled, key="btn_add_fam_eur"):
                    if selected_family:
                        familles_eur.append(selected_family)
                        ctx["save_familles_euros"](familles_eur)
                        st.success(f"✅ **{selected_family}** ajoutée aux familles EUR")
                        st.rerun()
        else:
            if all_families:
                st.success("✅ Toutes les familles sont déjà configurées en EUR !")
            else:
                st.warning("⚠️ Aucune famille disponible. Lancez d'abord une extraction TutorBird.")
        
        # Option pour ajouter manuellement
        with st.expander("📝 Ajouter manuellement (si non présent dans TutorBird)"):
            manual_fam = st.text_input("Nom de la famille", key="manual_famille_eur")
            if st.button("➕ Ajouter manuellement", key="btn_add_manual_eur"):
                if manual_fam and manual_fam.strip():
                    if manual_fam.strip() not in familles_eur:
                        familles_eur.append(manual_fam.strip())
                        ctx["save_familles_euros"](familles_eur)
                        st.success(f"✅ **{manual_fam.strip()}** ajoutée")
                        st.rerun()
                    else:
                        st.warning("⚠️ Cette famille est déjà dans la liste")
    
    # ===========================
    # TAB 3: Tarifs spéciaux (AMÉLIORÉ)
    # ===========================
    with tab3:
        st.markdown("### 🏷️ Tarifs spéciaux")
        st.caption("Définissez des tarifs personnalisés pour certaines combinaisons professeur/famille")
        
        tarifs = ctx["load_tarifs_speciaux"]()
        secrets = ctx["load_secrets"]()
        data = ctx["load_extracted_data"]()
        
        # Récupérer les profs et familles
        teacher_names = list(secrets.get("teachers", {}).keys()) if secrets else []
        
        all_families = []
        if data:
            for fam_id, fam_data in data.items():
                parent_name = fam_data.get("parent_name") or fam_data.get("family_name") or ""
                if parent_name and parent_name not in all_families:
                    all_families.append(parent_name)
        all_families.sort()
        
        st.info(f"📋 **{len(tarifs)}** tarif(s) spécial(aux) configuré(s)")
        
        # Afficher les tarifs existants dans un tableau
        if tarifs:
            table_data = []
            for t in tarifs:
                devise = t.get("currency", "EUR")
                if devise == "EUR" or "eur" in str(t.get("pay_rate", "")).lower():
                    devise = "EUR"
                    montant = t.get("pay_rate", 0)
                else:
                    devise = "CHF"
                    montant = t.get("pay_rate_chf", t.get("pay_rate", 0))
                
                table_data.append({
                    "Professeur": t.get("teacher", ""),
                    "Famille": t.get("parent", ""),
                    "Tarif": f"{montant}",
                    "Devise": devise,
                    "Supprimer": False
                })
            
            edited_tarifs_df = st.data_editor(
                table_data,
                column_config={
                    "Professeur": st.column_config.TextColumn(
                        "👨‍🏫 Professeur",
                        disabled=True,
                        width="medium"
                    ),
                    "Famille": st.column_config.TextColumn(
                        "👨‍👩‍👧 Famille",
                        disabled=True,
                        width="medium"
                    ),
                    "Tarif": st.column_config.TextColumn(
                        "💰 Tarif/h",
                        disabled=True,
                        width="small"
                    ),
                    "Devise": st.column_config.TextColumn(
                        "💱 Devise",
                        disabled=True,
                        width="small"
                    ),
                    "Supprimer": st.column_config.CheckboxColumn(
                        "🗑️",
                        width="small",
                        default=False
                    )
                },
                hide_index=True,
                width="stretch",
                key="tarifs_speciaux_table"
            )
            
            # Bouton supprimer
            to_delete_idx = [i for i, row in enumerate(edited_tarifs_df) if row.get("Supprimer")]
            if to_delete_idx:
                if st.button(f"🗑️ Supprimer {len(to_delete_idx)} tarif(s)", width="stretch"):
                    # Supprimer en ordre inverse pour éviter les problèmes d'index
                    for idx in sorted(to_delete_idx, reverse=True):
                        if idx < len(tarifs):
                            tarifs.pop(idx)
                    ctx["save_tarifs_speciaux"](tarifs)
                    st.success(f"✅ {len(to_delete_idx)} tarif(s) supprimé(s)")
                    st.rerun()
        
        st.markdown("---")
        st.markdown("#### ➕ Ajouter un tarif spécial")
        
        if not teacher_names:
            st.warning("⚠️ Aucun professeur configuré. Ajoutez d'abord des professeurs.")
        elif not all_families:
            st.warning("⚠️ Aucune famille disponible. Lancez d'abord une extraction TutorBird.")
        else:
            col1, col2 = st.columns(2)
            
            with col1:
                selected_teacher = st.selectbox(
                    "👨‍🏫 Professeur",
                    options=[""] + teacher_names,
                    format_func=lambda x: "-- Choisir un professeur --" if x == "" else x,
                    key="tarif_select_teacher"
                )
            
            with col2:
                selected_parent = st.selectbox(
                    "👨‍👩‍👧 Famille",
                    options=[""] + all_families,
                    format_func=lambda x: "-- Choisir une famille --" if x == "" else x,
                    key="tarif_select_parent"
                )
            
            col3, col4 = st.columns(2)
            
            with col3:
                tarif_amount = st.number_input(
                    "💰 Tarif horaire",
                    min_value=0.0,
                    max_value=500.0,
                    value=25.0,
                    step=1.0,
                    key="tarif_amount"
                )
            
            with col4:
                tarif_devise = st.selectbox(
                    "💱 Devise",
                    options=["EUR", "CHF"],
                    key="tarif_devise"
                )
            
            # Vérifier si ce tarif existe déjà
            already_exists = False
            if selected_teacher and selected_parent:
                for t in tarifs:
                    if t.get("teacher") == selected_teacher and t.get("parent") == selected_parent:
                        already_exists = True
                        break
            
            if already_exists:
                st.warning(f"⚠️ Un tarif spécial existe déjà pour **{selected_teacher}** / **{selected_parent}**")
            
            add_disabled = not selected_teacher or not selected_parent or already_exists
            
            if st.button("➕ Ajouter le tarif spécial", type="primary", width="stretch", disabled=add_disabled):
                new_tarif = {
                    "teacher": selected_teacher,
                    "parent": selected_parent,
                    "pay_rate": float(tarif_amount),
                    "currency": tarif_devise
                }
                tarifs.append(new_tarif)
                ctx["save_tarifs_speciaux"](tarifs)
                st.success(f"✅ Tarif spécial ajouté : **{selected_teacher}** / **{selected_parent}** → **{tarif_amount} {tarif_devise}/h**")
                st.rerun()
    
    # ===========================
    # TAB 4: Email
    # ===========================
    with tab4:
        secrets = ctx["load_secrets"]()
        if not secrets:
            secrets = {}
        
        gmail_config = secrets.get("gmail", {})
        
        st.markdown("### 📧 Configuration Email")
        st.info("Configurez votre email Gmail pour envoyer les factures et rappels.")
        
        email = st.text_input("📧 Email Gmail", value=gmail_config.get("email", ""), key="cfg_email")
        app_password = st.text_input("🔑 Mot de passe d'application", value=gmail_config.get("app_password", ""), type="password", key="cfg_app_pwd")
        
        st.markdown("""
        **Comment obtenir un mot de passe d'application :**
        1. Allez sur [myaccount.google.com](https://myaccount.google.com)
        2. Sécurité → Validation en 2 étapes (activez si besoin)
        3. Mots de passe des applications → Générer
        """)
        
        if st.button("💾 Sauvegarder la configuration email", type="primary", width="stretch"):
            if "gmail" not in secrets:
                secrets["gmail"] = {}
            secrets["gmail"]["email"] = email
            secrets["gmail"]["app_password"] = app_password
            ctx["save_secrets"](secrets)
            st.success("✅ Configuration email sauvegardée !")