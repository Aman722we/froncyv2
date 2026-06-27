import os

replacements = {
    "t.me/FroncyBot": "t.me/FroncyJobsBot",
    "@FroncyBot": "@FroncyJobsBot",
    "froncybot": "froncyjobsbot"
}

target_dir = "applixy-web"

for root, _, files in os.walk(target_dir):
    if ".git" in root or "node_modules" in root or ".next" in root:
        continue
        
    for file in files:
        if file.endswith((".tsx", ".ts", ".css", ".html", ".md", ".json")):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                
            new_content = content
            for old, new in replacements.items():
                new_content = new_content.replace(old, new)
                
            if new_content != content:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Updated {path}")
