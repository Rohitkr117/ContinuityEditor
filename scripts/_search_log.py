import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

log_path = "C:/Users/HP/.gemini/antigravity-cli/brain/524ca80c-8cd8-4c3a-8776-1fc409ef6563/.system_generated/tasks/task-512.log"
with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
# Find occurrences of 'Sunstone Amulet' or 'Inspector Valen' or 'Contradiction judge'
for i, line in enumerate(lines):
    if "Sunstone Amulet" in line or "Contradiction judge" in line:
        print(f"Line {i+1}: {line.strip()[:150]}")
