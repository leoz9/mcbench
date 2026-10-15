"""Build mcbench/fixtures/mock_data.json from responses recorded against the real
MCP server (scripts/record_live.py). Scrubs coupon ids/codes, trace ids, images,
user-bound data. Usage: python scripts/build_fixture.py <raw_dir>"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcbench import mcd  # noqa

raw = Path(sys.argv[1])
L = lambda n: mcd.payload(json.load(open(raw / f"{n}.json", encoding="utf-8")))  # noqa
stores = [{k: s.get(k) for k in ("storeCode", "storeName", "address", "distance", "businessStatus",
                                  "businessStartTime", "businessEndTime")} for s in L("query-nearby-stores")["data"]]
md = L("query-meals")["data"]
meals = {c: {k: v.get(k) for k in ("name", "currentPrice", "originalPrice", "discountType")} for c, v in md["meals"].items()}
cats = [{"name": c["name"], "meals": [{"code": m["code"], "tags": m.get("tags")} for m in c["meals"]]} for c in md["categories"]]
details = json.load(open(raw / "details_all.json", encoding="utf-8"))
cps, cprice = [], {}
for i, c in enumerate(L("query-store-coupons")["data"]):
    pc = c["products"][0]["productCode"]
    q = mcd.quote(json.load(open(raw / f"calc_coupon_{pc}.json", encoding="utf-8")))
    line = next(x for x in q["lines"] if x["productCode"] == pc)
    d = L(f"det_{pc}")["data"]
    details[pc] = d
    cprice[pc] = {"name": line["productName"], "couponPrice": line["subtotal"],
                  "originalPrice": next(x["originalSubtotal"] for x in L(f"calc_coupon_{pc}")["data"]["productList"] if x["productCode"] == pc) / 100}
    cps.append({"title": c["title"], "couponId": f"MOCKCOUPONID{i:04d}", "couponCode": f"MOCKCODE{i:04d}",
                "tradeDateTime": c["tradeDateTime"], "products": c["products"]})


def strip(d):
    if isinstance(d, dict):
        return {k: strip(v) for k, v in d.items() if k not in ("image", "traceId", "modification")}
    if isinstance(d, list):
        return [strip(x) for x in d]
    return d


out = {"_notice": "MOCK FIXTURE — 由 2026-10-15 在真实麦当劳 MCP（mcp.mcd.cn）上录制的只读响应生成（上海一家公开门店的菜单/价格/营养），"
                  "已去除 traceId、图片、个人券 ID/券码等。价格与供应会变化，仅用于 demo 模式；以麦当劳官方渠道实时结果为准。",
       "recorded": "2026-10-15", "stores": stores, "categories": cats, "meals": meals,
       "nutrition": L("list-nutrition-foods")["data"], "details": strip(details), "coupons": cps, "couponPrices": cprice}
dst = Path(__file__).resolve().parent.parent / "mcbench/fixtures/mock_data.json"
dst.write_text(json.dumps(out, ensure_ascii=False, indent=0), "utf-8")
print(dst, dst.stat().st_size)
