"""Adapter for the real McDonald's China MCP response shapes (recorded 2026-10-15).

Real responses come back as one text block: markdown display instructions + the
raw JSON (`{"success":true,"code":200,...,"data":...}`), sometimes followed by
more markdown. Prices are in 分 (fen) in calculate-price, yuan strings in menus.
list-nutrition-foods returns a compact table string keyed by product *name*.
"""
import json
import re

_DEC = json.JSONDecoder()


def payload(result):
    """Return the inner API dict ({success, code, message, data}) from a tool result."""
    if isinstance(result, dict) and "text" not in result:
        return result
    text = result.get("text", "") if isinstance(result, dict) else str(result)
    i = text.find('{"success"')
    if i < 0:
        return {"success": False, "message": text[:300]}
    try:
        return _DEC.raw_decode(text[i:])[0]
    except json.JSONDecodeError:
        return {"success": False, "message": "unparseable response"}


def yuan(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


# ---------- normalizers ----------

def stores(result):
    return [{k: s.get(k) for k in ("storeCode", "storeName", "address", "distance", "beCode", "businessStatus")}
            for s in payload(result).get("data") or []]


def menu(result):
    """-> {code: {code,name,price,originalPrice,category,tags}}"""
    d = payload(result).get("data") or {}
    meta = d.get("meals") or {}
    out = {}
    for cat in d.get("categories") or []:
        cname = (cat.get("name") or "").replace("\n", "")
        for m in cat.get("meals") or []:
            c = m.get("code")
            info = meta.get(c, {})
            e = out.setdefault(c, {"code": c, "name": info.get("name"), "price": yuan(info.get("currentPrice")),
                                   "originalPrice": yuan(info.get("originalPrice")), "category": cname, "tags": []})
            for t in m.get("tags") or []:
                if t not in e["tags"]:
                    e["tags"].append(t)
            if info.get("discountType"):
                e["discountType"] = info["discountType"]
    return out


def nutrition(result):
    """-> {productName: {kcal, protein, fat, carb, sodium}}"""
    data = payload(result).get("data")
    out = {}
    if isinstance(data, list):  # tolerate a JSON list shape
        for f in data:
            out[f.get("productName")] = {"kcal": f.get("energyKcal"), "protein": f.get("protein")}
        return out
    lines = (data or "").splitlines()
    if not lines:
        return out
    header = re.search(r"\{(.*)\}", lines[0])
    cols = header.group(1).split(",") if header else []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.strip().split(",")]
        if len(parts) != len(cols):
            continue
        row = dict(zip(cols, parts))

        def num(k):
            try:
                return float(row.get(k))
            except (TypeError, ValueError):
                return None
        out[row["productName"]] = {"kcal": num("energyKcal"), "protein": num("protein"), "fat": num("fat"),
                                   "carb": num("carbohydrate"), "sodium": num("sodium")}
    return out


def detail(result):
    """-> {code, name, rounds:[{name, quantity, choices:[{code,name,isDefault,diffPrice}]}]}"""
    d = payload(result).get("data") or {}
    return {"code": d.get("code"), "name": d.get("name"),
            "rounds": [{"id": r.get("id"), "name": r.get("name"), "quantity": r.get("quantity", 1),
                        "choices": [{"code": c.get("code"), "name": c.get("name"), "isDefault": c.get("isDefault"),
                                     "diffPrice": c.get("diffPrice")} for c in r.get("choices") or []]}
                       for r in d.get("rounds") or []]}


def coupons(result):
    return [{"title": c.get("title"), "couponId": c.get("couponId"), "couponCode": c.get("couponCode"),
             "validity": c.get("tradeDateTime"),
             "products": [{"productCode": p.get("productCode"), "productName": p.get("productName")}
                          for p in c.get("products") or []]}
            for c in payload(result).get("data") or []]


def quote(result):
    """-> {success, payable, subtotal, discount (yuan), lines:[{productCode, productName, quantity, subtotal}]}"""
    p = payload(result)
    if not p.get("success"):
        return {"success": False, "error": f"{p.get('code')} {p.get('message')}"}
    d = p.get("data") or {}
    f = lambda v: round((v or 0) / 100.0, 2)  # noqa: E731
    return {"success": True, "payable": f(d.get("price")), "subtotal": f(d.get("originalPrice")),
            "discount": f(d.get("discount")),
            "lines": [{"productCode": x.get("productCode"), "productName": x.get("productName"),
                       "quantity": x.get("quantity"), "subtotal": f(x.get("subtotal"))} for x in d.get("productList") or []]}


# ---------- compact views shown to agents (saves tokens; same for every model) ----------

def compact(tool, result):
    try:
        if tool == "query-nearby-stores":
            return {"stores": stores(result)}
        if tool == "query-meals":
            return {"meals": [{k: v for k, v in m.items() if k != "originalPrice"} for m in menu(result).values()]}
        if tool == "list-nutrition-foods":
            return {"foods": [dict(name=k, **v) for k, v in nutrition(result).items()]}
        if tool == "query-meal-detail":
            return detail(result)
        if tool == "query-store-coupons":
            return {"coupons": coupons(result)}
        if tool == "calculate-price":
            return quote(result)
    except Exception as e:  # noqa
        return {"error": f"parse error: {e}"}
    p = payload(result)
    if p.get("success") is False and "message" in p:
        return {"success": False, "code": p.get("code"), "message": p.get("message")}
    return result if not isinstance(result, dict) or len(json.dumps(result)) < 4000 else {"text": json.dumps(result, ensure_ascii=False)[:4000]}


# ---------- classification ----------

DRINK = re.compile(r"可乐|雪碧|咖啡|奶铁|拿铁|美式|红茶|柠檬茶|茶|牛奶|奶昔|果汁|苹果汁|橙橙|柠柠|纯悦|怡泉|豆浆|卡布奇诺|浓缩|芬达|饮料|燕麦奶|黑巧|雪冰|玛奇朵")
BURGER = re.compile(r"堡|麦满分|麦香鸡|麦香鱼|巨无霸|营养卷|叠叠卷")
SUGAR_FREE = re.compile(r"无糖|零度|美式|纯悦|矿泉水|浓缩咖啡|鲜萃咖啡")
SPICY = re.compile(r"辣|龙焰")


def kind(name):
    name = name or ""
    if DRINK.search(name) and not re.search(r"套餐|阿芙佳朵|麦旋风|新地", name):
        return "饮品"
    if BURGER.search(name):
        return "汉堡"
    return "小食"


def norm_name(n):
    return re.sub(r"[（(].*?[)）]|[\s\-]", "", n or "")


def match_nutrition(name, table):
    if not name:
        return None
    if name in table:
        return table[name]
    nn = norm_name(name)
    idx = {norm_name(k): v for k, v in table.items()}
    if nn in idx:
        return idx[nn]
    nn = nn.replace("麦咖啡™", "").replace("™", "")
    for pref in ("热" + nn + "中杯", nn + "中杯", "中杯" + nn, "热" + nn, nn):
        if pref in idx:
            return idx[pref]
    cands = [k for k in idx if len(nn) >= 2 and nn in k]
    for tag in ("中杯", "热", ""):
        for k in cands:
            if tag in k:
                return idx[k]
    return None
