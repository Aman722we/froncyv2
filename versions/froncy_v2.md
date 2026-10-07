# Froncy V2 — Career Page Jobs MVP

## Context

We are changing the direction of Froncy.

The current Froncy product focuses mainly on discovering frontend/fresher jobs from existing job sources. From conversations with users/interview candidates, we found a recurring problem:

Users do not simply want "more jobs."

They want:

1. Jobs with less applicant competition.
2. Jobs that were posted very recently.
3. Jobs that may not yet have appeared on major job boards such as LinkedIn or Naukri.
4. A way to discover relevant opportunities within minutes or hours of the company posting them.

A major source of these opportunities is the company's own careers page.

Many companies publish jobs through an Applicant Tracking System (ATS). The public careers page is often powered by platforms such as:

* Greenhouse
* Lever
* Ashby

These platforms expose public job-posting data that can be consumed without using the companies' private ATS credentials.

For the MVP, we are NOT trying to build a universal job scraper.

We are testing a much narrower hypothesis:

> "If Froncy continuously monitors a small, curated list of companies' public career pages, it can discover relevant jobs very quickly and deliver them to matched candidates before the jobs become widely distributed."

The purpose of this implementation is to validate that hypothesis with the smallest practical engineering effort.

---

# VERY IMPORTANT MVP PRINCIPLES

Do not overengineer this.

Do not build a generic web crawler.

Do not build 500 custom scrapers.

Do not build employer integrations.

Do not build an application-submission system.

Do not scrape LinkedIn.

Do not scrape Naukri.

Do not use private/authenticated Greenhouse, Lever, or Ashby APIs.

Do not introduce a new complicated job architecture if the existing Froncy code already has a job model, ingestion pipeline, matching system, Telegram notification system, or admin system.

First inspect the existing Froncy codebase and reuse the existing architecture wherever possible.

The objective is a working experiment, not a production-scale platform.

---

# WHAT WE ARE BUILDING

Add a new source called:

`Career Page`

The source providers for this MVP are:

* Greenhouse
* Lever
* Ashby

An admin manually adds companies that Froncy should monitor.

Example:

```text
Company: Example Startup
ATS: Greenhouse
Board Token: example
Careers URL: https://boards.greenhouse.io/example
Active: true
```

The backend periodically fetches the company's public jobs.

When a job appears for the first time:

1. Detect it.
2. Normalize it into Froncy's existing job format.
3. Deduplicate it against existing jobs.
4. Store its source information.
5. Record when Froncy first detected it.
6. Run the existing Froncy relevance/matching pipeline.
7. Send it through the existing notification mechanism where appropriate.
8. Display it in the existing jobs experience.

The user should not care whether the job came from Greenhouse, Lever, or Ashby.

That complexity should remain internal.

---

# WHY THESE ATS SOURCES

## Greenhouse

Greenhouse provides a public Job Board API.

Its public GET endpoints do not require authentication.

The main endpoint is:

`GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs`

The API also supports:

`?content=true`

to retrieve the full job description and additional information.

Greenhouse job records include fields such as:

* id
* title
* updated_at
* location
* absolute_url
* content
* departments
* offices

Greenhouse also provides a job-specific endpoint:

`GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}`

Do not implement application submission. We only need public job reading.

Official documentation:

https://docs.greenhouse.io/job-board.html

---

# Lever

Lever provides a public Postings API for published job postings.

For a company/site slug, the public postings endpoint is:

`GET https://api.lever.co/v0/postings/{site}?mode=json`

Example:

`https://api.lever.co/v0/postings/examplecompany?mode=json`

The public postings data can contain:

* id
* text/title
* categories
* description
* location
* commitment
* hosted URL
* apply URL
* created/posting timestamp
* salary information when supplied

Do not use Lever's authenticated private API.

Do not store API keys.

The public Postings API is the only thing needed for this MVP.

Official documentation/reference:

https://hire.lever.co/developer/support

and Lever's public postings documentation:

https://github.com/lever/postings-api

---

# Ashby

Ashby provides a public Job Postings API.

Endpoint:

`GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true`

Example:

`https://api.ashbyhq.com/posting-api/job-board/examplecompany?includeCompensation=true`

The response contains job data including:

* title
* location
* secondaryLocations
* department
* team
* isRemote
* workplaceType
* descriptionHtml
* descriptionPlain
* publishedAt
* employmentType
* jobUrl
* applyUrl
* compensation when available

Only use the public job-posting endpoint.

Do not use Ashby's authenticated API.

Do not store API credentials.

Official documentation:

https://developers.ashbyhq.com/docs/public-job-posting-api

---

# IMPORTANT: JOB FRESHNESS

One of the most important parts of this experiment is freshness.

Do NOT pretend that we know the exact company publication time in every case.

Different ATS providers expose different timestamp fields.

We need two separate concepts:

### `published_at`

The timestamp supplied by the ATS when available.

Examples:

* Greenhouse may expose publication/update information.
* Lever provides a posting timestamp in its public postings feed.
* Ashby exposes `publishedAt`.

### `first_seen_at`

The exact timestamp when Froncy first observed the job.

This must ALWAYS be stored.

Example:

```text
published_at: 2026-10-01T08:20:00Z
first_seen_at: 2026-10-01T08:27:15Z
```

This distinction is important.

If an ATS does not provide a reliable publication timestamp, do NOT fabricate one.

Use:

`first_seen_at`

as the Froncy freshness signal.

For the MVP, a job can display:

`Detected 7 minutes ago`

based on `first_seen_at`.

---

# COMPANY SOURCE MODEL

Add the smallest possible source configuration model.

Suggested structure:

```text
CareerSource
--------------------
id
company_name
company_logo_url (optional)
ats_provider
board_identifier
careers_url
active
last_checked_at
last_successful_check_at
last_error
created_at
updated_at
```

Where:

`ats_provider`

can be:

```text
GREENHOUSE
LEVER
ASHBY
```

And:

`board_identifier`

means:

Greenhouse:
`board_token`

Lever:
`site`

Ashby:
`JOB_BOARD_NAME`

Do not attempt automatic discovery of these identifiers in this MVP.

The admin enters them manually.

---

# JOB MODEL CHANGES

Inspect the current job model first.

If there is already an existing normalized Job entity, reuse it.

Do NOT create a second independent CareerJob system unless the current architecture absolutely requires it.

Add only the metadata needed to identify source and freshness.

Suggested fields, adapted to the existing schema:

```text
source_type
source_provider
source_company_id
source_external_id
source_url
apply_url
published_at
first_seen_at
```

Possible values:

```text
source_type = CAREER_PAGE

source_provider =
GREENHOUSE
LEVER
ASHBY
```

The important unique identity is:

```text
source_provider + source_external_id + company/source
```

Use the canonical job/application URL as an additional deduplication safeguard.

---

# DEDUPLICATION

This is important because the same job may already exist in Froncy from another source.

For example:

```text
Career page:
Frontend Engineer

LinkedIn:
Frontend Engineer

Froncy Career Page:
Frontend Engineer
```

Do not create three unrelated job records.

Use the existing Froncy deduplication system if one already exists.

If the existing system is insufficient, add a lightweight normalized dedupe layer.

The same job should preferably map to one canonical job record with multiple source records/metadata.

For MVP, at minimum prevent duplicate notifications.

Example:

```text
same company
same/similar title
same canonical application URL
```

should be treated as the same job.

Do not spend significant time building sophisticated AI deduplication.

Simple deterministic matching is enough for the experiment.

---

# FETCHING ARCHITECTURE

Create a provider abstraction.

Something conceptually like:

```ts
interface CareerProvider {
  fetchJobs(source: CareerSource): Promise<NormalizedCareerJob[]>
}
```

Then:

```text
GreenhouseProvider
LeverProvider
AshbyProvider
```

Each provider is responsible only for converting the provider response into Froncy's normalized format.

Example normalized object:

```ts
{
  externalId,
  title,
  description,
  location,
  employmentType,
  department,
  workplaceType,
  salary,
  publishedAt,
  jobUrl,
  applyUrl,
  sourceProvider,
  sourceCompany
}
```

Keep provider-specific parsing isolated.

This will allow us to add more ATS providers later without rewriting the job pipeline.

---

# POLLING

For the MVP, use polling.

Do not build webhooks.

Do not build real-time event infrastructure.

Run the career-page sync approximately every:

`10–15 minutes`

The exact schedule should use the existing cron/background-job infrastructure if Froncy already has one.

If the application already has a scheduled task system, reuse it.

The sync process should:

```text
Get active CareerSources
        ↓
Fetch jobs from each source
        ↓
Normalize response
        ↓
Compare against existing records
        ↓
Identify newly discovered jobs
        ↓
Store/update jobs
        ↓
Run existing matching pipeline
        ↓
Send notifications
```

For a tiny MVP, even a manually triggered "Sync Now" button plus a scheduled job is acceptable.

---

# ERROR HANDLING

One company's career page failing should NOT stop the whole sync.

Example:

```text
Company A → success
Company B → success
Company C → 404
Company D → timeout
Company E → success
```

The system should continue processing.

Record:

```text
last_checked_at
last_successful_check_at
last_error
```

for each CareerSource.

Avoid endless retry loops.

A failed source should simply be retried on the next scheduled cycle.

---

# ADMIN UI

Create a very simple internal admin page.

Possible route:

`/admin/career-sources`

The exact route should match the existing admin architecture.

The page should allow me to:

### Add company

Fields:

```text
Company name
ATS provider
Board identifier
Careers URL
Active
```

### View company sources

Show:

```text
Company
ATS
Active
Last checked
Last successful sync
Jobs found
Last error
```

### Actions

Each source should have:

`Sync Now`

This is extremely useful during testing.

The admin page does NOT need beautiful design.

Functionality is more important.

---

# CAREER PAGE JOB DISPLAY

Use the existing Froncy job UI.

Do not build a completely separate jobs UI.

Add a subtle source indicator.

For example:

```text
Career Page
```

and preferably:

```text
Detected 12 minutes ago
```

Potential future wording:

```text
Direct from company career page
```

Do NOT claim:

```text
No competition
```

because Froncy cannot know the number of applicants.

Do NOT claim:

```text
Only available on Froncy
```

unless that has actually been verified.

For the MVP, use factual labels such as:

`Career Page`

`Direct from company careers`

`Detected 12 minutes ago`

---

# MATCHING

This feature exists to improve the quality and speed of Froncy's existing job feed.

Do NOT build a new matching algorithm.

Use the existing Froncy matching engine.

Career-page jobs should pass through the exact same:

* skill matching
* experience matching
* location matching
* user preference matching
* score calculation
* Telegram notification logic

that normal Froncy jobs use.

This is important because the experiment should measure:

> "Does early career-page discovery produce useful matches?"

rather than:

> "Can we build an entirely new recommendation system?"

---

# TELEGRAM / NOTIFICATION BEHAVIOR

Reuse the existing notification pipeline.

When a new career-page job is discovered:

```text
new job
   ↓
dedupe
   ↓
matching
   ↓
eligible users
   ↓
existing notification system
```

Do not create a second notification mechanism.

The notification can include one extra piece of metadata:

```text
⚡ Career Page
Detected 8 minutes ago
```

Example conceptual notification:

```text
🚨 NEW JOB

Frontend Developer
Company XYZ

Remote
0–2 YOE
React · Next.js · TypeScript

94% match

⚡ Detected 8 minutes ago
🔗 Direct company career page
```

Adapt this to the existing Froncy notification format rather than redesigning all Telegram messages.

---

# WHAT NOT TO BUILD

For this version, explicitly DO NOT build:

* automatic discovery of company career pages
* crawling the entire internet
* LinkedIn scraping
* Naukri scraping
* browser automation for every company
* automatic ATS detection
* custom scraper for every company
* application submission
* resume auto-fill
* employer dashboard
* employer accounts
* company partnerships
* applicant-count estimation
* "competition score"
* AI-generated job summaries unless already available in Froncy
* AI deduplication unless already available
* complex analytics dashboards
* a new frontend design system

Those are future possibilities, not MVP requirements.

---

# TEST MODE / DEBUGGING

Add a way to test one source manually.

For example:

`Sync Now`

After synchronization, return a useful result:

```text
Company: Example Startup
Provider: Greenhouse

Fetched: 27 jobs
New: 2
Updated: 3
Duplicates: 22
Errors: 0
```

For development, log enough information to debug provider parsing.

Do not log sensitive user data.

---

# IMPORTANT SAFETY / DATA RULES

Only consume publicly available published job information.

Do not bypass authentication.

Do not access private/unlisted/draft jobs.

Do not attempt to access internal company ATS data.

Do not store ATS credentials.

Do not submit applications on behalf of users in this MVP.

The purpose is public job discovery and linking users to the original application page.

---

# MANUAL BOOTSTRAP WORKFLOW

The MVP depends on manually finding companies.

I will do this part manually.

I need to find approximately:

`15–20 companies`

that are relevant to Froncy's current users.

The target should NOT simply be famous companies.

Prefer startups/technology companies that:

* hire frontend developers
* hire software engineers
* hire freshers / entry-level / 0–2 YOE candidates where possible
* hire in India or remotely
* actively maintain their careers page
* have multiple current engineering openings
* appear to post jobs regularly
* ideally use Greenhouse, Lever, or Ashby

I should intentionally include companies that are NOT already heavily dependent on LinkedIn for every hiring post.

---

# MANUAL COMPANY RESEARCH

For each company, I should record:

```text
Company name
Company website
Careers page URL
ATS provider
ATS board identifier
Relevant current roles
India/remote relevance
Notes
```

Example:

```text
Company: Example Startup
Website: https://example.com
Careers: https://boards.greenhouse.io/example
ATS: Greenhouse
Board token: example
Relevant: Frontend Engineer, Software Engineer
India: Yes
Remote: Yes
```

For Greenhouse:

If the careers page is:

`https://boards.greenhouse.io/companyname`

then the board token is generally:

`companyname`

For Lever:

If the careers page is:

`https://jobs.lever.co/companyname`

then the site slug is:

`companyname`

For Ashby:

If the jobs page is:

`https://jobs.ashbyhq.com/companyname`

then the job board name is generally:

`companyname`

Do not assume these identifiers blindly.

I will verify that the public endpoint actually works before adding the company.

---

# HOW I SHOULD START THE EXPERIMENT

I should NOT immediately search for 500 companies.

Start with:

### Round 1

3–5 companies.

Ideally test all three providers if practical:

```text
1–2 Greenhouse
1–2 Lever
1–2 Ashby
```

The exact distribution can be adjusted based on which relevant companies I find.

Add them to the admin panel.

Run manual sync.

Confirm jobs appear correctly.

Confirm matching works.

Confirm Telegram notifications work.

Confirm deduplication works.

Then leave the scheduler running.

---

# ROUND 2

If Round 1 works, expand to roughly:

`15–20 companies`

Do not expand to 500 yet.

Let the system run for at least several days of normal hiring activity.

Observe:

```text
companies monitored
jobs fetched
new jobs detected
jobs per company
frontend/software jobs detected
relevant jobs matched to users
notifications sent
clicks
applications
```

The most important business signal is not how many jobs were scraped.

The important signal is:

> Do users actually find these career-page jobs useful enough to click and apply?

---

# FRESHNESS METRICS

Store enough information to calculate:

```text
first_seen_at
published_at (when available)
```

Then we can later measure:

```text
detection delay
```

For example:

```text
published_at: 10:02
first_seen_at: 10:11
detection delay: 9 minutes
```

If `published_at` is unavailable/reliable, only show:

```text
Detected at: 10:11
```

and calculate freshness from `first_seen_at`.

Do not invent data.

---

# FUTURE DIRECTION — DO NOT IMPLEMENT YET

If the experiment works, the next evolution could be:

```text
15 companies
   ↓
50 companies
   ↓
100 companies
   ↓
500+ companies
```

At that point we can build:

* automatic ATS detection
* company discovery
* better crawling
* more ATS providers
* career-page monitoring at scale
* smarter deduplication
* detection of jobs before major boards
* historical company posting behavior
* company-specific hiring frequency
* source freshness analytics
* ranking based on freshness
* "Froncy First" labeling

But none of those should be implemented now.

---

# ACCEPTANCE CRITERIA

The feature is complete when I can do all of the following:

### 1. Add a company manually

Example:

```text
Example Startup
Greenhouse
example
```

### 2. Click Sync Now

The backend successfully calls the correct public endpoint.

### 3. Fetch jobs

Jobs are normalized into the existing Froncy job system.

### 4. Detect new jobs

A job that was not previously present is identified as new.

### 5. Store first-seen time

Every newly discovered job has:

`first_seen_at`

### 6. Avoid duplicates

Running Sync Now repeatedly must not create duplicate jobs or duplicate notifications.

### 7. Use existing matching

The existing Froncy matching engine receives the new jobs.

### 8. Notify users

Existing Telegram notification functionality can distribute matching jobs.

### 9. Show source

The UI identifies the job as:

`Career Page`

and can show:

`Detected X minutes ago`

### 10. Handle errors

One broken company source does not break synchronization of the others.

### 11. No API keys required

The entire MVP works using publicly available job-posting endpoints for the supported providers.

---

# IMPLEMENTATION PROCESS

Before changing code:

1. Inspect the current Froncy architecture.
2. Identify the existing Job model.
3. Identify existing job ingestion/import logic.
4. Identify existing deduplication.
5. Identify existing matching logic.
6. Identify existing Telegram notification logic.
7. Identify existing scheduler/background-job infrastructure.
8. Identify existing admin UI.

Then implement the smallest integration possible.

Reuse existing components instead of creating parallel systems.

After implementation:

* run type checks
* run lint
* run existing tests
* manually test Greenhouse
* manually test Lever
* manually test Ashby
* manually test duplicate sync
* manually test new job detection
* manually test notification flow

Do not rewrite unrelated parts of Froncy.

Keep the implementation modular so additional ATS providers can be added later.

The core experiment is:

> **Manually curate a small number of high-quality companies → monitor their public careers feeds every 10–15 minutes → detect fresh jobs → feed them through existing Froncy matching → deliver them quickly to users.**

Build exactly that first.
