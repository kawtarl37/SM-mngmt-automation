"""
Show current pipeline status: pins, blogs, and publish schedule.

Usage:
    python -m tools.db_status
"""
import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from execution.db import get_connection


def main():
    with get_connection() as conn:
        c = conn.cursor()

        print("=" * 60)
        print("GENERATED PINS (last 15)")
        print("=" * 60)
        c.execute("""
            SELECT pin_id, substr(title,1,40) AS title, status, created_at
            FROM generated_pins
            ORDER BY created_at DESC LIMIT 15
        """)
        rows = c.fetchall()
        for r in rows:
            print(f"  pin_id={r[0]:>3}  status={r[2]:<12}  {r[1]}")

        print()
        print("=" * 60)
        print("BLOGS")
        print("=" * 60)
        c.execute("""
            SELECT blog_id, pin_id, substr(title,1,40) AS title, status, wp_url
            FROM blogs
            ORDER BY blog_id DESC LIMIT 10
        """)
        rows = c.fetchall()
        if rows:
            for r in rows:
                print(f"  blog_id={r[0]:>3}  pin={r[1]:>3}  status={r[3]:<12}  {r[2]}")
                if r[4]:
                    print(f"           wp_url={r[4]}")
        else:
            print("  (no blogs yet)")

        print()
        print("=" * 60)
        print("PUBLISH SCHEDULE")
        print("=" * 60)
        c.execute("""
            SELECT schedule_id, pin_id, scheduled_time, status, completed_at
            FROM publish_schedule
            ORDER BY scheduled_time DESC LIMIT 10
        """)
        rows = c.fetchall()
        if rows:
            for r in rows:
                print(f"  sched_id={r[0]:>3}  pin={r[1]:>3}  time={r[2]}  status={r[3]}")
        else:
            print("  (no scheduled publishes)")

        print()
        print("=" * 60)
        print("APPROVED PINS (ready to schedule / publish)")
        print("=" * 60)
        c.execute("""
            SELECT pin_id, substr(title,1,50) AS title, image_path
            FROM generated_pins
            WHERE status = 'approved'
            ORDER BY created_at ASC
        """)
        rows = c.fetchall()
        if rows:
            for r in rows:
                print(f"  pin_id={r[0]:>3}  {r[1]}")
                print(f"           image={r[2]}")
        else:
            print("  (no approved pins waiting)")


if __name__ == "__main__":
    main()
