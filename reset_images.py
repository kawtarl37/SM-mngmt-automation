"""Reset image_path to NULL for all pending pins so they get regenerated."""
import sqlite3

conn = sqlite3.connect('execution/data/egf.db')
c = conn.cursor()
c.execute("UPDATE generated_pins SET image_path = NULL WHERE status = 'pending'")
conn.commit()
print(f"Reset {c.rowcount} pins for regeneration.")
conn.close()
