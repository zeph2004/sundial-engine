# sundial-engine

An institution-agnostic **University Course Timetabling Constraint Satisfaction & Optimization Engine** built from first principles in pure Python 3 (zero external black-box solver dependencies).

`sundial-engine` models and solves real-world university scheduling constraints—starting with **Arusha Technical College (ATC)** as its primary empirical benchmark (`1,306` raw weekly sessions across `29` programs, `10` NTA levels, `123` cohorts, `175` lecturers, and `75` physical venues), and architected to generalize declaratively to other Tanzanian higher-learning institutions (`DIT`, `MUST`, `UDSM`, etc.) via JSON configuration schemas.

---

## 1. Benchmark Dataset: Arusha Technical College (ATC)

Extracted and normalized from ATC's master timetable (`data/raw/atc/`):

| Dimension | Specification |
| :--- | :--- |
| **Raw / Cleaned Weekly Sessions** | `1,306` raw rows (`S0001–S1306`) $\to$ **`1,233`** Clean Primary Sessions (`Mode A`) & **`1,299`** Full Stress-Test Sessions (`Mode B`) |
| **Programs & NTA Levels** | `29` Academic Programs across `10` NTA Level groupings (Levels `4` to `8`) |
| **Student Cohorts** | `123` total (`121` active in schedule, with `197` joint-cohort combinations up to 6 cohorts/session) |
| **Lecturers & Modules** | `175` Lecturers (1 to 5 co-lecturers per session) across `498` unique modules |
| **Physical Venues** | `75` Venues (`25` Lecture Rooms, `20` Engineering/Science Labs, `14` Workshops, `10` Computer Labs, `5` Field Sites, `1` Studio) |
| **Calendar Grid** | `6` Days (`MONDAY`–`SATURDAY`) $\times$ `18` Periods/Day (`45` minutes per period, `108` weekly slots) |
| **Full-Time Stream** | Periods `P1–P12` (`07:30–17:55`), with Tea Break after `P4` and Lunch Break after `P6` |
| **Evening Stream** | Periods `P13–P18` (`18:00–22:40`), with an optional Twilight Transition Buffer in `P11–P12` (`16:25–17:55`) |

---

## 2. Mathematical Formulation $(X, D, C_{\text{hard}}, C_{\text{soft}})$

### Variables ($X$)
Each weekly course session is a decision variable $x_i \in X$ with fixed attributes $(\text{moduleCode}_i, \text{lecturers}_i, \text{cohorts}_i, \text{stream}_i, \text{duration}_i \in \{1, 2, 4, 6\}, \text{category}_i)$.
We evaluate two benchmark modes:
* **Benchmark Mode A (Clean Primary Dataset, $|X| = 1,233$):** Primary venue-view schedule (`S0001–S1233`).
* **Benchmark Mode B (Full Stress-Test Dataset, $|X| = 1,299$):** Retains `66` secondary cohort-view clone rows from `S1234–S1306` (after removing `7` pigeonhole-violating split-group duplicates `S1269–S1275` and trimming `S0253` to 2 periods) to stress-test the solver under heavy resource contention.

### Factored Domains ($D$)
Rather than branching over flat $(\text{Day}, \text{StartPeriod}, \text{Venue})$ triples, each domain $D_i = T_i \times V_i$ is factored into a **valid time-slot set** $T_i$ and a **prioritized compatible venue list** $V_i$:
1. **Unary Time Filtering ($T_i$):** Computed declaratively from `configs/institution_schema.json`, enforcing stream windows, break non-crossing ($p \le b < p + d_i - 1$ for $b \in \{4, 6, 12\}$), and odd start-period alignment ($p \bmod 2 = 1$) for multi-period blocks ($d_i \ge 2$).
2. **3-Tier Departmental Venue Affinity ($V_i$, `configs/atc_venue_affinity.json`):**
   * **Hard Specialized Lab & Workshop Pinning:** For specialized physical infrastructure (`Engineering / Science Lab`, `Workshop`, `Studio`, `Field / Site`), $V_i$ is **strictly restricted** to the module's (`Tier 1A`) or department prefix's (`Tier 1C`) equipment pool—preventing an Automotive workshop (`AUT`/`AET`) from ever being placed in a Civil or Electrical lab.
   * **Prioritized Soft Home-Turf Tiers:** For general categories (`Theory / Lecture Room`, `Computer / Digital Lab`), candidate rooms are ordered strictly by:
     $$\text{Tier 1A (Exact Module)} \;\to\; \text{Tier 1B (Cohort Home Room)} \;\to\; \text{Tier 1C (Dept Prefix Pool)} \;\to\; \text{Tier 2 (General Category Overflow)}$$

### Hard Constraints ($C_{\text{hard}}$)
1. **Static Binary Conflict Graph $G_{\text{conflict}} = (X, E_{\text{conflict}})$:** An undirected edge $(x_i, x_j) \in E_{\text{conflict}}$ connects any two sessions sharing $\ge 1$ lecturer or $\ge 1$ target cohort ($17,454$ edges in Mode A; $20,003$ edges in Mode B; max degree $\Delta = 125$). Connected sessions cannot overlap in time.
2. **Dynamic Room-Time Exclusivity:** No two sessions assigned to the same physical venue $v$ may overlap on any $(\text{Day}, \text{Period})$ slot.

### Strict 2-Condition Saturday Fallback Policy (5-Day Default)
All schedules default strictly to **Monday–Friday** (`60` Full-Time periods / `30` standard Evening periods). A session is placed on `SATURDAY` **if and only if**:
* **Condition 1 (Cohort Time / Block Capacity Overflow):** At least one target cohort's weekly demand exceeds 5-day capacity (`> 60` Full-Time periods, `> 30` Evening periods, or `> 5` afternoon 6-period blocks), **OR**
* **Condition 2 (Hard-Constraint Weekday Contention):** Every Monday–Friday slot is blocked by Lecturer, Cohort, or Departmental Lab hard constraints.

---

## 3. Solver Architecture (`src/csp/`)

`src/csp/solver.py` achieves sub-second, **0-backtrack** solving across all `1,233` and `1,299` variables through five core techniques:

1. **Pre-Flight Pigeonhole Capacity Validator (`run_preflight_checks`):** Verifies before search begins that no lecturer, cohort, venue category, or restricted departmental lab sub-pool exceeds its weekly period supply.
2. **108-Bit Bitwise Time Masks:** Encodes the $6 \text{ days} \times 18 \text{ periods} = 108$ weekly calendar grid into a single Python integer bitmask (`slot_bit = day_idx * 18 + (period - 1)`), reducing interval overlap and venue availability checks to a single bitwise instruction: `(venue_busy_mask[v] & time_mask) == 0`.
3. **Weekday-Aware MRV + Degree + Block Rigidity (`select_unassigned_variable`):** Prioritizes sessions running low on Monday–Friday slots (`weekday_slot_count`) weighted by venue-pool tightness, breaking ties by conflict graph degree ($\deg \le 125$) and block duration ($6\text{p} \to 4\text{p} \to 2\text{p} \to 1\text{p}$). Once a heavy cohort exhausts its 60 Monday–Friday periods (`weekday_slot_count == 0`), its remaining sessions transition seamlessly to `SATURDAY`.
4. **Lexicographic Affinity-Aware Value Ordering (`order_domain_values`):** Ranks candidate placements by:
   ```python
   (is_saturday, twilight_penalty, best_available_venue_tier, lcv_conflict_score, subtier_rank, day_load_spread)
   ```
   guaranteeing that Monday–Friday (`is_saturday == 0`) always takes precedence over Saturday (`is_saturday == 1`) while steering sessions into free Tier 1 departmental/cohort home rooms.
5. **Reversible Eager Forward Checking (`forward_check` & `undo_log`):** Zero `copy.deepcopy` overhead. Prunes overlapping neighbor slots and exhausted room pools in real time using a lightweight reversible `undo_log`.

---

## 4. Empirical Benchmark Results

Comparison of the **Sundial CSP Solver** against the **Raw ATC Human Ground Truth**:

| Metric | Mode A: Clean Primary (`1,233` Sessions) | Mode B: Full Stress-Test (`1,299` Sessions) | Raw ATC Ground Truth (`1,299` Sessions) |
| :--- | :---: | :---: | :---: |
| **Preflight Pigeonhole & Sub-Pool Check** | **`PASS`** | **`PASS`** | — |
| **Conflict Graph Edges ($\vert E_{\text{conflict}} \vert$)** | `17,454` ($\max \deg = 125$) | `20,003` ($\max \deg = 125$) | `20,003` |
| **Solve Status & Wall-Clock Runtime** | **`SOLVED` in `~0.66s – 1.10s`** | **`SOLVED` in `~0.73s – 1.15s`** | Human-authored |
| **Recursive Nodes / Backtracks** | **`1,233` nodes / `0` backtracks** | **`1,299` nodes / `0` backtracks** | — |
| **Hard Constraint Violations (Lec / Coh / Ven)** | **`0` pairs (`0` slot collisions)** | **`0` pairs (`0` slot collisions)** | **`81` pairs** (`71` Lec, `71` Coh, `77` Ven) |
| **Specialized Lab / Workshop Dept Lock** | **`306 / 306` (`100.0%`)** | **`323 / 323` (`100.0%`)** | `100.0%` |
| **Tier 1 Departmental & Home Room Affinity** | **`1,233 / 1,233` (`100.0%`)** | **`1,298 / 1,299` (`99.9%`)** | — |
| — *Tier 1A: Exact Module Room Match* | `1,079 / 1,233` (`87.5%`) | `1,099 / 1,299` (`84.6%`) | — |
| — *Tier 1B: Cohort Home Room Match* | `125 / 1,233` (`10.1%`) | `144 / 1,299` (`11.1%`) | — |
| — *Tier 1C: Dept Prefix Pool Match* | `29 / 1,233` (`2.4%`) | `55 / 1,299` (`4.2%`) | — |
| **Tier 2 General Classroom Overflow** | **`0 / 1,233` (`0.0%`)** | **`1 / 1,299` (`0.1%`)** | — |
| **Saturday Sessions Placed** | **`17 / 1,233` (`1.4%`)** | **`39 / 1,299` (`3.0%`)** | `35` (Mode A) / `40` (Mode B) |
| — *Condition 1 (`>60p` FT / `>30p` Eve Overflow)* | **`17 / 17` (`100%`)** | **`39 / 39` (`100%`)** | — |
| — *Condition 2 (Hard-Constraint Bottleneck)* | **`0`** | **`0`** | — |
| **100% Saturday-Free Cohorts (Mon–Fri Only)** | **`111 / 121` (`91.7%`)** | **`107 / 121` (`88.4%`)** | **`86 / 121` (`71.1%`)** |

---

## 5. Repository Structure & Quickstart CLI

```text
sundial-engine/
├── configs/
│   ├── institution_schema.json      # Declarative calendar grid, stream rules & venue categories
│   └── atc_venue_affinity.json      # 3-Tier departmental venue affinity & hard lab sub-pool rules
├── data/
│   ├── raw/atc/                     # ATC master dataset (atc-timetable-dataset.json, atc-csp-sessions.json)
│   └── processed/                   # Solver-exported JSON bundle (timetable_view_data.json)
├── docs/
│   └── EDA_FINDINGS.md              # Empirical constraint discoveries & data anomaly analysis
├── notebooks/
│   └── 01_eda.py                    # Phase 1 exploratory data analysis & constraint audit
├── src/
│   ├── csp/
│   │   ├── domain.py                # Unary domain generator & pre-flight pigeonhole capacity checks
│   │   ├── constraints.py           # Conflict graph builder & ground-truth collision auditor
│   │   ├── affinity.py              # Departmental venue affinity miner & 3-tier room resolver
│   │   └── solver.py                # Bitmask backtracking solver, LCV heuristics & solution verifier
│   └── viz/
│       ├── exporter.py              # JSON & offline JS payload exporter for the web visualizer
│       ├── viewer.py                # Local HTTP server launcher for the web visualizer
│       └── index.html               # Single-page timetable visualizer & A4 Landscape PDF renderer
└── requirements.txt
```

### Quickstart Commands

```bash
# 1. Run Exploratory Data Analysis
python notebooks/01_eda.py

# 2. Generate / Refresh Departmental Venue Affinity Rules
python src/csp/affinity.py

# 3. Validate Unary Domains & Pre-Flight Pigeonhole Bounds
python src/csp/domain.py

# 4. Audit Conflict Graph & Raw Ground-Truth Collisions
python src/csp/constraints.py

# 5. Run the CSP Solver & Export Solved Timetables
python src/csp/solver.py

# 6. Launch Interactive Web Visualizer & A4 Landscape PDF Renderer
python src/viz/viewer.py
```
*(You can also open `src/viz/index.html` directly in any browser without starting a server.)*

---

## 6. Roadmap: Phase 4 (Soft-Constraint Local Search & Schedule Compaction)

With Phase 3 delivering a 0-conflict, 100% department-locked initial feasible solution in `< 1.2s`, Phase 4 will add a post-solve **Simulated Annealing / Min-Conflicts Local Search Optimizer** on top of the CSP solution to optimize soft pedagogical quality ($C_{\text{soft}}$):
* **Intra-Day Idle Gap Compaction:** Minimize empty periods between a cohort's first and last class of the day.
* **Evening Twilight Buffer Minimization:** Further reduce `P11–P12` twilight usage by swapping non-conflicting evening blocks into `P13–P18`.
* **Room Stability & Building Clustering:** Minimize mid-day room switches for consecutive lectures taught to the same cohort.
