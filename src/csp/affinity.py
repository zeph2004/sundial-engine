import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.csp.domain import get_compatible_venues, load_json


SPECIALIZED_HARD_CATEGORIES: Set[str] = {
    "Engineering / Science Lab",
    "Workshop",
    "Studio",
    "Field / Site",
}


def extract_module_prefixes(session: Dict[str, Any]) -> List[str]:
    """
    Extracts ordered unique alphabetical prefixes from a session's moduleCode / moduleCodes
    (e.g., "AUT 04112/MET 04114" -> ["AUT", "MET"]).
    """
    codes = list(session.get("moduleCodes") or [])
    raw_code = session.get("moduleCode", "")
    if raw_code and raw_code not in codes:
        codes.insert(0, raw_code)

    prefixes: List[str] = []
    for code in codes:
        for token in re.split(r"[/,&+]", str(code)):
            m = re.match(r"^\s*([A-Za-z]+)", token)
            if m:
                pref = m.group(1).upper()
                if pref not in prefixes:
                    prefixes.append(pref)
    return prefixes if prefixes else ["GEN"]


def extract_primary_prefix(session: Dict[str, Any]) -> str:
    """Returns the primary alphabetical prefix of session['moduleCode']."""
    return extract_module_prefixes(session)[0]


def _parse_venue_dept_prefixes(venue: Dict[str, Any]) -> Set[str]:
    """Extracts uppercase department prefixes from venue['departmentPrefix'] (comma/semicolon/slash separated)."""
    raw = str(venue.get("departmentPrefix") or venue.get("department_prefix") or "").strip()
    if not raw:
        return set()
    tokens = {
        tok.strip().upper()
        for tok in re.split(r"[;,/\s]+", raw)
        if tok.strip()
    }
    tokens.discard("GEN")
    return tokens


def _extract_cohort_dept_codes(cohorts: List[str]) -> Set[str]:
    """Extracts trailing department codes from cohort IDs (e.g., 'L7-2CS' -> 'CS', 'L7-2IT-E' -> 'IT')."""
    codes: Set[str] = set()
    for c in cohorts:
        cleaned = re.sub(r"-E$", "", str(c or "").strip().upper())
        m = re.search(r"([A-Z]{2,5})$", cleaned)
        if m:
            codes.add(m.group(1))
    return codes


def _venue_matches_session_dept(
    venue_prefixes: Set[str],
    session_prefixes: List[str],
    cohort_depts: Set[str],
) -> bool:
    if not venue_prefixes:
        return False
    for vp in venue_prefixes:
        if vp in session_prefixes or vp in cohort_depts:
            return True
        if len(vp) >= 2:
            for sp in session_prefixes:
                if sp.startswith(vp) or (len(sp) >= 2 and vp.startswith(sp)):
                    return True
            for cd in cohort_depts:
                if cd.startswith(vp) or (len(cd) >= 2 and vp.startswith(cd)):
                    return True
    return False


def _match_preferred_venue_ids(
    session: Dict[str, Any],
    venues: List[Dict[str, Any]],
    base_cat_set: Set[int | str],
) -> List[int | str]:
    pref_raw = session.get("preferredVenue")
    if pref_raw is None or str(pref_raw).strip() == "":
        return []
    pref_str = str(pref_raw).strip()
    pref_lower = pref_str.lower()
    matched: List[int | str] = []
    for v in venues:
        vid = v.get("venueId")
        if vid not in base_cat_set:
            continue
        if str(vid) == pref_str or str(v.get("name", "")).strip().lower() == pref_lower:
            if vid not in matched:
                matched.append(vid)
    return matched


def generate_venue_affinity_config(
    sessions: List[Dict[str, Any]],
    venues: List[Dict[str, Any]],
    schema: Dict[str, Any],
    output_path: Path | None = None,
) -> Dict[str, Any]:
    """
    Empirically mines historical venue usage from `sessions` and constructs a
    declarative 3-tier Venue Affinity configuration (`configs/atc_venue_affinity.json`):
      1. `category_overflow_policies`: per-category strictness rules
      2. `module_and_prefix_rules`:
         - `by_module_code`: (moduleCode -> category -> preferred_venue_ids)
         - `by_module_prefix`: (prefix -> category -> allowed_venue_ids)
      3. `cohort_home_venues`: (cohort -> category -> preferred_venue_ids)
    """
    venue_by_id = {v["venueId"]: v for v in venues}
    categories = list(schema["venue_rules"]["compatibility_map"].keys())

    # 1. Category overflow policies
    category_overflow_policies: Dict[str, Dict[str, Any]] = {}
    for cat in categories:
        is_hard = cat in SPECIALIZED_HARD_CATEGORIES
        category_overflow_policies[cat] = {
            "restrict_to_prefix_or_module_pool": is_hard,
            "allow_general_category_fallback_only_if_empty": True,
            "tier2_overflow_soft_penalty": 100 if is_hard else 20,
            "description": (
                "Hard departmental sub-pool lock: sessions may only use venues in their module or department prefix pool."
                if is_hard
                else "Soft home-turf preference: prioritize Tier 1 (Module / Cohort Home / Dept Prefix) venues before overflowing into the general category pool."
            ),
        }

    # 2. Mine frequency counts for (moduleCode, category), (prefix, category), and (cohort, category)
    mod_cat_counts: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    pref_cat_counts: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    cohort_cat_counts: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))

    for s in sessions:
        req_cat = s["requiredVenueCategory"]
        mod_code = s["moduleCode"]
        dur = int(s.get("durationPeriods", 1))
        gt_vid = s["groundTruth"]["venueId"]

        # Weight by durationPeriods so multi-period blocks reflect actual room-period affinity
        mod_cat_counts[mod_code][req_cat][gt_vid] += dur

        for pref in extract_module_prefixes(s):
            pref_cat_counts[pref][req_cat][gt_vid] += dur

        for coh in s.get("targetCohorts", []):
            cohort_cat_counts[coh][req_cat][gt_vid] += dur

    # Build by_module_code
    by_module_code: Dict[str, Dict[str, List[int | str]]] = {}
    for mod_code in sorted(mod_cat_counts.keys()):
        by_module_code[mod_code] = {}
        for cat in sorted(mod_cat_counts[mod_code].keys()):
            counter = mod_cat_counts[mod_code][cat]
            ordered_vids = [
                vid for vid, _ in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
            ]
            by_module_code[mod_code][cat] = ordered_vids

    # Build by_module_prefix
    by_module_prefix: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for pref in sorted(pref_cat_counts.keys()):
        by_module_prefix[pref] = {}
        for cat in sorted(pref_cat_counts[pref].keys()):
            counter = pref_cat_counts[pref][cat]
            ordered_vids = [
                vid for vid, _ in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
            ]
            by_module_prefix[pref][cat] = {
                "allowed_venue_ids": ordered_vids,
                "venue_names": [venue_by_id.get(v, {}).get("name", str(v)) for v in ordered_vids],
            }

    # Build cohort_home_venues
    cohort_home_venues: Dict[str, Dict[str, List[int | str]]] = {}
    for coh in sorted(cohort_cat_counts.keys()):
        cohort_home_venues[coh] = {}
        for cat in sorted(cohort_cat_counts[coh].keys()):
            counter = cohort_cat_counts[coh][cat]
            ordered_vids = [
                vid for vid, _ in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
            ]
            cohort_home_venues[coh][cat] = ordered_vids

    config: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "institution_code": schema["institution"]["code"],
        "description": (
            "Declarative 3-Tier Departmental Venue Affinity & Hard Specialized Lab Sub-Pool Configuration. "
            "Tier 1A = Exact Module Preferred Venues; Tier 1B = Cohort Home Venues; "
            "Tier 1C = Department Prefix Pool; Tier 2 = General Category Overflow Pool."
        ),
        "category_overflow_policies": category_overflow_policies,
        "module_and_prefix_rules": {
            "by_module_code": by_module_code,
            "by_module_prefix": by_module_prefix,
        },
        "cohort_home_venues": cohort_home_venues,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.write("\n")

    return config


def resolve_session_venues_and_tiers(
    session: Dict[str, Any],
    venues: List[Dict[str, Any]],
    schema: Dict[str, Any],
    affinity_config: Dict[str, Any] | None = None,
    include_fallbacks: bool | None = None,
) -> Tuple[List[int | str], Dict[int | str, str], Dict[int | str, int]]:
    """
    Resolves the ordered list of compatible venues for `session` along with each venue's
    affinity tier label and numeric tier rank:
      - Tier 1A (`tier_rank = 1`, label = `"Tier 1A: Module Preferred"`): Exact module match
      - Tier 1B (`tier_rank = 1`, label = `"Tier 1B: Cohort Home"`): Shared cohort home room
      - Tier 1C (`tier_rank = 1`, label = `"Tier 1C: Dept Prefix Pool"`): Department prefix pool
      - Tier 2  (`tier_rank = 2`, label = `"Tier 2: General Overflow"`): General category pool

    If `restrict_to_prefix_or_module_pool == True` for `session['requiredVenueCategory']`
    and `Tier 1A ∪ Tier 1C` is non-empty, restricts the returned venues strictly to
    `Tier 1A -> Tier 1C` (excluding unrelated departments' labs/workshops).
    """
    req_cat = session["requiredVenueCategory"]
    base_cat_vids = get_compatible_venues(
        required_category=req_cat,
        venues=venues,
        schema=schema,
        include_fallbacks=include_fallbacks,
    )
    base_cat_set = set(base_cat_vids)
    venue_by_id = {v["venueId"]: v for v in venues}

    mod_code = session["moduleCode"]
    prefixes = extract_module_prefixes(session)
    cohorts = session.get("targetCohorts", [])
    cohort_depts = _extract_cohort_dept_codes(cohorts)

    # Institution-agnostic signals present directly on uploaded CSVs/JSONs:
    # 1) Exact preferredVenue on session -> Tier 1A
    # 2) Venue departmentPrefix matching module prefix or cohort dept -> Tier 1C
    direct_preferred_vids = _match_preferred_venue_ids(session, venues, base_cat_set)
    direct_dept_vids: List[int | str] = []
    for vid in base_cat_vids:
        v_obj = venue_by_id.get(vid)
        if not v_obj:
            continue
        v_prefs = _parse_venue_dept_prefixes(v_obj)
        if _venue_matches_session_dept(v_prefs, prefixes, cohort_depts):
            direct_dept_vids.append(vid)

    if not affinity_config:
        if not direct_preferred_vids and not direct_dept_vids:
            tier_labels = {vid: "Tier 1A: Module Preferred" for vid in base_cat_vids}
            tier_ranks = {vid: 1 for vid in base_cat_vids}
            return base_cat_vids, tier_labels, tier_ranks

        ordered_vids: List[int | str] = []
        tier_labels: Dict[int | str, str] = {}
        tier_ranks: Dict[int | str, int] = {}

        def _add_direct(cands: List[int | str], label: str, rank: int) -> None:
            for vid in cands:
                if vid not in tier_labels:
                    ordered_vids.append(vid)
                    tier_labels[vid] = label
                    tier_ranks[vid] = rank

        _add_direct(direct_preferred_vids, "Tier 1A: Module Preferred", 1)
        _add_direct(direct_dept_vids, "Tier 1C: Dept Prefix Pool", 1)

        remaining_general = sorted(
            [vid for vid in base_cat_vids if vid not in tier_labels],
            key=lambda vid: (
                int(venue_by_id.get(vid, {}).get("capacity") or 9999),
                str(vid),
            ),
        )
        _add_direct(remaining_general, "Tier 2: General Overflow", 2)
        return ordered_vids, tier_labels, tier_ranks

    policy = affinity_config.get("category_overflow_policies", {}).get(req_cat, {})
    restrict_hard = bool(policy.get("restrict_to_prefix_or_module_pool", False))

    mod_rules = affinity_config.get("module_and_prefix_rules", {})
    by_mod = mod_rules.get("by_module_code", {})
    by_pref = mod_rules.get("by_module_prefix", {})
    by_coh = affinity_config.get("cohort_home_venues", {})

    # Tier 1A: Direct preferredVenue + exact module code venues within base_cat_set
    tier_1a: List[int | str] = list(direct_preferred_vids)
    for vid in by_mod.get(mod_code, {}).get(req_cat, []):
        if vid in base_cat_set and vid not in tier_1a:
            tier_1a.append(vid)

    # Tier 1B: Cohort home venues across targetCohorts (ranked by how many targetCohorts share the home room)
    cohort_vid_score: Counter = Counter()
    cohort_vid_order: Dict[int | str, int] = {}
    for coh in cohorts:
        coh_vids = by_coh.get(coh, {}).get(req_cat, [])
        for rank_idx, vid in enumerate(coh_vids):
            if vid in base_cat_set:
                cohort_vid_score[vid] += max(1, 10 - rank_idx)
                if vid not in cohort_vid_order:
                    cohort_vid_order[vid] = rank_idx

    tier_1b: List[int | str] = [
        vid for vid, _ in sorted(
            cohort_vid_score.items(),
            key=lambda kv: (-kv[1], cohort_vid_order[kv[0]], str(kv[0])),
        )
    ]

    # Tier 1C: Department prefix pool (from affinity_config + venue.departmentPrefix)
    tier_1c: List[int | str] = []
    for pref in prefixes:
        pref_entry = by_pref.get(pref, {}).get(req_cat, {})
        pref_vids = (
            pref_entry.get("allowed_venue_ids", [])
            if isinstance(pref_entry, dict)
            else pref_entry
        )
        for vid in pref_vids:
            if vid in base_cat_set and vid not in tier_1c:
                tier_1c.append(vid)
    for vid in direct_dept_vids:
        if vid not in tier_1c:
            tier_1c.append(vid)

    # Assemble ordered unique list and tier annotations
    ordered_vids: List[int | str] = []
    tier_labels: Dict[int | str, str] = {}
    tier_ranks: Dict[int | str, int] = {}

    def _add_candidates(cands: List[int | str], label: str, rank: int) -> None:
        for vid in cands:
            if vid not in tier_labels:
                ordered_vids.append(vid)
                tier_labels[vid] = label
                tier_ranks[vid] = rank

    if restrict_hard:
        # Hard specialized sub-pool: only allow Tier 1A (Module) and Tier 1C (Dept Prefix Pool),
        # with Tier 1B cohort rooms only if they are already inside the department's prefix pool.
        dept_allowed_set = set(tier_1a) | set(tier_1c)
        tier_1b_restricted = [vid for vid in tier_1b if vid in dept_allowed_set]
        _add_candidates(tier_1a, "Tier 1A: Module Preferred", 1)
        _add_candidates(tier_1b_restricted, "Tier 1B: Cohort Home", 1)
        _add_candidates(tier_1c, "Tier 1C: Dept Prefix Pool", 1)

        # Fallback only if the prefix/module has zero historical venues in this category
        if not ordered_vids:
            _add_candidates(base_cat_vids, "Tier 2: General Overflow", 2)
    else:
        # Soft preference category (Theory / Lecture Room, Computer / Digital Lab):
        # Order [Tier 1A -> Tier 1B -> Tier 1C -> Tier 2 General Overflow]
        _add_candidates(tier_1a, "Tier 1A: Module Preferred", 1)
        _add_candidates(tier_1b, "Tier 1B: Cohort Home", 1)
        _add_candidates(tier_1c, "Tier 1C: Dept Prefix Pool", 1)

        remaining_general = sorted(
            [vid for vid in base_cat_vids if vid not in tier_labels],
            key=lambda vid: (
                int(venue_by_id.get(vid, {}).get("capacity") or 9999),
                str(vid),
            ),
        )
        _add_candidates(remaining_general, "Tier 2: General Overflow", 2)

    return ordered_vids, tier_labels, tier_ranks


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    schema = load_json(root / "configs" / "institution_schema.json")
    dataset = load_json(root / "data" / "raw" / "atc" / "atc-timetable-dataset.json")
    sessions = load_json(root / "data" / "raw" / "atc" / "atc-csp-sessions.json")["sessions"]
    venues = dataset["venues"]

    out_cfg_path = root / "configs" / "atc_venue_affinity.json"
    cfg = generate_venue_affinity_config(sessions, venues, schema, output_path=out_cfg_path)

    print("=== 1. Generated Declarative Venue Affinity Config ===")
    print(f"  Output Path              : {out_cfg_path}")
    print(f"  Unique Module Rules      : {len(cfg['module_and_prefix_rules']['by_module_code'])}")
    print(f"  Department Prefix Pools  : {len(cfg['module_and_prefix_rules']['by_module_prefix'])}")
    print(f"  Cohort Home Profiles     : {len(cfg['cohort_home_venues'])}")

    print("\n=== 2. Sample Specialized Hard Sub-Pools (Workshops & Labs) ===")
    by_pref = cfg["module_and_prefix_rules"]["by_module_prefix"]
    for sample_pref in ["AUT", "AET", "CEU", "EEU", "MEU", "CSU"]:
        if sample_pref in by_pref:
            for cat, info in by_pref[sample_pref].items():
                if cat in SPECIALIZED_HARD_CATEGORIES or cat == "Computer / Digital Lab":
                    print(f"  Prefix {sample_pref:4s} | {cat:26s} -> {len(info['allowed_venue_ids']):2d} venues: {info['venue_names']}")
