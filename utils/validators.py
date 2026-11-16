"""
utils/validators.py - Centralized validation and normalization for technical skills,
conversational intent detection, and candidate profile inputs.
"""
import re
from typing import Tuple, List, Optional

# Canonical mapping from lower-case alias to standardized display name
CANONICAL_SKILL_MAP: dict[str, str] = {
    # Languages
    "python": "Python",
    "py": "Python",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "golang": "Go",
    "go": "Go",
    "java": "Java",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    ".net": ".NET",
    "dotnet": ".NET",
    "ruby": "Ruby",
    "rust": "Rust",
    "php": "PHP",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "scala": "Scala",
    "dart": "Dart",
    "r": "R",

    # Frontend
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "next": "Next.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "angularjs": "Angular",
    "svelte": "Svelte",
    "redux": "Redux",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "tailwind": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    "bootstrap": "Bootstrap",
    "sass": "SASS",
    "webpack": "Webpack",
    "vite": "Vite",

    # Backend & Frameworks
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "express": "Express.js",
    "expressjs": "Express.js",
    "express.js": "Express.js",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "spring": "Spring Boot",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "nest": "NestJS",
    "nestjs": "NestJS",
    "rails": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "graphql": "GraphQL",
    "gql": "GraphQL",
    "rest": "REST APIs",
    "rest api": "REST APIs",
    "rest apis": "REST APIs",
    "restful": "REST APIs",
    "grpc": "gRPC",
    "websocket": "WebSockets",
    "websockets": "WebSockets",

    # Databases & Caching
    "sql": "SQL",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "pgsql": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "cassandra": "Cassandra",
    "elasticsearch": "Elasticsearch",
    "dynamodb": "DynamoDB",
    "prisma": "Prisma",
    "hibernate": "Hibernate",

    # Cloud & DevOps
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "azure": "Azure",
    "terraform": "Terraform",
    "tf": "Terraform",
    "ansible": "Ansible",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "jenkins": "Jenkins",
    "github actions": "GitHub Actions",
    "gitlab ci": "GitLab CI",
    "linux": "Linux",
    "nginx": "Nginx",

    # AI / ML & Data Science
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "keras": "Keras",
    "scikit-learn": "Scikit-Learn",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "nlp": "NLP",
    "llm": "LLMs",
    "llms": "LLMs",
    "langchain": "LangChain",
    "rag": "RAG",
    "opencv": "OpenCV",
    "data science": "Data Science",
    "data engineering": "Data Engineering",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "kafka": "Kafka",
    "airflow": "Airflow",

    # Tools & Methodologies
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "postman": "Postman",
    "jira": "Jira",
    "agile": "Agile",
    "dsa": "DSA",
    "system design": "System Design",
}

# Known multi-word skills used for space-separated input disambiguation
MULTI_WORD_SKILLS = sorted([
    s for s in CANONICAL_SKILL_MAP.keys() if " " in s
], key=len, reverse=True)

# Intent triggers that signal the user wants to upload a resume
RESUME_INTENT_REGEXES = [
    re.compile(r"\b(can|could|may)\s+i\s+(upload|send|attach|give|share|provide)\b", re.IGNORECASE),
    re.compile(r"\b(upload|send|attach|give|share)\s+(my\s+)?(resume|cv|file|pdf)\b", re.IGNORECASE),
    re.compile(r"\b(here\s+is\s+my|check\s+my|take\s+my)\s+(resume|cv)\b", re.IGNORECASE),
    re.compile(r"\b(resume\s+upload|upload\s+resume|cv\s+upload|upload\s+cv)\b", re.IGNORECASE),
    re.compile(r"^(resume|cv|pdf)$", re.IGNORECASE),
    re.compile(r"\b(kya\s+main\s+resume|resume\s+de\s+sakta)\b", re.IGNORECASE),
]


def is_resume_intent(text: str) -> bool:
    """
    Check if the user input expresses intent to upload a resume.
    Ensures tech keywords (like 'OpenCV', 'C#', etc.) are never falsely intercepted.
    """
    if not text:
        return False
    trimmed = text.strip()
    lowered = trimmed.lower()

    # Never intercept if it's a known technical skill
    if lowered in CANONICAL_SKILL_MAP:
        return False

    return any(p.search(trimmed) for p in RESUME_INTENT_REGEXES)


def validate_and_normalize_skills(raw_input: str | list[str], max_skills: int = 15) -> Tuple[bool, List[str], Optional[str]]:
    """
    Validate, sanitize, and normalize user skills input.
    Guarantees:
      - Rejects sentences, conversational questions, entries ending in '?'
      - Disambiguates space-separated technical skills cleanly
      - Deduplicates and canonicalizes casing
      - Enforces hard max cap (default 15)
    Returns:
      (is_valid, normalized_skills_list, error_message)
    """
    if not raw_input:
        return False, [], "Please enter at least one technical skill."

    # If input is a string
    if isinstance(raw_input, str):
        text = raw_input.strip()
        if not text:
            return False, [], "Please enter at least one technical skill."

        # 1. Reject questions / conversational sentences
        if text.endswith("?") or " ke liye " in text.lower() or " job hai" in text.lower():
            return False, [], (
                "It looks like you typed a question or message.\n\n"
                "Please list your *technical skills* separated by commas (e.g. React, Node.js, SQL)."
            )

        # 2. Check if text has standard delimiters: comma, semicolon, newline
        has_delimiter = any(d in text for d in [",", ";", "\n"])

        tokens: list[str] = []
        if has_delimiter:
            # Split by delimiters
            tokens = [t.strip() for t in re.split(r"[,;\n]+", text) if t.strip()]
        else:
            # Check for space-separated input (e.g. 'python sql react' vs 'machine learning')
            temp_text = text.lower()
            found_multi: list[str] = []
            for mw in MULTI_WORD_SKILLS:
                pattern = r"\b" + re.escape(mw) + r"\b"
                if re.search(pattern, temp_text):
                    found_multi.append(mw)
                    temp_text = re.sub(pattern, " ", temp_text)

            single_tokens = [w for w in temp_text.split() if w.strip()]
            all_tokens = single_tokens + found_multi

            # Check if all tokens match known tech skills
            all_known = len(all_tokens) > 0 and all(tok in CANONICAL_SKILL_MAP for tok in all_tokens)

            if all_known:
                tokens = all_tokens
            else:
                # If single token under 30 chars and not a sentence, treat as single skill
                words = text.split()
                if len(words) <= 3 and len(text) <= 30:
                    tokens = [text]
                else:
                    return False, [], (
                        "Please separate your skills with *commas* (e.g. React, Node.js, AWS)."
                    )
    else:
        tokens = [str(s).strip() for s in raw_input if str(s).strip()]

    # Validate each token
    cleaned_skills: list[str] = []
    seen = set()

    for token in tokens:
        # Check token sanity
        if token.endswith("?") or len(token) > 40:
            continue
        if len(token.split()) > 4:
            continue

        token_lower = token.lower()
        if is_resume_intent(token):
            continue

        # Canonical normalization
        canonical = CANONICAL_SKILL_MAP.get(token_lower)
        if not canonical:
            # Format nicely if not in predefined map
            canonical = token.title() if len(token) > 3 else token.upper()

        if canonical.lower() not in seen:
            seen.add(canonical.lower())
            cleaned_skills.append(canonical)

    if not cleaned_skills:
        return False, [], (
            "We couldn't recognize valid skills in your message.\n\n"
            "Please list your technical skills separated by commas (e.g. React, Python, PostgreSQL)."
        )

    # Apply hard cap
    capped_skills = cleaned_skills[:max_skills]
    return True, capped_skills, None
