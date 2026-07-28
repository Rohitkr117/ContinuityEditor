import sqlite3
try:
    conn = sqlite3.connect("dev.db")
    cursor = conn.cursor()
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print("Tables:", tables)
    if "projects" in tables:
        cursor.execute("SELECT id, title FROM projects")
        print("Projects:", cursor.fetchall())
    if "chapters" in tables:
        cursor.execute("SELECT id, project_id, number, title FROM chapters")
        print("Chapters:", cursor.fetchall())
    if "contradictions" in tables:
        cursor.execute("SELECT id, project_id, field, value_a, value_b, severity, quote_a, quote_b, reason FROM contradictions")
        print("Contradictions:")
        for r in cursor.fetchall():
            print(" ", r)
except Exception as e:
    print("Error:", e)
