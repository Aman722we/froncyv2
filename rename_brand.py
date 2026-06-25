import os

replacements = {
    "FroncyBot": "FroncyBot",
    "Froncy": "Froncy",
    "froncybot": "froncybot",
    "froncy": "froncy"
}

# The image is Froncy_banner.png -> Froncy_banner.png
if os.path.exists("assets/images/Froncy_banner.png"):
    os.rename("assets/images/Froncy_banner.png", "assets/images/Froncy_banner.png")

target_dirs = ["handlers", "services", "utils", "."]

for root, _, files in os.walk("."):
    if ".git" in root or "__pycache__" in root or "venv" in root or ".venv" in root or "froncy-web" in root:
        continue
        
    for file in files:
        if file.endswith(".py"):
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
