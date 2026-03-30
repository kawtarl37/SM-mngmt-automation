import sqlite3

def display_pins():
    conn = sqlite3.connect('execution/data/egf.db')
    conn.row_factory = sqlite3.Row
    curr = conn.cursor()
    
    with open('pins_output.txt', 'w', encoding='utf-8') as f:
        f.write("--- CONTENT IDEAS ---\n")
        curr.execute('SELECT title, total_score, selected FROM content_ideas ORDER BY total_score DESC LIMIT 5')
        for r in curr.fetchall():
            f.write(f"[{'X' if r['selected'] else ' '}] {r['total_score']:.2f} - {r['title']}\n")
            
        f.write("\n--- GENERATED PINS ---\n")
        curr.execute('SELECT pin_id, title, description, seo_keywords, image_path FROM generated_pins')
        pins = curr.fetchall()
        if not pins:
            f.write("No pins found in generated_pins table!\n")
        for r in pins:
            f.write(f"\nPIN #{r['pin_id']}: {r['title']}\n")
            f.write(f"IMG_PATH: {r['image_path']}\n")
            f.write(f"SEO: {r['seo_keywords']}\n")
            f.write(f"DESC: {r['description']}\n")

if __name__ == "__main__":
    display_pins()
