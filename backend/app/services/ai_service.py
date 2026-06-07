"""AI service for generating build playbooks.

Supports dual LLM providers via env vars:
  - SiliconFlow (default, paid): deepseek-ai/DeepSeek-V4-Flash
  - OpenRouter (backup, free tier): qwen/qwen3-next-80b-a3b-instruct:free
Switch by changing LLM_BASE_URL, LLM_API_KEY, LLM_MODEL in docker-compose.yml.
"""

import os
import json
import re
import logging
from openai import OpenAI
from app.models.schemas import DecodeResponse
from app.core.database import SessionLocal
from app.models.build import ModTranslation

logger = logging.getLogger(__name__)

# LLM provider — defaults to SiliconFlow paid, switchable to OpenRouter free
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

client = OpenAI(
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
)


def _translate_unknown_mods(mods: list[str]) -> dict[str, str]:
    """Use AI to translate unknown English mods and save to database."""
    if not mods:
        return {}
        
    prompt = "你是一个 Path of Exile 2 的资深翻译专家。请将以下英文装备词缀翻译为准确的中文。保留数值占位符（如果有）。\n\n"
    for i, mod in enumerate(mods):
        prompt += f"{i}. {mod}\n"
    
    prompt += "\n请严格按以下 JSON 格式输出，键是原英文，值是中文翻译：\n"
    prompt += '{\n  "英文词缀1": "中文翻译1",\n  "英文词缀2": "中文翻译2"\n}'
    
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        
        content = response.choices[0].message.content or ""
                
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            translations = json.loads(json_match.group(1))
        else:
            brace_start = content.find('{')
            brace_end = content.rfind('}')
            if brace_start >= 0 and brace_end > brace_start:
                translations = json.loads(content[brace_start:brace_end + 1])
            else:
                translations = {}
                
        # Save to database
        if translations:
            db = SessionLocal()
            try:
                for en, zh in translations.items():
                    if isinstance(en, str) and isinstance(zh, str) and en in mods:
                        # Ensure it doesn't already exist to avoid unique constraint violation
                        existing = db.query(ModTranslation).filter(ModTranslation.mod_en == en).first()
                        if not existing:
                            new_mod = ModTranslation(mod_en=en, mod_zh=zh, source="ai")
                            db.add(new_mod)
                db.commit()
            except Exception as e:
                logger.error(f"Failed to save translations to DB: {e}")
                db.rollback()
            finally:
                db.close()
                
        return translations
    except Exception as e:
        logger.error(f"AI translation failed: {e}")
        return {}


def _translate_item_mods(items: list, db_session) -> list[str]:
    """Translate item mods using DB cache first, then AI fallback."""
    item_list = []
    unknown_mods = set()
    
    # 1. Collect all raw lines
    all_raw_lines = []
    USELESS_LINES = {"Unique ID", "Item Level", "Quality", "Sockets", "Rune:", "LevelReq:"}
    
    for i in items:
        if not i.name:
            continue
        raw_lines = i.raw.split("\n") if i.raw else []
        filtered = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped or any(stripped.startswith(prefix) for prefix in USELESS_LINES):
                continue
            filtered.append(stripped)
            
        if len(filtered) > 3:
            all_raw_lines.extend(filtered[3:]) # Skip Rarity, Name, BaseName
            
    # 2. Query DB for existing translations
    existing_translations = {}
    if all_raw_lines:
        db_mods = db_session.query(ModTranslation).filter(ModTranslation.mod_en.in_(list(set(all_raw_lines)))).all()
        for m in db_mods:
            existing_translations[m.mod_en] = m.mod_zh
            
    # 3. Find unknown mods
    for line in set(all_raw_lines):
        # Only translate actual mod lines, skip simple things like "Armour: 100"
        if line not in existing_translations and ":" not in line and not line.startswith("Requires"):
            unknown_mods.add(line)
            
    # 4. Use AI to translate unknown mods
    ai_translations = {}
    if unknown_mods:
        ai_translations = _translate_unknown_mods(list(unknown_mods))
        
    # Combine translations
    all_translations = {**existing_translations, **ai_translations}
    
    # 5. Format items with translated mods
    for i in items:
        if not i.name:
            continue
        raw_lines = i.raw.split("\n") if i.raw else []
        filtered = []
        for idx, line in enumerate(raw_lines):
            stripped = line.strip()
            if not stripped or any(stripped.startswith(prefix) for prefix in USELESS_LINES):
                continue
            
            # Translate mods (usually after line 2)
            if idx > 2 and stripped in all_translations:
                filtered.append(f"{stripped} ({all_translations[stripped]})")
            else:
                filtered.append(stripped)
                
        item_text = "\n  ".join(filtered)
        item_list.append(f"[{i.rarity}] {i.name}\n  {item_text}")
        
    return item_list


def _build_prompt(build_data: DecodeResponse) -> str:
    """Build a prompt for the AI to generate a Chinese playbook."""
    build = build_data.build
    stats = build_data.playerStats
    tree = build_data.treeSpecs
    skills = build_data.skillSets
    items = build_data.items

    # Extract key stats
    life = stats.get("Life", "N/A")
    mana = stats.get("Mana", "N/A")
    dps = stats.get("TotalDPS", "N/A")
    ehp = stats.get("TotalEHP", "N/A")
    str_val = stats.get("Str", "N/A")
    dex_val = stats.get("Dex", "N/A")
    int_val = stats.get("Int", "N/A")
    fire_res = stats.get("FireResist", "N/A")
    cold_res = stats.get("ColdResist", "N/A")
    lightning_res = stats.get("LightningResist", "N/A")

    # Group skills by socket group (SkillSet > Skill > Gem)
    # PoB organizes gems into socket groups — each Skill in a SkillSet is one socket group
    companions = []
    socket_groups = []
    for ss in skills:
        # Each ss.gems is a flat list, but they come from multiple Skill elements
        # Group by slot
        current_slot = None
        current_gems = []
        for g in ss.gems:
            if not g.nameSpec or not g.enabled:
                continue
            if g.slot != current_slot:
                if current_gems:
                    socket_groups.append({"slot": current_slot, "gems": current_gems})
                current_slot = g.slot
                current_gems = []
            current_gems.append(g)
        if current_gems:
            socket_groups.append({"slot": current_slot, "gems": current_gems})

    # Also collect companions separately for highlighting
    for sg in socket_groups:
        for g in sg["gems"]:
            if "companion" in (g.nameSpec or "").lower() or "Companion" in (g.nameSpec or ""):
                companions.append(g)

    gems_str = ""
    if companions:
        gems_str += "=== Companion（伙伴）— PoE2 独立战斗实体，与普通召唤物不同 ===\n"
        for c in companions:
            gems_str += f"- **{c.nameSpec}** Lv{c.level} Q{c.quality}\n"
        gems_str += "\n"

    gems_str += "=== Socket Groups（技能组合）===\n"
    for sg in socket_groups:
        slot = sg["slot"] or "unknown"
        gem_names = [f"{g.nameSpec}(Lv{g.level})" for g in sg["gems"]]
        gems_str += f"[{slot}] {' + '.join(gem_names)}\n"
    if not gems_str:
        gems_str = "未配置"

    # Extract items with FULL raw text, filter useless lines
    # And apply translation
    db = SessionLocal()
    try:
        item_list = _translate_item_mods(items, db)
        items_str = "\n\n".join(item_list) or "无装备数据"
    finally:
        db.close()

    # Extract tree info
    node_count = sum(len(ts.nodes) for ts in tree)

    return f"""你是一个 Path of Exile 2（流放之路2）构建分析专家。请仔细分析以下构建数据，生成一份中文攻略。

重要规则：
- 这是 Path of Exile 2，不是 PoE1。PoE2 的技能、装备、机制和 PoE1 差异很大，不要混用。
- 所有分析必须严格基于下方提供的实际数据，不要编造不存在的装备、技能或天赋节点。
- 如果数据中没有足够信息来回答某个方面，请在该字段写"数据不足，暂无法分析"，不要猜测。
- Companion（伙伴）是 PoE2 独立战斗实体，有自己的 AI 和技能，与传统 Minion（召唤物）不同
- 请基于数据自行判断：Companion 是核心输出还是辅助手段，不要预设结论
- 装备数据包含完整词缀，仔细阅读词缀来判断装备的核心价值
- 如果 DPS 为 0，请分析伤害可能来自哪里（Companion、Minion、DoT 等）

## 构建信息
- 职业: {build.className} / {build.ascendClassName}
- 等级: {build.level}
- 天赋节点数: {node_count}

## 关键属性
- 生命: {life}
- 魔力: {mana}
- DPS: {dps}
- EHP: {ehp}
- 力量/敏捷/智慧: {str_val}/{dex_val}/{int_val}
- 抗性: 火{fire_res} / 冰{cold_res} / 电{lightning_res}

## 技能宝石（按 Socket Group 分组）
{gems_str}

## 装备（完整词缀）
{items_str}

## 输出要求
1. 用中文回答
2. 基于实际数据分析，不要编造不存在的装备或技能
3. 重点分析这个构建的核心输出手段和独特玩法
4. 如果有 Companion/Minion/Totem，详细说明它们的作用
5. 平价替代：只推荐你在当前装备数据中看到的更便宜选择，或明确写"当前数据不足以推荐替代品"
6. 天赋亮点：基于天赋节点数量来分析加点密度和方向，不要编造具体节点名称

请严格按以下 JSON 格式输出，每个字段的值必须是纯字符串：
{{
  "core_idea": "核心思路：分析这个构建的核心输出手段和玩法特色",
  "core_items": "核心装备：列出关键装备及其作用",
  "budget_alternatives": "预算替代：低成本替代方案（无数据则写数据不足）",
  "talent_highlights": "天赋亮点：基于节点数的分析",
  "strength_review": "强度评估：优劣势和适用场景"
}}"""


def _fix_keys(result: dict) -> dict:
    """Fix common AI typos in JSON keys."""
    KEY_MAP = {
        "core_idea": "core_idea",
        "core_ista": "core_idea",
        "core_id": "core_idea",
        "core_ide": "core_idea",
        "core_items": "core_items",
        "core_item": "core_items",
        "budget_alternatives": "budget_alternatives",
        "budget_alternative": "budget_alternatives",
        "budget_alternatives": "budget_alternatives",
        "talent_highlights": "talent_highlights",
        "talent_highlight": "talent_highlights",
        "talent_points": "talent_highlights",
        "talent_point": "talent_highlights",
        "strength_review": "strength_review",
        "strength_reviews": "strength_review",
    }
    fixed = {}
    for k, v in result.items():
        canonical = KEY_MAP.get(k, k)
        # If already exists, merge (prefer longer content)
        if canonical in fixed:
            if len(str(v)) > len(str(fixed[canonical])):
                fixed[canonical] = v
        else:
            fixed[canonical] = v
    return fixed


def _parse_ai_response(content: str) -> dict:
    """Parse AI response, handling various formats robustly."""
    # Try direct JSON parse first
    try:
        return _fix_keys(json.loads(content))
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        try:
            return _fix_keys(json.loads(json_match.group(1)))
        except json.JSONDecodeError:
            pass

    # Try finding any JSON object in the content
    brace_start = content.find('{')
    brace_end = content.rfind('}')
    if brace_start >= 0 and brace_end > brace_start:
        json_str = content[brace_start:brace_end + 1]
        try:
            return _fix_keys(json.loads(json_str))
        except json.JSONDecodeError:
            # Try fixing common JSON issues
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                return _fix_keys(json.loads(json_str))
            except json.JSONDecodeError:
                pass

    # If all else fails, try to extract key-value pairs manually
    # Also handle fuzzy key names (typos like core_ista -> core_idea)
    result = {}
    fuzzy_patterns = {
        "core_idea": [r"core_idea", r"core_ista", r"core_id", r"core_ide[a-z]?"],
        "core_items": [r"core_items?", r"core_item"],
        "budget_alternatives": [r"budget_alternatives?", r"budget_alternative"],
        "talent_highlights": [r"talent_highlights?", r"talent_highlight", r"talent_points?", r"talent亮点"],
        "strength_review": [r"strength_reviews?", r"strength_review"],
    }
    for canonical, patterns in fuzzy_patterns.items():
        for pat in patterns:
            # Look for "key": "value" pattern
            pattern = rf'"{pat}"\s*:\s*"((?:[^"\\]|\\.)*)"'
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                result[canonical] = match.group(1)
                break
            # Look for 'key': 'value' pattern
            pattern = rf"'{pat}'\s*:\s*'((?:[^'\\]|\\.)*)'"
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                result[canonical] = match.group(1)
                break

    if result:
        return _fix_keys(result)

    raise ValueError(f"Could not parse AI response as JSON: {content[:200]}...")


def _validate_ai_homework(homework: dict, build_data: DecodeResponse) -> dict:
    """Cross-validate AI generated homework against actual build data to reduce hallucinations.
    
    If AI mentions items or skills that don't exist in the build, append a warning warning.
    """
    # 1. Collect actual names from build
    actual_item_names = {i.name.lower() for i in build_data.items if i.name}
    actual_gem_names = set()
    for ss in build_data.skillSets:
        for g in ss.gems:
            if g.nameSpec:
                actual_gem_names.add(g.nameSpec.lower())
                
    # 2. Extract potential entities from AI homework (very basic keyword matching)
    core_items_text = homework.get("core_items", "").lower()
    
    warnings = []
    
    # 3. Check for common PoE2 unique items mentioned by AI but missing in build
    # This is a naive approach, in a real scenario we'd use NLP or a known item DB
    # Here we just look for specific exact matches if AI mentions them
    mentioned_items = re.findall(r'【(.*?)】|\[(.*?)\]|"(.*?)"', core_items_text)
    for match_tuple in mentioned_items:
        item = next((m for m in match_tuple if m), None)
        if item and len(item) > 2:
            item_lower = item.lower()
            # If the item mentioned doesn't exist in actual items (fuzzy match)
            if not any(item_lower in actual or actual in item_lower for actual in actual_item_names):
                warnings.append(f"⚠️ 警告: AI 提到的装备「{item}」在原始 PoB 数据中并未装备。")
                
    if warnings:
        homework["core_items"] += "\n\n" + "\n".join(set(warnings))
        
    return homework


def chat_about_build(build, question: str, db_session=None) -> str:
    """Chat with the AI about a specific build, enhanced with RAG retrieval.

    1. Gathers rich context from the build (class, skills, items, tree, homework).
    2. Retrieves knowledge chunks from the vector DB (current build + similar builds).
    3. Combines both contexts and asks the AI for an answer.
    """
    from app.core.database import SessionLocal
    from app.services.knowledge_service import retrieve_similar

    # 1. Prepare rich context from build
    build_data = build.get_build_data()
    homework = build.get_homework()

    context_str = f"职业: {build.class_name} / {build.ascendancy}\n"
    context_str += f"等级: {build.level}\n"

    # Stats
    stats = build_data.get("playerStats", {})
    stat_parts = []
    for label, key in [("生命", "Life"), ("能量护盾", "EnergyShield"), ("DPS", "TotalDPS"), ("EHP", "TotalEHP")]:
        val = stats.get(key)
        if val:
            stat_parts.append(f"{label}: {val}")
    if stat_parts:
        context_str += "【面板数据】" + " | ".join(stat_parts) + "\n\n"

    # Skills
    skills = []
    for ss in build_data.get("skillSets", []):
        for g in ss.get("gems", []):
            if g.get("nameSpec") and g.get("enabled"):
                name = g["nameSpec"]
                lvl = g.get("level", "")
                skills.append(f"{name}(Lv{lvl})" if lvl else name)
    if skills:
        context_str += f"【主要技能】: {', '.join(list(dict.fromkeys(skills)))}\n\n"

    # Key items
    items = build_data.get("items", [])
    unique_items = [i for i in items if i.get("rarity") == "UNIQUE" and i.get("name")]
    if unique_items:
        item_names = [f"{i['name']}({i.get('baseName', '')})" for i in unique_items[:8]]
        context_str += f"【暗金装备】: {', '.join(item_names)}\n\n"

    # All homework sections
    if homework:
        context_str += "【已有分析报告】\n"
        for key, label in [
            ("core_idea", "核心思路"),
            ("core_items", "核心装备"),
            ("budget_alternatives", "平价替代"),
            ("talent_highlights", "天赋亮点"),
            ("strength_review", "强度评估"),
        ]:
            val = homework.get(key, "")
            if val and not val.startswith("AI 未生成") and val != "暂无数据（AI 生成失败）":
                context_str += f"{label}: {val}\n"
        context_str += "\n"

    # 2. RAG retrieval — search ALL knowledge including current build
    rag_context = ""
    rag_sources = []
    try:
        db = db_session or SessionLocal()
        try:
            # First: retrieve current build's own knowledge (most relevant)
            own_chunks = retrieve_similar(
                db=db,
                query=question,
                league=build.league,
                game_version=build.game_version,
                top_k=3,
                exclude_build_id=None,  # Include current build
            )

            if own_chunks:
                rag_context = "【知识库参考】\n"
                for i, chunk in enumerate(own_chunks, 1):
                    rag_context += f"[{i}] {chunk['content']}\n\n"
                    if chunk.get("build_id") and chunk["build_id"] != build.id:
                        rag_sources.append(f"Build#{chunk['build_id']}")
        finally:
            if db_session is None:
                db.close()
    except Exception as e:
        logger.warning(f"RAG retrieval failed (falling back to direct context only): {e}")

    # 3. Build combined prompt — strict, PoE2-focused, no guessing
    prompt = f"""你是一个专业的 Path of Exile 2（流放之路2，注意是 PoE2 不是 PoE1）游戏助手。
请严格根据以下玩家构建(Build)的实际数据来回答提问。

重要规则：
1. 你的回答必须基于【当前构建上下文】和【知识库参考】中的实际数据，不要编造信息。
2. 如果上下文中没有相关信息，请直接说"当前BD数据中没有这方面的信息"，不要用 PoE1 的知识来猜测 PoE2 的内容。
3. PoE2 和 PoE1 的机制、技能、装备差异很大，不要混用。
4. 回答要具体、实用，用中文。

{context_str}
{rag_context if rag_context else ''}【玩家提问】
{question}
"""

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        answer = response.choices[0].message.content or "抱歉，我无法回答这个问题。"
        # Append RAG source info if used
        if rag_sources:
            sources = ", ".join(set(rag_sources))
            answer += f"\n\n（参考了知识库中相似BD: {sources}）"
        return answer
    except Exception as e:
        logger.error(f"Chat generation failed: {e}")
        return f"系统繁忙，请稍后再试。(错误: {str(e)})"


def generate_homework(build_data: DecodeResponse) -> dict:
    """Generate a Chinese playbook from BuildData using DeepSeek V4 Flash.

    Returns a dict with five sections:
    - core_idea: Build philosophy and playstyle
    - core_items: Essential equipment
    - budget_alternatives: Cheaper substitutes
    - talent_highlights: Notable passive tree choices
    - strength_review: Build strengths and weaknesses
    """
    prompt = _build_prompt(build_data)

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=4000,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        content = response.choices[0].message.content or ""
        if not content:
            raise ValueError("AI response contained no text content")

        # Parse JSON from response
        result = _parse_ai_response(content)

        # Validate and flatten required fields
        for key in ["core_idea", "core_items", "budget_alternatives", "talent_highlights", "strength_review"]:
            if key not in result:
                result[key] = f"AI 未生成 {key} 内容"
            elif isinstance(result[key], dict):
                desc = result[key].get("description", "")
                if not desc:
                    desc = str(result[key])
                result[key] = desc
            elif not isinstance(result[key], str):
                result[key] = str(result[key])

        # Cross-validation against hallucination
        result = _validate_ai_homework(result, build_data)

        return result

    except Exception as e:
        # Fallback: generate basic analysis from data
        build = build_data.build
        stats = build_data.playerStats
        items = build_data.items
        skills = build_data.skillSets

        # Try to identify key items
        unique_items = [i.name for i in items if i.rarity == "UNIQUE" and i.name]
        key_items_str = "、".join(unique_items[:5]) if unique_items else "未知"

        # Try to identify main skill
        main_gems = []
        for ss in skills:
            for g in ss.gems:
                if g.enabled and g.nameSpec and g.level >= 15:
                    main_gems.append(g.nameSpec)
        main_skill_str = "、".join(main_gems[:3]) if main_gems else "未知"

        return {
            "core_idea": f"{build.className} / {build.ascendClassName} 构建，等级 {build.level}。主要技能: {main_skill_str}。DPS: {stats.get('TotalDPS', 'N/A')}。AI 分析失败: {e}",
            "core_items": f"核心装备: {key_items_str}",
            "budget_alternatives": "暂无数据（AI 生成失败）",
            "talent_highlights": f"天赋树共 {sum(len(ts.nodes) for ts in build_data.treeSpecs)} 个节点",
            "strength_review": f"生命: {stats.get('Life', 'N/A')}, DPS: {stats.get('TotalDPS', 'N/A')}",
        }
