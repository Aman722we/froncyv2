text = """Backend QA Engineer - Air Apps  
Job link: https://www.linkedin.com/jobs/view/4407847866  
📍 Lisbon (Onsite) | Fulltime | €52K–€65K/yr  
🎓 2–3 YOE  
🏷 Node.js, TypeScript, PostgreSQL, SQL, Postman, Swagger  
⏰ 21h ago"""

lines = [line.strip() for line in text.split("\n") if line.strip()]

try:
    # Line 1: Title - Company
    title_company = lines[0].split("-", 1)
    title = title_company[0].strip()
    company = title_company[1].strip() if len(title_company) > 1 else "Unknown"

    # Line 2: URL
    url_line = lines[1]
    url = url_line.replace("Job link:", "").strip()

    # Line 3: Location | Job Type | Salary
    loc_type_sal = lines[2].replace("📍", "").split("|")
    location = loc_type_sal[0].strip() if len(loc_type_sal) > 0 else "Remote"
    
    job_type_str = loc_type_sal[1].strip() if len(loc_type_sal) > 1 else "Fulltime"
    job_type = "internship" if "intern" in job_type_str.lower() else "fulltime"
    duration = job_type_str if job_type == "internship" else None
    
    salary = loc_type_sal[2].strip() if len(loc_type_sal) > 2 else "Not disclosed"

    # Line 4: Batches | YOE
    batch_yoe = lines[3].replace("🎓", "").split("|")
    batch_str = batch_yoe[0].strip()
    
    yoe_str = "0"
    if len(batch_yoe) > 1:
        yoe_str = batch_yoe[1].strip()
    elif "yoe" in batch_str.lower():
        yoe_str = batch_str
        batch_str = ""

    batches = []
    if batch_str:
        parts = batch_str.split("/")
        for p in parts:
            p = p.strip()
            if p.isdigit():
                batches.append(int(p))
    
    import re
    min_yoe = 0
    yoe_digits = re.findall(r'\d+', yoe_str)
    if yoe_digits:
        min_yoe = int(yoe_digits[0])

    # Line 5: Skills
    skills_str = lines[4].replace("🏷", "").strip()
    skills = [s.strip() for s in skills_str.split(",")]

    # Line 6: Time (Optional)
    posted_at = None
    if len(lines) > 5 and "⏰" in lines[5]:
        time_str = lines[5].replace("⏰", "").replace("ago", "").replace("(Optional)", "").strip()
        from datetime import datetime, timedelta, timezone
        num = int(''.join(filter(str.isdigit, time_str)))
        if 'd' in time_str:
            posted_at = datetime.now(timezone.utc) - timedelta(days=num)
        elif 'h' in time_str:
            posted_at = datetime.now(timezone.utc) - timedelta(hours=num)

    data = {
        "title": title,
        "company": company,
        "url": url,
        "location": location,
        "salary": salary,
        "job_type": job_type,
        "duration": duration,
        "skills": skills,
        "min_yoe": min_yoe,
        "eligible_batches": batches,
        "posted_at": posted_at
    }
    import pprint
    pprint.pprint(data)
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")
