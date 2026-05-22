from flask import Flask, render_template, request, redirect, session, flash, jsonify, url_for
from flask_mail import Mail, Message
from datetime import datetime, timedelta
import sqlite3
import hashlib
import os
import random
import string

app = Flask(__name__)
app.secret_key = 'hitna_secret'

# ---------- Configuration email ----------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'hitnasuperette@gmail.com'
app.config['MAIL_PASSWORD'] = 'bpju ppvd rbiv lszk'  # À remplacer par le mot de passe d'application Gmail
app.config['MAIL_DEFAULT_SENDER'] = 'hitnasuperette@gmail.com'

mail = Mail(app)

# ---------- Injection de variables globales ----------
@app.context_processor
def inject_now():
    return {'date_actuelle': datetime.now().strftime('%d/%m/%Y %H:%M')}

# ---------- Initialisation base principale ----------
def init_db():
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        role TEXT,
        role_personnalise TEXT,
        password_hash TEXT,
        nom TEXT)''')
    
    # Ajouter les colonnes manquantes
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'actif' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN actif INTEGER DEFAULT 1")
        print("✅ Colonne 'actif' ajoutée")
    
    if 'motif_absence' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN motif_absence TEXT DEFAULT ''")
        print("✅ Colonne 'motif_absence' ajoutée")
    
    if 'role_personnalise' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN role_personnalise TEXT DEFAULT ''")
        print("✅ Colonne 'role_personnalise' ajoutée")
    
    if 'permissions' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT 'vente'")
        print("✅ Colonne 'permissions' ajoutée")
    
    c.execute('''CREATE TABLE IF NOT EXISTS produits (
        id INTEGER PRIMARY KEY,
        nom TEXT,
        prix INTEGER,
        stock INTEGER DEFAULT 0,
        stock_min INTEGER DEFAULT 5)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ventes (
        id INTEGER PRIMARY KEY,
        produit_id INTEGER,
        quantite INTEGER,
        prix_unitaire INTEGER,
        total_produit INTEGER,
        date_vente TEXT,
        employe_id INTEGER,
        client TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS entrees (
        id INTEGER PRIMARY KEY,
        produit_id INTEGER,
        quantite INTEGER,
        prix_unitaire INTEGER,
        total INTEGER,
        date_entree TEXT,
        fournisseur TEXT,
        employe_id INTEGER)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS sorties (
        id INTEGER PRIMARY KEY,
        produit_id INTEGER,
        quantite INTEGER,
        prix_unitaire INTEGER,
        total INTEGER,
        date_sortie TEXT,
        client TEXT,
        employe_id INTEGER)''')
    
    # Table pour les tokens de réinitialisation
    c.execute('''CREATE TABLE IF NOT EXISTS reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        token TEXT,
        expires_at TEXT,
        used INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id))''')
    
    c.execute("SELECT * FROM users")
    if not c.fetchone():
        c.execute("INSERT INTO users (role, role_personnalise, password_hash, nom, actif, permissions) VALUES ('admin', 'Administrateur', ?, 'Administrateur', 1, 'admin')", 
                  (hashlib.sha256('admin123'.encode()).hexdigest(),))
        c.execute("INSERT INTO users (role, role_personnalise, password_hash, nom, actif, permissions) VALUES ('employe', 'Employé', ?, 'Employé', 1, 'vente')", 
                  (hashlib.sha256('emp123'.encode()).hexdigest(),))
    
    c.execute("SELECT * FROM produits")
    if not c.fetchone():
        exemples = [
            ('Coca-Cola 33cl', 500, 20, 5),
            ('Fanta 33cl', 500, 15, 5),
            ('Eau 1.5L', 300, 30, 5),
            ('Pringles', 1200, 10, 3),
            ('Chocolat', 600, 25, 5),
            ('Bonbon', 100, 50, 10),
            ('Jus Orange', 400, 12, 5),
        ]
        for ex in exemples:
            c.execute("INSERT INTO produits (nom, prix, stock, stock_min) VALUES (?,?,?,?)", ex)
    
    conn.commit()
    conn.close()
    
    init_archive_db()

# ---------- Initialisation base d'archive ----------
def init_archive_db():
    conn = sqlite3.connect('archive.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS archive_ventes (
        id INTEGER,
        produit_id INTEGER,
        quantite INTEGER,
        prix_unitaire INTEGER,
        total INTEGER,
        date_vente TEXT,
        employe_id INTEGER,
        client TEXT,
        archive_date TEXT,
        semaine INTEGER,
        annee INTEGER,
        produit_nom TEXT,
        employe_nom TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS archive_entrees (
        id INTEGER,
        produit_id INTEGER,
        quantite INTEGER,
        prix_unitaire INTEGER,
        total INTEGER,
        date_entree TEXT,
        fournisseur TEXT,
        employe_id INTEGER,
        archive_date TEXT,
        semaine INTEGER,
        annee INTEGER,
        produit_nom TEXT,
        employe_nom TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS archive_recap (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        semaine INTEGER,
        annee INTEGER,
        date_debut TEXT,
        date_fin TEXT,
        nb_ventes INTEGER,
        total_ventes INTEGER,
        nb_entrees INTEGER,
        total_achats INTEGER,
        archive_date TEXT)''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_archive_ventes_date ON archive_ventes(date_vente)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_archive_entrees_date ON archive_entrees(date_entree)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_archive_semaine ON archive_recap(semaine, annee)')
    
    conn.commit()
    conn.close()

# ---------- Fonction d'archivage automatique ----------
def get_derniere_archive():
    conn = sqlite3.connect('archive.db')
    c = conn.cursor()
    c.execute("SELECT semaine, annee FROM archive_recap ORDER BY id DESC LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def archiver_hebdomadaire():
    conn_main = sqlite3.connect('hitna.db')
    conn_archive = sqlite3.connect('archive.db')
    c_main = conn_main.cursor()
    c_archive = conn_archive.cursor()
    
    today = datetime.now()
    debut_semaine = today - timedelta(days=7)
    fin_semaine = today - timedelta(days=1)
    
    semaine = debut_semaine.isocalendar()[1]
    annee = debut_semaine.isocalendar()[0]
    
    c_main.execute('''SELECT s.id, s.produit_id, s.quantite, s.prix_unitaire, s.total, s.date_sortie, s.client, s.employe_id, p.nom, u.nom
                      FROM sorties s
                      JOIN produits p ON s.produit_id = p.id
                      JOIN users u ON s.employe_id = u.id
                      WHERE date(s.date_sortie) >= date(?) AND date(s.date_sortie) <= date(?)''',
                   (debut_semaine.strftime('%Y-%m-%d'), fin_semaine.strftime('%Y-%m-%d')))
    ventes_a_archiver = c_main.fetchall()
    
    for v in ventes_a_archiver:
        c_archive.execute('''INSERT INTO archive_ventes 
            (id, produit_id, quantite, prix_unitaire, total, date_vente, employe_id, client, archive_date, semaine, annee, produit_nom, employe_nom)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (v[0], v[1], v[2], v[3], v[4], v[5], v[7], v[6], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), semaine, annee, v[8], v[9]))
        c_main.execute("DELETE FROM sorties WHERE id=?", (v[0],))
    
    c_main.execute('''SELECT e.id, e.produit_id, e.quantite, e.prix_unitaire, e.total, e.date_entree, e.fournisseur, e.employe_id, p.nom, u.nom
                      FROM entrees e
                      JOIN produits p ON e.produit_id = p.id
                      JOIN users u ON e.employe_id = u.id
                      WHERE date(e.date_entree) >= date(?) AND date(e.date_entree) <= date(?)''',
                   (debut_semaine.strftime('%Y-%m-%d'), fin_semaine.strftime('%Y-%m-%d')))
    entrees_a_archiver = c_main.fetchall()
    
    for e in entrees_a_archiver:
        c_archive.execute('''INSERT INTO archive_entrees 
            (id, produit_id, quantite, prix_unitaire, total, date_entree, fournisseur, employe_id, archive_date, semaine, annee, produit_nom, employe_nom)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), semaine, annee, e[8], e[9]))
        c_main.execute("DELETE FROM entrees WHERE id=?", (e[0],))
    
    total_ventes = sum(v[4] for v in ventes_a_archiver) if ventes_a_archiver else 0
    total_achats = sum(e[4] for e in entrees_a_archiver) if entrees_a_archiver else 0
    
    c_archive.execute('''INSERT INTO archive_recap 
        (semaine, annee, date_debut, date_fin, nb_ventes, total_ventes, nb_entrees, total_achats, archive_date)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (semaine, annee, debut_semaine.strftime('%Y-%m-%d'), fin_semaine.strftime('%Y-%m-%d'),
         len(ventes_a_archiver), total_ventes, len(entrees_a_archiver), total_achats,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn_main.commit()
    conn_archive.commit()
    conn_main.close()
    conn_archive.close()

def archiver_si_necessaire():
    today = datetime.now()
    if today.weekday() == 0 and today.hour < 2:
        derniere_archive = get_derniere_archive()
        semaine_actuelle = today.isocalendar()[1]
        if derniere_archive != semaine_actuelle:
            archiver_hebdomadaire()

# ---------- Récupération des rôles pour le login ----------
def get_all_roles():
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT DISTINCT role, role_personnalise FROM users WHERE actif = 1 ORDER BY role, role_personnalise")
    roles = c.fetchall()
    conn.close()
    
    roles_list = []
    roles_set = set()
    
    for r in roles:
        if r[1] and r[1] not in roles_set:
            roles_list.append({'role_base': r[0], 'role_affiche': r[1]})
            roles_set.add(r[1])
        elif r[0] not in roles_set:
            role_name = 'Administrateur' if r[0] == 'admin' else 'Employé'
            roles_list.append({'role_base': r[0], 'role_affiche': role_name})
            roles_set.add(r[0])
    
    return roles_list

# ---------- Fonctions de récupération de mot de passe ----------
def generate_reset_token(user_id):
    token = ''.join(random.choices(string.ascii_letters + string.digits, k=50))
    expires_at = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("INSERT INTO reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
              (user_id, token, expires_at))
    conn.commit()
    conn.close()
    
    return token

def send_reset_email(email, token):
    reset_link = url_for('reset_password', token=token, _external=True)
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f4f4f4; margin: 0; padding: 20px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; margin: -20px -20px 20px -20px; }}
            .btn {{ display: inline-block; background: #28a745; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
            .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 20px; padding-top: 20px; border-top: 1px solid #eee; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>🏪 HITNA</h2>
                <p>Réinitialisation de votre mot de passe</p>
            </div>
            <p>Bonjour,</p>
            <p>Vous avez demandé à réinitialiser votre mot de passe. Cliquez sur le bouton ci-dessous pour créer un nouveau mot de passe :</p>
            <div style="text-align: center;">
                <a href="{reset_link}" class="btn">🔑 Réinitialiser mon mot de passe</a>
            </div>
            <p>Ce lien est valable pendant 24 heures.</p>
            <p>Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.</p>
            <div class="footer">
                <p>HITNA - Système de gestion de produits</p>
                <p>Email automatique, merci de ne pas y répondre.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    msg = Message("HITNA - Réinitialisation de votre mot de passe",
                  recipients=[email],
                  html=html_body)
    mail.send(msg)

# ---------- Routes principales ----------
@app.route('/')
def accueil():
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        selected_role = request.form['role']
        
        conn = sqlite3.connect('hitna.db')
        c = conn.cursor()
        
        c.execute("SELECT id, nom, actif, role_personnalise, role, permissions FROM users WHERE (role_personnalise = ? OR role = ?) AND password_hash = ?", 
                  (selected_role, selected_role, hashlib.sha256(request.form['password'].encode()).hexdigest()))
        user = c.fetchone()
        
        if not user:
            role_base = 'admin' if selected_role == 'Administrateur' else ('employe' if selected_role == 'Employé' else None)
            if role_base:
                c.execute("SELECT id, nom, actif, role_personnalise, role, permissions FROM users WHERE role = ? AND password_hash = ?", 
                          (role_base, hashlib.sha256(request.form['password'].encode()).hexdigest()))
                user = c.fetchone()
        
        conn.close()
        
        if user:
            if user[2] == 0:
                flash('❌ Votre compte est désactivé. Veuillez contacter l\'administrateur.')
                return redirect('/login')
            
            session['user_id'] = user[0]
            session['role'] = user[4]
            session['role_affiche'] = user[3] if user[3] else ('Administrateur' if user[4] == 'admin' else 'Employé')
            session['user_nom'] = user[1]
            session['permissions'] = user[5]
            
            if user[4] == 'admin':
                return redirect('/dashboard')
            else:
                return redirect('/vente')
        
        flash('Identifiants incorrects')
    
    roles = get_all_roles()
    return render_template('login.html', roles=roles)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/changer_mdp', methods=['GET', 'POST'])
def changer_mdp():
    if 'user_id' not in session:
        return redirect('/login')
    
    if request.method == 'POST':
        new_pwd = hashlib.sha256(request.form['new_password'].encode()).hexdigest()
        conn = sqlite3.connect('hitna.db')
        c = conn.cursor()
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (new_pwd, session['user_id']))
        conn.commit()
        conn.close()
        flash('Mot de passe changé avec succes !')
        return redirect('/dashboard' if session['role'] == 'admin' else '/vente')
    
    return render_template('changer_mdp.html')

# ---------- Routes de récupération de mot de passe ----------
@app.route('/mot_de_passe_oublie', methods=['GET', 'POST'])
def mot_de_passe_oublie():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        
        if not email:
            flash('❌ Veuillez entrer votre adresse email')
            return redirect('/mot_de_passe_oublie')
        
        conn = sqlite3.connect('hitna.db')
        c = conn.cursor()
        
        if email == 'hitnasuperette@gmail.com':
            c.execute("SELECT id, nom FROM users WHERE role='admin'")
        else:
            c.execute("SELECT id, nom FROM users WHERE nom = ? AND role='employe'", (email,))
        
        user = c.fetchone()
        
        if user:
            token = generate_reset_token(user[0])
            try:
                send_reset_email(email, token)
                flash('✅ Un email de réinitialisation vous a été envoyé. Vérifiez votre boîte de réception.')
            except Exception as e:
                flash(f'❌ Erreur lors de l\'envoi de l\'email : {str(e)}')
        else:
            flash('❌ Aucun compte trouvé avec cet email')
        
        conn.close()
        return redirect('/login')
    
    return render_template('mot_de_passe_oublie.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute('''SELECT user_id, expires_at, used 
                 FROM reset_tokens 
                 WHERE token = ? AND used = 0''', (token,))
    token_data = c.fetchone()
    
    if not token_data:
        conn.close()
        flash('❌ Lien invalide ou déjà utilisé')
        return redirect('/login')
    
    user_id, expires_at, used = token_data
    
    if datetime.now() > datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S'):
        conn.close()
        flash('❌ Le lien a expiré. Veuillez refaire une demande.')
        return redirect('/mot_de_passe_oublie')
    
    if request.method == 'POST':
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        
        if new_password != confirm_password:
            flash('❌ Les mots de passe ne correspondent pas')
            return redirect(f'/reset_password/{token}')
        
        if len(new_password) < 4:
            flash('❌ Le mot de passe doit contenir au moins 4 caractères')
            return redirect(f'/reset_password/{token}')
        
        password_hash = hashlib.sha256(new_password.encode()).hexdigest()
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        c.execute("UPDATE reset_tokens SET used = 1 WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        
        flash('✅ Votre mot de passe a été réinitialisé avec succès ! Connectez-vous avec votre nouveau mot de passe.')
        return redirect('/login')
    
    conn.close()
    return render_template('reset_password.html', token=token)

# ---------- Admin : Gestion des produits ----------
@app.route('/admin/produits')
def produits_list():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT id, nom, prix, stock, stock_min FROM produits ORDER BY nom")
    produits = c.fetchall()
    conn.close()
    
    return render_template('produits.html', produits=produits)

@app.route('/admin/produits/ajouter', methods=['POST'])
def ajouter_produit():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    nom = request.form['nom']
    prix = int(float(request.form['prix']))
    stock = int(request.form.get('stock', 0))
    stock_min = int(request.form.get('stock_min', 5))
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("INSERT INTO produits (nom, prix, stock, stock_min) VALUES (?,?,?,?)", 
              (nom, prix, stock, stock_min))
    conn.commit()
    conn.close()
    
    flash(f'Produit "{nom}" ajoute ({prix} FCFA, stock: {stock})')
    return redirect('/admin/produits')

@app.route('/admin/produits/modifier/<int:id>', methods=['POST'])
def modifier_produit(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    nom = request.form['nom']
    prix = int(float(request.form['prix']))
    stock_min = int(request.form.get('stock_min', 5))
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("UPDATE produits SET nom=?, prix=?, stock_min=? WHERE id=?", 
              (nom, prix, stock_min, id))
    conn.commit()
    conn.close()
    
    flash(f'Produit "{nom}" modifie')
    return redirect('/admin/produits')

@app.route('/admin/produits/supprimer/<int:id>')
def supprimer_produit(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT nom FROM produits WHERE id=?", (id,))
    produit = c.fetchone()
    
    if produit:
        c.execute("DELETE FROM produits WHERE id=?", (id,))
        conn.commit()
        flash(f'Produit "{produit[0]}" supprime')
    
    conn.close()
    return redirect('/admin/produits')

# ---------- Admin : Entrees de stock (avec vérification permissions) ----------
@app.route('/admin/entrees')
def entrees_list():
    if session.get('role') != 'admin':
        conn = sqlite3.connect('hitna.db')
        c = conn.cursor()
        c.execute("SELECT permissions FROM users WHERE id=?", (session['user_id'],))
        result = c.fetchone()
        conn.close()
        
        if not (result and 'entrees' in result[0].split(',')):
            flash('❌ Vous n\'avez pas la permission d\'accéder aux entrées de stock')
            return redirect('/vente')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute('''SELECT e.id, p.nom, e.quantite, e.prix_unitaire, e.total, e.date_entree, e.fournisseur
                 FROM entrees e
                 JOIN produits p ON e.produit_id = p.id
                 ORDER BY e.date_entree DESC
                 LIMIT 50''')
    entrees = c.fetchall()
    
    c.execute("SELECT id, nom, stock FROM produits ORDER BY nom")
    produits = c.fetchall()
    conn.close()
    
    return render_template('entrees.html', entrees=entrees, produits=produits)

@app.route('/admin/entrees/ajouter', methods=['POST'])
def ajouter_entree():
    if session.get('role') != 'admin':
        conn = sqlite3.connect('hitna.db')
        c = conn.cursor()
        c.execute("SELECT permissions FROM users WHERE id=?", (session['user_id'],))
        result = c.fetchone()
        conn.close()
        
        if not (result and 'entrees' in result[0].split(',')):
            flash('❌ Vous n\'avez pas la permission d\'ajouter des entrées de stock')
            return redirect('/vente')
    
    produit_id = int(request.form['produit_id'])
    quantite = int(request.form['quantite'])
    prix_unitaire = int(request.form['prix_unitaire'])
    fournisseur = request.form.get('fournisseur', '')
    total = quantite * prix_unitaire
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute('''INSERT INTO entrees (produit_id, quantite, prix_unitaire, total, date_entree, fournisseur, employe_id)
                 VALUES (?,?,?,?,?,?,?)''',
              (produit_id, quantite, prix_unitaire, total, now, fournisseur, session['user_id']))
    
    c.execute("UPDATE produits SET stock = stock + ? WHERE id=?", (quantite, produit_id))
    conn.commit()
    conn.close()
    
    flash(f'Entree ajoutee : +{quantite} unites')
    return redirect('/admin/entrees')

# ---------- Admin : Ventes ----------
@app.route('/admin/ventes', methods=['GET', 'POST'])
def admin_ventes():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT id, nom, prix, stock FROM produits WHERE stock > 0 ORDER BY nom")
    produits = c.fetchall()
    
    if request.method == 'POST':
        produit_id = int(request.form['produit_id'])
        quantite = int(request.form['quantite'])
        client = request.form.get('client', '')
        
        c.execute("SELECT nom, prix, stock FROM produits WHERE id=?", (produit_id,))
        nom, prix, stock = c.fetchone()
        
        if quantite > stock:
            flash(f'Stock insuffisant ! Il reste {stock} unites de {nom}')
            conn.close()
            return redirect('/admin/ventes')
        
        total = prix * quantite
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute('''INSERT INTO sorties (produit_id, quantite, prix_unitaire, total, date_sortie, client, employe_id)
                     VALUES (?,?,?,?,?,?,?)''',
                  (produit_id, quantite, prix, total, now, client, session['user_id']))
        
        c.execute("UPDATE produits SET stock = stock - ? WHERE id=?", (quantite, produit_id))
        conn.commit()
        
        flash(f'✅ Vente enregistree par Administrateur ! {quantite} {nom} vendu(s) pour {total} FCFA')
    
    c.execute('''
        SELECT s.id, p.nom, s.quantite, s.total, s.date_sortie, 
               u.nom as vendeur,
               s.client
        FROM sorties s
        JOIN produits p ON s.produit_id = p.id
        JOIN users u ON s.employe_id = u.id
        ORDER BY s.date_sortie DESC
        LIMIT 100
    ''')
    historique = c.fetchall()
    
    c.execute('''
        SELECT 
            u.nom as nom_affiche,
            u.role,
            COUNT(s.id) as nb_ventes,
            SUM(s.total) as total_ventes
        FROM sorties s
        JOIN users u ON s.employe_id = u.id
        WHERE date(s.date_sortie) = date('now')
        GROUP BY u.id
        ORDER BY total_ventes DESC
    ''')
    stats_vendeurs = c.fetchall()
    
    conn.close()
    return render_template('admin_ventes.html', produits=produits, historique=historique, stats_vendeurs=stats_vendeurs)

# ---------- Employe : Ventes ----------
@app.route('/vente', methods=['GET', 'POST'])
def vente():
    if session.get('role') != 'employe':
        return redirect('/login')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT id, nom, prix, stock FROM produits WHERE stock > 0 ORDER BY nom")
    produits = c.fetchall()
    
    if request.method == 'POST':
        produit_id = int(request.form['produit_id'])
        quantite = int(request.form['quantite'])
        client = request.form.get('client', '')
        
        c.execute("SELECT nom, prix, stock FROM produits WHERE id=?", (produit_id,))
        nom, prix, stock = c.fetchone()
        
        if quantite > stock:
            flash(f'Stock insuffisant ! Il reste {stock} unites de {nom}')
            conn.close()
            return redirect('/vente')
        
        total = prix * quantite
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute('''INSERT INTO sorties (produit_id, quantite, prix_unitaire, total, date_sortie, client, employe_id)
                     VALUES (?,?,?,?,?,?,?)''',
                  (produit_id, quantite, prix, total, now, client, session['user_id']))
        
        c.execute("UPDATE produits SET stock = stock - ? WHERE id=?", (quantite, produit_id))
        conn.commit()
        
        flash(f'✅ Vente enregistree par Employe ! {quantite} {nom} vendu(s) pour {total} FCFA')
    
    c.execute('''
        SELECT s.id, p.nom, s.quantite, s.total, s.date_sortie, s.client,
               u.nom as vendeur,
               u.role as role_vendeur
        FROM sorties s
        JOIN produits p ON s.produit_id = p.id
        JOIN users u ON s.employe_id = u.id
        WHERE date(s.date_sortie) = date('now')
        ORDER BY s.date_sortie DESC
    ''')
    historique = c.fetchall()
    
    c.execute('''
        SELECT 
            u.role,
            COUNT(s.id) as nb_ventes,
            SUM(s.total) as total_ventes
        FROM sorties s
        JOIN users u ON s.employe_id = u.id
        WHERE date(s.date_sortie) = date('now')
        GROUP BY u.role
    ''')
    stats_vendeurs = c.fetchall()
    
    c.execute('''
        SELECT SUM(total) as total_jour, COUNT(*) as nb_ventes
        FROM sorties
        WHERE date(date_sortie) = date('now')
    ''')
    total_general = c.fetchone()
    
    conn.close()
    
    return render_template('vente.html', 
                         produits=produits, 
                         historique=historique,
                         stats_vendeurs=stats_vendeurs,
                         total_general=total_general)

# ---------- Vérification mot de passe admin ----------
@app.route('/admin/acteurs/verifier_mdp', methods=['POST'])
def verifier_mdp_admin():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Non autorisé'})
    
    data = request.get_json()
    mot_de_passe = data.get('mot_de_passe', '')
    
    if not mot_de_passe:
        return jsonify({'success': False, 'message': 'Veuillez entrer votre mot de passe'})
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE id=? AND role='admin'", (session['user_id'],))
    result = c.fetchone()
    conn.close()
    
    if result and result[0] == hashlib.sha256(mot_de_passe.encode()).hexdigest():
        session['mdp_verifie'] = True
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'Mot de passe incorrect'})

# ---------- Admin : Dashboard ----------
@app.route('/dashboard')
def dashboard():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    archiver_si_necessaire()
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute("SELECT SUM(total) FROM sorties WHERE date(date_sortie) = date('now')")
    total_jour = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM produits")
    nb_produits = c.fetchone()[0]
    
    c.execute("SELECT SUM(stock) FROM produits")
    stock_total = c.fetchone()[0] or 0
    
    c.execute('''
        SELECT s.id, p.nom, s.quantite, s.total, s.date_sortie, 
               u.nom as vendeur,
               s.client
        FROM sorties s
        JOIN produits p ON s.produit_id = p.id
        JOIN users u ON s.employe_id = u.id
        ORDER BY s.date_sortie DESC
        LIMIT 50
    ''')
    historique = c.fetchall()
    
    c.execute("SELECT nom, stock, stock_min FROM produits WHERE stock <= stock_min")
    stock_bas = c.fetchall()
    
    c.execute('''
        SELECT p.nom, SUM(s.quantite) as total_vendu
        FROM sorties s
        JOIN produits p ON s.produit_id = p.id
        GROUP BY p.id
        ORDER BY total_vendu DESC
        LIMIT 5
    ''')
    top_produits = c.fetchall()
    
    c.execute('''
        SELECT 
            u.nom as nom_affiche,
            u.role,
            COUNT(s.id) as nb_ventes,
            SUM(s.total) as total_ventes
        FROM sorties s
        JOIN users u ON s.employe_id = u.id
        WHERE date(s.date_sortie) = date('now')
        GROUP BY u.id
        ORDER BY total_ventes DESC
    ''')
    stats_vendeurs = c.fetchall()
    
    conn.close()
    
    return render_template('dashboard.html', 
                         total_jour=total_jour,
                         nb_produits=nb_produits,
                         stock_total=stock_total,
                         historique=historique,
                         stock_bas=stock_bas,
                         top_produits=top_produits,
                         stats_vendeurs=stats_vendeurs)

# ---------- Admin : Gestion des acteurs ----------
@app.route('/admin/acteurs')
def admin_acteurs():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("SELECT id, nom, role, role_personnalise, password_hash, COALESCE(actif, 1) as actif, COALESCE(motif_absence, '') as motif_absence, COALESCE(permissions, 'vente') as permissions FROM users ORDER BY role DESC, actif DESC, id")
    acteurs = c.fetchall()
    conn.close()
    
    return render_template('admin_acteurs.html', acteurs=acteurs)

@app.route('/admin/acteurs/ajouter', methods=['POST'])
def ajouter_acteur():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    nom = request.form['nom']
    role_base = request.form['role_base']
    role_personnalise = request.form.get('role_personnalise', '')
    mot_de_passe = request.form['mot_de_passe']
    password_hash = hashlib.sha256(mot_de_passe.encode()).hexdigest()
    
    if role_personnalise:
        role_affiche = role_personnalise
    else:
        role_affiche = 'Administrateur' if role_base == 'admin' else 'Employé'
    
    permissions = 'admin' if role_base == 'admin' else 'vente'
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    try:
        c.execute("INSERT INTO users (role, role_personnalise, password_hash, nom, actif, permissions) VALUES (?, ?, ?, ?, 1, ?)", 
                  (role_base, role_affiche, password_hash, nom, permissions))
        conn.commit()
        flash(f'✅ {role_affiche} "{nom}" ajouté avec succès ! Mot de passe: {mot_de_passe}')
    except sqlite3.IntegrityError:
        flash('❌ Ce nom existe déjà')
    conn.close()
    
    return redirect('/admin/acteurs')

@app.route('/admin/acteurs/modifier/<int:id>', methods=['POST'])
def modifier_acteur(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    nom = request.form['nom']
    role = request.form['role']
    nouveau_mdp = request.form.get('nouveau_mdp', '')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute("SELECT role FROM users WHERE id=?", (id,))
    actuel = c.fetchone()
    
    if actuel and actuel[0] == 'admin' and id == session['user_id'] and role != 'admin':
        flash('❌ Vous ne pouvez pas changer votre propre rôle !')
        conn.close()
        return redirect('/admin/acteurs')
    
    if nouveau_mdp:
        password_hash = hashlib.sha256(nouveau_mdp.encode()).hexdigest()
        c.execute("UPDATE users SET nom=?, role=?, password_hash=? WHERE id=?", 
                  (nom, role, password_hash, id))
        flash(f'✅ {nom} modifié avec nouveau mot de passe')
    else:
        c.execute("UPDATE users SET nom=?, role=? WHERE id=?", (nom, role, id))
        flash(f'✅ {nom} modifié')
    
    conn.commit()
    conn.close()
    
    return redirect('/admin/acteurs')

@app.route('/admin/acteurs/modifier_role/<int:id>', methods=['POST'])
def modifier_role_acteur(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    role_personnalise = request.form['role_personnalise']
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute("UPDATE users SET role_personnalise = ? WHERE id=?", (role_personnalise, id))
    conn.commit()
    conn.close()
    
    flash(f'✅ Rôle modifié avec succès')
    return redirect('/admin/acteurs')

@app.route('/admin/acteurs/permissions/<int:id>', methods=['POST'])
def modifier_permissions(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    if not session.get('mdp_verifie', False):
        flash('❌ Veuillez vérifier votre mot de passe avant de modifier les permissions')
        return redirect('/admin/acteurs')
    
    permissions = request.form.getlist('permissions')
    permissions_str = ','.join(permissions) if permissions else 'vente'
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    c.execute("UPDATE users SET permissions = ? WHERE id=?", (permissions_str, id))
    conn.commit()
    conn.close()
    
    session['mdp_verifie'] = False
    
    flash(f'✅ Permissions modifiées avec succès')
    return redirect('/admin/acteurs')

@app.route('/admin/acteurs/desactiver/<int:id>', methods=['POST'])
def desactiver_acteur(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    if id == session['user_id']:
        flash('❌ Vous ne pouvez pas vous désactiver vous-même !')
        return redirect('/admin/acteurs')
    
    motif = request.form['motif']
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute("SELECT role, nom, role_personnalise FROM users WHERE id=?", (id,))
    user = c.fetchone()
    
    if user:
        c.execute("UPDATE users SET actif = 0, motif_absence = ? WHERE id=?", (motif, id))
        conn.commit()
        role_affiche = user[2] if user[2] else ('Administrateur' if user[0] == 'admin' else 'Employé')
        flash(f'👤 {user[1]} ({role_affiche}) désactivé. Motif: {motif}')
    
    conn.close()
    return redirect('/admin/acteurs')

@app.route('/admin/acteurs/reactiver/<int:id>')
def reactiver_acteur(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute("SELECT role, nom, role_personnalise FROM users WHERE id=?", (id,))
    user = c.fetchone()
    
    if user:
        c.execute("UPDATE users SET actif = 1, motif_absence = '' WHERE id=?", (id,))
        conn.commit()
        role_affiche = user[2] if user[2] else ('Administrateur' if user[0] == 'admin' else 'Employé')
        flash(f'✅ {user[1]} ({role_affiche}) réactivé')
    
    conn.close()
    return redirect('/admin/acteurs')

@app.route('/admin/acteurs/supprimer/<int:id>')
def supprimer_acteur(id):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    if id == session['user_id']:
        flash('❌ Vous ne pouvez pas vous supprimer vous-même !')
        return redirect('/admin/acteurs')
    
    conn = sqlite3.connect('hitna.db')
    c = conn.cursor()
    
    c.execute("SELECT role, nom, role_personnalise FROM users WHERE id=?", (id,))
    user = c.fetchone()
    
    if user:
        c.execute("DELETE FROM users WHERE id=?", (id,))
        conn.commit()
        role_affiche = user[2] if user[2] else ('Administrateur' if user[0] == 'admin' else 'Employé')
        flash(f'🗑️ {user[1]} ({role_affiche}) supprimé définitivement')
    
    conn.close()
    return redirect('/admin/acteurs')

# ---------- Admin : Archives ----------
@app.route('/admin/archives')
def archives():
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('archive.db')
    c = conn.cursor()
    
    c.execute('''SELECT id, semaine, annee, date_debut, date_fin, nb_ventes, total_ventes, nb_entrees, total_achats, archive_date
                 FROM archive_recap 
                 ORDER BY annee DESC, semaine DESC''')
    semaines = c.fetchall()
    
    semaine_id = request.args.get('semaine', type=int)
    type_data = request.args.get('type', 'ventes')
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    produit_nom = request.args.get('produit_nom', '')
    tri = request.args.get('tri', 'desc')
    
    ventes_archive = []
    entrees_archive = []
    semaine_selectionnee = None
    
    if semaine_id:
        c.execute("SELECT * FROM archive_recap WHERE id=?", (semaine_id,))
        semaine_selectionnee = c.fetchone()
        
        if semaine_selectionnee:
            if type_data == 'ventes':
                query = '''SELECT v.*, u.nom as employe_nom
                           FROM archive_ventes v
                           LEFT JOIN users u ON v.employe_id = u.id
                           WHERE v.semaine=? AND v.annee=?'''
                params = [semaine_selectionnee[1], semaine_selectionnee[2]]
                if produit_nom:
                    query += " AND v.produit_nom LIKE ?"
                    params.append(f'%{produit_nom}%')
                query += f" ORDER BY v.date_vente {'DESC' if tri == 'desc' else 'ASC'}"
                c.execute(query, params)
                ventes_archive = c.fetchall()
            else:
                query = '''SELECT e.*, u.nom as employe_nom
                           FROM archive_entrees e
                           LEFT JOIN users u ON e.employe_id = u.id
                           WHERE e.semaine=? AND e.annee=?'''
                params = [semaine_selectionnee[1], semaine_selectionnee[2]]
                if produit_nom:
                    query += " AND e.produit_nom LIKE ?"
                    params.append(f'%{produit_nom}%')
                query += f" ORDER BY e.date_entree {'DESC' if tri == 'desc' else 'ASC'}"
                c.execute(query, params)
                entrees_archive = c.fetchall()
    
    elif date_debut:
        if type_data == 'ventes':
            query = '''SELECT v.*, u.nom as employe_nom
                       FROM archive_ventes v
                       LEFT JOIN users u ON v.employe_id = u.id
                       WHERE date(v.date_vente) >= ?'''
            params = [date_debut]
            if date_fin:
                query += " AND date(v.date_vente) <= ?"
                params.append(date_fin)
            if produit_nom:
                query += " AND v.produit_nom LIKE ?"
                params.append(f'%{produit_nom}%')
            query += f" ORDER BY v.date_vente {'DESC' if tri == 'desc' else 'ASC'}"
            c.execute(query, params)
            ventes_archive = c.fetchall()
        else:
            query = '''SELECT e.*, u.nom as employe_nom
                       FROM archive_entrees e
                       LEFT JOIN users u ON e.employe_id = u.id
                       WHERE date(e.date_entree) >= ?'''
            params = [date_debut]
            if date_fin:
                query += " AND date(e.date_entree) <= ?"
                params.append(date_fin)
            if produit_nom:
                query += " AND e.produit_nom LIKE ?"
                params.append(f'%{produit_nom}%')
            query += f" ORDER BY e.date_entree {'DESC' if tri == 'desc' else 'ASC'}"
            c.execute(query, params)
            entrees_archive = c.fetchall()
    
    c.execute("SELECT COUNT(*) FROM archive_ventes")
    total_ventes_archive = c.fetchone()[0]
    
    c.execute("SELECT SUM(total) FROM archive_ventes")
    total_ca_archive = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM archive_entrees")
    total_entrees_archive = c.fetchone()[0]
    
    c.execute("SELECT SUM(total) FROM archive_entrees")
    total_achats_archive = c.fetchone()[0] or 0
    
    conn.close()
    
    return render_template('archives.html', 
                         semaines=semaines,
                         semaine_selectionnee=semaine_selectionnee,
                         ventes_archive=ventes_archive,
                         entrees_archive=entrees_archive,
                         type_data=type_data,
                         total_ventes_archive=total_ventes_archive,
                         total_ca_archive=total_ca_archive,
                         total_entrees_archive=total_entrees_archive,
                         total_achats_archive=total_achats_archive)

@app.route('/admin/archives/jour/<jour>')
def archive_jour(jour):
    if session.get('role') != 'admin':
        return redirect('/login')
    
    conn = sqlite3.connect('archive.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT v.*, u.nom as employe_nom
        FROM archive_ventes v
        LEFT JOIN users u ON v.employe_id = u.id
        WHERE date(v.date_vente) = ?
        ORDER BY v.date_vente DESC
    ''', (jour,))
    ventes_jour = c.fetchall()
    
    c.execute('''
        SELECT e.*, u.nom as employe_nom
        FROM archive_entrees e
        LEFT JOIN users u ON e.employe_id = u.id
        WHERE date(e.date_entree) = ?
        ORDER BY e.date_entree DESC
    ''', (jour,))
    entrees_jour = c.fetchall()
    
    c.execute('''
        SELECT 
            COUNT(*) as nb_ventes,
            SUM(quantite) as quantite_totale,
            SUM(total) as total_ca
        FROM archive_ventes
        WHERE date(date_vente) = ?
    ''', (jour,))
    stats_ventes = c.fetchone()
    
    c.execute('''
        SELECT 
            COUNT(*) as nb_entrees,
            SUM(quantite) as quantite_totale,
            SUM(total) as total_achats
        FROM archive_entrees
        WHERE date(date_entree) = ?
    ''', (jour,))
    stats_entrees = c.fetchone()
    
    conn.close()
    
    return render_template('archive_jour.html',
                         jour=jour,
                         ventes_jour=ventes_jour,
                         entrees_jour=entrees_jour,
                         stats_ventes=stats_ventes,
                         stats_entrees=stats_entrees)

# ---------- Lancement ----------
if __name__ == '__main__':
    init_db()
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)