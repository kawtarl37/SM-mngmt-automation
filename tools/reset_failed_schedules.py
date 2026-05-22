"""
Reset failed publish schedule entries to 'pending' and re-run the scheduler.

Usage:
    python -m tools.reset_failed_schedules
"""
import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from execution.db import get_connection
from execution.content.publish_scheduler import run_scheduled_publishes
from datetime import datetime, timezone


def main():
    print("=" * 60)
    print("STEP 1: Reset failed schedule entries to pending")
    print("=" * 60)

    with get_connection() as conn:
        c = conn.cursor()

        # Reset failed entries
        c.execute("""
            UPDATE publish_schedule
            SET status = 'pending', error_message = NULL
            WHERE status = 'failed'
        """)
        reset_count = c.rowcount
        conn.commit()
        print(f"  Reset {reset_count} failed entries back to 'pending'")

        # Show pending entries
        c.execute("""
            SELECT schedule_id, pin_id, scheduled_time, status
            FROM publish_schedule
            WHERE status = 'pending'
            ORDER BY scheduled_time ASC
        """)
        pending = c.fetchall()
        print(f"\n  Pending entries to process ({len(pending)} total):")
        for r in pending:
            print(f"    sched_id={r[0]}  pin={r[1]}  time={r[2]}  status={r[3]}")

    print()
    print("=" * 60)
    print("STEP 2: Run scheduled publishes")
    print("=" * 60)
    print(f"  Current UTC time: {datetime.now(timezone.utc).isoformat()}")
    print()

    run_scheduled_publishes()

    print()
    print("=" * 60)
    print("STEP 3: Final status check")
    print("=" * 60)

    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT s.schedule_id, s.pin_id, s.status, s.completed_at, s.error_message,
                   b.wp_url
            FROM publish_schedule s
            LEFT JOIN blogs b ON s.blog_id = b.blog_id
            ORDER BY s.schedule_id
        """)
        rows = c.fetchall()
        for r in rows:
            print(f"  sched_id={r[0]}  pin={r[1]}  status={r[2]}")
            if r[3]:
                print(f"    completed_at={r[3]}")
            if r[5]:
                print(f"    wp_url={r[5]}")
            if r[4]:
                print(f"    error={r[4]}")


if __name__ == "__main__":
    main()
