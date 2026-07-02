"""Ground truth: every scheduled task that touches this repo -> its action.
Used to verify what scripts are actually WIRED before any cleanup. Laptop."""
import subprocess, csv, io

out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/v"],
                     capture_output=True, text=True, errors="replace").stdout
seen = {}
for row in csv.reader(io.StringIO(out)):
    if len(row) < 10 or row[1] == "TaskName":
        continue
    name = row[1].rsplit("\\", 1)[-1]
    blob = " | ".join(row)
    if "prediction-market" in blob.lower():
        # find the action-ish column (contains path or python)
        action = next((c for c in row if "prediction-market" in c.lower()), "")[:120]
        seen[name] = action
for k in sorted(seen):
    print(f"  {k:26} -> {seen[k]}")
print(f"\n{len(seen)} repo-wired tasks")
