# sundial-engine

An institution-agnostic University Course Timetabling Constraint Satisfaction Problem (CSP) engine built from first principles in pure Python 3. Designed to model and solve complex scheduling constraints across Tanzanian higher-learning institutions—starting with **Arusha Technical College (ATC)** as the primary benchmark dataset, and architected to generalize to institutions like DIT, MUST, and UDSM via declarative JSON schemas.

---

## 1. Mathematical Formulation $(X, D, C)$

The timetabling problem is modeled as a discrete Constraint Satisfaction & Optimization Problem:

* **Variables ($X$):** Each of the $N = 1,306$ weekly class sessions is a variable $x_i \in X$ carrying fixed resource requirements:
  * Module code(s) and session type (`Theory` vs. `Lab`)
  * Assigned lecturer(s) (1 to 5 co-lecturers per session)
  * Target student cohort(s) (1 to 6 joint cohorts per session)
  * Stream classification (`Full-Time` vs. `Evening`)
  * Required contiguous duration in periods ($d_i \in \{1, 2, 4, 6\}$)
  * Required normalized venue category
* **Domains ($D$):** For each session $x_i$, its domain $D_i$ consists of valid assignment tuples:
  $$D_i = \{ (\text{Day}, \text{StartPeriod}, \text{Venue}) \}$$
  pre-filtered by unary constraints so that invalid time-blocks and incompatible rooms are pruned before search begins.
* **Constraints ($C = C_{\text{hard}} \cup C_{\text{soft}}$):**
  * **Unary Hard Constraints:** Stream period boundaries, tea/lunch break contiguity preservation, start-period quantization, and normalized venue category matching.
  * **Binary Hard Constraints ($C_{\text{hard}}$):** Zero-overlap time-slot exclusion across any two sessions $x_i, x_j$ sharing at least one lecturer, at least one student cohort, or the same physical venue.
  * **Soft Constraints ($C_{\text{soft}}$):** Evening twilight-buffer avoidance (Periods 11–12), lecturer/cohort daily load balancing, and venue capacity slack optimization.

---

## 2. Benchmark Dataset: Arusha Technical College (ATC)

Extracted and normalized from ATC's live timetable endpoints (`data/raw/atc/`):

| Metric | Count / Specification |
| :--- | :--- |
| **Total Weekly Sessions ($\vert{}X\vert{}$)** | 1,306 (`S0001` – `S1306`) |
| **Programs & NTA Levels** | 29 Programs across 10 NTA Level groupings (Levels 4–8) |
| **Active Student Cohorts** | 123 (with 197 unique joint-cohort combinations) |
| **Active Lecturers** | 175 |
| **Unique Modules** | 498 |
| **Physical Venues** | 75 (Lecture Rooms, Computer Labs, Engineering Labs, Workshops, Studios, Field Sites) |
| **Calendar Grid** | 6 Days (`MONDAY`–`SATURDAY`) $\times$ 18 Periods/Day (45 mins each) |
| **Full-Time Window** | Periods `1–12` (07:30 – 17:55), Tea Break after `P4`, Lunch Break after `P6` |
| **Evening Window** | Periods `13–18` (18:00 – 22:40), with optional twilight buffer in `P11–P12` |

---

## 3. Repository Structure

```text
sundial-engine/
├── configs/
│   └── institution_schema.json   # Declarative institution-agnostic time & constraint rules
├── data/
│   ├── raw/atc/                  # Benchmark datasets (atc-timetable-dataset.json, atc-csp-sessions.json)
│   └── processed/                # Cleaned & solver-ready intermediate artifacts
├── docs/
│   └── EDA_FINDINGS.md           # Empirical constraint discoveries & data anomaly log
├── notebooks/
│   └── 01_eda.py                 # Phase 1 exploratory data analysis & constraint verification
├── src/
│   └── csp/                      # Core pure-Python CSP solver (Domain, Constraints, Search, Heuristics)
├── tests/                        # Unit & constraint validation test suite
└── requirements.txt

# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run Phase 1 Exploratory Data Analysis
python notebooks/01_eda.py