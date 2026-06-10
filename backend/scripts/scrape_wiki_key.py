"""Scrape key mechanics pages from poe2wiki.net that were missed."""
import cloudscraper, json, sys, time
from bs4 import BeautifulSoup

s = cloudscraper.create_scraper()

KEY_PAGES = [
    'Aura', 'Buff', 'Herald', 'Ailment', 'Ascendancy_class',
    'Huntress', 'Beast', 'Minion', 'Curse', 'Charge',
    'Skill_gem', 'Support_gem', 'Spirit_gem', 'Passive_Skill_Tree',
    'Attribute', 'Accuracy', 'Block', 'Evasion', 'Energy_shield',
    'Armour', 'Bleeding', 'Poison', 'Ignite', 'Freeze', 'Shock',
    'Critical_strike', 'Life', 'Mana', 'Resistance',
]

results = []
for page in KEY_PAGES:
    time.sleep(3)
    url = 'https://www.poe2wiki.net/wiki/' + page
    try:
        resp = s.get(url, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            content = soup.find('div', class_='mw-parser-output')
            title = soup.find('h1')
            title_text = title.get_text(strip=True) if title else page
            text = content.get_text(strip=True)[:4000] if content else ''
            results.append({'title': title_text, 'path': page, 'full_text': text})
            print('OK: ' + page + ' - ' + str(len(text)) + ' chars')
        else:
            print('SKIP: ' + page + ' (HTTP ' + str(resp.status_code) + ')')
    except Exception as e:
        print('ERR: ' + page + ' ' + str(e))

out_path = sys.argv[1] if len(sys.argv) > 1 else '/data/poe2wiki_key.jsonl'
lines = []
for r in results:
    chunk = {
        'chunk_id': 'wiki_key_' + r['path'],
        'content_type': 'wiki',
        'source_page': 'poe2wiki',
        'title': r['title'],
        'path': r['path'],
        'search_text': r.get('full_text', ''),
    }
    lines.append(json.dumps(chunk, ensure_ascii=False))

with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')

print('Total: ' + str(len(results)) + '/' + str(len(KEY_PAGES)))
