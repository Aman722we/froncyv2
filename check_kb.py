with open("utils/keyboards.py", "r", encoding="utf-8") as f:
    content = f.read()
import re
match = re.search(r"Row 1: Cover Letter.*?buttons\.append\(\[.*?\]\)", content, re.DOTALL)
if match:
    # safe print without emojis crashing
    print(match.group(0).encode('ascii', 'ignore').decode())
