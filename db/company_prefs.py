"""
Company Preferences & Directory Service (RFC-004)
High-performance company follow, employer mute, hierarchy expansion, and bundle operations.
"""
from datetime import datetime, timezone
from loguru import logger
from db.connection import get_pool


def build_children_hierarchy(companies: list[dict]) -> dict[int, set[int]]:
    """
    Builds a recursive mapping: parent_id -> set of all descendant child company IDs.
    Enforces maximum depth 3 and uses a visited set to strictly prevent infinite cycles.
    """
    direct_children: dict[int, set[int]] = {}
    for c in companies:
        cid = c["id"]
        pid = c.get("parent_id")
        if pid and pid != cid:
            direct_children.setdefault(pid, set()).add(cid)

    descendants: dict[int, set[int]] = {}

    def get_descendants(parent: int, depth: int, visited: set[int]) -> set[int]:
        if depth > 3 or parent in visited:
            return set()
        visited.add(parent)
        res = set()
        for child in direct_children.get(parent, set()):
            res.add(child)
            res.update(get_descendants(child, depth + 1, visited.copy()))
        return res

    for pid in direct_children:
        descendants[pid] = get_descendants(pid, depth=1, visited=set())

    return descendants


async def get_user_company_prefs(telegram_id: int, is_pro: bool = False) -> tuple[set[int], set[int]]:
    """
    Loads active company preferences for a single user:
    Returns (expanded_mutes, active_follows).
    - expanded_mutes: direct mutes plus all child subsidiaries (max depth 3). Unlimited for all users.
    - active_follows: Pro: unlimited; Free: deterministic top 5 by (created_at ASC, company_id ASC).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Load all companies to build hierarchy
        comp_rows = await conn.fetch("SELECT id, parent_id FROM companies WHERE is_active = TRUE")
        children_map = build_children_hierarchy([dict(r) for r in comp_rows])

        # Load direct mutes (unlimited for all users)
        mute_rows = await conn.fetch(
            "SELECT company_id FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'mute'",
            telegram_id
        )
        direct_mutes = {r["company_id"] for r in mute_rows}
        expanded_mutes = set(direct_mutes)
        for mid in direct_mutes:
            expanded_mutes.update(children_map.get(mid, set()))

        # Load active follows (Pro: unlimited, Free: 5)
        if is_pro:
            follow_rows = await conn.fetch(
                """
                SELECT company_id
                FROM user_company_prefs
                WHERE telegram_id = $1 AND pref_type = 'follow'
                ORDER BY created_at ASC, company_id ASC
                """,
                telegram_id
            )
        else:
            follow_rows = await conn.fetch(
                """
                SELECT company_id
                FROM user_company_prefs
                WHERE telegram_id = $1 AND pref_type = 'follow'
                ORDER BY created_at ASC, company_id ASC
                LIMIT 5
                """,
                telegram_id
            )
        active_follows = {r["company_id"] for r in follow_rows}

    return expanded_mutes, active_follows


async def load_all_active_company_prefs() -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    """
    Single-query bulk loader for crawl sync runs (career_sync and scheduler).
    Returns (all_user_mutes, all_user_follows) mapping telegram_id -> set of company_ids.
    """
    pool = get_pool()
    all_user_mutes: dict[int, set[int]] = {}
    all_user_follows: dict[int, set[int]] = {}

    async with pool.acquire() as conn:
        # 1. Build hierarchy
        comp_rows = await conn.fetch("SELECT id, parent_id FROM companies WHERE is_active = TRUE")
        children_map = build_children_hierarchy([dict(r) for r in comp_rows])

        # 2. Get pro users set
        pro_rows = await conn.fetch(
            """
            SELECT telegram_id, plan, is_trial, trial_expires_at
            FROM users
            WHERE is_onboarded = TRUE AND (is_deleted IS NULL OR is_deleted = FALSE)
            """
        )
        now_utc = datetime.now(timezone.utc)
        pro_uids = set()
        for r in pro_rows:
            uid = r["telegram_id"]
            plan = r.get("plan", "free")
            is_trial = r.get("is_trial", False)
            exp = r.get("trial_expires_at")
            if is_trial and exp:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp > now_utc:
                    pro_uids.add(uid)
                    continue
            if plan in ("pro", "trial", "proplus", "premium"):
                pro_uids.add(uid)

        # 3. Load all preferences ordered deterministically
        pref_rows = await conn.fetch(
            """
            SELECT telegram_id, company_id, pref_type
            FROM user_company_prefs
            ORDER BY created_at ASC, company_id ASC
            """
        )

        user_follow_counts: dict[int, int] = {}
        for r in pref_rows:
            uid = r["telegram_id"]
            cid = r["company_id"]
            ptype = r["pref_type"]

            if ptype == "mute":
                all_user_mutes.setdefault(uid, set()).add(cid)
                # Expand children
                all_user_mutes[uid].update(children_map.get(cid, set()))
            elif ptype == "follow":
                if uid in pro_uids:
                    all_user_follows.setdefault(uid, set()).add(cid)
                else:
                    cnt = user_follow_counts.get(uid, 0)
                    if cnt < 5:
                        all_user_follows.setdefault(uid, set()).add(cid)
                        user_follow_counts[uid] = cnt + 1

    return all_user_mutes, all_user_follows


async def follow_company(telegram_id: int, company_id: int, plan: str = "free") -> dict:
    """
    Follows a company atomically under a user-row lock.
    Enforces cap dynamically: Free: 5, Pro: Unlimited.
    Mutual exclusion: If company was previously muted, removes mute and converts to follow.
    """
    PRO_PLANS = ("pro", "trial", "proplus", "premium")
    is_pro = plan in PRO_PLANS
    cap = None if is_pro else 5
    pool = get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock user row to serialize concurrent writes
            await conn.execute("SELECT 1 FROM users WHERE telegram_id = $1 FOR UPDATE", telegram_id)

            # Check if this company is already followed
            existing = await conn.fetchval(
                "SELECT pref_type FROM user_company_prefs WHERE telegram_id = $1 AND company_id = $2",
                telegram_id, company_id
            )
            if existing == "follow":
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'follow'",
                    telegram_id
                )
                return {"success": True, "cap": cap, "count": count, "already_following": True}

            # Check current follow count for Free users
            current_count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'follow'",
                telegram_id
            )
            if not is_pro and current_count >= 5:
                return {"success": False, "reason": "quota_reached", "cap": 5, "count": current_count}

            # Upsert follow (clears mute if present)
            await conn.execute(
                """
                INSERT INTO user_company_prefs (telegram_id, company_id, pref_type, created_at)
                VALUES ($1, $2, 'follow', NOW())
                ON CONFLICT (telegram_id, company_id) DO UPDATE
                SET pref_type = 'follow', created_at = NOW();
                """,
                telegram_id, company_id
            )

            new_count = current_count + 1
            converted = (existing == "mute")

    return {"success": True, "cap": cap, "count": new_count, "converted_from_mute": converted}


async def mute_company(telegram_id: int, company_id: int) -> dict:
    """
    Mutes a company (employer or disliked firm) atomically.
    Unlimited for all users (Free and Pro).
    Mutual exclusion: If company was previously followed, removes follow and converts to mute.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT 1 FROM users WHERE telegram_id = $1 FOR UPDATE", telegram_id)

            existing = await conn.fetchval(
                "SELECT pref_type FROM user_company_prefs WHERE telegram_id = $1 AND company_id = $2",
                telegram_id, company_id
            )
            if existing == "mute":
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'mute'",
                    telegram_id
                )
                return {"success": True, "count": count, "already_muted": True}

            await conn.execute(
                """
                INSERT INTO user_company_prefs (telegram_id, company_id, pref_type, created_at)
                VALUES ($1, $2, 'mute', NOW())
                ON CONFLICT (telegram_id, company_id) DO UPDATE
                SET pref_type = 'mute', created_at = NOW();
                """,
                telegram_id, company_id
            )

            current_count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'mute'",
                telegram_id
            )
            converted = (existing == "follow")

    return {"success": True, "count": current_count, "converted_from_follow": converted}


async def unfollow_company(telegram_id: int, company_id: int) -> bool:
    """Removes a company from user's followed list."""
    pool = get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM user_company_prefs WHERE telegram_id = $1 AND company_id = $2 AND pref_type = 'follow'",
            telegram_id, company_id
        )
        return "DELETE 1" in res


async def unmute_company(telegram_id: int, company_id: int) -> bool:
    """Unmutes a company (undo action)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM user_company_prefs WHERE telegram_id = $1 AND company_id = $2 AND pref_type = 'mute'",
            telegram_id, company_id
        )
        return "DELETE 1" in res


async def follow_bundle(telegram_id: int, bundle_id: int, plan: str = "free") -> dict:
    """
    Follows all companies in a curated bundle.
    All-or-nothing: Pro required. Rejects partial addition if remaining quota < bundle size.
    """
    PRO_PLANS = ("pro", "trial", "proplus", "premium")
    if plan not in PRO_PLANS:
        return {"success": False, "reason": "pro_required"}

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT 1 FROM users WHERE telegram_id = $1 FOR UPDATE", telegram_id)

            bundle_cids = await conn.fetch(
                "SELECT company_id FROM company_bundle_members WHERE bundle_id = $1",
                bundle_id
            )
            cids = [r["company_id"] for r in bundle_cids]
            if not cids:
                return {"success": False, "reason": "bundle_empty"}

            current_follows = await conn.fetch(
                "SELECT company_id FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'follow'",
                telegram_id
            )
            cur_set = {r["company_id"] for r in current_follows}
            new_cids = [c for c in cids if c not in cur_set]

            if new_cids:
                await conn.executemany(
                    """
                    INSERT INTO user_company_prefs (telegram_id, company_id, pref_type, created_at)
                    VALUES ($1, $2, 'follow', NOW())
                    ON CONFLICT (telegram_id, company_id) DO UPDATE
                    SET pref_type = 'follow';
                    """,
                    [(telegram_id, cid) for cid in new_cids]
                )

    return {"success": True, "added": len(new_cids), "total": len(cur_set) + len(new_cids)}


async def search_companies(query_str: str, limit: int = 5) -> list[dict]:
    """
    Searches active companies with prefix-first sorting.
    Escapes '%' and '_' wildcards from user input.
    """
    clean_q = query_str.strip().replace("%", "").replace("_", "")
    if not clean_q:
        return []

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name
            FROM companies
            WHERE is_active = TRUE AND name ILIKE '%' || $1 || '%'
            ORDER BY
                CASE WHEN name ILIKE $1 || '%' THEN 1 ELSE 2 END,
                name ASC
            LIMIT $2
            """,
            clean_q, limit
        )
        return [dict(r) for r in rows]


async def get_company_by_id(company_id: int) -> dict | None:
    """Fetches single company by ID."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, parent_id, is_active FROM companies WHERE id = $1",
            company_id
        )
        return dict(row) if row else None


async def get_user_prefs_detail(telegram_id: int, is_pro: bool = False) -> dict:
    """Returns detailed user preferences for UI rendering."""
    pool = get_pool()
    async with pool.acquire() as conn:
        mode = await conn.fetchval(
            "SELECT company_filter_mode FROM users WHERE telegram_id = $1",
            telegram_id
        ) or "all"

        follow_rows = await conn.fetch(
            """
            SELECT c.id, c.name, p.created_at
            FROM user_company_prefs p
            JOIN companies c ON p.company_id = c.id
            WHERE p.telegram_id = $1 AND p.pref_type = 'follow'
            ORDER BY p.created_at ASC, p.company_id ASC
            """,
            telegram_id
        )
        mute_rows = await conn.fetch(
            """
            SELECT c.id, c.name, p.created_at
            FROM user_company_prefs p
            JOIN companies c ON p.company_id = c.id
            WHERE p.telegram_id = $1 AND p.pref_type = 'mute'
            ORDER BY p.created_at ASC, p.company_id ASC
            """,
            telegram_id
        )

    cap = None if is_pro else 5
    follows_list = [dict(r) for r in follow_rows]
    active_follows = follows_list if is_pro else follows_list[:5]
    frozen_follows = [] if is_pro else follows_list[5:]

    return {
        "mode": mode,
        "active_follows": active_follows,
        "frozen_follows": frozen_follows,
        "mutes": [dict(r) for r in mute_rows],
        "cap": cap,
        "is_pro": is_pro
    }


async def set_company_filter_mode(telegram_id: int, mode: str, is_pro: bool = False) -> dict:
    """Toggles filter mode between 'all' and 'watchlist'."""
    if mode == "watchlist":
        if not is_pro:
            return {"success": False, "reason": "pro_required"}
        pool = get_pool()
        async with pool.acquire() as conn:
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM user_company_prefs WHERE telegram_id = $1 AND pref_type = 'follow'",
                telegram_id
            )
            if not cnt or cnt == 0:
                return {"success": False, "reason": "empty_watchlist"}
            await conn.execute("UPDATE users SET company_filter_mode = 'watchlist' WHERE telegram_id = $1", telegram_id)
            return {"success": True, "mode": "watchlist"}
    else:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET company_filter_mode = 'all' WHERE telegram_id = $1", telegram_id)
            return {"success": True, "mode": "all"}


async def check_unlinked_sources_and_cycles() -> dict:
    """Audits unlinked crawler sources and detects any parent-child cycles in companies."""
    pool = get_pool()
    async with pool.acquire() as conn:
        unlinked = await conn.fetchval(
            "SELECT COUNT(*) FROM career_sources WHERE is_active = TRUE AND company_id IS NULL"
        )
        comp_rows = await conn.fetch("SELECT id, parent_id FROM companies WHERE is_active = TRUE")

    # Detect cycles via recursive walk
    direct_children: dict[int, set[int]] = {}
    for c in comp_rows:
        cid = c["id"]
        pid = c.get("parent_id")
        if pid:
            direct_children.setdefault(pid, set()).add(cid)

    cycles_found = []
    for pid in direct_children:
        visited = set()
        stack = [(pid, [pid])]
        while stack:
            curr, path = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            for child in direct_children.get(curr, set()):
                if child in path:
                    cycles_found.append(path + [child])
                else:
                    stack.append((child, path + [child]))

    if unlinked and unlinked > 0:
        logger.warning(f"⚠️ RFC-004 Audit: {unlinked} active career_sources have company_id = NULL!")
    if cycles_found:
        logger.error(f"❌ RFC-004 Audit: Parent-child cycles detected in companies: {cycles_found}")

    return {
        "unlinked_sources": unlinked or 0,
        "cycles_found": cycles_found
    }
