"""
Reusable InlineKeyboardMarkup builders for all bot flows.
Matches the UX Design document exactly.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from urllib.parse import urlparse
from config import settings


# ──────────────────────────────────────────────
# Onboarding
# ──────────────────────────────────────────────

def onboarding_welcome_keyboard() -> InlineKeyboardMarkup:
    """Step 1: What describes you?"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Actively Job Hunting", callback_data="onboard_hunting"),
            InlineKeyboardButton("📚 Just Exploring", callback_data="onboard_exploring"),
        ]
    ])


SKILL_CATEGORIES = {
    "🛠️ Core Front-End": ["HTML", "CSS", "JavaScript", "TypeScript"],
    # FUTURE (multi-role): "⚙️ Core Backend": ["Node.js", "Express", "MongoDB", "PostgreSQL", "MySQL"],
    "⚡ Frameworks": ["React", "Next.js", "Vue", "Angular", "Svelte", "React Native"],
    "🎨 Styling & UI": ["Tailwind", "Bootstrap", "Figma", "Framer"],
    # FUTURE (multi-role): "⚙️ Tools & DevOps": ["Git", "GitHub", "GraphQL", "CI/CD", "Docker"]
}

# Flatten for easy validation
ALL_SKILLS = [skill for category in SKILL_CATEGORIES.values() for skill in category]


def skills_keyboard(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """Step 2: Skill selection grid with categorized checkmarks."""
    selected = selected or []
    buttons = []

    for category_name, skills in SKILL_CATEGORIES.items():
        # Add visual separator / header (non-clickable)
        buttons.append([InlineKeyboardButton(f"── {category_name} ──", callback_data="ignore")])
        
        row = []
        for skill in skills:
            check = "✅ " if skill.lower() in [s.lower() for s in selected] else ""
            row.append(
                InlineKeyboardButton(
                    f"{check}{skill}",
                    callback_data=f"skill_{skill.lower().replace('.', '').replace(' ', '_').replace('/', '_')}",
                )
            )
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

    buttons.append([InlineKeyboardButton("➕ Add your own skills", callback_data="add_custom_skill")])
    
    if selected:
        buttons.append([InlineKeyboardButton("Next ▶️", callback_data="skills_done")])

    return InlineKeyboardMarkup(buttons)


def experience_keyboard(prefix: str = "exp_") -> InlineKeyboardMarkup:
    """Step 2.5: Years of Experience — limited to fresher range (0-1 yr)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Fresher (0 yrs)", callback_data=f"{prefix}0"),
            InlineKeyboardButton("🌱 1 Year", callback_data=f"{prefix}1"),
        ],
        # FUTURE (mid-senior): [
        #     InlineKeyboardButton("🚀 2 Years", callback_data=f"{prefix}2"),
        #     InlineKeyboardButton("🔥 2+ Years", callback_data=f"{prefix}2_plus"),
        # ]
    ])


def location_keyboard() -> InlineKeyboardMarkup:
    """Step 3: Location preference."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Remote Only", callback_data="loc_remote"),
            InlineKeyboardButton("🏢 Onsite Only", callback_data="loc_onsite"),
        ],
        [
            InlineKeyboardButton("🌍 Hybrid Only", callback_data="loc_hybrid"),
            InlineKeyboardButton("🔄 All", callback_data="loc_all"),
        ]
    ])


def role_keyboard(prefix: str = "role_") -> InlineKeyboardMarkup:
    """Role preference selection — frontend only in current niche."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💻 Frontend", callback_data=f"{prefix}frontend"),
            # FUTURE (multi-role): InlineKeyboardButton("⚙️ Backend", callback_data=f"{prefix}backend"),
        ],
        # FUTURE (multi-role): [
        #     InlineKeyboardButton("🚀 Fullstack", callback_data=f"{prefix}fullstack"),
        # ]
    ])


def resume_prompt_keyboard() -> InlineKeyboardMarkup:
    """Step 4: Resume upload prompt."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📎 Upload Resume PDF", callback_data="resume_upload"),
            InlineKeyboardButton("⏭ Skip for now", callback_data="resume_skip"),
        ]
    ])


def onboarding_complete_keyboard() -> InlineKeyboardMarkup:
    """Step 5: Post-onboarding actions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 View Jobs Now", callback_data="menu_jobs"),
            InlineKeyboardButton("📄 Upload Resume", callback_data="resume_upload"),
        ],
        [
            InlineKeyboardButton("✍️ Get Cover Letter", callback_data="menu_coverletter"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
        ],
    ])


# ──────────────────────────────────────────────
# Main Menu
# ──────────────────────────────────────────────

def main_menu_keyboard(plan: str = "free", upgrade_price: int | None = None) -> InlineKeyboardMarkup:
    """Main menu dynamic rendering based on plan. upgrade_price shown on button when free plan."""
    buttons = [
        [
            InlineKeyboardButton("🔍 Browse Jobs", callback_data="menu_jobs"),
            InlineKeyboardButton("📅 Daily Feed", callback_data="menu_daily"),
        ],
        [
            InlineKeyboardButton("💾 Saved Jobs", callback_data="menu_saved"),
            InlineKeyboardButton("📋 My Applications", callback_data="tracker"),
        ],
        [
            InlineKeyboardButton("✍️ Cover Letter", callback_data="menu_coverletter"),
            InlineKeyboardButton("🔗 Submit Job Link", callback_data="submit_job_link_info"),
        ],
    ]
    if plan == "pro":
        buttons.append([
            InlineKeyboardButton("📊 Weekly Summary", callback_data="weekly_summary"),
        ])
        buttons.append([
            InlineKeyboardButton("📄 Resume", callback_data="menu_resume"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
        ])
        # Pro users don't need a referral incentive — they're already subscribed
    else:
        buttons.append([
            InlineKeyboardButton("📄 Resume", callback_data="menu_resume"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
        ])
        buttons.append([
            InlineKeyboardButton("🎁 Refer a Friend — Earn 5 Free Pro Days!", callback_data="menu_refer"),
        ])
        price_label = f"₹{upgrade_price}/mo" if upgrade_price else "Upgrade"
        buttons.append([
            InlineKeyboardButton(f"💎 Go Pro — {price_label}", callback_data="menu_upgrade"),
        ])

    return InlineKeyboardMarkup(buttons)



# ──────────────────────────────────────────────
# Jobs
# ──────────────────────────────────────────────

def job_list_keyboard(jobs: list[dict], plan: str, total_count: int = 0, page: int = 1) -> InlineKeyboardMarkup:
    """Apply buttons for each job in the listing, with pagination and filters."""
    buttons = []

    # Apply buttons row
    apply_row = []
    
    # Render jobs 1 through 5 relative to their spot on the page
    for i, job in enumerate(jobs[:5], 1):
        num = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][i - 1]
        
        is_manual = job.get("is_manual", False)
        prefix = "manual" if is_manual else "job"
        
        apply_row.append(
            InlineKeyboardButton(f"{num} Apply", callback_data=f"{prefix}_view_{job['id']}")
        )
            
        if len(apply_row) == 3:
            buttons.append(apply_row)
            apply_row = []

    if apply_row:
        buttons.append(apply_row)

    # Pagination controls
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"jobs_page_{page - 1}"))
        
    if (page * 5) < total_count:
        if plan == "free" and (page * 5) >= 6:
            # Free users hit the upscale wall after 6 jobs
            buttons.append([
                InlineKeyboardButton(
                    f"🔒 See all {total_count} jobs — Upgrade to Pro",
                    callback_data="menu_upgrade",
                )
            ])
        else:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"jobs_page_{page + 1}"))

    if nav_row:
        buttons.append(nav_row)

    filter_btn = InlineKeyboardButton("⚙️ Filters", callback_data="jobs_filter_menu")
    if plan == "free":
        filter_btn = InlineKeyboardButton("🔒 Filters (Pro)", callback_data="menu_upgrade")

    buttons.append([
        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
        filter_btn,
    ])

    return InlineKeyboardMarkup(buttons)


def daily_feed_keyboard(jobs: list[dict], plan: str) -> InlineKeyboardMarkup:
    """12-job grid for the daily curated feed."""
    buttons = []
    apply_row = []
    
    for i, job in enumerate(jobs[:12], 1):
        is_manual = job.get("is_manual", False)
        prefix = "manual" if is_manual else "job"
        
        apply_row.append(
            InlineKeyboardButton(f"[{i}] Apply", callback_data=f"{prefix}_view_{job['id']}_daily")
        )
            
        if len(apply_row) == 3:
            buttons.append(apply_row)
            apply_row = []

    if apply_row:
        buttons.append(apply_row)

    buttons.append([
        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
    ])

    return InlineKeyboardMarkup(buttons)


def filter_menu_keyboard(filters: dict) -> InlineKeyboardMarkup:
    """Keyboard for selecting job filters."""
    f_exp = filters.get("exp", "any")
    f_time = filters.get("time", "any")
    f_match = filters.get("match", "any")
    f_loc = filters.get("loc", "any")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("── Experience ──", callback_data="ignore")],
        [
            InlineKeyboardButton("✅ 0 YOE" if f_exp == "0" else "0 YOE", callback_data="filter_exp_0"),
            InlineKeyboardButton("✅ 1 YOE" if f_exp == "1" else "1 YOE", callback_data="filter_exp_1"),
            InlineKeyboardButton("✅ 2 YOE" if f_exp == "2" else "2 YOE", callback_data="filter_exp_2"),
        ],
        [
            InlineKeyboardButton("✅ 3+ YOE" if f_exp == "3" else "3+ YOE", callback_data="filter_exp_3"),
            InlineKeyboardButton("✅ Any" if f_exp == "any" else "Any", callback_data="filter_exp_any"),
        ],
        [InlineKeyboardButton("── Location ──", callback_data="ignore")],
        [
            InlineKeyboardButton("✅ Remote" if f_loc == "remote" else "Remote", callback_data="filter_loc_remote"),
            InlineKeyboardButton("✅ Onsite" if f_loc == "onsite" else "Onsite", callback_data="filter_loc_onsite"),
            InlineKeyboardButton("✅ Any" if f_loc == "any" else "Any", callback_data="filter_loc_any"),
        ],
        [InlineKeyboardButton("── Recency ──", callback_data="ignore")],
        [
            InlineKeyboardButton("✅ <24h" if f_time == "1d" else "<24h", callback_data="filter_time_1d"),
            InlineKeyboardButton("✅ <3 Days" if f_time == "3d" else "<3 Days", callback_data="filter_time_3d"),
            InlineKeyboardButton("✅ Any" if f_time == "any" else "Any", callback_data="filter_time_any"),
        ],
        [InlineKeyboardButton("── Match Level ──", callback_data="ignore")],
        [
            InlineKeyboardButton("✅ High (>70%)" if f_match == "high" else "High (>70%)", callback_data="filter_match_high"),
            InlineKeyboardButton("✅ Medium (>40%)" if f_match == "med" else "Medium (>40%)", callback_data="filter_match_med"),
            InlineKeyboardButton("✅ Any" if f_match == "any" else "Any", callback_data="filter_match_any"),
        ],
        [
            InlineKeyboardButton("🗑 Clear", callback_data="filter_clear"),
            InlineKeyboardButton("▶️ Apply Filters", callback_data="menu_jobs_filtered")
        ]
    ])


def job_detail_keyboard(job: dict, plan: str, score: int = -1, from_saved: bool = False, from_daily: bool = False, user_id: int | None = None, apply_smart_locked: bool = False) -> InlineKeyboardMarkup:
    """Actions for a single job detail view.
    Layout:
        Row 1: [🚀 Apply Smart (Complete Kit)]        ← Full Width
        Row 2: [📄 ATS Resume]  [✍️ Cover Letter]
        Row 3: [✅ Mark as Applied]  [⏳ Remind Me]
        Row 4: [🔗 Open Link]  [⬅️ Back]
    """
    is_manual = job.get("is_manual", False)
    prefix = "manual" if is_manual else "job"
    cl_prefix = "manual_cl" if is_manual else "cl"
    ats_prefix = "manual_ats" if is_manual else "ats"
    remind_callback = f"remind_manual_{job['id']}" if is_manual else f"remind_job_{job['id']}"
    applied_cb = f"manual_applied_{job['id']}" if is_manual else f"applied_{job['id']}"

    # Build the apply URL
    raw_url = job.get("url", "https://t.me/FroncyJobsBot")
    webhook_raw = settings.WEBHOOK_URL or ""
    if webhook_raw:
        parsed = urlparse(webhook_raw if webhook_raw.startswith("http") else f"https://{webhook_raw}")
        base = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base = ""
    if base and user_id:
        apply_url = f"{base}/r/{job['id']}?uid={user_id}"
    else:
        apply_url = raw_url

    buttons = []

    # Row 1: Apply Smart — Full Width (only for manual jobs that have HM data)
    # Show for all manual jobs; the handler will check quota and HM availability
    if is_manual:
        if apply_smart_locked:
            buttons.append([
                InlineKeyboardButton("🔒 Apply Smart — Limit Reached (Upgrade)", callback_data="apply_smart_locked"),
            ])
        else:
            buttons.append([
                InlineKeyboardButton("🚀 Apply Smart (Complete Kit)", callback_data=f"apply_smart_{job['id']}"),
            ])
    
    # Row 2: ATS + Cover Letter
    if plan in ("pro", "trial"):
        buttons.append([
            InlineKeyboardButton("📄 ATS Resume", callback_data=f"{ats_prefix}_job_{job['id']}"),
            InlineKeyboardButton("✍️ Cover Letter", callback_data=f"{cl_prefix}_generate_{job['id']}"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🔒 ATS Resume (Pro)", callback_data="menu_upgrade"),
            InlineKeyboardButton("✍️ Cover Letter", callback_data=f"{cl_prefix}_generate_{job['id']}"),
        ])

    # Row 3: Mark as Applied + Remind Me
    buttons.append([
        InlineKeyboardButton("✅ Mark as Applied", callback_data=applied_cb),
        InlineKeyboardButton("⏳ Remind Me", callback_data=remind_callback),
    ])

    # Row 4: Open Link + Back (split)
    if from_saved:
        back_cb = "menu_saved"
        back_label = "⬅️ Back to Saved"
    elif from_daily:
        back_cb = "menu_daily"
        back_label = "⬅️ Back to Feed"
    else:
        back_cb = "menu_jobs"
        back_label = "⬅️ Back to Jobs"

    buttons.append([
        InlineKeyboardButton("🔗 Open Link", url=apply_url),
        InlineKeyboardButton(back_label, callback_data=back_cb),
    ])

    return InlineKeyboardMarkup(buttons)


# ──────────────────────────────────────────────
# Cover Letter
# ──────────────────────────────────────────────

def cover_letter_result_keyboard(job_id: int, is_manual: bool = False) -> InlineKeyboardMarkup:
    """Actions after cover letter is generated."""
    cl_prefix = "manual_cl" if is_manual else "cl"
    back_prefix = "manual_view" if is_manual else "job_view"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Copy Text", callback_data=f"{cl_prefix}_copy_{job_id}"),
            InlineKeyboardButton("🔄 Regenerate", callback_data=f"{cl_prefix}_regen_{job_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Formal", callback_data=f"{cl_prefix}_tone_formal_{job_id}"),
            InlineKeyboardButton("✏️ Friendly", callback_data=f"{cl_prefix}_tone_friendly_{job_id}"),
            InlineKeyboardButton("✏️ Concise", callback_data=f"{cl_prefix}_tone_concise_{job_id}"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Job", callback_data=f"{back_prefix}_{job_id}"),
        ],
    ])


def cover_letter_limit_keyboard() -> InlineKeyboardMarkup:
    """Shown when free user hits daily cover letter limit."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 Upgrade to Pro", callback_data="upgrade_pro"),
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_menu"),
        ],
    ])


# ──────────────────────────────────────────────
# Auto-Apply
# ──────────────────────────────────────────────




# ──────────────────────────────────────────────
# Resume
# ──────────────────────────────────────────────

def resume_keyboard(has_resume: bool, plan: str = "free") -> InlineKeyboardMarkup:
    """Resume management actions."""
    if has_resume:
        buttons = [
            [
                InlineKeyboardButton("🔄 Replace", callback_data="resume_upload"),
                InlineKeyboardButton("📊 ATS Analysis", callback_data="ats_analyze"),
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="back_menu")
            ]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📎 Upload Resume PDF", callback_data="resume_upload")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_menu")],
        ]
    return InlineKeyboardMarkup(buttons)


# ──────────────────────────────────────────────
# Upgrade / Plans
# ──────────────────────────────────────────────

def upgrade_keyboard() -> InlineKeyboardMarkup:
    """Fallback subscription plan selection (used if dynamic handler fails)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 Pay via UPI/Card", callback_data="upgrade_pro"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
        ],
    ])


# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────

def settings_keyboard(is_active_pro: bool = False) -> InlineKeyboardMarkup:
    """Settings menu."""
    buttons = [
        [
            InlineKeyboardButton("🏷 Edit Skills", callback_data="settings_skills"),
            # FUTURE (multi-role): InlineKeyboardButton("💼 Edit Role", callback_data="settings_role"),
        ],
        [
            InlineKeyboardButton("🧠 Edit Experience", callback_data="settings_experience"),
            InlineKeyboardButton("🎓 Edit Batch Year", callback_data="settings_batch"),
        ],
        [
            InlineKeyboardButton("📍 Change Location", callback_data="settings_location"),
            InlineKeyboardButton("⏰ Alert Time", callback_data="settings_alert_time"),
        ],
        [
            InlineKeyboardButton("📊 My Status", callback_data="settings_status"),
        ],
        [
            InlineKeyboardButton("🗑 Delete Account", callback_data="settings_delete"),
        ],
    ]

    if is_active_pro:
        buttons.insert(-1, [
            InlineKeyboardButton("🛑 Cancel Subscription", callback_data="settings_cancel_sub"),
        ])

    buttons.append([
        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu"),
    ])

    return InlineKeyboardMarkup(buttons)


def confirm_delete_keyboard() -> InlineKeyboardMarkup:
    """Account deletion confirmation."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Yes, Delete Everything", callback_data="confirm_delete_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="menu_settings"),
        ]
    ])


def saved_jobs_keyboard(jobs: list[dict]) -> InlineKeyboardMarkup:
    """Saved jobs list with remove options."""
    buttons = []
    for i, job in enumerate(jobs[:10], 1):
        is_manual = job.get("is_manual", False)
        prefix = "manual" if is_manual else "job"
        unsave_callback = f"manual_job_unsave_{job['id']}" if is_manual else f"job_unsave_{job['id']}"
        
        buttons.append([
            InlineKeyboardButton(
                f"{i}. {job['title'][:30]} — {job.get('company', 'N/A')}",
                callback_data=f"{prefix}_view_{job['id']}_saved",
            ),
            InlineKeyboardButton("🗑", callback_data=unsave_callback),
        ])

    buttons.append([
        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
    ])

    return InlineKeyboardMarkup(buttons)
