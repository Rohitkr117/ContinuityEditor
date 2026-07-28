import sqlite3
conn = sqlite3.connect("dev.db")
cursor = conn.cursor()
cursor.execute("SELECT id, canonical_name, attributes_json FROM entities")
print("Entities and current attributes:")
for r in cursor.fetchall():
    print(f"  {r[0]}: {r[1]} -> {r[2]}")
