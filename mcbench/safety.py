"""Safety layer: McBench NEVER places real orders or mutates the user's account.

Only read-only tools + calculate-price (a pure quote) are exposed to agents.
Anything else is blocked in the harness before it reaches the MCP server.
"""
ALLOWED_TOOLS = {
    "now-time-info",
    "query-nearby-stores",
    "query-meals",
    "query-meal-detail",
    "list-nutrition-foods",
    "query-store-coupons",
    "query-my-coupons",
    "campaign-calendar",
    "calculate-price",
}
# Explicitly listed so the intent is auditable. Never forwarded.
BLOCKED_TOOLS = {
    "create-order", "cancel-order", "mall-create-order", "party-order-create",
    "auto-bind-coupons", "delivery-create-address", "draw-lottery",
}


class BlockedToolError(Exception):
    pass


def check_tool(name: str) -> None:
    if name in BLOCKED_TOOLS or name not in ALLOWED_TOOLS:
        raise BlockedToolError(
            f"[McBench dry-run] tool '{name}' is blocked: McBench never places real "
            "orders or changes account state. Use submit_order (virtual, dry-run) instead.")
