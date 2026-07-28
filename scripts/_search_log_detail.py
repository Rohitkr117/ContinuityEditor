log_path = "C:/Users/HP/.gemini/antigravity-cli/brain/524ca80c-8cd8-4c3a-8776-1fc409ef6563/.system_generated/tasks/task-512.log"
with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "Contradiction judge failed" in line:
        print(f"\n--- Line {i+1}: {line.strip()}")
        # Let's print the preceding lines to see what the raw output was
        start = max(0, i - 10)
        end = min(len(lines), i + 1)
        for j in range(start, end):
            print(f"  [{j+1}] {lines[j].strip()}")
