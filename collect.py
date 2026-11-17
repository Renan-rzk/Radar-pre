#!/usr/bin/env python3
"""Coletor de preços. Só biblioteca padrão do Python. Cada loja falha de forma independente."""
import json, re, sys, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


def get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


_diag_done = set()


def diag(store, html):
    """Registra no log por que uma loja não retornou ofertas (uma vez por loja)."""
    if store in _diag_done:
        return
    _diag_done.add(store)
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    print(f"[diag {store}] {len(html)}B titulo={(t.group(1).strip()[:60] if t else '-')!r} "
          f"poly={html.count('poly-component__title')} ld={html.count('ld+json')} "
          f"next={html.count('__NEXT_DATA__')} preco={html.count('andes-money-amount__fraction')}")


def ld_products(html, store, base):
    """Lê produtos em JSON-LD (schema.org Product), formato comum em lojas."""
    out = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
            elif isinstance(o, dict):
                t = o.get("@type")
                if (t == "Product" or (isinstance(t, list) and "Product" in t)) and o.get("name"):
                    offers = o.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = offers.get("price") or offers.get("lowPrice") if isinstance(offers, dict) else None
                    url = o.get("url") or (offers.get("url") if isinstance(offers, dict) else None)
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        price = None
                    if price and url:
                        out.append({"store": store, "title": str(o["name"]), "price": price,
                                    "url": urllib.parse.urljoin(base, url).split("#")[0]})
                stack.extend(o.values())
    return out


# ---------- Mercado Livre (páginas públicas) ----------
TOKEN = re.compile(
    r'class="(andes-money-amount(?!_)[^"]*)"'
    r'|andes-money-amount__fraction[^>]*>([\d.]+)<'
    r'|andes-money-amount__cents[^>]*>(\d+)<')


def parse_ml(html):
    out = []
    titles = list(re.finditer(
        r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*poly-component__title[^"]*"[^>]*>(.*?)</a>'
        r'|<a[^>]*class="[^"]*poly-component__title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.S))
    for i, m in enumerate(titles):
        url = m.group(1) or m.group(3)
        title = re.sub(r"<[^>]+>", "", m.group(2) or m.group(4) or "").strip()
        end = titles[i + 1].start() if i + 1 < len(titles) else len(html)
        seg = html[m.end():end]
        last_cls, price = "", None
        for t in TOKEN.finditer(seg):
            if t.group(1):
                if price is not None:
                    break
                last_cls = t.group(1)
            elif t.group(2) and "previous" not in last_cls and price is None:
                price = float(t.group(2).replace(".", ""))
            elif t.group(3) and price is not None:
                price += int(t.group(3)) / 100
                break
        if price:
            out.append({"store": "Mercado Livre", "title": title, "price": price,
                        "url": url.split("#")[0]})
    return out


def src_ml(query):
    slug = "-".join(norm(query).split())
    base = "https://lista.mercadolivre.com.br/"
    html = get(base + urllib.parse.quote(slug))
    offers = parse_ml(html) or ld_products(html, "Mercado Livre", base)
    if not offers:
        diag("Mercado Livre", html)
    return offers


# ---------- KaBuM (página de busca pública) ----------
def walk(o, acc):
    if isinstance(o, dict):
        name = o.get("name") or o.get("title")
        price = o.get("priceWithDiscount") or o.get("price_with_discount") or o.get("price")
        code = o.get("code") or o.get("id")
        if isinstance(name, str) and isinstance(price, (int, float)) and price > 0 and code:
            acc.append((name, float(price), code))
        for v in o.values():
            walk(v, acc)
    elif isinstance(o, list):
        for v in o:
            walk(v, acc)


def src_kabum(query):
    slug = "-".join(norm(query).split())
    base = "https://www.kabum.com.br/"
    html = get(base + "busca/" + urllib.parse.quote(slug))
    out = []
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            acc = []
            walk(json.loads(m.group(1)), acc)
            out = [{"store": "KaBuM", "title": n, "price": p, "url": f"{base}produto/{c}"}
                   for n, p, c in acc]
        except Exception:
            out = []
    out = out or ld_products(html, "KaBuM", base)
    if not out:
        diag("KaBuM", html)
    return out


SOURCES = {"Mercado Livre": src_ml, "KaBuM": src_kabum}


def relevant(offer, item):
    t = norm(offer["title"])
    if not all(norm(w) in t for w in item.get("deve_conter", [])):
        return False
    if any(re.search(r"(?<![a-z0-9])" + re.escape(norm(w)) + r"(?![a-z0-9])", t)
           for w in item.get("excluir", [])):
        return False
    return offer["price"] >= item.get("preco_min", 0)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    wishlist = json.loads((ROOT / "wishlist.json").read_text(encoding="utf-8"))
    hist_path = DATA / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    status = {s: {"ok": 0, "erro": 0, "ultimo_erro": ""} for s in SOURCES}
    items, total = [], 0

    for item in wishlist:
        offers = []
        for sname, fn in SOURCES.items():
            try:
                found = [o for o in fn(item["busca"]) if relevant(o, item)]
                offers += found
                status[sname]["ok"] += 1
            except Exception as e:  # uma loja quebrar não derruba o resto
                status[sname]["erro"] += 1
                status[sname]["ultimo_erro"] = f"{type(e).__name__}: {e}"[:160]
        seen, uniq = set(), []
        for o in sorted(offers, key=lambda o: o["price"]):
            if o["url"] not in seen:
                seen.add(o["url"]); uniq.append(o)
        uniq = uniq[:12]
        total += len(uniq)
        prices = sorted(o["price"] for o in uniq)
        median = prices[len(prices) // 2] if prices else None
        for o in uniq:
            o["suspeito"] = bool(median and o["price"] < 0.6 * median)
        h = history.setdefault(item["id"], [])
        for store in {o["store"] for o in uniq}:
            ok = [o["price"] for o in uniq if o["store"] == store and not o["suspeito"]]
            if not ok:
                continue
            best = min(ok)
            row = next((r for r in h if r["d"] == today and r["s"] == store), None)
            if row:
                row["p"] = min(row["p"], best)
            else:
                h.append({"d": today, "s": store, "p": best})
        items.append({"id": item["id"], "nome": item["nome"], "alvo": item.get("alvo"),
                      "historico_ref": item.get("historico_ref"), "ofertas": uniq})

    if total == 0:
        print("Nenhuma oferta coletada; mantendo dados anteriores.", json.dumps(status, ensure_ascii=False))
        sys.exit(1)

    (DATA / "latest.json").write_text(json.dumps(
        {"atualizado": now.isoformat(), "fontes": status, "itens": items}, ensure_ascii=False), encoding="utf-8")
    hist_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {total} ofertas", json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
