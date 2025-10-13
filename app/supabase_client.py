import os
from supabase import create_client
from dotenv import load_dotenv
from decimal import Decimal

load_dotenv()

# -------------------- CONFIG --------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# -------------------- CLIENTS --------------------
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# -------------------- AUTH --------------------
def register_user(email, password):
    return supabase.auth.sign_up({"email": email, "password": password})

def login_user(email, password):
    return supabase.auth.sign_in_with_password({"email": email, "password": password})

def reset_password_for_email(email):
    return supabase.auth.reset_password_for_email(
        email,
        {'redirect_to': f"{os.getenv('BASE_URL', 'http://127.0.0.1:5000')}/update-password"}
    )

def verify_token(access_token):
    try:
        user = supabase.auth.get_user(access_token)
        return user.user.id if user and user.user else None
    except Exception as e:
        print(f"[verify_token] {e}")
        return None

# -------------------- PANIER --------------------
def get_cart_data(user_id):
    try:
        res = supabase.table("carts").select("id,product_name,price,qty,size,product_image,path").eq("user_id", user_id).execute()
        return res.data or []
    except Exception as e:
        print(f"[get_cart_data] {e}")
        return []

def add_to_cart(user_id, product_name, path, product_image, price, qty=1, size=None):
    try:
        item = {
            "user_id": user_id,
            "product_name": product_name,
            "path": path,
            "product_image": product_image,
            "price": float(price),
            "qty": int(qty),
            "size": size
        }
        return supabase.table("carts").insert(item).execute()
    except Exception as e:
        print(f"[add_to_cart] {e}")
        raise e

# -------------------- ORDERS --------------------
def create_order(payload):
    try:
        return supabase.table("orders").insert(payload).execute()
    except Exception as e:
        print(f"[create_order] {e}")
        raise e

# -------------------- ADRESSES --------------------
def get_user_address(user_id):
    try:
        res = supabase.table("user_addresses").select("*").eq("user_id", user_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[get_user_address] {e}")
        return None

def save_user_address(user_id, address_data):
    try:
        existing = get_user_address(user_id)
        if existing:
            return supabase.table("user_addresses").update({
                "full_name": address_data["full_name"],
                "address_line1": address_data["address_line1"],
                "address_line2": address_data.get("address_line2", ""),
                "city": address_data["city"],
                "postal_code": address_data["postal_code"],
                "country": address_data.get("country", "France"),
            }).eq("id", existing["id"]).execute()
        else:
            address_data.update({"user_id": user_id, "is_default": True})
            return supabase.table("user_addresses").insert(address_data).execute()
    except Exception as e:
        print(f"[save_user_address] {e}")
        raise e

# -------------------- STORAGE --------------------
def upload_image(file, filename):
    try:
        supabase.storage.from_("product-images").upload(filename, file.stream, {"content-type": file.mimetype})
        return f"{SUPABASE_URL}/storage/v1/object/public/product-images/{filename}"
    except Exception as e:
        print(f"[upload_image] {e}")
        return None
