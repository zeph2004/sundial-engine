import json
from pathlib import Path
import pandas as pd

# 1. Point to the raw ATC files relative to project root
RAW_DIR = Path("data/raw/atc")
SESSIONS_PATH = RAW_DIR / "atc-csp-sessions.json"
DATASET_PATH = RAW_DIR / "atc-timetable-dataset.json"

# 2. Load the JSONs
with open(SESSIONS_PATH, "r") as f:
    sessions_data = json.load(f)

with open(DATASET_PATH, "r") as f:
    dataset_data = json.load(f)

# 3. Flatten sessions into a DataFrame (turns groundTruth.startPeriod into a column)
df_sessions = pd.json_normalize(sessions_data["sessions"])
df_venues = pd.DataFrame(dataset_data["venues"])

print(f"Loaded {len(df_sessions)} sessions and {len(df_venues)} venues.")
print("\nSession Columns:")
print(df_sessions.columns.tolist())

# 4. Stream vs. Period boundary checks
inspect_cols = [
    "sessionId",
    "moduleCode",
    "cohortRaw",
    "isEveningStream",
    "sessionType",
    "groundTruth.scheduledDay",
    "durationPeriods",
    "groundTruth.startPeriod",
    "groundTruth.endPeriod",
]

# Early Evening Sessions: isEveningStream == True, but groundTruth.startPeriod < 13
early_evening = df_sessions[
    (df_sessions["isEveningStream"] == True) & (df_sessions["groundTruth.startPeriod"] < 13)
]
print(f"\nEarly Evening Sessions (isEveningStream == True & startPeriod < 13): {len(early_evening)}")
if len(early_evening) > 0:
    print(early_evening[inspect_cols].to_string(index=False))

# Late Full-Time Sessions: isEveningStream == False, but groundTruth.endPeriod > 12
late_full_time = df_sessions[
    (df_sessions["isEveningStream"] == False) & (df_sessions["groundTruth.endPeriod"] > 12)
]
print(f"\nLate Full-Time Sessions (isEveningStream == False & endPeriod > 12): {len(late_full_time)}")
if len(late_full_time) > 0:
    print(late_full_time[inspect_cols].to_string(index=False))

# --- Q2: Break Crossings & Valid Start Periods by Duration ---
# Tea break is between 4 & 5; Lunch break is between 6 & 7; Stream boundary is between 12 & 13
crosses_tea = df_sessions[(df_sessions['groundTruth.startPeriod'] <= 4) & (df_sessions['groundTruth.endPeriod'] >= 5)]
crosses_lunch = df_sessions[(df_sessions['groundTruth.startPeriod'] <= 6) & (df_sessions['groundTruth.endPeriod'] >= 7)]
print(f"\n--- Q2: Break Crossings ---")
print(f"Crosses Tea Break (4->5): {len(crosses_tea)}")
print(f"Crosses Lunch Break (6->7): {len(crosses_lunch)}")

print("\nLegal Start Periods by Duration (Stream=False vs True):")
print(df_sessions.groupby(['isEveningStream', 'durationPeriods'])['groundTruth.startPeriod'].unique())

# --- Q3: Multi-Lecturer & Joint-Cohort Bottlenecks ---
print(f"\n--- Q3: Bottlenecks ---")
print(f"Max lecturers in a single session: {df_sessions['lecturers'].str.len().max()}")
print(f"Max cohorts in a single session: {df_sessions['targetCohorts'].str.len().max()}")

# --- Q4: Venue Category vs Upstream Venue Type Mismatches ---
print(f"\n--- Q4: Venue Mismatches ---")
print(pd.crosstab(df_sessions['requiredVenueCategory'], df_sessions['groundTruth.venueUpstreamType']))