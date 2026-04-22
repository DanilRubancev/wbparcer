#!/usr/bin/env python3
"""
WB Diagnostics — артикул и ссылка.
Запуск: python wb_diag_article.py

Зависимости: pip install requests
"""

import json
import time
import requests

# ─── Настройки ────────────────────────────────────────────────────────────────
# Вставьте сюда любой реальный артикул с WB (можно взять из адресной строки)
TEST_ARTICLE = 485389018
TEST_URL = f"https://www.wildberries.ru/catalog/{TEST_ARTICLE}/detail.aspx"

# Контрольный артикул — заведомо существующий (Креатин от PWR)
# Используется для проверки что basket CDN вообще доступен с вашего IP
CONTROL_ARTICLE = 136906466

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.wildberries.ru/",
}

SEP = "─" * 60

results = {}


def p(msg=""):
    print(msg, flush=True)


def ok(label, detail=""):
    p(f"  ✓ OK    {label}")
    if detail:
        p(f"          {detail}")


def fail(label, detail=""):
    p(f"  ✗ FAIL  {label}")
    if detail:
        p(f"          {detail}")


def get(url, params=None, timeout=10):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def try_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


# ─── БЛОК 1: Вычисление basket номера ────────────────────────────────────────

def get_basket_variants(article: int):
    """Возвращает список возможных basket номеров для проверки."""
    vol = article // 100000
    # Алгоритм WB (пороги могут меняться — проверяем диапазон)
    thresholds = [
        143, 287, 431, 719, 1007, 1061, 1115, 1169, 1313, 1601,
        1655, 1919, 2045, 2189, 2405, 2621, 2837, 3200, 3479,
        3758, 4037, 4316, 4595, 4874, 5153, 5432, 5711, 5990,
        6269, 6548, 6827, 7106, 7385, 7664, 7943, 8222, 8501,
    ]
    # Вычисляем "правильный" по алгоритму
    computed = len(thresholds) + 1
    for i, t in enumerate(thresholds):
        if vol <= t:
            computed = i + 1
            break

    # Возвращаем computed ± 3 на случай если алгоритм немного изменился
    variants = sorted(set(range(max(1, computed - 3), min(25, computed + 4))))
    return computed, variants


p()
p("=" * 60)
p("  WB Parser — Диагностика артикул / ссылка")
p("=" * 60)
p(f"  Артикул: {TEST_ARTICLE}")
p(f"  URL:     {TEST_URL}")
p()

vol  = TEST_ARTICLE // 100000
part = TEST_ARTICLE // 1000
p(f"  vol={vol}, part={part}")

computed, basket_variants = get_basket_variants(TEST_ARTICLE)
p(f"  Вычисленный basket: {computed:02d}")
p(f"  Проверяем basket: {[str(b).zfill(2) for b in basket_variants]}")

# ─── БЛОК 1: basket-N.wbbasket.ru — card.json ─────────────────────────────────
p()
p(SEP)
p("  БЛОК 1 — basket CDN (card.json)")
p(SEP)

working_basket = None
card_data = None

for basket_num in basket_variants:
    basket = str(basket_num).zfill(2)
    url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{TEST_ARTICLE}/info/ru/card.json"
    p(f"\n  basket-{basket}: {url}")
    code, body = get(url)
    p(f"  HTTP: {code}  |  тело: {len(body)} байт")

    if code == 200 and body.strip():
        data = try_json(body)
        if data and data.get("imt_name"):
            ok(f"basket-{basket} card.json", f"name={data['imt_name'][:60]}")
            ok(f"  subj={data.get('subj_name','?')}  brand={data.get('selling',{}).get('brand_name','?')}")
            working_basket = basket
            card_data = data
            results["card.json"] = {"status": "ok", "basket": basket, "name": data["imt_name"]}
            break
        else:
            fail(f"basket-{basket}", f"JSON без imt_name: {body[:100]}")
    else:
        fail(f"basket-{basket}", body[:80] if code != 404 else "404 Not Found")

if not working_basket:
    p()
    p("  !! Ни один basket не вернул card.json — перебираем ВСЕ 1-25...")
    for basket_num in range(1, 31):
        basket = str(basket_num).zfill(2)
        url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{TEST_ARTICLE}/info/ru/card.json"
        code, body = get(url, timeout=6)
        if code == 200 and body.strip():
            data = try_json(body)
            if data and data.get("imt_name"):
                ok(f"basket-{basket} card.json (найден при полном переборе!)")
                ok(f"  name={data['imt_name'][:60]}")
                working_basket = basket
                card_data = data
                results["card.json"] = {"status": "ok", "basket": basket, "name": data["imt_name"]}
                break
        print(f"  basket-{basket}: {code}", end="", flush=True)
    print()
    if not working_basket:
        results["card.json"] = {"status": "fail", "detail": "все basket 1-30 вернули 404"}
        p("\n  !! Артикул не найден ни на одном basket-сервере.")
        p("     Возможные причины:")
        p("     - Артикул не существует на WB")
        p("     - Товар удалён")
        p("     Попробуйте открыть ссылку в браузере:")
        p(f"     {TEST_URL}")

# ─── БЛОК 2: sellers.json ─────────────────────────────────────────────────────
# ─── БЛОК 1б: Проверка контрольного артикула ─────────────────────────────────
p()
p(SEP)
p("  БЛОК 1б — Контрольный артикул (проверка доступности basket CDN)")
p(SEP)

c_vol  = CONTROL_ARTICLE // 100000
c_part = CONTROL_ARTICLE // 1000
c_comp, _ = get_basket_variants(CONTROL_ARTICLE)

p(f"\n  Контрольный артикул: {CONTROL_ARTICLE} (Креатин)")
p(f"  basket={c_comp:02d}, vol={c_vol}, part={c_part}")

c_url = f"https://basket-{c_comp:02d}.wbbasket.ru/vol{c_vol}/part{c_part}/{CONTROL_ARTICLE}/info/ru/card.json"
p(f"  URL: {c_url}")
c_code, c_body = get(c_url)
p(f"  HTTP: {c_code}  |  тело: {len(c_body)} байт")

if c_code == 200:
    c_data = try_json(c_body)
    c_name = (c_data or {}).get("imt_name", "?")
    ok("Контрольный артикул доступен", f"{c_name[:60]}")
    results["control_article"] = {"status": "ok", "name": c_name}
else:
    fail("Контрольный артикул НЕДОСТУПЕН", f"HTTP {c_code} — basket CDN заблокирован с вашего IP")
    results["control_article"] = {"status": f"http_{c_code}"}

time.sleep(0.5)

p()
p(SEP)
p("  БЛОК 2 — sellers.json (поставщик)")
p(SEP)

if working_basket:
    url = f"https://basket-{working_basket}.wbbasket.ru/vol{vol}/part{part}/{TEST_ARTICLE}/info/sellers.json"
    p(f"\n  URL: {url}")
    code, body = get(url)
    p(f"  HTTP: {code}")
    if code == 200:
        data = try_json(body)
        supplier = data.get("supplierName", "?") if data else "?"
        ok("sellers.json", f"supplier={supplier}")
        results["sellers.json"] = {"status": "ok", "supplier": supplier}
    else:
        fail("sellers.json", body[:80])
        results["sellers.json"] = {"status": f"http_{code}"}
else:
    p("  (пропущен — basket не найден)")

# ─── БЛОК 3: price-history.json ───────────────────────────────────────────────
p()
p(SEP)
p("  БЛОК 3 — price-history.json (цена)")
p(SEP)

if working_basket:
    url = f"https://basket-{working_basket}.wbbasket.ru/vol{vol}/part{part}/{TEST_ARTICLE}/info/price-history.json"
    p(f"\n  URL: {url}")
    code, body = get(url)
    p(f"  HTTP: {code}  |  тело: {len(body)} байт")
    if code == 200:
        data = try_json(body)
        if data and isinstance(data, list) and data:
            last = data[-1]
            price = last.get("price", {}).get("RUB", 0) // 100
            max_price = max(e.get("price", {}).get("RUB", 0) // 100 for e in data)
            ok("price-history.json", f"текущая={price} руб, макс={max_price} руб, записей={len(data)}")
            results["price-history.json"] = {"status": "ok", "price": price, "max_price": max_price}
        else:
            p(f"  ? JSON пуст или неверный формат: {body[:150]}")
            results["price-history.json"] = {"status": "empty"}
    else:
        fail("price-history.json", body[:80])
        results["price-history.json"] = {"status": f"http_{code}"}
else:
    p("  (пропущен — basket не найден)")

# ─── БЛОК 4: feedbacks (рейтинг) ──────────────────────────────────────────────
p()
p(SEP)
p("  БЛОК 4 — feedbacks (рейтинг и отзывы)")
p(SEP)

for fb_url in [
    f"https://feedbacks2.wb.ru/feedbacks/v2/{TEST_ARTICLE}",
    f"https://feedbacks1.wb.ru/feedbacks/v2/{TEST_ARTICLE}",
    f"https://feedbacks2.wb.ru/feedbacks/v1/{TEST_ARTICLE}",
]:
    p(f"\n  URL: {fb_url}")
    code, body = get(fb_url)
    p(f"  HTTP: {code}  |  тело: {len(body)} байт")
    if code == 200:
        data = try_json(body)
        if data:
            rating    = data.get("valuation", 0)
            feedbacks = data.get("feedbackCount", 0)
            ok(fb_url.split(".ru")[1][:40], f"rating={rating}, feedbacks={feedbacks}")
            results["feedbacks"] = {"status": "ok", "url": fb_url, "rating": rating, "feedbacks": feedbacks}
            break
        else:
            p(f"  ? не JSON: {body[:100]}")
    else:
        fail(fb_url.split(".ru")[1][:40], f"HTTP {code}")
    time.sleep(0.3)
else:
    if "feedbacks" not in results:
        results["feedbacks"] = {"status": "fail"}

# ─── БЛОК 5: card.wb.ru (старый API) ──────────────────────────────────────────
p()
p(SEP)
p("  БЛОК 5 — card.wb.ru (прямой API карточки)")
p(SEP)

for url, params in [
    ("https://card.wb.ru/cards/v2/detail", {"appType": 1, "curr": "rub", "dest": -1257786, "nm": TEST_ARTICLE}),
    ("https://card.wb.ru/cards/v3/detail", {"appType": 1, "curr": "rub", "dest": -1257786, "nm": TEST_ARTICLE}),
    ("https://card.wb.ru/cards/v2/detail", {"appType": 1, "curr": "rub", "dest": -1059500, "nm": TEST_ARTICLE}),
]:
    p(f"\n  URL: {url}  dest={params.get('dest')}")
    code, body = get(url, params=params)
    p(f"  HTTP: {code}  |  тело: {len(body)} байт")
    if code == 200:
        data = try_json(body)
        prods = (data or {}).get("data", {}).get("products") or (data or {}).get("products") or []
        if prods:
            ok(url.split(".ru")[1][:30], f"products={len(prods)}, name={prods[0].get('name','?')[:50]}")
            results["card.wb.ru"] = {"status": "ok", "url": url, "count": len(prods)}
            break
        else:
            p(f"  ? JSON без products. Keys: {list((data or {}).keys())}")
    else:
        fail(url.split(".ru")[1][:30], f"HTTP {code}")
    time.sleep(0.3)
else:
    if "card.wb.ru" not in results:
        results["card.wb.ru"] = {"status": "fail"}

# ─── БЛОК 6: URL парсинг (извлечение артикула) ────────────────────────────────
p()
p(SEP)
p("  БЛОК 6 — Извлечение артикула из разных форматов URL")
p(SEP)

import re
from urllib.parse import urlparse

url_variants = [
    f"https://www.wildberries.ru/catalog/{TEST_ARTICLE}/detail.aspx",
    f"https://wildberries.ru/catalog/{TEST_ARTICLE}/detail.aspx",
    f"https://www.wildberries.ru/catalog/{TEST_ARTICLE}",
    f"http://www.wildberries.ru/catalog/{TEST_ARTICLE}/detail.aspx",
]

for test_url in url_variants:
    m = re.search(r"/catalog/(\d+)", test_url)
    if m:
        extracted = int(m.group(1))
        match = "✓" if extracted == TEST_ARTICLE else "✗"
        p(f"  {match} '{test_url[:60]}' → {extracted}")
    else:
        p(f"  ✗ '{test_url[:60]}' → не найдено")

# ─── ИТОГИ ────────────────────────────────────────────────────────────────────
p()
p("=" * 60)
p("  ИТОГИ")
p("=" * 60)

if working_basket:
    p(f"\n  ✓ Рабочий basket: basket-{working_basket}")
    p(f"    URL шаблон: https://basket-{working_basket}.wbbasket.ru/vol{{vol}}/part{{part}}/{{article}}/info/ru/card.json")
    p()

ok_items  = [(k, v) for k, v in results.items() if v.get("status") == "ok"]
fail_items = [(k, v) for k, v in results.items() if v.get("status") != "ok"]

p(f"  ✓ Работает: {len(ok_items)}")
for k, v in ok_items:
    extra = v.get("name") or v.get("supplier") or v.get("url","") or ""
    p(f"    • {k}: {str(extra)[:70]}")

p(f"\n  ✗ Ошибки: {len(fail_items)}")
for k, v in fail_items:
    p(f"    • {k}: [{v.get('status','')}] {v.get('detail','')}")

# Сохраняем результат
import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wb_diag_article_result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({
        "article": TEST_ARTICLE,
        "working_basket": working_basket,
        "vol": vol,
        "part": part,
        "results": results,
    }, f, ensure_ascii=False, indent=2)

p(f"\n  Результаты сохранены: {out}")
p()