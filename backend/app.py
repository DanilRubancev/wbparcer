#!/usr/bin/env python3
"""
Wildberries Parser — Flask backend
Парсит данные о товарах через публичное API Wildberries.
При недоступности API (rate-limit/блокировка) генерирует
реалистичные данные для демонстрации дашбордов.
"""

import sqlite3
import json
import time
import threading
import random
import os
import re
from datetime import datetime
from urllib.parse import urlparse, unquote
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from werkzeug.security import generate_password_hash, check_password_hash

# Папка с фронтендом — на уровень выше backend/, затем frontend/public/
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_DIR = os.path.join(_BASE_DIR, "..", "frontend", "public")

app = Flask(__name__, static_folder=None)
CORS(app, origins="*")

DB_PATH = os.path.join(os.path.dirname(__file__), "wb_parser.db")

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            consent_agreed BOOLEAN DEFAULT 0,
            consent_date TIMESTAMP,
            consent_ip TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT NOT NULL,
            query_type TEXT NOT NULL DEFAULT 'keyword',
            status TEXT NOT NULL DEFAULT 'pending',
            product_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL,
            article INTEGER NOT NULL,
            name TEXT,
            brand TEXT,
            price INTEGER,
            price_original INTEGER,
            discount INTEGER,
            rating REAL,
            feedbacks INTEGER,
            supplier TEXT,
            category TEXT,
            colors TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (search_id) REFERENCES searches(id)
        );

        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            search_id INTEGER,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (search_id) REFERENCES searches(id)
        );
    """)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO users 
               (username, password, consent_agreed, consent_date, consent_ip) 
               VALUES (?, ?, ?, ?, ?)""",
            ("demo", generate_password_hash("demo123"), 1, datetime.now().isoformat(), "127.0.0.1")
        )
        conn.execute("ALTER TABLE users ADD COLUMN consent_agreed BOOLEAN DEFAULT 0")
        conn.execute("ALTER TABLE users ADD COLUMN consent_date TIMESTAMP")
        conn.execute("ALTER TABLE users ADD COLUMN consent_ip TEXT")
        conn.commit()
    except Exception:
        pass
    # Миграция: хэшируем пароли существующих пользователей, которые ещё в открытом виде
    try:
        rows = conn.execute("SELECT id, password FROM users").fetchall()
        for row in rows:
            pw = row["password"]
            # werkzeug хэши начинаются с 'scrypt:', 'pbkdf2:' и т.п.
            if not (pw.startswith("scrypt:") or pw.startswith("pbkdf2:")):
                conn.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (generate_password_hash(pw), row["id"])
                )
        conn.commit()
    except Exception:
        pass
    conn.close()


# ─── Mock data generator ──────────────────────────────────────────────────────

BRANDS_POOL = [
    "Samsung", "Apple", "Xiaomi", "Huawei", "Sony", "LG", "JBL", "Beats",
    "Bose", "Lenovo", "ASUS", "Acer", "HP", "Dell", "MSI", "Realme",
    "OnePlus", "Oppo", "Vivo", "Nothing", "Motorola", "Nokia", "Philips",
    "Panasonic", "Sennheiser", "AKG", "Audio-Technica", "Plantronics",
]

SUPPLIERS_POOL = [
    "ООО ТехноТрейд", "ИП Иванов А.С.", "МегаМаркет Электроника",
    "GlobalTech Store", "Электроника Онлайн", "ООО РитейлГрупп",
    "TechStore RU", "ИП Смирнова В.П.", "Цифровой Мир",
    "ООО ЭлектроПоставки", "Prime Electronics", "ООО ТехноЛэнд",
]

PRODUCT_ADJECTIVES = [
    "Беспроводные", "Профессиональные", "Игровые", "Спортивные",
    "Складные", "Накладные", "Вакуумные", "Компактные", "Бюджетные",
    "Флагманские", "Шумоподавляющие", "Сертифицированные",
]

COLORS_POOL = [
    ["Чёрный"], ["Белый"], ["Серый"], ["Синий"], ["Красный"],
    ["Чёрный", "Белый"], ["Чёрный", "Синий"], ["Золотой", "Серебристый"],
    ["Зелёный"], ["Фиолетовый"], ["Розовый"],
]


def _make_product_name(query: str, brand: str, adj: str) -> str:
    query_words = query.strip().split()
    base = " ".join(query_words[:2]).capitalize() if query_words else "Товар"
    return f"{brand} {adj} {base} 2024"


def generate_mock_products(query: str, count: int = 40) -> list[dict]:
    """
    Генерирует реалистичные данные товаров для демонстрации.
    Используется как fallback когда WB API недоступен.
    """
    rng = random.Random(hash(query) % 2**32)

    # Определяем ценовой диапазон из запроса
    if any(w in query.lower() for w in ["premium", "флагман", "apple", "iphone", "macbook"]):
        base_price = rng.randint(30000, 150000)
    elif any(w in query.lower() for w in ["бюджет", "дешев", "дешёв"]):
        base_price = rng.randint(500, 5000)
    else:
        base_price = rng.randint(2000, 25000)

    brands = rng.sample(BRANDS_POOL, min(8, len(BRANDS_POOL)))
    suppliers = rng.sample(SUPPLIERS_POOL, min(6, len(SUPPLIERS_POOL)))

    products = []
    for i in range(count):
        brand = rng.choice(brands)
        adj = rng.choice(PRODUCT_ADJECTIVES)
        name = _make_product_name(query, brand, adj)
        if i > 0:
            name += f" v{rng.randint(1, 5)}.{rng.randint(0, 9)}"

        price_factor = rng.uniform(0.3, 2.5)
        price_original = int(base_price * price_factor)
        discount = rng.choice([0, 0, 5, 10, 15, 20, 25, 30, 35, 40, 50])
        price = int(price_original * (1 - discount / 100))
        if price < 50:
            price = 50

        rating = rng.uniform(3.5, 5.0)
        feedbacks = rng.randint(0, 8000)
        # Высокорейтинговые товары — больше отзывов
        if rating > 4.5:
            feedbacks = int(feedbacks * 2.5)

        products.append({
            "article": rng.randint(10000000, 999999999),
            "name": name,
            "brand": brand,
            "price": price,
            "price_original": price_original,
            "discount": discount,
            "rating": round(rating, 1),
            "feedbacks": feedbacks,
            "supplier": rng.choice(suppliers),
            "category": query.capitalize()[:30],
            "colors": json.dumps(rng.choice(COLORS_POOL), ensure_ascii=False),
        })

    return products


# ─── Real WB parsers ──────────────────────────────────────────────────────────

WB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": "https://www.wildberries.ru/",
    "Origin": "https://www.wildberries.ru",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

_wb_session = requests.Session()
_wb_session.headers.update(WB_HEADERS)


def _normalize_product(raw: dict) -> dict:
    sizes = raw.get("sizes", [{}])
    price_data = sizes[0].get("price", {}) if sizes else {}

    # v4 API: price.product = текущая цена, price.basic = цена до скидки (в копейках)
    price_product = price_data.get("product", 0)
    price_basic = price_data.get("basic", 0)

    price = price_product // 100 if price_product else raw.get("salePriceU", 0) // 100
    price_original = price_basic // 100 if price_basic else raw.get("priceU", 0) // 100

    if price == 0:
        price = raw.get("salePriceU", 0) // 100
    if price_original == 0 or price_original < price:
        price_original = price

    discount = 0
    if price_original > 0 and price > 0 and price < price_original:
        discount = round((1 - price / price_original) * 100)

    colors = raw.get("colors", [])
    color_names = [c.get("name", "") for c in colors] if isinstance(colors, list) else []

    return {
        "article": raw.get("id", 0),
        "name": raw.get("name", ""),
        "brand": raw.get("brand", ""),
        "price": price,
        "price_original": price_original,
        "discount": discount,
        "rating": raw.get("reviewRating", raw.get("rating", 0)),
        "feedbacks": raw.get("feedbacks", 0),
        "supplier": raw.get("supplier", ""),
        "category": raw.get("category", raw.get("subjectName", "")),
        "colors": json.dumps(color_names, ensure_ascii=False),
    }


# Все известные рабочие dest-коды. При 429 пробуем следующий с паузой.
# Порядок подобран по результатам диагностики (первые — наиболее стабильные)
_WB_DESTS = [-1257786, 12358062, -2133462, -1059500, -1581744, 1259570991, -1569611]

# Единый persistent session — важно не пересоздавать его между запросами
_wb_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.wildberries.ru/",
    "Origin": "https://www.wildberries.ru",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
})

# Время последнего успешного запроса к WB — для rate-limit control
_last_wb_request: float = 0.0


# Пауза между попытками нарастает с каждым 429.
# WB считает запросы в окне ~10 сек — нужно выходить за это окно.
_RETRY_DELAYS = [4, 7, 11, 16, 21, 25, 30]   # сек ожидания перед каждым dest

def _wb_get(params: dict, timeout: int = 15):
    """
    Запрос к WB API v4 с перебором всех dest-кодов и нарастающими паузами.
    Возвращает список сырых товаров или [].
    """
    global _last_wb_request

    url = "https://search.wb.ru/exactmatch/ru/common/v4/search"

    for i, dest in enumerate(_WB_DESTS):
        # Пауза: при первой попытке — с момента последнего запроса,
        # при retry — фиксированная нарастающая задержка
        wait = _RETRY_DELAYS[i]
        now = time.time()
        elapsed = now - _last_wb_request
        if elapsed < wait:
            actual_wait = wait - elapsed + random.uniform(0.3, 1.0)
            app.logger.info(f"WB: ждём {actual_wait:.1f} сек перед dest={dest}...")
            time.sleep(actual_wait)

        p = dict(params)
        p["dest"] = dest

        try:
            _last_wb_request = time.time()
            app.logger.info(f"WB: запрос dest={dest} (попытка {i+1}/{len(_WB_DESTS)})...")
            resp = _wb_session.get(url, params=p, timeout=timeout)
            app.logger.info(f"WB: ответ dest={dest} → HTTP {resp.status_code}")

            if resp.status_code == 429:
                app.logger.warning(f"WB 429 dest={dest}, след. попытка через {_RETRY_DELAYS[min(i+1, len(_RETRY_DELAYS)-1)]} сек")
                continue

            if resp.status_code != 200:
                app.logger.warning(f"WB HTTP {resp.status_code} dest={dest}")
                continue

            data = resp.json()

            # WB возвращает две разных структуры в зависимости от dest:
            # Структура A (большинство dest): {"data": {"products": [...]}}
            # Структура B (dest=12358062):    {"products": [...], "metadata": ..., "total": ...}
            products = (
                data.get("data", {}).get("products")   # структура A
                or data.get("products")                # структура B
                or []
            )

            # Проверяем что товары реально соответствуют запросу:
            # иногда WB возвращает 1 случайный товар вместо пустого ответа
            query_kw = params.get("query", "").lower().split()
            if len(products) == 1 and query_kw:
                name = (products[0].get("name") or "").lower()
                subj = (products[0].get("subjectName") or products[0].get("entity") or "").lower()
                # Если ни одно слово запроса не встречается — игнорируем
                match = any(w in name or w in subj for w in query_kw)
                if not match:
                    app.logger.warning(
                        f"WB: dest={dest} вернул 1 нерелевантный товар "
                        f"('{products[0].get('name','')}'), пропускаем"
                    )
                    continue

            if products:
                app.logger.info(f"WB OK: {len(products)} товаров (dest={dest})")
                return products
            else:
                app.logger.warning(f"WB: пустой ответ dest={dest}, ключи: {list(data.keys())}")

        except Exception as e:
            app.logger.error(f"WB error dest={dest}: {e}")
            continue

    app.logger.error("WB: все dest исчерпаны, товаров нет")
    return []


def parse_wb_search_real(query: str, limit: int = 100) -> list[dict]:
    """Поиск товаров по ключевому слову через WB API v4."""
    params = {
        "query": query,
        "resultset": "catalog",
        "limit": min(limit, 100),
        "sort": "popular",
        "page": 1,
        "appType": 1,
        "curr": "rub",
        # spp НЕ передаём — с ним чаще 429
        # dest подставляется внутри _wb_get
    }
    products_raw = _wb_get(params)
    return [_normalize_product(p) for p in products_raw]


def _get_wb_basket(article: int) -> str:
    """Вычисляет номер basket-сервера WB по артикулу.
    Пороги обновлены по данным диагностики (basket-26 активен).
    """
    vol = article // 100000
    thresholds = [
        143, 287, 431, 719, 1007, 1061, 1115, 1169, 1313, 1601,
        1655, 1919, 2045, 2189, 2405, 2621, 2837, 3200, 3479,
        3758, 4037, 4316, 4595, 4874, 5153, 5432, 5711, 5990,
        6269, 6548, 6827, 7106, 7385, 7664, 7943, 8222, 8501,
        8780, 9059, 9338, 9617, 9896,  # basket 39-43 (запас)
    ]
    for i, t in enumerate(thresholds):
        if vol <= t:
            return str(i + 1).zfill(2)
    return str(len(thresholds) + 1).zfill(2)


def _find_wb_basket(article: int) -> str | None:
    """Находит реальный basket перебором если _get_wb_basket промахнулся.
    Проверяет вычисленный ±4, потом полный перебор 1-35.
    """
    computed = int(_get_wb_basket(article))
    vol  = article // 100000
    part = article // 1000

    def _check(bn: int) -> bool:
        basket = str(bn).zfill(2)
        url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}/info/ru/card.json"
        try:
            resp = _wb_session.get(url, timeout=6)
            if resp.status_code == 200 and resp.text.strip():
                d = resp.json()
                # card.json должен быть dict с полем imt_name
                return isinstance(d, dict) and bool(d.get("imt_name"))
        except Exception:
            pass
        return False

    # Сначала проверяем computed ±4
    candidates = sorted(set(range(max(1, computed - 4), min(36, computed + 5))))
    for bn in candidates:
        if _check(bn):
            return str(bn).zfill(2)

    # Полный перебор 1-35
    for bn in range(1, 36):
        if bn in candidates:
            continue
        if _check(bn):
            return str(bn).zfill(2)

    return None


def parse_wb_article_real(article: int) -> dict | None:
    """
    Получает данные одного товара по артикулу через basket CDN WB.
    Автоматически находит правильный basket-сервер.
    """
    # Пробуем вычисленный basket, при 404 — перебираем все
    basket = _get_wb_basket(article)
    vol  = article // 100000
    part = article // 1000
    base = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}"

    try:
        # 1. card.json — название, категория, бренд
        r_card = _wb_session.get(f"{base}/info/ru/card.json", timeout=10)
        if r_card.status_code != 200:
            app.logger.info(f"basket-{basket} промах для {article}, ищем правильный...")
            basket = _find_wb_basket(article)
            if not basket:
                app.logger.warning(f"Артикул {article} не найден ни на одном basket-сервере")
                return None
            base = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}"
            r_card = _wb_session.get(f"{base}/info/ru/card.json", timeout=10)
            if r_card.status_code != 200:
                app.logger.warning(f"basket card.json HTTP {r_card.status_code} для артикула {article}")
                return None
        card = r_card.json()

        imt_id   = card.get("imt_id", 0)   # нужен для запроса рейтинга
        name     = card.get("imt_name", "")
        category = card.get("subj_name", "")
        brand    = card.get("selling", {}).get("brand_name", "")
        # colors в card.json — список артикулов (int) или dict с name
        # Безопасно извлекаем только если элемент является словарём
        colors = [
            c["name"] for c in card.get("colors", [])
            if isinstance(c, dict) and c.get("name")
        ]

        # 2. sellers.json — поставщик
        supplier = ""
        try:
            r_sell = _wb_session.get(f"{base}/info/sellers.json", timeout=8)
            if r_sell.status_code == 200:
                supplier = r_sell.json().get("supplierName", "")
        except Exception:
            pass

        # 3. price-history.json — текущая цена (последняя запись)
        price = 0
        price_original = 0
        try:
            r_price = _wb_session.get(f"{base}/info/price-history.json", timeout=8)
            if r_price.status_code == 200:
                history = r_price.json()
                if history:
                    last = history[-1]
                    price = last.get("price", {}).get("RUB", 0) // 100
                if len(history) > 1:
                    price_original = max(
                        e.get("price", {}).get("RUB", 0) // 100 for e in history
                    )
                if price_original < price:
                    price_original = price
        except Exception:
            pass

        # 4. feedbacks — рейтинг и количество отзывов
        # WB хранит агрегированный рейтинг по imt_id, а не по nm_id (артикулу)
        rating = 0.0
        feedbacks = 0
        try:
            # Пробуем сначала по imt_id (там реальные данные), потом по артикулу
            fb_ids = [imt_id, article] if imt_id and imt_id != article else [article]
            for fb_id in fb_ids:
                for fb_host in ["feedbacks2.wb.ru", "feedbacks1.wb.ru"]:
                    fb_url = f"https://{fb_host}/feedbacks/v2/{fb_id}"
                    r_fb = _wb_session.get(fb_url, timeout=8)
                    if r_fb.status_code == 200:
                        fb_data = r_fb.json()
                        raw_cnt = fb_data.get("feedbackCount")
                        raw_val = fb_data.get("valuation")
                        if raw_cnt:
                            feedbacks = int(raw_cnt)
                            try:
                                rating = float(raw_val) if raw_val else 0.0
                            except (ValueError, TypeError):
                                rating = 0.0
                            break  # нашли
                if feedbacks > 0:
                    break
        except Exception:
            pass

        discount = 0
        if price_original > 0 and price > 0 and price < price_original:
            discount = round((1 - price / price_original) * 100)

        result = {
            "article":        article,
            "name":           name,
            "brand":          brand,
            "price":          price,
            "price_original": price_original,
            "discount":       discount,
            "rating":         rating,
            "feedbacks":      feedbacks,
            "supplier":       supplier,
            "category":       category,
            "colors":         colors,
        }
        app.logger.info(f"basket OK: {name[:50]} (артикул {article})")
        return result

    except Exception as e:
        app.logger.error(f"basket error для {article}: {e}")
        return None


def smart_parse(query: str, query_type: str, limit: int = 50) -> list[dict]:
    """
    Реальный парсинг через WB API v4.
    Возвращает пустой список если API недоступен.
    """
    products = []

    if query_type == "article":
        try:
            article = int(query)
            p = parse_wb_article_real(article)
            if p:
                products = [p]
        except ValueError:
            products = parse_wb_search_real(query, limit)
    elif query_type == "url":
        products = _parse_by_url(query)
    else:
        products = parse_wb_search_real(query, limit)

    return products


def _parse_by_url(wb_url: str) -> list[dict]:
    m = re.search(r"/catalog/(\d+)/", wb_url)
    if m:
        p = parse_wb_article_real(int(m.group(1)))
        return [p] if p else []
    m2 = re.search(r"[?&]search=([^&]+)", wb_url)
    if m2:
        return parse_wb_search_real(unquote(m2.group(1)))
    parsed = urlparse(wb_url)
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        return parse_wb_search_real(path_parts[-1].replace("-", " "))
    return []


# ─── Background job ───────────────────────────────────────────────────────────

def run_parse_job(search_id: int, query: str, query_type: str):
    conn = get_db()
    try:
        conn.execute("UPDATE searches SET status='running' WHERE id=?", (search_id,))
        conn.commit()

        products = smart_parse(query, query_type, limit=100)

        if not products:
            conn.execute(
                "UPDATE searches SET status='error' WHERE id=?", (search_id,)
            )
            conn.commit()
            conn.close()
            app.logger.warning(f"No products found for '{query}'")
            return

        for p in products:
            conn.execute(
                """INSERT INTO products
                   (search_id, article, name, brand, price, price_original,
                    discount, rating, feedbacks, supplier, category, colors)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    search_id, p["article"], p["name"], p["brand"],
                    p["price"], p["price_original"], p["discount"],
                    p["rating"], p["feedbacks"], p["supplier"],
                    p["category"],
                    json.dumps(p.get("colors") or [], ensure_ascii=False),
                )
            )

        conn.execute(
            "UPDATE searches SET status='done', product_count=? WHERE id=?",
            (len(products), search_id)
        )
        conn.commit()
    except Exception as e:
        app.logger.error(f"Parse job error: {e}")
        conn.execute("UPDATE searches SET status='error' WHERE id=?", (search_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Auth ─────────────────────────────────────────────────────────────────────

_sessions: dict[str, int] = {}


def get_current_user() -> int | None:
    token = request.headers.get("X-Auth-Token") or request.args.get("token")
    return _sessions.get(token) if token else None


def require_auth():
    uid = get_current_user()
    if uid is None:
        return jsonify({"error": "Unauthorized"}), 401
    return None


@app.post("/api/auth/login")
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    conn = get_db()
    row = conn.execute(
        "SELECT id, password FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    if not row or not check_password_hash(row["password"], password):
        return jsonify({"error": "Неверный логин или пароль"}), 401
    import secrets
    token = secrets.token_hex(32)
    _sessions[token] = row["id"]
    return jsonify({"token": token, "username": username})


@app.post("/api/auth/register")
@app.post("/api/auth/register")
def register():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    consent = data.get("consent", True)

    if not username or not password:
        return jsonify({"error": "Заполните все поля"}), 400
    if len(password) < 6:
        return jsonify({"error": "Пароль минимум 6 символов"}), 400

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO users (username, password, consent_agreed, consent_date, consent_ip) 
               VALUES (?,?,?,?,?)""",
            (username,
             generate_password_hash(password),
             1 if consent else 0,
             datetime.now().isoformat(),
             request.remote_addr)
        )
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        import secrets
        token = secrets.token_hex(32)
        _sessions[token] = row["id"]
        conn.close()
        return jsonify({"token": token, "username": username}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Пользователь уже существует"}), 409


@app.post("/api/auth/logout")
def logout():
    token = request.headers.get("X-Auth-Token")
    if token and token in _sessions:
        del _sessions[token]
    return jsonify({"ok": True})


# ─── Searches ─────────────────────────────────────────────────────────────────

@app.get("/api/searches")
def list_searches():
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM searches WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (uid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/searches")
def create_search():
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Введите запрос, артикул или ссылку"}), 400

    # Auto-detect type
    query_type = "keyword"
    if query.isdigit():
        query_type = "article"
    elif query.startswith("http"):
        query_type = "url"

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO searches (user_id, query, query_type, status) VALUES (?,?,?,?)",
        (uid, query, query_type, "pending")
    )
    search_id = cur.lastrowid
    conn.commit()
    conn.close()

    t = threading.Thread(target=run_parse_job, args=(search_id, query, query_type), daemon=True)
    t.start()

    return jsonify({"id": search_id, "status": "pending"}), 201


@app.get("/api/searches/<int:search_id>")
def get_search(search_id: int):
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM searches WHERE id=? AND user_id=?", (search_id, uid)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.delete("/api/searches/<int:search_id>")
def delete_search(search_id: int):
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()

    # Проверяем, есть ли сохранённые дашборды
    dashboard_count = conn.execute(
        "SELECT COUNT(*) FROM dashboards WHERE search_id = ?",
        (search_id,)
    ).fetchone()[0]

    if dashboard_count > 0:
        conn.close()
        return jsonify({"error": "Нельзя удалить поиск: сначала удалите дашборд из сохраннёных"}), 400

    conn.execute("DELETE FROM products WHERE search_id=?", (search_id,))
    conn.execute("DELETE FROM searches WHERE id=? AND user_id=?", (search_id, uid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ─── Products & Analytics ─────────────────────────────────────────────────────


@app.post("/api/searches/<int:search_id>/ingest")
def ingest_products(search_id: int):
    """Принимает товары, спарсенные браузером клиента, и сохраняет в БД."""
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    s = conn.execute(
        "SELECT id FROM searches WHERE id=? AND user_id=?", (search_id, uid)
    ).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    data = request.json or {}
    products = data.get("products", [])

    if not products:
        conn.execute("UPDATE searches SET status='error' WHERE id=?", (search_id,))
        conn.commit()
        conn.close()
        return jsonify({"error": "Нет товаров"}), 400

    # Очистим старые результаты для этого поиска
    conn.execute("DELETE FROM products WHERE search_id=?", (search_id,))

    for p in products:
        try:
            price = int(p.get("price", 0))
            price_original = int(p.get("price_original", price))
            if price_original < price:
                price_original = price
            discount = 0
            if price_original > 0 and price > 0 and price < price_original:
                discount = round((1 - price / price_original) * 100)

            colors = p.get("colors", [])
            colors_json = json.dumps(colors if isinstance(colors, list) else [], ensure_ascii=False)

            conn.execute(
                """INSERT INTO products
                   (search_id, article, name, brand, price, price_original,
                    discount, rating, feedbacks, supplier, category, colors)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    search_id,
                    int(p.get("article", 0)),
                    str(p.get("name", "")),
                    str(p.get("brand", "")),
                    price,
                    price_original,
                    discount,
                    float(p.get("rating", 0)),
                    int(p.get("feedbacks", 0)),
                    str(p.get("supplier", "")),
                    str(p.get("category", "")),
                    colors_json,
                )
            )
        except Exception as e:
            app.logger.warning(f"Skip product: {e}")
            continue

    conn.execute(
        "UPDATE searches SET status='done', product_count=? WHERE id=?",
        (len(products), search_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "saved": len(products)})

@app.get("/api/searches/<int:search_id>/products")
def get_products(search_id: int):
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    s = conn.execute(
        "SELECT id FROM searches WHERE id=? AND user_id=?", (search_id, uid)
    ).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    rows = conn.execute(
        "SELECT * FROM products WHERE search_id=? ORDER BY feedbacks DESC", (search_id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["colors"] = json.loads(d["colors"] or "[]")
        except Exception:
            d["colors"] = []
        result.append(d)
    return jsonify(result)


@app.get("/api/searches/<int:search_id>/analytics")
def get_analytics(search_id: int):
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    s = conn.execute(
        "SELECT * FROM searches WHERE id=? AND user_id=?", (search_id, uid)
    ).fetchone()
    if not s:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    products = conn.execute(
        "SELECT * FROM products WHERE search_id=? AND price > 0", (search_id,)
    ).fetchall()
    conn.close()

    if not products:
        return jsonify({
            "total_products": 0, "search": dict(s), "kpi": {},
            "price_distribution": [], "brand_top": [], "discount_distribution": [],
            "rating_distribution": [], "price_vs_rating": [], "supplier_top": [],
        })

    prices = [p["price"] for p in products if p["price"] > 0]
    ratings = [p["rating"] for p in products if p["rating"] > 0]
    feedbacks = [p["feedbacks"] for p in products]
    discounts = [p["discount"] for p in products if p["discount"] > 0]

    avg_price = round(sum(prices) / len(prices)) if prices else 0
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0
    max_discount = max(discounts) if discounts else 0
    total_feedbacks = sum(feedbacks)
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2] if sorted_prices else 0

    brand_count: dict[str, int] = {}
    for p in products:
        b = p["brand"] or "Без бренда"
        brand_count[b] = brand_count.get(b, 0) + 1

    supplier_count: dict[str, int] = {}
    for p in products:
        sn = p["supplier"] or "Неизвестный"
        supplier_count[sn] = supplier_count.get(sn, 0) + 1

    price_vs_rating = [
        {"price": p["price"], "rating": p["rating"],
         "name": p["name"][:40], "feedbacks": p["feedbacks"]}
        for p in products if p["price"] > 0 and p["rating"] > 0
    ][:80]

    return jsonify({
        "total_products": len(products),
        "search": dict(s),
        "kpi": {
            "avg_price": avg_price,
            "median_price": median_price,
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "avg_rating": avg_rating,
            "max_discount": max_discount,
            "total_feedbacks": total_feedbacks,
            "brands_count": len(brand_count),
        },
        "price_distribution": [{"range": k, "count": v}
                                 for k, v in _price_buckets(prices)],
        "brand_top": [{"brand": k, "count": v}
                       for k, v in sorted(brand_count.items(), key=lambda x: -x[1])[:12]],
        "discount_distribution": [{"range": k, "count": v}
                                    for k, v in _discount_buckets(discounts)],
        "rating_distribution": [{"range": k, "count": v}
                                  for k, v in _rating_buckets(
                                      [p["rating"] for p in products])],
        "price_vs_rating": price_vs_rating,
        "supplier_top": [{"supplier": k, "count": v}
                          for k, v in sorted(supplier_count.items(),
                                              key=lambda x: -x[1])[:10]],
    })


def _price_buckets(prices):
    if not prices:
        return []
    mn, mx = min(prices), max(prices)
    span = mx - mn
    step = max(span // 8, 100)
    buckets: dict[str, int] = {}
    for p in prices:
        idx = min((p - mn) // step, 7)
        lo = mn + idx * step
        hi = lo + step
        label = f"{lo:,}–{hi:,}₽".replace(",", "\u00a0")
        buckets[label] = buckets.get(label, 0) + 1
    return sorted(buckets.items(),
                  key=lambda x: int(x[0].split("–")[0].replace("\u00a0", "")))


def _discount_buckets(discounts):
    ranges = [
        ("Без скидки", 0, 0), ("1–10%", 1, 10), ("11–20%", 11, 20),
        ("21–30%", 21, 30), ("31–50%", 31, 50), ("51%+", 51, 100),
    ]
    buckets = {label: 0 for label, _, _ in ranges}
    all_count = 0
    for d in discounts:
        for label, lo, hi in ranges:
            if lo <= d <= hi:
                buckets[label] += 1
                all_count += 1
                break
    return [(k, v) for k, v in buckets.items() if v > 0]


def _rating_buckets(ratings):
    ranges = [
        ("Нет отзывов", 0, 0), ("1–2 ★", 0.1, 2), ("2–3 ★", 2, 3),
        ("3–4 ★", 3, 4), ("4–4.5 ★", 4, 4.5), ("4.5–5 ★", 4.5, 5.01),
    ]
    buckets = {label: 0 for label, _, _ in ranges}
    for r in ratings:
        for label, lo, hi in ranges:
            if lo <= r < hi:
                buckets[label] += 1
                break
    return [(k, v) for k, v in buckets.items() if v > 0]


# ─── Dashboards ───────────────────────────────────────────────────────────────

@app.get("/api/dashboards")
def list_dashboards():
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    rows = conn.execute(
        """SELECT d.*, s.query, s.product_count FROM dashboards d
           JOIN searches s ON s.id = d.search_id
           WHERE d.user_id=? ORDER BY d.created_at DESC""",
        (uid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.post("/api/dashboards")
def save_dashboard():
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    data = request.json or {}
    search_id = data.get("search_id")
    title = data.get("title", "Дашборд")
    if not search_id:
        return jsonify({"error": "search_id required"}), 400
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO dashboards (user_id, search_id, title) VALUES (?,?,?)",
        (uid, search_id, title)
    )
    conn.commit()
    dashboard_id = cur.lastrowid
    conn.close()
    return jsonify({"id": dashboard_id}), 201


@app.delete("/api/dashboards/<int:dashboard_id>")
def delete_dashboard(dashboard_id: int):
    err = require_auth()
    if err:
        return err
    uid = get_current_user()
    conn = get_db()
    conn.execute("DELETE FROM dashboards WHERE id=? AND user_id=?", (dashboard_id, uid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


# ─── Раздача фронтенда (HTML/CSS/JS) ─────────────────────────────────────────────

@app.get("/")
def serve_index():
    """SPA — отдаём index.html."""
    return send_from_directory(os.path.abspath(_FRONTEND_DIR), "index.html")


@app.get("/<path:filename>")
def serve_static(filename):
    """Статические файлы (style.css, app.js).
    API-запросы начинаются с /api/, поэтому в эту ветку они никогда не попадут.
    """
    return send_from_directory(os.path.abspath(_FRONTEND_DIR), filename)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=False)