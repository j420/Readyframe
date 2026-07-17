from pathlib import Path

required = ["agents", "skills", "schemas", "engine", "knowledge", "sites", "fixtures", "harness"]
missing = [name for name in required if not (Path("deploygrade") / name).is_dir()]
if missing:
    raise SystemExit(f"missing scaffold directories: {missing}")
print("audit: scaffold present; readiness signal, not certification")
