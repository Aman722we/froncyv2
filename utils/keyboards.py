"""
Reusable InlineKeyboardMarkup builders for all bot flows.
Matches the UX Design document exactly.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
    "⚡ Frameworks": ["React", "Next.js", "Vue", "Angular", "Svelte", "React Native"],
    "🎨 Styling & UI": ["Tailwind", "SCSS", "Figma", "Framer", "Bootstrap"],
    "⚙️ Tools & DevOps": ["Git", "GitHub", "Node.js", "GraphQL", "CI/CD", "Docker"]
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
            # 2 columns per row looks cleaner with long skill names
            if len(row) == 2:
                buttons.append(row)
                row = []
                
        if row:
            buttons.append(row)

    buttons.append([
        InlineKeyboardButton("✅ Done — Save my skills", callback_data="skills_done")
    ])

    return InlineKeyboardMarkup(buttons)


def experience_keyboard(prefix: str = "exp_") -> InlineKeyboardMarkup:
    """Step 2.5: Years of Experience."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎓 Fresher (0 yrs)", callback_data=f"{prefix}0"),
            InlineKeyboardButton("🌱 1 Year", callback_data=f"{prefix}1"),
        ],
        [
            InlineKeyboardButton("🚀 2 Years", callback_data=f"{prefix}2"),
            InlineKeyboardButton("⚡ 3-5 Years", callback_data=f"{prefix}3_5"),
        ],
        [
            InlineKeyboardButton("🔥 5+ Years", callback_data=f"{prefix}5_plus"),
        ]
    ])


def location_keyboard() -> InlineKeyboardMarkup:
    """Step 3: Location preference."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌏 Remote Only", callback_data="loc_remote"),
            InlineKeyboardButton("🇮🇳 India Only", callback_data="loc_india"),
            InlineKeyboardButton("🌐 Both", callback_data="loc_both"),
        ]
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
            InlineKeyboardButton("💾 Saved Jobs", callback_data="menu_saved"),
        ],
        [
            InlineKeyboardButton("📋 My Applications", callback_data="tracker"),
            InlineKeyboardButton("✍️ Cover Letter", callback_data="menu_coverletter"),
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
    else:
        buttons.append([
            InlineKeyboardButton("📄 Resume", callback_data="menu_resume"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
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
    """Apply + Save buttons for each job in the listing, with pagination."""
    buttons = []

    # Apply buttons row
    apply_row = []
    save_row = []
    
    # Render jobs 1 through 5 relative to their spot on the page
    for i, job in enumerate(jobs[:5], 1):
        num = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][i - 1]
        
        is_manual = job.get("is_manual", False)
        prefix = "manual" if is_manual else "job"
        
        apply_row.append(
            InlineKeyboardButton(f"{num} Apply", callback_data=f"{prefix}_view_{job['id']}")
        )
        
        if is_manual:
            save_row.append(
                InlineKeyboardButton(f"💾 Save #{i}", callback_data=f"manual_job_save_{job['id']}")
            )
        else:
            save_row.append(
                InlineKeyboardButton(f"💾 Save #{i}", callback_data=f"job_save_{job['id']}")
            )
            
        if len(apply_row) == 3:
            buttons.append(apply_row)
            buttons.append(save_row)
            apply_row = []
            save_row = []

    if apply_row:
        buttons.append(apply_row)
    if save_row:
        buttons.append(save_row)

    # Pagination controls
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("◀️ Previous", callback_data=f"jobs_page_{page - 1}"))
        
    if (page * 5) < total_count:
        if plan == "free":
            # Free users hit the upscale wall
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

    buttons.append([
        InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")
    ])

    return InlineKeyboardMarkup(buttons)


def job_detail_keyboard(job: dict, plan: str, score: int = -1, from_saved: bool = False) -> InlineKeyboardMarkup:
    """Actions for a single job detail view."""
    is_manual = job.get("is_manual", False)
    prefix = "manual" if is_manual else "job"
    cl_prefix = "manual_cl" if is_manual else "cl"
    ats_prefix = "manual_ats" if is_manual else "ats"

    top_row = [
        InlineKeyboardButton("✍️ Cover Letter", callback_data=f"{cl_prefix}_generate_{job['id']}"),
    ]
    if is_manual:
        top_row.append(InlineKeyboardButton("💾 Save", callback_data=f"manual_job_save_{job['id']}"))
    else:
        top_row.append(InlineKeyboardButton("💾 Save", callback_data=f"job_save_{job['id']}"))

    buttons = [
        top_row,
        [
            InlineKeyboardButton("✅ Mark as Applied", callback_data=f"applied_{job['id']}"),
            InlineKeyboardButton("🔗 Open Link", url=job["url"]),
        ]
    ]

    if plan in ("pro", "trial"):
        buttons.append([
            InlineKeyboardButton("📊 ATS Analyze This Job", callback_data=f"{ats_prefix}_job_{job['id']}"),
        ])
    elif score >= 0:
        if score >= 70:
            buttons.insert(0, [InlineKeyboardButton("🔍 Unlock Match Breakdown → Go Pro", callback_data="menu_upgrade")])
        elif score < 70:
            buttons.insert(0, [InlineKeyboardButton("🔍 See What's Missing → Go Pro", callback_data="menu_upgrade")])

    if from_saved:
        buttons.append([
            InlineKeyboardButton("🔙 Back to Saved Jobs", callback_data="menu_saved")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🔙 Back to Jobs", callback_data="menu_jobs")
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
            InlineKeyboardButton("🧠 Edit Experience", callback_data="settings_experience"),
        ],
        [
            InlineKeyboardButton("🎓 Edit Batch Year", callback_data="settings_batch"),
            InlineKeyboardButton("📍 Change Location", callback_data="settings_location"),
        ],
        [
            InlineKeyboardButton("⏰ Alert Time", callback_data="settings_alert_time"),
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
