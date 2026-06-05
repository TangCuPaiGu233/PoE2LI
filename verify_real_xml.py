#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 pasteofexile 仓库里的真实 build XML 测试数据，验证 parse_build 字段抽取，
并验证 encode->decode 完整往返。"""
import io, tarfile, base64, zlib
import xml.etree.ElementTree as ET
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept":"*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

# ---------- 待验证的生产函数 ----------
def encode_pob(xml_bytes: bytes) -> str:
    compressed = zlib.compress(xml_bytes, 9)
    b64 = base64.b64encode(compressed).decode("ascii")
    return b64.replace("+","-").replace("/","_")

def decode_pob(code: str) -> bytes:
    code = code.strip().replace("\n","").replace("\r","")
    s = code.replace("-","+").replace("_","/")
    s += "=" * (-len(s) % 4)
    raw = base64.b64decode(s)
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return zlib.decompress(raw, -15)

def parse_build(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    out = {"class": None, "ascendancy": None, "level": None,
           "main_skills": [], "items": [], "tree_specs": []}
    bd = root.find("Build")
    if bd is not None:
        out["class"] = bd.get("className")
        out["ascendancy"] = bd.get("ascendClassName")
        out["level"] = bd.get("level")
    # 技能：Skills/SkillSet/Skill/Gem 或 Skills/Skill/Gem
    for gem in root.iter("Gem"):
        name = gem.get("nameSpec") or gem.get("skillId")
        if name:
            out["main_skills"].append(name)
    # 装备
    for it in root.iter("Item"):
        txt = (it.text or "").strip()
        if txt:
            first_line = txt.splitlines()[0] if txt.splitlines() else ""
            out["items"].append(first_line)
    # 天赋树
    for spec in root.iter("Spec"):
        out["tree_specs"].append(spec.get("title") or "default")
    return out

# ---------- 拉真实测试 XML ----------
b = fetch("https://codeload.github.com/Dav1dde/pasteofexile/tar.gz/refs/heads/master")
tf = tarfile.open(fileobj=io.BytesIO(b), mode="r:gz")
targets = ["pasteofexile-master/pob/test/316_poison_occ.xml",
           "pasteofexile-master/pob/test/325_loadouts.xml",
           "pasteofexile-master/pob/test/318_skillset.xml"]

for name in targets:
    try:
        xml_bytes = tf.extractfile(name).read()
    except Exception as e:
        print(f"[skip] {name}: {e}"); continue
    print(f"\n{'='*60}\n真实测试数据: {name}  ({len(xml_bytes)} bytes)")
    # 1) 解析真实 XML
    try:
        info = parse_build(xml_bytes)
        print(f"  [parse_build] class={info['class']} ascend={info['ascendancy']} level={info['level']}")
        print(f"                main_skills({len(info['main_skills'])}): {info['main_skills'][:8]}")
        print(f"                items({len(info['items'])}): {info['items'][:4]}")
        print(f"                tree_specs({len(info['tree_specs'])}): {info['tree_specs'][:5]}")
    except Exception as e:
        print(f"  [parse_build] ❌ {e}")
        continue
    # 2) 完整往返：encode -> decode == 原文
    code = encode_pob(xml_bytes)
    back = decode_pob(code)
    ok = back == xml_bytes
    print(f"  [round-trip] code_len={len(code)}, code_head={code[:24]}, decode==原文: {'✅' if ok else '❌'}")
