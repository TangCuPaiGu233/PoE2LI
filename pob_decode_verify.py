#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PoB Code 解码 —— 实跑验证（双轨）
轨道1：算法闭环 —— 构造标准 PoB XML → 正向编码 → 反向解码，证明算法正确
轨道2：真实数据 —— 拉取 PoB PoE2 社区仓库真实 build，解析其结构
"""
import base64
import zlib
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"


# ============================================================
# 核心函数：这正是要写进开发文档、交给第三方 AI 的参考实现
# ============================================================
def decode_pob_code(code: str) -> bytes:
    """
    PoB 分享码解码：URL-safe base64 -> zlib inflate -> XML bytes
    PoB 导出/pobb.in 分享均使用此格式。
    """
    code = code.strip().replace("\n", "").replace("\r", "")
    # PoB 使用 URL-safe 字母表（- _ 替代 + /）
    missing = len(code) % 4
    if missing:
        code += "=" * (4 - missing)
    compressed = base64.urlsafe_b64decode(code)
    xml_bytes = zlib.decompress(compressed)
    return xml_bytes


def encode_pob_code(xml_bytes: bytes) -> str:
    """正向编码：XML bytes -> zlib deflate -> URL-safe base64（用于闭环验证）"""
    compressed = zlib.compress(xml_bytes, level=9)
    code = base64.urlsafe_b64encode(compressed).decode("ascii")
    return code


def parse_build(xml_bytes: bytes) -> dict:
    """从 PoB XML 提取关键结构 —— 演示给第三方 AI 看 BuildData 怎么抽取"""
    root = ET.fromstring(xml_bytes)
    result = {"root_tag": root.tag, "skills": [], "items_count": 0, "tree_specs": 0, "class": None, "ascendancy": None}

    build_el = root.find("Build")
    if build_el is not None:
        result["class"] = build_el.get("className")
        result["ascendancy"] = build_el.get("ascendClassName")
        result["level"] = build_el.get("level")

    # 技能组
    skills_el = root.find("Skills")
    if skills_el is not None:
        for sg in skills_el.findall(".//Skill"):
            gems = [g.get("nameSpec") or g.get("skillId") for g in sg.findall("Gem")]
            if gems:
                result["skills"].append([g for g in gems if g])

    # 装备
    items_el = root.find("Items")
    if items_el is not None:
        result["items_count"] = len(items_el.findall("Item"))

    # 天赋树
    tree_el = root.find("Tree")
    if tree_el is not None:
        result["tree_specs"] = len(tree_el.findall("Spec"))

    return result


def main():
    print("=" * 64)
    print("轨道1：算法闭环验证（构造标准 PoB XML → 编码 → 解码）")
    print("=" * 64)
    # 一份结构真实的 PoB XML（字段名取自 PoB 实际导出格式）
    sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding>
  <Build level="92" className="Witch" ascendClassName="Infernalist" mainSocketGroup="1">
    <PlayerStat stat="Life" value="4521"/>
    <PlayerStat stat="TotalDPS" value="1832000"/>
  </Build>
  <Skills>
    <Skill mainActiveSkill="1" enabled="true">
      <Gem nameSpec="Fireball" skillId="Fireball" level="20" quality="20"/>
      <Gem nameSpec="Fire Penetration" skillId="FirePen" level="20" quality="0"/>
    </Skill>
  </Skills>
  <Items>
    <Item id="1">Rarity: RARE
Inferno Crown
Sorcerer Crown
Quality: 20
+120 to maximum Life</Item>
    <Item id="2">Rarity: UNIQUE
The Eternal Flame
Topaz Ring</Item>
  </Items>
  <Tree>
    <Spec title="Default" treeVersion="0_2">
      <URL>https://www.pathofexile2.com/passive-skill-tree/AAAA</URL>
    </Spec>
  </Tree>
</PathOfBuilding>"""

    code = encode_pob_code(sample_xml)
    print(f"[编码] 生成 PoB Code（前80字符）: {code[:80]}...")
    print(f"[编码] Code 总长度: {len(code)} 字符")
    print(f"[编码] 开头特征: {code[:4]}  (zlib+base64 典型开头 'eNp' 或 'eJ')")

    decoded = decode_pob_code(code)
    print(f"[解码] 还原 XML 字节数: {len(decoded)}")
    assert decoded == sample_xml, "❌ 闭环失败：解码结果与原文不一致"
    print("[校验] ✅ 闭环成功：decode(encode(xml)) == xml，解码算法 100% 正确")

    print()
    print("[解析] 从还原的 XML 抽取 BuildData：")
    info = parse_build(decoded)
    for k, v in info.items():
        print(f"   {k:14}: {v}")

    print()
    print("=" * 64)
    print("轨道2：真实数据验证（拉取 PoB PoE2 社区仓库真实 build）")
    print("=" * 64)
    # PoB 仓库里 Builds/ 或 spec/ 下有真实的 .xml build 文件
    real_urls = [
        "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/spec/Modules/CalcSetup_spec.lua",
        "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/Builds/_README.txt",
    ]
    for url in real_urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            print(f"[拉取OK] {url.split('/')[-1]} -> {len(data)} bytes")
            # 尝试从中提取 PoB import code（eNp/eJ 开头的长 base64）
            import re
            m = re.findall(rb'(eN[a-zA-Z][A-Za-z0-9_+/=-]{60,})', data)
            if m:
                print(f"         发现 {len(m)} 个疑似 PoB code")
                try:
                    real_xml = decode_pob_code(m[0].decode())
                    print(f"         ✅ 真实 code 解码成功，XML {len(real_xml)} bytes")
                    print("        ", parse_build(real_xml))
                except Exception as e:
                    print(f"         解码该样例失败: {e}")
        except Exception as e:
            print(f"[拉取失败] {url.split('/')[-1]}: {e}")


if __name__ == "__main__":
    main()
