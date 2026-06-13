"""Trade market realm configuration - CN (Tencent) and global."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

MarketId = Literal["cn", "global"]

DEFAULT_MARKET: MarketId = "cn"


@dataclass(frozen=True)
class TradeRealmConfig:
    id: MarketId
    label_cn: str
    host: str
    default_league: str

    @property
    def origin(self) -> str:
        return f"https://{self.host}"


REALMS: dict[MarketId, TradeRealmConfig] = {
    "cn": TradeRealmConfig(
        id="cn",
        label_cn="国服",
        host="poe.game.qq.com",
        default_league="奥杜尔秘符",
    ),
    "global": TradeRealmConfig(
        id="global",
        label_cn="国际服",
        host="www.pathofexile.com",
        default_league="Standard",
    ),
}


def get_realm(market: str = DEFAULT_MARKET) -> TradeRealmConfig:
    """Return realm config for market id; unknown values fall back to default."""
    return REALMS.get(market, REALMS[DEFAULT_MARKET])


def resolve_league(market: str = DEFAULT_MARKET, league: str | None = None) -> str:
    """Resolve league segment for API URLs; None uses realm default."""
    realm = get_realm(market)
    if not league or not str(league).strip():
        return realm.default_league
    raw = str(league).strip()
    if market == "cn" and raw.lower() in ("standard", "null"):
        return realm.default_league
    if market == "global" and raw.lower() == "null":
        return "Standard"
    return raw


def search_api_url(market: str = DEFAULT_MARKET, league: str | None = None) -> str:
    """POST endpoint to create a new trade search."""
    realm = get_realm(market)
    lg = resolve_league(market, league)
    return f"{realm.origin}/api/trade2/search/poe2/{quote(lg)}"


def trade_page_url(
    market: str = DEFAULT_MARKET,
    league: str | None = None,
    search_id: str = "",
) -> str:
    """User-facing trade page URL."""
    realm = get_realm(market)
    lg = resolve_league(market, league)
    base = f"{realm.origin}/trade2/search/poe2/{quote(lg)}"
    return f"{base}/{search_id}" if search_id else base


def search_result_api_url(
    market: str = DEFAULT_MARKET,
    league: str | None = None,
    search_id: str = "",
) -> str:
    """GET endpoint to retrieve search result item IDs."""
    realm = get_realm(market)
    lg = resolve_league(market, league)
    return f"{realm.origin}/api/trade2/search/poe2/{quote(lg)}/{search_id}"


def fetch_api_url(
    market: str = DEFAULT_MARKET,
    item_ids: list[str] | str = "",
    search_id: str = "",
) -> str:
    """GET endpoint to fetch item details."""
    realm = get_realm(market)
    ids = item_ids if isinstance(item_ids, str) else ",".join(item_ids)
    return f"{realm.origin}/api/trade2/fetch/{ids}?query={search_id}"


def referer_url(market: str = DEFAULT_MARKET, league: str | None = None) -> str:
    """Referer header value for trade API requests."""
    return trade_page_url(market, league)


def trade_status_filter(market: str = DEFAULT_MARKET) -> dict | None:
    if market == "cn":
        return None
    return {"option": "online"}
