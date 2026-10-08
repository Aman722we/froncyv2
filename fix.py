with open('services/career_sync.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace("\x08", "\\b")
with open('services/career_sync.py', 'w', encoding='utf-8') as f:
    f.write(c)