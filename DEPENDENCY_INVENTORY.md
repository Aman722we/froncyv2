# Dependency & Licensing Inventory

This document outlines the provenance, licensing, and dependencies for the **Froncy Bot / Applixy** repository to ensure full compliance for data procurement, AI training, and enterprise review.

## 1. Code Provenance
* **Authorship:** 100% proprietary code developed by the original repository owner (Shubham Verma).
* **AI Assistance:** Code was developed with standard AI-assistance tools (Claude/Gemini).
* **Copyleft Exclusion:** **No** source code was copy-pasted from GPL, AGPL, or other restrictive open-source repositories. The core logic, routing, matching algorithms, and system architecture are entirely original.

## 2. External APIs & Services
The software integrates with the following external services via their official SDKs or REST APIs. No proprietary code from these platforms is included in the repository:
* **Telegram Bot API:** Messaging, Webhooks, Long-Polling, and Inline Keyboard UI.
* **NVIDIA NIM / OpenAI / Gemini API:** LLM inference (Llama-3.1 70B & 8B, OpenAI client) for ATS parsing, job metadata extraction, and viral LinkedIn post generation.
* **Supabase / PostgreSQL:** Cloud database hosting with connection pooling (`asyncpg`).
* **Railway:** Cloud container execution, automated buildpacks, and deployment platform.
* **Razorpay:** Payment processing, Pro subscriptions, and webhook events.
* **Public ATS Feeds (Greenhouse, Lever, Ashby):** Direct public REST endpoints for automated career page monitoring across 525+ tech companies.

## 3. Backend Dependencies (Python)
All backend dependencies are imported via `pip` and tracked in `requirements.txt`. None are modified or embedded directly into the source code.

| Package | Purpose | License Type |
|---|---|---|
| `python-telegram-bot` (v21) | Telegram API Wrapper & Async Event Handlers | LGPL-3.0 |
| `fastapi` | Webhook & Click-Tracking Redirect HTTP Server | MIT |
| `uvicorn` | Production ASGI Server | BSD |
| `asyncpg` | High-performance PostgreSQL Connection Pooling | Apache 2.0 |
| `openai` / `httpx` | Async HTTP Client & OpenAI-compatible LLM Client | MIT / BSD |
| `feedparser` | RSS / XML Feed Ingestion | BSD |
| `pymupdf` (fitz) | PDF Text & Structure Extraction | AGPL-3.0 / Commercial |
| `pymupdf4llm` | Markdown Extraction from PDF Resumes | AGPL-3.0 / Commercial |
| `playwright` | Headless Web Automation & Verification | Apache 2.0 |
| `apscheduler` | Cron & Interval Background Job Scheduling | MIT |
| `python-dateutil` | Timezone & ISO Timestamp Arithmetic | Apache 2.0 / BSD |
| `razorpay` | Payment Gateway Integration SDK | MIT |
| `python-dotenv` | Environment Variable Management | BSD |
| `pydantic` / `pydantic-settings` | Schema Validation & Settings Management | MIT |
| `loguru` | Structured Asynchronous Logging | MIT |
| `jinja2` | Resume & Template Rendering Engine | BSD |
| `scikit-learn` | NLP & TF-IDF Cosine Similarity Computation | BSD |

*(Note: `pymupdf` is utilized strictly as an external library for PDF text extraction. No PyMuPDF source code is included or modified in this repository).*

## 4. Frontend Dependencies (Next.js / TypeScript)
Located in the `applixy-web` directory. All frontend packages are highly permissive standard web libraries.

| Package | Purpose | License Type |
|---|---|---|
| `next` (v16.2.4) | React Production Framework | MIT |
| `react` / `react-dom` (v19.2.4) | Core UI Library | MIT |
| `tailwindcss` (v4) | Utility-first CSS Engine | MIT |
| `framer-motion` | Smooth Animations & Transitions | MIT |
| `lucide-react` | Modern SVG Icon Library | ISC |
| `@hello-pangea/dnd` | Accessible Drag-and-Drop Primitives | MIT |
| `pdf-parse` / `pdf2json` | Client-Side Resume Preview & Text Extraction | MIT |
| `typescript` (v5) | Static Type Checking | Apache 2.0 |

## 5. Assets & Datasets
* **Fonts:** Standard Google Fonts (Open Font License).
* **Images/Logos:** Custom vectors/images owned by the repository author (`Applixy_logo.png`, `Froncy_banner.png`).
* **Datasets:** No proprietary third-party datasets were embedded or utilized in the repository. All AI inferences are zero-shot or few-shot using standard API calls. All job records are aggregated live from public company career pages.
