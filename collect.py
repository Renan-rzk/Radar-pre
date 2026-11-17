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
    return parse_ml(get(f"https://lista.mercadolivre.com.br/{urllib.parse.quote(slug)}"))


# ---------- KaBuM (API interna, leitura tolerante) ----------
def walk(o, acc):
    if isinstance(o, dict):
        name = o.get("name") or o.get("title")
        price = o.get("price_with_discount") or o.get("priceWithDiscount") or o.get("price")
        code = o.get("code") or o.get("id")
        if isinstance(name, str) and isinstance(price, (int, float)) and price > 0:
            acc.append((name, float(price), code, o.get("friendly_name") or o.get("slug")))
        for v in o.values():
            walk(v, acc)
    elif isinstance(o, list):
        for v in o:
            walk(v, acc)


def src_kabum(query):
    q = urllib.parse.quote(query)
    raw = get("https://servicespub.prod.kabum.com.br/search/v3/products?query=" + q +
              "&page_number=1&page_size=20&sort=most_searched")
    acc = []
    walk(json.loads(raw), acc)
    out = []
    for name, price, code, slug in acc:
        url = f"https://www.kabum.com.br/produto/{code}" if code else "https://www.kabum.com.br"
        out.append({"store": "KaBuM", "title": name, "price": price, "url": url})
    return out


SOURCES = {"Mercado Livre": src_ml, "KaBuM": src_kabum}


def relevant(offer, item):
    t = norm(offer["title"])
    words = set(re.findall(r"[a-z0-9]+", t))
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
            best = min(o["price"] for o in uniq if o["store"] == store and not o["suspeito"]
                       ) if any(o["store"] == store and not o["suspeito"] for o in uniq) else None
            if best is None:
                continue
            row = next((r for r in h if r["d"] == today and r["s"] == store), None)
            if row:
                row["p"] = min(row["p"], best)
            else:
                h.append({"d": today, "s": store, "p": best})
        items.append({"id": item["id"], "nome": item["nome"], "alvo": item.get("alvo"),
                      "historico_ref": item.get("historico_ref"), "ofertas": uniq})

    if total == 0:
        print("Nenhuma oferta coletada; mantendo dados anteriores.", json.dumps(status, ensure_ascii=False))
        (DATA / "status.json").write_text(json.dumps({"atualizado": now.isoformat(), "fontes": status},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
        sys.exit(1)

    (DATA / "latest.json").write_text(json.dumps(
        {"atualizado": now.isoformat(), "fontes": status, "itens": items}, ensure_ascii=False), encoding="utf-8")
    hist_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    print(f"OK: {total} ofertas", json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
