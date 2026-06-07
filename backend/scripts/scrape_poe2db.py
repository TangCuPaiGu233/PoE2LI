import urllib.request
from bs4 import BeautifulSoup
import json
import re

def scrape_poe2db_mods():
    """Scrape explicit modifiers from poe2db to build a base translation dictionary."""
    translations = {}
    
    # We will try a few different pages that contain item affixes or passive skills
    urls = [
        "https://poe2db.tw/cn/Modifiers",
        "https://poe2db.tw/cn/Passive_Skill_Tree",
        "https://poe2db.tw/cn/Skill_Gems"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Cookie': 'poe2db_language=cn'
    }
    
    for url in urls:
        print(f"Fetching {url}...")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')
                
            soup = BeautifulSoup(html, 'html.parser')
            
            tables = soup.find_all('table', class_='table')
            for table in tables:
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        # Look for translation spans
                        en_span = cols[0].find('span', class_='en') or cols[1].find('span', class_='en')
                        cn_span = cols[0].find('span', class_='lc') or cols[1].find('span', class_='lc')
                        
                        if not (en_span and cn_span):
                            # Fallback to direct text if classes aren't present
                            en_text = cols[0].get_text(separator=" ", strip=True)
                            cn_text = cols[1].get_text(separator=" ", strip=True)
                            if not re.search(r'[a-zA-Z]', en_text) and re.search(r'[a-zA-Z]', cn_text):
                                en_text, cn_text = cn_text, en_text
                        else:
                            en_text = en_span.get_text(strip=True)
                            cn_text = cn_span.get_text(strip=True)
                        
                        if en_text and cn_text:
                            # Split by newlines (often mods are multiline)
                            en_lines = en_text.split('\n')
                            cn_lines = cn_text.split('\n')
                            
                            for i in range(min(len(en_lines), len(cn_lines))):
                                e_line = en_lines[i].strip()
                                c_line = cn_lines[i].strip()
                                
                                if e_line and c_line:
                                    en_template = re.sub(r'[+-]?\d+(?:\.\d+)?', '#', e_line)
                                    cn_template = re.sub(r'[+-]?\d+(?:\.\d+)?', '#', c_line)
                                    
                                    if en_template and cn_template and en_template != cn_template:
                                        translations[en_template] = cn_template
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            
    return translations

if __name__ == "__main__":
    print("Scraping poe2db modifiers...")
    data = scrape_poe2db_mods()
    print(f"Found {len(data)} translation templates.")
    
    # Add script to inject data into database
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.core.database import SessionLocal
    from app.models.build import ModTranslation
    
    print("Injecting into database...")
    db = SessionLocal()
    count = 0
    for en, zh in data.items():
        existing = db.query(ModTranslation).filter(ModTranslation.mod_en == en).first()
        if not existing:
            new_mod = ModTranslation(mod_en=en, mod_zh=zh, source="poe2db")
            db.add(new_mod)
            count += 1
    db.commit()
    db.close()
    print(f"Successfully injected {count} new modifiers into database.")
