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