"""
Application Flask optimisée - E-commerce avec Stripe Connect
Version avec gestion test/réel
"""
import os
import stripe
import smtplib
import psycopg2
import requests
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from threading import Thread
from datetime import datetime
from urllib.parse import quote_plus, unquote_plus
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from dotenv import load_dotenv

# Configuration
load_dotenv()

CONFIG = {
    'SUPABASE_URL': os.getenv("SUPABASE_URL"),
    'SUPABASE_ANON_KEY': os.getenv("SUPABASE_ANON_KEY"),
    'DB_NAME': os.getenv("DB_NAME"),
    'DB_USER': os.getenv("DB_USER"),
    'DB_PASSWORD': os.getenv("DB_PASSWORD"),
    'DB_HOST': os.getenv("DB_HOST"),
    'DB_PORT': os.getenv("DB_PORT", "5432"),
    'STRIPE_SECRET_KEY': os.getenv("STRIPE_SECRET_KEY"),
    'APP_BASE_URL': os.getenv("BASE_URL", "http://127.0.0.1:5000"),
    'SMTP_SERVER': os.getenv("SMTP_SERVER", "smtp.gmail.com"),
    'SMTP_PORT': int(os.getenv("SMTP_PORT", 587)),
    'SMTP_USER': os.getenv("SMTP_USER"),
    'SMTP_PASS': os.getenv("SMTP_PASS"),
    'SUPPLIER_EMAIL': os.getenv("SUPPLIER_EMAIL"),
    'COMMISSION_RATE': float(os.getenv("COMMISSION_RATE", 0.15)),
    'PRICE_MULTIPLIER': float(os.getenv("PRICE_MULTIPLIER", "2.0")),
    'ADMIN_PASSWORD': os.getenv("ADMIN_PASSWORD", "admin123"),
    # Mode flexible : utilise votre compte pour les tests, peut être changé via le dashboard
    'SUPPLIER_STRIPE_ACCOUNT': os.getenv("ACCT_SUPPLIER_ID", "acct_1S0gMxKrDjSJk26R")
}

# Validation config
if not all([CONFIG['SUPABASE_URL'], CONFIG['SUPABASE_ANON_KEY'], CONFIG['DB_NAME'], CONFIG['DB_USER'], CONFIG['DB_PASSWORD'], CONFIG['DB_HOST']]):
    print("⚠️ Variables d'environnement manquantes")

AUTH_URLS = {
    'signup': f"{CONFIG['SUPABASE_URL']}/auth/v1/signup",
    'token': f"{CONFIG['SUPABASE_URL']}/auth/v1/token?grant_type=password",
    'recover': f"{CONFIG['SUPABASE_URL']}/auth/v1/recover"
}

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
stripe.api_key = CONFIG['STRIPE_SECRET_KEY']

from scraper import get_categories, get_category_products, get_product_details, get_gender_sections

# ==================== CACHE AMÉLIORÉ ====================

PRELOAD_CACHE = {
    'home_products': {}, 
    'gender_sections': None, 
    'categories': None, 
    'popular_products': [], 
    'category_pages': {},  # Nouveau: cache des pages de catégories
    'last_preload': 0
}

def preload_essential_data():
    """Précharge les données essentielles de manière plus complète"""
    print("🔄 Préchargement des données étendu...")
    try:
        # Données de base
        PRELOAD_CACHE.update({
            'gender_sections': get_gender_sections(), 
            'categories': get_categories()
        })
        
        # Produits par genre pour la page d'accueil (plus de produits)
        GENDER_PATHS = {
            "homme": "/Chaussures-Homme-c100.html", 
            "femme": "/Chaussures-Femme-c101.html", 
            "enfant": "/Chaussures-Enfant-c102.html"
        }
        
        for gender, path in GENDER_PATHS.items():
            try:
                # Charger 2 pages au lieu d'1 pour avoir plus de produits
                all_products = []
                for page in range(1, 3):  # Pages 1 et 2
                    products, _ = get_category_products(path, page)
                    all_products.extend(products)
                PRELOAD_CACHE['home_products'][gender] = all_products[:12]  # 12 produits par genre
            except Exception as e:
                print(f"❌ Erreur préchargement {gender}: {e}")
        
        # Produits populaires (plus de marques)
        popular_brands = [
            "/Nike-c1.html", "/Adidas-c2.html", "/Jordan-c3.html",
            "/New-Balance-c4.html", "/Puma-c5.html", "/Converse-c6.html"
        ]
        
        all_popular = []
        for path in popular_brands:
            try:
                products, _ = get_category_products(path, 1)
                all_popular.extend(products[:6])  # 6 produits par marque
            except Exception as e:
                print(f"❌ Erreur préchargement {path}: {e}")
        
        PRELOAD_CACHE['popular_products'] = all_popular[:18]  # 18 produits populaires max
        
        # Préchargement des premières pages des catégories principales
        print("📦 Préchargement des pages de catégories...")
        main_categories = [
            "/Chaussures-Homme-c100.html",
            "/Chaussures-Femme-c101.html", 
            "/Chaussures-Enfant-c102.html",
            "/Nike-c1.html",
            "/Adidas-c2.html"
        ]
        
        for category_path in main_categories:
            try:
                category_key = category_path.replace('/', '_').replace('-', '_')
                PRELOAD_CACHE['category_pages'][category_key] = {}
                
                # Précharger les 2 premières pages de chaque catégorie
                for page_num in range(1, 3):
                    products, paging = get_category_products(category_path, page_num)
                    PRELOAD_CACHE['category_pages'][category_key][page_num] = {
                        'products': products,
                        'paging': paging
                    }
                print(f"✅ Catégorie préchargée: {category_path}")
            except Exception as e:
                print(f"❌ Erreur préchargement catégorie {category_path}: {e}")
        
        PRELOAD_CACHE['last_preload'] = time.time()
        print(f"🎉 Préchargement terminé! {len(PRELOAD_CACHE['category_pages'])} catégories préchargées")
        
    except Exception as e:
        print(f"❌ Erreur préchargement: {e}")

def get_cached_category_page(path, page):
    """Récupère une page de catégorie depuis le cache si disponible"""
    category_key = path.replace('/', '_').replace('-', '_')
    
    if (category_key in PRELOAD_CACHE['category_pages'] and 
        page in PRELOAD_CACHE['category_pages'][category_key]):
        return (PRELOAD_CACHE['category_pages'][category_key][page]['products'],
                PRELOAD_CACHE['category_pages'][category_key][page]['paging'])
    
    # Fallback: chargement normal
    return get_category_products(path, page)

def background_preloader():
    while True:
        time.sleep(600)
        try:
            preload_essential_data()
        except Exception as e:
            print(f"❌ Erreur préchargeur: {e}")
            time.sleep(60)

# ==================== BASE DE DONNÉES ====================

def db_connect():
    try:
        return psycopg2.connect(
            dbname=CONFIG['DB_NAME'], user=CONFIG['DB_USER'], password=CONFIG['DB_PASSWORD'],
            host=CONFIG['DB_HOST'], port=CONFIG['DB_PORT'], sslmode='require'
        )
    except Exception as e:
        print(f"❌ Erreur DB: {e}")
        raise

def execute_db_query(query, params=None, user_id=None, fetch=False):
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute("SET local app.user_id = %s", (str(user_id),))
                cur.execute(query, params or ())
                
                if fetch and 'SELECT' in query.upper():
                    columns = [desc[0] for desc in cur.description]
                    return [dict(zip(columns, row)) for row in cur.fetchall()]
                conn.commit()
                return True
    except Exception as e:
        print(f"❌ Erreur DB: {e}")
        return [] if fetch else False

# ==================== DÉCORATEURS ====================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Connectez-vous pour accéder à cette page", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_authenticated"):
            flash('❌ Accès admin requis', 'error')
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ==================== AUTHENTIFICATION ====================

def auth_request(url, data):
    try:
        response = requests.post(url, json=data, headers={
            "apikey": CONFIG['SUPABASE_ANON_KEY'], "Content-Type": "application/json"
        }, timeout=10)
        return response.json() if response.status_code == 200 else {'error': 'Erreur authentification'}
    except Exception as e:
        return {'error': f'Erreur connexion: {str(e)}'}

def register_user(email, password):
    return auth_request(AUTH_URLS['signup'], {"email": email, "password": password})

def login_user(email, password):
    result = auth_request(AUTH_URLS['token'], {"email": email, "password": password})
    return {'success': True, **result} if 'user' in result else {'success': False, 'error': result.get('error', 'Erreur connexion')}

# ==================== FONCTIONS MÉTIER ====================

def get_cart_data(user_id):
    return execute_db_query(
        "SELECT id, product_name, path, product_image, price, qty, size FROM carts WHERE user_id = %s",
        (user_id,), user_id, fetch=True
    ) or []

def add_to_cart(user_id, product_data):
    return execute_db_query("""
        INSERT INTO carts (user_id, product_name, path, product_image, price, qty, size)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, product_data['name'], product_data.get('path', ''), 
          product_data.get('image', ''), product_data['price'], 
          product_data.get('qty', 1), product_data.get('size', 'Unique')), user_id)

def calculate_total(cart_items):
    return sum(float(item.get('price', 0)) * int(item.get('qty', 1)) for item in cart_items)

def calculate_financials(total_price):
    try:
        original_total = total_price / CONFIG['PRICE_MULTIPLIER']
        margin = total_price - original_total
        commission = margin * CONFIG['COMMISSION_RATE']
        supplier_amount = original_total + (margin - commission)
        return (round(supplier_amount, 2), round(commission, 2))
    except Exception as e:
        print(f"❌ Erreur calcul financier: {e}")
        return (0, 0)

def get_user_address(user_id):
    result = execute_db_query(
        "SELECT full_name, address_line1, address_line2, city, postal_code, country FROM user_addresses WHERE user_id = %s",
        (user_id,), user_id, fetch=True
    )
    return result[0] if result else None

def save_user_address(user_id, address_data):
    execute_db_query("DELETE FROM user_addresses WHERE user_id = %s", (user_id,), user_id)
    return execute_db_query("""
        INSERT INTO user_addresses (user_id, full_name, address_line1, address_line2, city, postal_code, country)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, address_data['full_name'], address_data['address_line1'],
          address_data.get('address_line2', ''), address_data['city'],
          address_data['postal_code'], address_data.get('country', 'France')), user_id)

# ==================== STRIPE CONNECT - Gestion Test/Réel ====================

def check_supplier_account_access():
    """Vérifie si le compte fournisseur est accessible"""
    try:
        account = stripe.Account.retrieve(CONFIG['SUPPLIER_STRIPE_ACCOUNT'])
        return {
            'accessible': True,
            'charges_enabled': account.charges_enabled,
            'details_submitted': account.details_submitted,
            'account_id': account.id
        }
    except stripe.error.PermissionError:
        return {'accessible': False, 'error': 'Accès refusé - compte inaccessible'}
    except stripe.error.InvalidRequestError:
        return {'accessible': False, 'error': 'Compte inexistant'}
    except Exception as e:
        return {'accessible': False, 'error': str(e)}

def create_connect_checkout_session(user_id, cart_items):
    if not cart_items: 
        raise ValueError("Panier vide")
    
    total = calculate_total(cart_items)
    supplier_amount, commission_amount = calculate_financials(total)
    
    print(f"💰 RÉPARTITION: Total:{total}€ | Fournisseur:{supplier_amount}€ | Commission:{commission_amount}€")
    
    # Vérifier l'accès au compte fournisseur
    account_status = check_supplier_account_access()
    
    if not account_status['accessible']:
        # Mode test : utiliser le paiement standard sans Stripe Connect
        print("🔄 Mode test activé - Paiement standard")
        return create_standard_checkout_session(user_id, cart_items, total, supplier_amount, commission_amount)
    
    try:
        # Mode réel : Stripe Connect avec séparation des fonds
        session_stripe = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": f"Commande {len(cart_items)} articles",
                        "description": f"{len(cart_items)} produit(s)"
                    },
                    "unit_amount": int(total * 100),
                },
                "quantity": 1,
            }],
            payment_intent_data={
                "application_fee_amount": int(commission_amount * 100),
                "transfer_data": {"destination": CONFIG['SUPPLIER_STRIPE_ACCOUNT']},
            },
            success_url=f"{CONFIG['APP_BASE_URL']}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CONFIG['APP_BASE_URL']}/checkout/cancel",
            metadata={
                "user_id": str(user_id), 
                "total_amount": str(total), 
                "supplier_amount": str(supplier_amount), 
                "commission_amount": str(commission_amount),
                "mode": "connect"
            },
            shipping_address_collection={"allowed_countries": ["FR"]},
            customer_email=session.get("user_email")
        )
        return session_stripe
    except Exception as e:
        print(f"❌ Erreur Stripe Connect: {e}")
        # Fallback vers le mode standard
        return create_standard_checkout_session(user_id, cart_items, total, supplier_amount, commission_amount)

def create_standard_checkout_session(user_id, cart_items, total, supplier_amount, commission_amount):
    """Mode test - Paiement standard sans Stripe Connect"""
    try:
        session_stripe = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": f"Commande {len(cart_items)} articles",
                        "description": f"{len(cart_items)} produit(s) - MODE TEST"
                    },
                    "unit_amount": int(total * 100),
                },
                "quantity": 1,
            }],
            success_url=f"{CONFIG['APP_BASE_URL']}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CONFIG['APP_BASE_URL']}/checkout/cancel",
            metadata={
                "user_id": str(user_id), 
                "total_amount": str(total), 
                "supplier_amount": str(supplier_amount), 
                "commission_amount": str(commission_amount),
                "mode": "test"
            },
            shipping_address_collection={"allowed_countries": ["FR"]},
            customer_email=session.get("user_email")
        )
        print("✅ Session de test créée")
        return session_stripe
    except Exception as e:
        print(f"❌ Erreur session test: {e}")
        raise

# ==================== FONCTIONS POUR RÉCUPÉRER L'ADRESSE ====================

def get_shipping_from_payment_intent(session_id):
    """Récupère l'adresse depuis le PaymentIntent - SOLUTION ALTERNATIVE"""
    try:
        session_stripe = stripe.checkout.Session.retrieve(session_id)
        payment_intent_id = session_stripe.payment_intent
        
        if payment_intent_id:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            if hasattr(payment_intent, 'shipping') and payment_intent.shipping:
                shipping = payment_intent.shipping
                return {
                    'name': getattr(shipping, 'name', ''),
                    'line1': shipping.address.line1 if shipping.address else '',
                    'line2': shipping.address.line2 if shipping.address else '',
                    'city': shipping.address.city if shipping.address else '',
                    'postal_code': shipping.address.postal_code if shipping.address else '',
                    'country': shipping.address.country if shipping.address else ''
                }
    except Exception as e:
        print(f"⚠️ Erreur récupération adresse PaymentIntent: {e}")
    return {}

def get_shipping_from_session(session_stripe):
    """Récupère l'adresse depuis la session Stripe"""
    shipping_address = {}
    
    try:
        # Méthode 1: Depuis shipping_details (méthode recommandée par Stripe)
        if hasattr(session_stripe, 'shipping_details') and session_stripe.shipping_details:
            shipping = session_stripe.shipping_details
            if hasattr(shipping, 'address') and shipping.address:
                shipping_address = {
                    'name': getattr(shipping, 'name', ''),
                    'line1': getattr(shipping.address, 'line1', ''),
                    'line2': getattr(shipping.address, 'line2', ''),
                    'city': getattr(shipping.address, 'city', ''),
                    'postal_code': getattr(shipping.address, 'postal_code', ''),
                    'country': getattr(shipping.address, 'country', '')
                }
                print(f"📍 Adresse trouvée via shipping_details: {shipping_address}")
                return shipping_address
    except Exception as e:
        print(f"⚠️ Erreur récupération shipping_details: {e}")
    
    try:
        # Méthode 2: Depuis l'attribut shipping direct
        if hasattr(session_stripe, 'shipping') and session_stripe.shipping:
            shipping = session_stripe.shipping
            if hasattr(shipping, 'address') and shipping.address:
                shipping_address = {
                    'name': getattr(shipping, 'name', ''),
                    'line1': shipping.address.line1 if shipping.address else '',
                    'line2': shipping.address.line2 if shipping.address else '',
                    'city': shipping.address.city if shipping.address else '',
                    'postal_code': shipping.address.postal_code if shipping.address else '',
                    'country': shipping.address.country if shipping.address else ''
                }
                print(f"📍 Adresse trouvée via shipping: {shipping_address}")
                return shipping_address
    except Exception as e:
        print(f"⚠️ Erreur récupération shipping: {e}")
    
    return shipping_address

# ==================== EMAIL ====================

def send_email(to_email, subject, body):
    if not CONFIG['SMTP_USER'] or not CONFIG['SMTP_PASS']:
        return False
    
    try:
        msg = MIMEMultipart()
        msg["From"] = CONFIG['SMTP_USER']
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(CONFIG['SMTP_SERVER'], CONFIG['SMTP_PORT'], timeout=10) as server:
            server.starttls()
            server.login(CONFIG['SMTP_USER'], CONFIG['SMTP_PASS'])
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"❌ Erreur email: {e}")
        return False

def send_order_emails(session_id, cart_items, total, supplier_amount, commission_amount, customer_email, shipping_address=None, mode="connect"):
    try:
        items_text = "\n".join([f"- {item.get('qty', 1)}x {item.get('product_name', 'Produit')} ({item.get('size', '')}) - {float(item.get('price', 0)):.2f}€" for item in cart_items])
        
        # FORMATAGE AMÉLIORÉ DE L'ADRESSE
        address_text = "Non renseignée"
        if shipping_address and shipping_address.get('line1'):
            address_parts = []
            if shipping_address.get('name'):
                address_parts.append(f"👤 {shipping_address['name']}")
            if shipping_address.get('line1'):
                address_parts.append(f"📍 {shipping_address['line1']}")
            if shipping_address.get('line2'):
                address_parts.append(f"   {shipping_address['line2']}")
            if shipping_address.get('postal_code') and shipping_address.get('city'):
                address_parts.append(f"🏙️ {shipping_address['postal_code']} {shipping_address['city']}")
            if shipping_address.get('country'):
                address_parts.append(f"🌍 {shipping_address['country']}")
            
            address_text = "\n".join(address_parts)
        
        mode_indicator = "🧪 MODE TEST" if mode == "test" else "💳 STRIPE CONNECT"
        
        # Email fournisseur
        supplier_body = f"""🎁 NOUVELLE COMMANDE - {session_id}
{mode_indicator}
👤 CLIENT: {customer_email or 'Non renseigné'}

💰 FINANCES:
• Total: {total:.2f}€ | Base: {total / CONFIG['PRICE_MULTIPLIER']:.2f}€
• Commission ({CONFIG['COMMISSION_RATE']*100}%): {commission_amount:.2f}€
• Transféré: {supplier_amount:.2f}€

🏠 ADRESSE DE LIVRAISON:
{address_text}

🛍️ ARTICLES COMMANDÉS: 
{items_text}

📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        # Email client
        customer_body = f"""✅ COMMANDE CONFIRMÉE - {session_id}
Merci pour votre commande !

📦 RÉSUMÉ DE VOTRE COMMANDE: 
{items_text}

💰 TOTAL: {total:.2f}€

🏠 VOTRE ADRESSE DE LIVRAISON:
{address_text}

📞 Pour toute question concernant votre commande, contactez-nous.

📅 Date de commande: {datetime.now().strftime('%d/%m/%Y à %H:%M')}"""
        
        if CONFIG['SUPPLIER_EMAIL']:
            Thread(target=lambda: send_email(CONFIG['SUPPLIER_EMAIL'], f"🎁 Commande - {session_id}", supplier_body), daemon=True).start()
        
        if customer_email:
            Thread(target=lambda: send_email(customer_email, f"✅ Confirmation de commande - {session_id}", customer_body), daemon=True).start()
            
        print(f"✅ Emails envoyés - Adresse: {'Oui' if shipping_address.get('line1') else 'Non'}")
    except Exception as e:
        print(f"❌ Erreur emails: {e}")

# ==================== INIT DB ====================

def init_database():
    try:
        tables = {
            'carts': """
                CREATE TABLE IF NOT EXISTS carts (
                    id SERIAL PRIMARY KEY, user_id UUID NOT NULL, product_name TEXT NOT NULL,
                    path TEXT, product_image TEXT, price DECIMAL(10,2) NOT NULL,
                    qty INTEGER DEFAULT 1, size TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
                )""",
            'user_addresses': """
                CREATE TABLE IF NOT EXISTS user_addresses (
                    id SERIAL PRIMARY KEY, user_id UUID NOT NULL UNIQUE, full_name TEXT NOT NULL,
                    address_line1 TEXT NOT NULL, address_line2 TEXT, city TEXT NOT NULL,
                    postal_code TEXT NOT NULL, country TEXT DEFAULT 'France', created_at TIMESTAMPTZ DEFAULT NOW()
                )"""
        }
        
        with db_connect() as conn:
            with conn.cursor() as cur:
                for table_name, create_query in tables.items():
                    cur.execute(create_query)
                    cur.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
                    cur.execute("SELECT 1 FROM pg_policies WHERE tablename = %s AND policyname = %s", 
                               (table_name, f"Users can manage their own {table_name}"))
                    if not cur.fetchone():
                        cur.execute(f"""
                            CREATE POLICY "Users can manage their own {table_name}" ON {table_name} 
                            FOR ALL USING (user_id = current_setting('app.user_id', true)::uuid)
                        """)
                conn.commit()
                print("✅ DB initialisée")
    except Exception as e:
        print(f"❌ Erreur DB: {e}")

# ==================== CONTEXT PROCESSOR ====================

@app.context_processor
def inject_global_data():
    user_id = session.get("user_id")
    cart_count, user_address = 0, None
    
    if user_id:
        try:
            cart_count = len(get_cart_data(user_id))
            user_address = get_user_address(user_id)
        except Exception as e:
            print(f"⚠️ Erreur context: {e}")
    
    return {
        'cart_count': cart_count, 'user_id': user_id, 'user_email': session.get('user_email'), 
        'user_address': user_address, 'price_multiplier': CONFIG['PRICE_MULTIPLIER'],
        'sections': PRELOAD_CACHE.get('gender_sections') or get_gender_sections(),
        'categories': PRELOAD_CACHE.get('categories') or get_categories() or {'headers': [], 'brands': []}
    }

# ==================== ROUTES PRINCIPALES ====================

@app.route("/")
def home():
    gender = request.args.get("gender", "all")
    cache_data = {
        'categories': PRELOAD_CACHE.get('categories') or get_categories() or {'headers': [], 'brands': []},
        'sections': PRELOAD_CACHE.get('gender_sections') or get_gender_sections()
    }
    
    if gender == "all":
        products = []
        for g in ["homme", "femme", "enfant"]:
            products.extend(PRELOAD_CACHE['home_products'].get(g, [])[:4])
    else:
        products = PRELOAD_CACHE['home_products'].get(gender, [])
    
    return render_template("home.html", **cache_data, gender=gender, products=products)

@app.route("/category")
def category():
    if not (path := request.args.get("path")): 
        return redirect(url_for("home"))
    
    path, page = unquote_plus(path), max(1, int(request.args.get("page", 1)))
    
    # Utiliser le cache pour les premières pages des catégories principales
    if page <= 2:  # Seulement pour les pages 1 et 2
        try:
            products, paging = get_cached_category_page(path, page)
        except Exception as e:
            print(f"category cache error: {e}, fallback to direct call")
            products, paging = get_category_products(path, page)
    else:
        # Pour les pages au-delà de 2, chargement normal
        try:
            products, paging = get_category_products(path, page)
        except Exception as e:
            print(f"category error: {e}")
            products, paging = [], {'current': page, 'total': 1, 'has_next': False, 'has_prev': page > 1}
    
    return render_template("category.html", categories=get_categories() or {'headers': [], 'brands': []}, 
                         products=products, category_path=path, category_path_enc=quote_plus(path), paging=paging)

@app.route("/product")
def product():
    if not (path := request.args.get("path")): 
        return redirect(url_for("home"))
    
    product_data = get_product_details(unquote_plus(path)) or {}
    return render_template("product.html", categories=get_categories() or {'headers': [], 'brands': []}, 
                         product=product_data, sections=get_gender_sections())

@app.route("/search")
def search():
    if not (query := request.args.get("q", "").strip()): 
        return redirect(url_for("home"))
    
    all_products = []
    for path in ["/Chaussures-Homme-c100.html", "/Chaussures-Femme-c101.html", "/Chaussures-Enfant-c102.html"]:
        for page in range(1, 3):
            try: 
                products, paging = get_category_products(path, page)
                all_products.extend(products)
                if not paging.get('has_next', False): break
            except Exception: break
    
    query_terms = query.lower().split()
    seen_names, results = set(), []
    
    for product in all_products:
        product_name = product.get("name", "").lower()
        if (query.lower() in product_name or 
            sum(1 for term in query_terms if len(term) > 2 and term in product_name) > 0):
            if product.get('name') not in seen_names:
                seen_names.add(product.get('name'))
                results.append(product)
    
    return render_template("search.html", categories=get_categories() or {"headers": [], "brands": []}, 
                         results=results, query=query, results_count=len(results))

# ==================== AUTH ====================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email, password = request.form["email"], request.form["password"]
        try:
            res = register_user(email, password)
            if res.get('user'):
                flash('✅ Inscription réussie! Connectez-vous.', 'success')
                return redirect(url_for("login"))
            error = res.get('msg', 'Erreur inscription')
        except Exception as e:
            error = "Email déjà utilisé" if "User already registered" in str(e) else f"Erreur: {e}"
        return render_template("auth/register.html", error=error)
    return render_template("auth/register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, password = request.form["email"], request.form["password"]
        result = login_user(email, password)
        
        if result['success']:
            user_data = result['user']
            session.update({
                "user_id": user_data['id'], "access_token": result['access_token'],
                "refresh_token": result.get('refresh_token', ''), "user_email": user_data['email']
            })
            flash('✅ Connexion réussie!', 'success')
            return redirect(request.args.get('next') or url_for("home"))
        else:
            flash(f'❌ {result["error"]}', 'error')
    
    return render_template("auth/login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash('✅ Déconnexion réussie!', 'success')
    return redirect(url_for("home"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        if not email:
            flash('❌ Veuillez entrer votre email', 'error')
            return render_template("auth/forgot_password.html")
        
        try:
            response = requests.post(AUTH_URLS['recover'], json={"email": email, "redirect_to": f"{CONFIG['APP_BASE_URL']}/reset-password"},
                                   headers={"apikey": CONFIG['SUPABASE_ANON_KEY'], "Content-Type": "application/json"})
            
            if response.status_code == 200:
                flash('✅ Email de réinitialisation envoyé!', 'success')
                return redirect(url_for('login'))
            else:
                error_msg = response.json().get("msg", "Erreur envoi email")
                flash('❌ Trop de tentatives' if "rate limit" in error_msg.lower() else f'❌ {error_msg}', 'error')
        except Exception as e:
            print(f"Erreur réinitialisation: {e}")
            flash('❌ Erreur envoi email', 'error')
    
    return render_template("auth/forgot_password.html")

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token, type_param = request.args.get("token") or request.args.get("access_token"), request.args.get("type")
    
    if not token or type_param != "recovery":
        flash('❌ Lien invalide', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == "POST":
        new_password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if not new_password or new_password != confirm_password:
            flash('❌ Champs invalides', 'error')
            return render_template("auth/reset_password.html", token=token)
        
        try:
            response = requests.put(f"{CONFIG['SUPABASE_URL']}/auth/v1/user", json={"password": new_password},
                                  headers={"apikey": CONFIG['SUPABASE_ANON_KEY'], "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            
            if response.status_code == 200:
                flash('✅ Mot de passe réinitialisé!', 'success')
                return redirect(url_for('login'))
            else:
                flash(f'❌ {response.json().get("message", "Erreur réinitialisation")}', 'error')
        except Exception as e:
            print(f"Erreur réinitialisation: {e}")
            flash('❌ Erreur réinitialisation', 'error')
    
    return render_template("auth/reset_password.html", token=token)

# ==================== PANIER ====================

@app.route("/cart")
@login_required
def cart_view():
    user_id = session.get("user_id")
    cart, total = get_cart_data(user_id), calculate_total(get_cart_data(user_id))
    return render_template("cart.html", categories=get_categories() or {'headers': [], 'brands': []}, cart=cart, total=total)

@app.route("/cart/add", methods=["POST"])
@login_required
def cart_add():
    user_id = session.get("user_id")
    data = request.form
    
    try:
        if not data.get('name') or not data.get('price'):
            flash('❌ Données manquantes', 'error')
            return redirect(request.referrer or url_for('home'))
        
        product_data = {
            'name': data.get('name'), 'path': data.get('path', ''), 'image': data.get('image', ''),
            'price': float(data.get('price', '0').replace('€', '').replace(',', '.').strip() or 0),
            'qty': int(data.get('qty', 1) or 1), 'size': data.get('size', 'Unique')
        }
        
        # CORRECTION : Appel manquant à add_to_cart
        if add_to_cart(user_id, product_data):
            flash('✅ Produit ajouté!', 'success')
        else:
            flash('❌ Erreur ajout', 'error')
    except Exception as e:
        flash(f'❌ Erreur: {str(e)}', 'error')
    
    return redirect(request.referrer or url_for('home'))

@app.route("/cart/remove/<item_id>", methods=["POST"])
@login_required
def cart_remove(item_id):
    user_id = session.get("user_id")
    if execute_db_query("DELETE FROM carts WHERE id = %s AND user_id = %s", (item_id, user_id), user_id):
        flash('✅ Produit retiré', 'success')
    else:
        flash('❌ Erreur suppression', 'error')
    return redirect(url_for('cart_view'))

@app.route("/cart/clear", methods=["POST"])
@login_required
def cart_clear():
    user_id = session.get("user_id")
    if execute_db_query("DELETE FROM carts WHERE user_id = %s", (user_id,), user_id):
        flash('✅ Panier vidé', 'success')
    else:
        flash('❌ Erreur vidage', 'error')
    return redirect(url_for('cart_view'))

# ==================== ADRESSE ====================

@app.route("/profile/address", methods=["GET", "POST"])
@login_required
def manage_address():
    user_id = session.get("user_id")

    if request.method == "POST":
        try:
            if save_user_address(user_id, {
                "full_name": request.form.get("full_name"), "address_line1": request.form.get("address_line1"),
                "address_line2": request.form.get("address_line2", ""), "city": request.form.get("city"),
                "postal_code": request.form.get("postal_code"), "country": request.form.get("country", "France"),
            }):
                flash("✅ Adresse enregistrée!", "success")
                return redirect(url_for("cart_view"))
            else:
                flash("❌ Erreur sauvegarde", "error")
        except Exception as e:
            flash(f"❌ Erreur: {str(e)}", "error")

    address = get_user_address(user_id)
    return render_template("address_form.html", address=address)

# ==================== CHECKOUT ====================

@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    user_id = session.get("user_id")
    try:
        if not (cart_items := get_cart_data(user_id)):
            flash('❌ Panier vide', 'error')
            return redirect(url_for('cart_view'))
        
        session_stripe = create_connect_checkout_session(user_id, cart_items)
        return redirect(session_stripe.url, code=303)
    except Exception as e:
        print(f"❌ Erreur paiement: {e}")
        flash('❌ Erreur création session', 'error')
        return redirect(url_for('cart_view'))

@app.route("/checkout/success")
@login_required
def checkout_success():
    user_id = session.get("user_id")
    if not (session_id := request.args.get("session_id")):
        flash('❌ Session ID manquant', 'error')
        return redirect(url_for("home"))
    
    try:
        session_stripe = stripe.checkout.Session.retrieve(session_id)
        
        if session_stripe.payment_status != 'paid':
            flash('❌ Paiement non confirmé', 'error')
            return redirect(url_for('checkout_cancel'))
        
        cart_items = get_cart_data(user_id)
        if not cart_items:
            flash('❌ Panier vide', 'error')
            return redirect(url_for('home'))
        
        # CORRECTION : Récupération correcte des métadonnées
        metadata = session_stripe.metadata
        total = float(metadata.get("total_amount", 0))
        supplier_amount = float(metadata.get("supplier_amount", 0))
        commission_amount = float(metadata.get("commission_amount", 0))
        mode = metadata.get("mode", "connect")
        
        # Si les métadonnées sont vides, calculer depuis le panier
        if total == 0:
            total = calculate_total(cart_items)
            supplier_amount, commission_amount = calculate_financials(total)
        
        # CORRECTION AMÉLIORÉE : Récupération de l'adresse de livraison
        shipping_address = {}
        customer_email = session.get("user_email")
        
        # Méthode 1: Récupérer depuis la session Stripe
        shipping_address = get_shipping_from_session(session_stripe)
        
        # Méthode 2: SOLUTION ALTERNATIVE - Récupérer depuis le PaymentIntent
        if not shipping_address.get('line1'):
            shipping_address = get_shipping_from_payment_intent(session_id)
            if shipping_address.get('line1'):
                print("📍 Adresse récupérée via PaymentIntent")
        
        # Récupérer l'email du client
        if hasattr(session_stripe, 'customer_details') and session_stripe.customer_details:
            customer_details = session_stripe.customer_details
            if hasattr(customer_details, 'email') and customer_details.email:
                customer_email = customer_details.email
        
        print(f"📍 Résultat récupération adresse: {'Adresse trouvée' if shipping_address.get('line1') else 'Aucune adresse'}")
        
        Thread(target=send_order_emails, args=(
            session_id, cart_items, total, supplier_amount, commission_amount, customer_email, shipping_address, mode
        ), daemon=True).start()
        
        execute_db_query("DELETE FROM carts WHERE user_id = %s", (user_id,), user_id)
        
        message = "✅ Paiement réussi! " 
        message += "Fonds automatiquement répartis via Stripe Connect." if mode == "connect" else "Mode test - Les fonds iront sur votre compte Stripe."
        
        return render_template("checkout/success.html", 
                             order={"session_id": session_id, "total": total, "supplier_amount": supplier_amount,
                                   "commission_amount": commission_amount, "customer_email": customer_email,
                                   "shipping_address": shipping_address, "mode": mode}, 
                             config=CONFIG,
                             message=message)
            
    except Exception as e:
        print(f"❌ Erreur success: {e}")
        flash('❌ Erreur traitement commande', 'error')
        return redirect(url_for('home'))
    
@app.route("/checkout/cancel")
def checkout_cancel():
    return render_template("checkout/cancel.html")

# ==================== ADMIN ====================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get('admin_authenticated'):
        return redirect(url_for('admin_dashboard'))
    
    if request.method == "POST":
        password = request.form.get("password")
        if password and password == CONFIG['ADMIN_PASSWORD']:
            session['admin_authenticated'] = True
            session.permanent = True
            flash('✅ Connexion admin réussie!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('❌ Mot de passe incorrect', 'error')
    
    return render_template("admin/login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get('admin_authenticated'):
        flash('❌ Accès non autorisé. Veuillez vous connecter.', 'error')
        return redirect(url_for('admin_login'))
    
    try:
        # Vérifier le statut du compte fournisseur
        account_status = check_supplier_account_access()
        
        stats = {
            'total_users': execute_db_query("SELECT COUNT(DISTINCT user_id) FROM carts", fetch=True)[0]['count'] or 0,
            'active_carts': execute_db_query("SELECT COUNT(*) FROM carts", fetch=True)[0]['count'] or 0
        }
        
        # Déterminer le statut Stripe Connect
        if account_status['accessible']:
            stripe_status = 'success'
            stripe_message = f"Stripe Connect actif - Compte: {CONFIG['SUPPLIER_STRIPE_ACCOUNT'][:8]}..."
        else:
            stripe_status = 'warning'
            stripe_message = f"Mode test - Utilisation de paiements standards"
        
        tests = {
            'database': {'status': 'success', 'message': 'Base de données connectée'},
            'stripe_connect': {'status': stripe_status, 'message': stripe_message},
            'email': {'status': 'success' if CONFIG['SMTP_USER'] and CONFIG['SMTP_PASS'] else 'warning',
                     'message': 'Email configuré' if CONFIG['SMTP_USER'] and CONFIG['SMTP_PASS'] else 'Email non configuré'},
            'cache': {'status': 'success', 'message': f'Cache: {len(PRELOAD_CACHE["home_products"])} produits'}
        }
        
        return render_template("admin/dashboard.html", 
                             stats=stats, 
                             tests=tests, 
                             config=CONFIG,
                             account_status=account_status)
        
    except Exception as e:
        flash(f'❌ Erreur dashboard: {str(e)}', 'error')
        return redirect(url_for('home'))

@app.route("/admin/logout")
def admin_logout():
    session.pop('admin_authenticated', None)
    flash('✅ Déconnexion admin!', 'success')
    return redirect(url_for('home'))

@app.route("/admin/check-account-status")
@admin_required
def check_account_status():
    return jsonify(check_supplier_account_access())

@app.route("/admin/create-connect-link")
@admin_required
def create_connect_link():
    try:
        account_link = stripe.AccountLink.create(
            account=CONFIG['SUPPLIER_STRIPE_ACCOUNT'],
            refresh_url=f"{CONFIG['APP_BASE_URL']}/admin/reauth",
            return_url=f"{CONFIG['APP_BASE_URL']}/admin/onboarding-success",
            type="account_onboarding",
        )
        return redirect(account_link.url)
    except Exception as e:
        flash(f'❌ Erreur création lien: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route("/admin/onboarding-success")
@admin_required
def onboarding_success():
    flash('✅ Le fournisseur a été redirigé vers Stripe pour compléter son inscription!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/reauth")
@admin_required
def reauth():
    flash('🔒 Session expirée, veuillez renvoyer l\'invitation', 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/change-supplier-account", methods=["POST"])
@admin_required
def change_supplier_account():
    new_account = request.form.get("supplier_account")
    if new_account and new_account.startswith("acct_"):
        CONFIG['SUPPLIER_STRIPE_ACCOUNT'] = new_account
        flash(f'✅ Compte fournisseur mis à jour: {new_account[:8]}...', 'success')
    else:
        flash('❌ Format de compte Stripe invalide', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/test-payment")
@admin_required
def test_payment():
    """Route pour tester un paiement en mode test"""
    try:
        # Créer un produit de test
        session_stripe = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": "Produit Test", "description": "Test de paiement"},
                    "unit_amount": 1000,  # 10.00€
                },
                "quantity": 1,
            }],
            success_url=f"{CONFIG['APP_BASE_URL']}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CONFIG['APP_BASE_URL']}/checkout/cancel",
            metadata={
                "total_amount": "10.00",
                "supplier_amount": "8.50", 
                "commission_amount": "1.50",
                "mode": "test"
            }
        )
        return redirect(session_stripe.url)
    except Exception as e:
        flash(f'❌ Erreur test paiement: {str(e)}', 'error')
        return redirect(url_for('admin_dashboard'))

# ==================== DÉMARRAGE ====================

def startup_tasks():
    init_database()
    preload_essential_data()
    threading.Thread(target=background_preloader, daemon=True).start()
    print("🚀 Application démarrée!")
    print(f"💳 Mode: {'Stripe Connect' if check_supplier_account_access()['accessible'] else 'TEST'}")

with app.app_context():
    startup_tasks()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")