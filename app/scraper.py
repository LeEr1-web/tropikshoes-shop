"""
Scraper optimisé pour destockenligne.com - Extraction complète
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import os
import time
import json
from functools import lru_cache

# Configuration
BASE_URL = "https://www.destockenligne.com"
PRICE_MULTIPLIER = float(os.getenv('PRICE_MULTIPLIER', '1.685'))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)

# Cache
PRODUCT_CACHE = {}
CACHE_DURATION = 300

# ==================== OPTIMISATIONS SCRAPER ====================

# Cache plus agressif pour les pages fréquentes
FREQUENT_PAGES_CACHE = {}
FREQUENT_PATHS = [
    "/Chaussures-Homme-c100.html",
    "/Chaussures-Femme-c101.html", 
    "/Chaussures-Enfant-c102.html",
    "/Nike-c1.html", "/Adidas-c2.html"
]

def safe_get_cached(url, timeout=10):
    """Version cached de safe_get pour les pages fréquentes"""
    if url in FREQUENT_PAGES_CACHE:
        return FREQUENT_PAGES_CACHE[url]
    
    html = safe_get(url, timeout)
    if html:
        FREQUENT_PAGES_CACHE[url] = html
    return html

def preload_frequent_pages():
    """Précharge les pages les plus fréquentées"""
    print("🔧 Préchargement des pages fréquentes...")
    for path in FREQUENT_PATHS:
        try:
            full_url = _normalize_href(path)
            html = safe_get(full_url, timeout=8)
            if html:
                FREQUENT_PAGES_CACHE[full_url] = html
                print(f"✅ Page préchargée: {path}")
            else:
                print(f"❌ Échec préchargement: {path}")
        except Exception as e:
            print(f"❌ Erreur préchargement {path}: {e}")

# Chargement des overrides
OVERRIDES = {}
OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), 'overrides.json')

def load_overrides():
    """Charge les overrides depuis le fichier JSON"""
    global OVERRIDES
    try:
        if os.path.exists(OVERRIDES_FILE):
            with open(OVERRIDES_FILE, 'r', encoding='utf-8') as f:
                OVERRIDES = json.load(f)
            print(f"✅ Overrides chargés: {len(OVERRIDES)} règles")
        else:
            print("❌ Fichier overrides.json non trouvé")
            OVERRIDES = {}
    except Exception as e:
        print(f"❌ Erreur chargement overrides: {e}")
        OVERRIDES = {}

# Charger les overrides au démarrage
load_overrides()

def get_gender_sections():
    """Récupère les sections par genre - OPTIMISÉE"""
    pages = {
        "homme": "/Chaussures-Homme-c100.html", 
        "femme": "/Chaussures-Femme-c101.html", 
        "enfant": "/Chaussures-Enfant-c102.html"
    }
    
    out = {}
    
    for key, path in pages.items():
        try:
            html = safe_get(_normalize_href(path))
            if not html:
                out[key] = []
                continue
                
            soup = BeautifulSoup(html, "html.parser")
            div = soup.find("div", id="prohref")
            items = []
            
            if div:
                for a in div.find_all("a", href=True):
                    name = a.get("title") or a.get_text(strip=True)
                    href = a["href"]
                    
                    # Normaliser l'URL
                    if href.startswith("http"):
                        parsed = urlparse(href)
                        href = parsed.path or href
                        if parsed.query: 
                            href += "?" + parsed.query
                    
                    # Image
                    image = None
                    img = a.find("img")
                    if img and img.get("src"):
                        image = img.get("src")
                        if image and not image.startswith("http"):
                            image = urljoin(BASE_URL, image)
                    
                    # Prix
                    price_text = ""
                    price_span = (a.find_previous("span", class_=lambda x: x and "price" in x.lower()) or 
                                 a.find_next("span", class_=lambda x: x and "price" in x.lower()))
                    if price_span: 
                        price_text = price_span.get_text(strip=True)
                    
                    # Appliquer multiplicateur
                    display_price = ""
                    if price_text:
                        try:
                            clean_price = price_text.replace('€', '').replace(',', '.').strip()
                            price_value = float(clean_price) if clean_price else 0.0
                            multiplied_price = price_value * PRICE_MULTIPLIER
                            display_price = f"€ {multiplied_price:.2f}"
                        except (ValueError, TypeError):
                            display_price = price_text
                    
                    items.append({
                        "name": name, 
                        "path": href, 
                        "image": image, 
                        "display_price": display_price, 
                        "original_price": price_text
                    })
            
            out[key] = items
        except Exception as e:
            print(f"get_gender_sections error for {key}: {e}")
            out[key] = []
    
    return out

def apply_category_overrides(product_path, product_data, category_path=None):
    """Applique les overrides de catégorie aux produits - VERSION CORRIGÉE"""
    if not OVERRIDES or not product_data:
        return product_data
    
    # Vérifier d'abord les overrides exacts (URL complète)
    for override_path, override_data in OVERRIDES.items():
        if override_path == product_path:
            if override_data.get('hidden', False):
                return None
            
            # Sauvegarder le prix de base AVANT override
            original_base_price = product_data.get('base_price', product_data.get('price_value', 0))
            print (original_base_price)
            
            # Appliquer le prix override
            if 'price' in override_data:
                try:
                    price_str = override_data['price'].replace('€', '').replace(',', '.').strip()
                    price_value = float(price_str) if price_str else 0.0
                    product_data['price_value'] = price_value
                    product_data['new_price'] = f"€ {price_value:.2f}"
                    # Conserver le prix de base original
                    product_data['base_price'] = original_base_price
                    print(f"✅ Override EXACT appliqué: {override_path} -> {price_value}€ (base: {original_base_price}€)")
                except (ValueError, TypeError) as e:
                    print(f"❌ Erreur override prix exact {override_path}: {e}")
            
            # L'image dans l'override est optionnelle
            if 'image' in override_data:
                product_data['main_img'] = override_data['image']
            
            return product_data
    
    # Ensuite vérifier les overrides par catégorie avec motifs
    for override_path, override_data in OVERRIDES.items():
        # Si l'override est pour une catégorie (contient un motif * ou correspond à la catégorie actuelle)
        if '*' in override_path:
            # Créer un motif regex à partir du chemin d'override
            pattern = override_path.replace('*', '.*')
            if re.search(pattern, product_path):
                # Masquer le produit si nécessaire
                if override_data.get('hidden', False):
                    return None
                
                # Sauvegarder le prix de base AVANT override
                original_base_price = product_data.get('base_price', product_data.get('price_value', 0))
                
                # Appliquer le prix override
                if 'price' in override_data:
                    try:
                        price_str = override_data['price'].replace('€', '').replace(',', '.').strip()
                        price_value = float(price_str) if price_str else 0.0
                        product_data['price_value'] = price_value
                        product_data['new_price'] = f"€ {price_value:.2f}"
                        # Conserver le prix de base original
                        product_data['base_price'] = original_base_price
                        print(f"✅ Override CATÉGORIE appliqué: {override_path} -> {product_path} = {price_value}€ (base: {original_base_price}€)")
                    except (ValueError, TypeError) as e:
                        print(f"❌ Erreur override prix {override_path}: {e}")
                
                # Appliquer l'image si spécifiée (optionnel)
                if 'image' in override_data:
                    product_data['main_img'] = override_data['image']
                
                return product_data
        
        # Vérifier aussi si l'override correspond à la catégorie parente
        if category_path and override_path in category_path:
            if override_data.get('hidden', False):
                return None
            
            # Sauvegarder le prix de base AVANT override
            original_base_price = product_data.get('base_price', product_data.get('price_value', 0))
            
            if 'price' in override_data:
                try:
                    price_str = override_data['price'].replace('€', '').replace(',', '.').strip()
                    price_value = float(price_str) if price_str else 0.0
                    product_data['price_value'] = price_value
                    product_data['new_price'] = f"€ {price_value:.2f}"
                    # Conserver le prix de base original
                    product_data['base_price'] = original_base_price
                    print(f"✅ Override CATÉGORIE PARENTE appliqué: {override_path} -> {product_path} = {price_value}€ (base: {original_base_price}€)")
                except (ValueError, TypeError) as e:
                    print(f"❌ Erreur override prix catégorie {override_path}: {e}")
            
            return product_data
    
    return product_data

# ----------------- FONCTIONS DE BASE -----------------
def safe_get(url, timeout=12):
    """Récupère le contenu HTML avec gestion d'erreurs améliorée"""
    try:
        # Essayer d'abord le cache pour les pages fréquentes
        if url in FREQUENT_PAGES_CACHE:
            return FREQUENT_PAGES_CACHE[url]
            
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Erreur requête {url}: {e}")
        return ""

def _normalize_href(href, base=BASE_URL):
    """Normalise les URLs"""
    if not href:
        return None
    if href.startswith(('http://', 'https://')):
        return href
    return urljoin(base, href.lstrip('/'))

def _extract_price(price_text, apply_multiplier=True):
    """Extrait et applique le multiplicateur de prix de manière robuste"""
    if not price_text:
        return 0.0, ""
    
    # Nettoyage plus agressif du texte de prix
    clean_text = re.sub(r'[^\d,]', '', price_text.strip())
    clean_text = clean_text.replace(',', '.')
    
    # Extraction du premier nombre trouvé
    price_match = re.search(r'(\d+\.?\d*)', clean_text)
    if price_match:
        try:
            price_value = float(price_match.group(1))
            # Appliquer le multiplicateur seulement si demandé
            final_price = price_value * PRICE_MULTIPLIER if apply_multiplier else price_value
            return final_price, f"€ {final_price:.2f}"
        except (ValueError, TypeError):
            pass
    
    return 0.0, "Prix non disponible"

# ----------------- EXTRACTION COMPLÈTE -----------------
def _extract_title_improved(soup):
    """Extrait le titre du produit de manière robuste"""
    selectors = ['div.h_name', 'h1', '.product-title', '#bar b', 'title']
    
    for selector in selectors:
        title_tag = soup.select_one(selector)
        if title_tag:
            title = title_tag.get_text(strip=True)
            if title and title not in ['', 'Détail', 'Product']:
                title = re.sub(r'^\s*-\s*', '', title)
                return title
    
    return "Produit sans nom"

def _extract_breadcrumb(soup):
    """Extrait le fil d'Ariane"""
    breadcrumb = []
    bar_div = soup.select_one("div#bar")
    if bar_div:
        # Supprimer les scripts
        for script in bar_div.select("script"):
            script.decompose()
        
        # Extraire les liens
        links = bar_div.select("a")
        for link in links:
            href = link.get("href")
            text = link.get_text(strip=True)
            if href and text:
                breadcrumb.append({
                    "text": text,
                    "path": href,
                    "url": _normalize_href(href)
                })
    
    return breadcrumb

def _extract_prohref_links(soup):
    """Extrait les liens de navigation prohref"""
    prohref_links = []
    prohref_div = soup.select_one("div#prohref")
    if prohref_div:
        for a in prohref_div.select("a"):
            href = a.get("href")
            title = a.get("title") or a.get_text(strip=True)
            if href and title:
                prohref_links.append({
                    "title": title,
                    "path": href,
                    "url": _normalize_href(href)
                })
    return prohref_links

def _extract_pagination_info(soup, current_path, current_page=1):
    """Extrait les informations de pagination complètes"""
    paging = {
        "current": current_page,
        "total": 1,
        "has_next": False,
        "has_prev": False,
        "pages": [],
        "total_items": 0,
        "display_text": "",
        "prev_url": None,
        "next_url": None
    }
    
    showpage_div = soup.select_one("div#showpage")
    if not showpage_div:
        return paging

    # Extraire le texte d'affichage
    display_text = showpage_div.get_text(" ", strip=True)
    paging["display_text"] = display_text
    
    # Extraire le nombre total d'items
    total_match = re.search(r'Total\s*<font[^>]*>(\d+)</font>\s*item', display_text)
    if total_match:
        paging["total_items"] = int(total_match.group(1))
    
    # Extraire la pagination du select
    select = showpage_div.select_one('select[name="page"]')
    if select:
        pages = []
        for option in select.select('option'):
            try:
                page_num = int(option.get('value'))
                pages.append(page_num)
            except (ValueError, TypeError):
                continue
        if pages:
            paging["pages"] = pages
            paging["total"] = max(pages) if pages else 1
    
    # Vérifier les boutons précédent/suivant
    prev_links = showpage_div.select('a:contains("Prev")')
    next_links = showpage_div.select('a:contains("Next")')
    
    paging["has_prev"] = len(prev_links) > 0 and current_page > 1
    paging["has_next"] = len(next_links) > 0 and current_page < paging["total"]
    
    # Construire les URLs de pagination
    base_path = current_path.split('.html')[0]
    base_path = re.sub(r"_[0-9]+$", "", base_path)
    
    if paging["has_prev"]:
        prev_page = current_page - 1
        paging["prev_url"] = f"{base_path}_{prev_page}.html" if prev_page > 1 else f"{base_path}.html"
    
    if paging["has_next"]:
        next_page = current_page + 1
        paging["next_url"] = f"{base_path}_{next_page}.html"
    
    return paging

def _extract_main_image_improved(soup):
    """Extrait l'image principale"""
    img_selectors = [
        'div.views_pics img',
        'a#zoom1 img',
        'img.abc',
        '.main-image img',
        'img[src*="/pic/"]',
        'img[src*="/product/"]'
    ]
    
    for selector in img_selectors:
        img_tag = soup.select_one(selector)
        if img_tag and img_tag.get('src'):
            return _normalize_href(img_tag['src'])
    
    return None

def _extract_sizes_improved(soup):
    """Extrait les tailles disponibles"""
    size_selectors = [
        'select[name="hw_sizeone"]',
        'select[name="hw_size"]',
        '.size-select'
    ]
    
    sizes = []
    for selector in size_selectors:
        size_select = soup.select_one(selector)
        if size_select:
            for option in size_select.select('option'):
                value = option.get('value', '').strip()
                if value and value not in ['', 'Taille', 'Size']:
                    sizes.append(value)
            if sizes:
                break
    
    return sizes if sizes else ["Unique"]

def _extract_products_from_soup(soup, category_path=None):
    """Extrait les produits d'une page de catégorie"""
    products = []
    for ul in soup.select("ul.re00"):
        try:
            img_tag = ul.select_one("li.hw1 img")
            info_a = ul.select_one("li.hw2 a")
            old_price_tag = ul.select_one("li.hw2 s")
            spans = ul.select("li.hw2 span")
            new_price_tag = spans[0] if spans else None

            # Économie
            econ = ""
            for sp in spans:
                if "Economie" in sp.get_text():
                    econ = sp.get_text(strip=True)
                    break
            if not econ and len(spans) >= 2:
                econ = spans[-1].get_text(strip=True)

            name = info_a.get_text(strip=True) if info_a else ""
            href = info_a.get("href") if info_a else None

            # Extraction du prix SANS multiplicateur d'abord (prix de base)
            new_price_text = new_price_tag.get_text(strip=True) if new_price_tag else ""
            base_price, base_formatted = _extract_price(new_price_text, apply_multiplier=False)
            
            # Prix final avec multiplicateur
            final_price = base_price * PRICE_MULTIPLIER
            final_formatted = f"€ {final_price:.2f}"

            product_data = {
                "name": name,
                "path": href,
                "url": _normalize_href(href),
                "image": _normalize_href(img_tag["src"]) if img_tag and img_tag.get("src") else None,
                "old_price": old_price_tag.get_text(strip=True) if old_price_tag else "",
                "new_price": final_formatted,
                "price_value": final_price,
                "base_price": base_price,  # Prix de base SANS modifications
                "economy": econ,
            }

            # Appliquer les overrides de catégorie (PRIORITÉ ABSOLUE)
            if href:
                product_data = apply_category_overrides(href, product_data, category_path)
            
            if product_data:  # Si le produit n'est pas masqué
                products.append(product_data)
                
        except Exception as e:
            print(f"Erreur extraction produit: {e}")
            continue
            
    return products

# ----------------- SCRAPING PRINCIPAL AMÉLIORÉ -----------------
@lru_cache(maxsize=128)
def get_categories():
    """Récupère les catégories"""
    try:
        html = safe_get(BASE_URL + "/")
        if not html:
            return {"headers": [], "brands": []}
            
        soup = BeautifulSoup(html, "html.parser")
        sidebar = soup.select_one("div.sideBar_left") or soup.select_one("#leftsideBar")
        
        if not sidebar:
            return {"headers": [], "brands": []}
        
        headers = [h.get_text(strip=True) for h in sidebar.select(".insort0")]
        brands = []
        last_header = ""
        
        for el in sidebar.find_all(recursive=False):
            for h in el.select(".insort0"):
                last_header = h.get_text(strip=True)
            for a in el.select(".insort1 a"):
                href = a.get("href")
                title = a.get_text(strip=True)
                if href and title:
                    brands.append({
                        "title": title, 
                        "path": href, 
                        "header": last_header
                    })
        
        return {"headers": headers, "brands": brands}
    except Exception as e:
        print(f"Erreur catégories: {e}")
        return {"headers": [], "brands": []}

def get_category_products(path, page=1):
    """Récupère les produits d'une catégorie avec pagination"""
    try:
        # Construction URL paginée
        if page > 1:
            base = path.split(".html")[0]
            base = re.sub(r"_[0-9]+$", "", base)
            page_path = f"{base}_{page}.html"
        else:
            page_path = path

        html = safe_get(_normalize_href(page_path))
        if not html:
            return [], {"current": page, "total": 1, "has_next": False}
            
        soup = BeautifulSoup(html, "html.parser")
        products = _extract_products_from_soup(soup, category_path=path)
        
        # Pagination complète
        paging = _extract_pagination_info(soup, path, page)
        
        return products, paging
        
    except Exception as e:
        print(f"Erreur produits catégorie {path}: {e}")
        return [], {"current": page, "total": 1, "has_next": False}

def get_product_details(path, page=1):
    """Récupère les détails d'un produit - VERSION COMPLÈTE"""
    try:
        # Construction URL
        if page > 1:
            base = path.split(".html")[0]
            base = re.sub(r"_[0-9]+$", "", base)
            page_path = f"{base}_{page}.html"
        else:
            page_path = path

        full_url = _normalize_href(page_path)
        html = safe_get(full_url)
        
        if not html:
            return {}
            
        soup = BeautifulSoup(html, "html.parser")

        # Vérification type de page
        is_category = bool(soup.select("ul.re00")) and not bool(soup.select("div.views_pics, select[name='hw_sizeone']"))
        
        if is_category:
            # Extraction titre de catégorie
            category_title = ""
            bar_div = soup.select_one("div#bar")
            if bar_div:
                b_tag = bar_div.select_one("b")
                if b_tag:
                    category_title = b_tag.get_text(strip=True)
            
            return {
                "is_category": True,
                "category_title": category_title,
                "breadcrumb": _extract_breadcrumb(soup),
                "prohref_links": _extract_prohref_links(soup),
                "products": _extract_products_from_soup(soup, category_path=path),
                "paging": _extract_pagination_info(soup, path, page),
                "path": path
            }

        # EXTRACTION PRODUIT - VERSION COMPLÈTE
        title = _extract_title_improved(soup)
        main_img = _extract_main_image_improved(soup)
        
        # PRIX - EXTRACTION AMÉLIORÉE
        price_text = ""
        # Chercher d'abord dans les balises de prix spécifiques
        price_selectors = [
            'b[style*="color"]',
            'font[color="#FF0000"]',
            'span.price',
            'b.price',
            'b[style]',
            'b'
        ]

        for selector in price_selectors:
            price_tag = soup.select_one(selector)
            if price_tag:
                candidate_text = price_tag.get_text(strip=True)
                # Vérifier que c'est bien un prix (contient des chiffres)
                if re.search(r'\d', candidate_text):
                    price_text = candidate_text
                    break
        
        # Extraction SANS multiplicateur d'abord (prix de base)
        base_price, base_formatted = _extract_price(price_text, apply_multiplier=False)
        
        # Ancien prix
        old_price = ""
        old_price_tag = soup.select_one("s")
        if old_price_tag:
            old_price = old_price_tag.get_text(strip=True)
        
        # Tailles
        sizes = _extract_sizes_improved(soup)
        
        # Options quantité
        qty_options = list(range(1, 11))
        
        # Description
        description = ""
        desc_tag = soup.select_one("#Content .con_bot") or soup.select_one("div#Content") or soup.select_one("div.product_description")
        if desc_tag:
            description = desc_tag.get_text("\n", strip=True)

        # Produits similaires
        related = _extract_products_from_soup(soup)

        result = {
            "is_category": False,
            "title": title,
            "main_img": main_img,
            "old_price": old_price,
            "new_price": base_formatted,
            "price_value": base_price,  # Prix de base pour l'instant
            "base_price": base_price,   # Prix de base SANS modifications
            "sizes": sizes,
            "qty_options": qty_options,
            "description": description,
            "related": related,
            "breadcrumb": _extract_breadcrumb(soup),
            "prohref_links": _extract_prohref_links(soup),
            "path": path,
            "url": full_url,
        }

        # Appliquer les overrides (PRIORITÉ ABSOLUE)
        result = apply_category_overrides(path, result)
        
        # Si pas d'override, appliquer le multiplicateur au prix final
        if result and result.get('price_value') == result.get('base_price'):
            final_price = result['price_value'] * PRICE_MULTIPLIER
            result['price_value'] = final_price
            result['new_price'] = f"€ {final_price:.2f}"
        
        return result
        
    except Exception as e:
        print(f"Erreur détails produit {path}: {e}")
        return {}

def reload_overrides():
    """Recharge les overrides depuis le fichier"""
    load_overrides()
    print("✅ Overrides rechargés")

def clear_frequent_cache():
    """Vide le cache des pages fréquentes"""
    FREQUENT_PAGES_CACHE.clear()
    print("✅ Cache pages fréquentes vidé")

# Appeler le préchargement au chargement du module
try:
    preload_frequent_pages()
except Exception as e:
    print(f"❌ Erreur préchargement initial: {e}")

if __name__ == "__main__":
    print(f"🔧 Multiplicateur: {PRICE_MULTIPLIER}x")
    
    # Test avec le produit problématique
    test_path = "/Nike-Air-Max-Plus-2025-325541.html"
    print(f"Test extraction: {test_path}")
    
    product_data = get_product_details(test_path)
    if product_data:
        print(f"✅ Titre: {product_data.get('title')}")
        print(f"✅ Prix client: {product_data.get('new_price')}")
        print(f"✅ Prix de base: {product_data.get('base_price')}€")
        print(f"✅ Ancien prix: {product_data.get('old_price')}")
        print(f"✅ Image: {product_data.get('main_img')}")
        print(f"✅ Tailles: {product_data.get('sizes')}")
    else:
        print("❌ Produit non trouvé")