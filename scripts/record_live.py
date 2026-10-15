"""Record READ-ONLY responses from the real MCP server for fixture building.
Never calls write tools (SafeMCP blocks them anyway). Output dir stays OUTSIDE the
repo because raw responses contain user-bound coupon codes.
Usage: MCD_MCP_TOKEN=... python scripts/record_live.py /tmp/mcd-raw [city] [keyword]"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcbench import mcd  # noqa
from mcbench.mcp_client import HttpMCP, SafeMCP  # noqa

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
city, kw = (sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else ("上海", "人民广场")
c = SafeMCP(HttpMCP(os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn"), os.environ["MCD_MCP_TOKEN"], min_interval=0.5))


def call(name, args, tag=None):
    r = c.call_tool(name, args)
    (out / f"{tag or name}.json").write_text(json.dumps(r, ensure_ascii=False), "utf-8")
    return mcd.payload(r)


json.dump(c.list_tools(), open(out / "tools.json", "w"), ensure_ascii=False)
store = call("query-nearby-stores", {"searchType": 2, "city": city, "keyword": kw, "beType": 1})["data"][0]["storeCode"]
b = {"storeCode": store, "orderType": 1, "beType": 1}
call("list-nutrition-foods", {})
meals = call("query-meals", b)["data"]["meals"]
coupons = call("query-store-coupons", b)["data"] or []
details = {code: call("query-meal-detail", {**b, "code": code}, f"det_{code}").get("data") for code in meals}
json.dump(details, open(out / "details_all.json", "w"), ensure_ascii=False)
for cp in coupons:
    pc = cp["products"][0]["productCode"]
    call("query-meal-detail", {**b, "code": pc}, f"det_{pc}")
    call("calculate-price", {**b, "items": [{"productCode": pc, "quantity": 1, "couponId": cp["couponId"],
                                             "couponCode": cp["couponCode"]}]}, f"calc_coupon_{pc}")
print("recorded to", out, "store", store)
