"""PoB decoding service — wraps pob_decoder.py for the API layer.

Includes in-memory cache to avoid duplicate decoding for the same pob_code.
"""

import sys
import hashlib
import re
import urllib.request
import urllib.parse
import json
from urllib.error import URLError
from pathlib import Path

# Add project root to path so we can import pob_decoder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from pob_decoder import decode_pob_code, parse_build_data, PoBDecodeError
from app.models.schemas import (
    BuildInfo, TreeSpec, Gem, SkillSet, Item,
    DecodeResponse, ErrorResponse,
)

# Simple in-memory cache: pob_code_hash -> DecodeResponse
_decode_cache: dict[str, DecodeResponse] = {}
MAX_CACHE_SIZE = 256


def fetch_pobbin_raw(url: str) -> str | ErrorResponse:
    """Fetch raw PoB code from a pobb.in URL.
    
    e.g., https://pobb.in/XXXXX -> GET https://pobb.in/XXXXX/raw
    """
    match = re.match(r'https?://pobb\.in/([a-zA-Z0-9_-]+)', url)
    if not match:
        return ErrorResponse(error="无效的 pobb.in 链接格式", reason="invalid_url")
        
    pob_id = match.group(1)
    raw_url = f"https://pobb.in/{pob_id}/raw"
    
    try:
        # We must provide a User-Agent, otherwise pobb.in might block us
        req = urllib.request.Request(
            raw_url,
            headers={'User-Agent': 'PoE2LI-Bot/1.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status != 200:
                return ErrorResponse(error=f"获取 pobb.in 失败 (HTTP {response.status})", reason="fetch_failed")
            
            # The raw endpoint returns the base64 code directly
            raw_code = response.read().decode('utf-8').strip()
            if not raw_code:
                return ErrorResponse(error="获取到的 pobb.in 数据为空", reason="empty_data")
                
            return raw_code
    except URLError as e:
        return ErrorResponse(error=f"请求 pobb.in 网络错误: {e.reason}", reason="network_error")
    except Exception as e:
        return ErrorResponse(error=f"解析 pobb.in 发生未知错误: {e}", reason="unknown_error")


def fetch_pob_ninja_raw(url: str) -> str | ErrorResponse:
    """Fetch raw PoB code from a poe.ninja build URL.
    
    e.g., https://poe.ninja/poe2/builds/...
    This requires extracting the PoB code from the page or calling their API.
    For simplicity, if we can't extract it directly, we might need a more complex scraper.
    Let's check if poe.ninja provides an easy raw endpoint or if we need to parse the HTML.
    """
    # poe.ninja builds don't have a simple /raw endpoint. 
    # Usually the pobb code is embedded in the page or fetched via their API.
    # We will need to scrape the page and look for 'window.poeNinja.build' or a pobb.in link
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            
            # poe.ninja usually embeds a pobb.in link or base64 code for copying
            # Let's search for a pobb.in link first
            pobb_match = re.search(r'https://pobb\.in/[a-zA-Z0-9_-]+', html)
            if pobb_match:
                return fetch_pobbin_raw(pobb_match.group(0))
                
            # Try to find their internal build data which contains pobb.in links sometimes
            # Or the copy-paste code which is inside a script tag
            script_match = re.search(r'window\.poeNinja\.build\s*=\s*({.*?});', html, re.DOTALL)
            if script_match:
                try:
                    data = json.loads(script_match.group(1))
                    if 'pobCode' in data and data['pobCode']:
                        return data['pobCode']
                except:
                    pass
                    
            # Or look for a direct base64 string (sometimes eN is at the start of a very long string)
            code_match = re.search(r'[\'"](eN[a-zA-Z0-9\+\/_-]{100,})[\'"]', html)
            if code_match:
                return code_match.group(1)
                
            parsed_url = urllib.parse.urlparse(url)
            path_parts = parsed_url.path.strip('/').split('/')
            
            if 'character' in path_parts:
                idx = path_parts.index('character')
                if len(path_parts) > idx + 2:
                    account = path_parts[idx + 1]
                    name = path_parts[idx + 2]
                    
                    league = "runesofaldur"
                    if 'builds' in path_parts:
                        b_idx = path_parts.index('builds')
                        if len(path_parts) > b_idx + 1:
                            league = path_parts[b_idx + 1]
                    
                    # For PoE2 builds, poe.ninja uses versioned APIs.
                    # We need to fetch index-state to get the current snapshot version and name
                    index_req = urllib.request.Request(
                        "https://poe.ninja/poe2/api/data/index-state",
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    
                    version = ""
                    snapshot_name = league
                    try:
                        with urllib.request.urlopen(index_req, timeout=10) as resp_idx:
                            index_data = json.loads(resp_idx.read().decode('utf-8'))
                            for snap in index_data.get("snapshotVersions", []):
                                if snap.get("url") == league:
                                    version = snap.get("version", "")
                                    snapshot_name = snap.get("snapshotName", league)
                                    break
                    except Exception as e:
                        pass
                    
                    if version:
                        api_url = f"https://poe.ninja/poe2/api/builds/{urllib.parse.quote(version)}/character?account={urllib.parse.quote(account)}&name={urllib.parse.quote(name)}&overview={urllib.parse.quote(snapshot_name)}&timeMachine="
                        
                        req2 = urllib.request.Request(
                            api_url,
                            headers={'User-Agent': 'Mozilla/5.0'}
                        )
                        try:
                            with urllib.request.urlopen(req2, timeout=10) as resp2:
                                api_data = json.loads(resp2.read().decode('utf-8'))
                                # The PoB code is stored in pathOfBuildingExport
                                if 'pathOfBuildingExport' in api_data and api_data['pathOfBuildingExport']:
                                    return api_data['pathOfBuildingExport']
                        except Exception:
                            pass
                            
            return ErrorResponse(error="无法从 poe.ninja 页面提取 PoB 码", reason="parse_failed")
    except URLError as e:
        return ErrorResponse(error=f"请求 poe.ninja 网络错误: {e.reason}", reason="network_error")
    except Exception as e:
        return ErrorResponse(error=f"解析 poe.ninja 发生未知错误: {e}", reason="unknown_error")


def _cache_key(pob_code: str) -> str:
    """Generate a cache key from pob_code."""
    return hashlib.sha256(pob_code.encode()).hexdigest()[:16]


def decode_pob(pob_code: str) -> DecodeResponse | ErrorResponse:
    """Decode a PoB share code or a pobb.in URL into a structured DecodeResponse.

    Results are cached by pob_code hash to avoid duplicate decoding.
    Returns ErrorResponse if decoding or parsing fails.
    """
    pob_code = pob_code.strip(" `\n\r\t")
    
    # If the input is a pobb.in URL, fetch the raw code first
    if "pobb.in" in pob_code:
        raw_result = fetch_pobbin_raw(pob_code)
        if isinstance(raw_result, ErrorResponse):
            return raw_result
        pob_code = raw_result
    # If the input is a poe.ninja URL, fetch the raw code
    elif "poe.ninja" in pob_code:
        raw_result = fetch_pob_ninja_raw(pob_code)
        if isinstance(raw_result, ErrorResponse):
            return raw_result
        pob_code = raw_result

    # Basic validation for PoB code (must start with eN after fetching from URLs)
    pob_code = pob_code.strip()
    if not pob_code.startswith("eN"):
        return ErrorResponse(error=f"PoB 解码失败: 提取到的代码格式错误 (非 eN 开头)", reason="invalid_prefix")

    # Check cache
    key = _cache_key(pob_code)
    if key in _decode_cache:
        return _decode_cache[key]

    # Decode
    try:
        xml_str = decode_pob_code(pob_code)
    except PoBDecodeError as e:
        return ErrorResponse(error=f"PoB 解码失败: {e.detail}", reason=e.reason)
    except Exception as e:
        return ErrorResponse(error=f"PoB 解码异常: {e}", reason="unknown")

    # Parse
    try:
        raw_data = parse_build_data(xml_str)
    except PoBDecodeError as e:
        return ErrorResponse(error=f"PoB 解析失败: {e.detail}", reason=e.reason)
    except Exception as e:
        return ErrorResponse(error=f"PoB 解析异常: {e}", reason="unknown")

    # Convert to response model
    build_info = BuildInfo(**raw_data.get("build", {}))
    tree_specs = [TreeSpec(**ts) for ts in raw_data.get("treeSpecs", [])]

    skill_sets = []
    for ss in raw_data.get("skillSets", []):
        gems = [Gem(**g) for g in ss.get("gems", [])]
        skill_sets.append(SkillSet(id=ss.get("id"), gems=gems))

    items = [Item(**i) for i in raw_data.get("items", [])]
    player_stats = raw_data.get("playerStats", {})
    config = raw_data.get("config", {})

    result = DecodeResponse(
        build=build_info,
        treeSpecs=tree_specs,
        skillSets=skill_sets,
        items=items,
        playerStats=player_stats,
        config=config,
    )

    # Cache result (evict oldest if full)
    if len(_decode_cache) >= MAX_CACHE_SIZE:
        oldest_key = next(iter(_decode_cache))
        del _decode_cache[oldest_key]
    _decode_cache[key] = result

    return result
