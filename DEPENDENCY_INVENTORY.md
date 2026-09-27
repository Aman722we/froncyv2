# Dependency & Licensing Inventory

This document outlines the provenance, licensing, and dependencies for the **Applixy Bot** repository to ensure full compliance for data procurement, AI training, and enterprise review.

## 1. Code Provenance
* **Authorship:** 100% proprietary code developed by the original repository owner (Shubham Verma).
* **AI Assistance:** Code was developed with standard AI-assistance tools (Claude/Gemini).
* **Copyleft Exclusion:** **No** source code was copy-pasted from GPL, AGPL, or other restrictive open-source repositories. The core logic, routing, and system architecture are entirely original.

## 2. External APIs & Services
The software integrates with the following external services via their official SDKs or REST APIs. No proprietary code from these platforms is included in the repository.
* **Telegram Bot API:** Messaging and Webhook delivery.
* **Groq API:** LLM inference (Llama-3 models) for ATS parsing and generation.
* **Supabase:** PostgreSQL database hosting.
* **Razorpay:** Payment processing and subscription webhooks.

## 3. Backend Dependencies (Python)
All backend dependencies are imported via `pip`. None are modified or embedded directly into the source code.

| Package | Purpose | License Type |
|---|---|---|
| `fastapi` | Web Server | MIT |
| `uvicorn` | ASGI Server | BSD |
| `python-telegram-bot` | Telegram API Wrapper | LGPL-3.0 |
| `asyncpg` | Database Driver | Apache 2.0 |
| `apscheduler` | Job Scheduling | MIT |
| `playwright` | Web Automation | Apache 2.0 |
| `scikit-learn` | NLP utilities | BSD |
| `openai` / `httpx` | Groq API standard client | MIT |
| `razorpay` | Payment Gateway | MIT |
| `jinja2` | PDF/LaTeX Templating | BSD |
| `loguru` | Logging | MIT |
| `pymupdf` (fitz) | PDF parsing | AGPL-3.0 / Commercial |

*(Note: `pymupdf` is utilized strictly as an external library for PDF text extraction. No PyMuPDF source code is included or modified in this repository).*

## 4. Frontend Dependencies (Next.js / TypeScript)
Located in the `applixy-web` directory. All frontend packages are highly permissive standard web libraries.

| Package | Purpose | License Type |
|---|---|---|
| `next` (v16) | React Framework | MIT |
| `react` / `react-dom` | UI Library | MIT |
| `tailwindcss` | CSS Framework | MIT |
| `framer-motion` | Animations | MIT |
| `lucide-react` | Icons | ISC |
| `@hello-pangea/dnd` | Drag-and-drop | MIT |
| `pdf-parse` / `pdf2json` | Client-side PDF handling | MIT |

## 5. Assets & Datasets
* **Fonts:** Standard Google Fonts (Open Font License).
* **Images/Logos:** Custom vectors/images owned by the repository author.
* **Datasets:** No proprietary third-party datasets were embedded or utilized in the repository. All AI inferences are zero-shot or few-shot using standard API calls.
