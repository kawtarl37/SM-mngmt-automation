"""
Publish Scheduler
-----------------
Manages the 3-per-day publish cadence (US/Eastern, 8 AM / 12 PM / 4 PM).

Two public functions:
  - schedule_approved_pins()  → assign time slots to newly approved pins
  - run_scheduled_publishes() → execute any slots whose time has arrived
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from execution.config import (
    PUBLISH_TIMEZONE,
    DAILY_PUBLISH_COUNT,
    PUBLISH_INTERVAL_HOURS,
    PUBLISH_START_HOUR,
)
from execution.db import get_connection
from execution.content.blog_generator import generate_blog
from execution.content.wordpress_publisher import publish_blog_to_wp
from execution.content.pinterest_publisher import post_pin_to_pinterest
from execution.utils.logger import setup_logger

logger = setup_logger("publish_scheduler")
TZ = ZoneInfo(PUBLISH_TIMEZONE)


# ──────────────────────────────────────────────
# Time slot calculation
# ──────────────────────────────────────────────

def _get_todays_slots() -> list[datetime]:
    """
    Return the 3 daily publish slots in UTC for today (US/Eastern).
    Slots: PUBLISH_START_HOUR, +PUBLISH_INTERVAL_HOURS, +PUBLISH_INTERVAL_HOURS
    e.g. 8 AM, 12 PM, 4 PM Eastern → converted to UTC.
    """
    now_local = datetime.now(TZ)
    today = now_local.date()

    slots = []
    for i in range(DAILY_PUBLISH_COUNT):
        hour = PUBLISH_START_HOUR + (i * PUBLISH_INTERVAL_HOURS)
        local_dt = datetime(today.year, today.month, today.day,
                            hour, 0, 0, tzinfo=TZ)
        utc_dt = local_dt.astimezone(timezone.utc)
        slots.append(utc_dt)
    return slots


def _get_taken_slots_today() -> list[str]:
    """Return UTC scheduled_times already assigned today."""
    now_utc = datetime.now(timezone.utc)
    day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = now_utc.replace(hour=23, minute=59, second=59).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT scheduled_time FROM publish_schedule
            WHERE scheduled_time BETWEEN ? AND ?
        """, (day_start, day_end))
        return [row["scheduled_time"] for row in cursor.fetchall()]


def _next_available_slot() -> datetime | None:
    """
    Find the next available publish slot (today or future days).
    Searches up to 7 days ahead.
    """
    now_utc = datetime.now(timezone.utc)

    for day_offset in range(7):
        target_date = (now_utc + timedelta(days=day_offset)).date()
        for i in range(DAILY_PUBLISH_COUNT):
            hour = PUBLISH_START_HOUR + (i * PUBLISH_INTERVAL_HOURS)
            local_dt = datetime(target_date.year, target_date.month, target_date.day,
                                hour, 0, 0, tzinfo=TZ)
            utc_dt = local_dt.astimezone(timezone.utc)

            # Skip slots in the past (with 5-min buffer)
            if utc_dt < now_utc - timedelta(minutes=5):
                continue

            # Check if slot is taken
            slot_str = utc_dt.isoformat()
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM publish_schedule
                    WHERE scheduled_time = ? AND status != 'failed'
                """, (slot_str,))
                count = cursor.fetchone()[0]

            if count == 0:
                return utc_dt

    logger.warning("No available publish slots found in the next 7 days.")
    return None


# ──────────────────────────────────────────────
# Schedule approved pins
# ──────────────────────────────────────────────

def schedule_approved_pins():
    """
    Find all approved pins that don't yet have a schedule entry,
    and assign them the next available time slot.
    Called from the dashboard when a pin is approved.
    """
    # Find approved pins without a schedule
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.pin_id FROM generated_pins p
            WHERE p.status = 'approved'
            AND p.pin_id NOT IN (SELECT pin_id FROM publish_schedule)
        """)
        unscheduled = [row["pin_id"] for row in cursor.fetchall()]

    if not unscheduled:
        logger.info("No unscheduled approved pins found.")
        return

    for pin_id in unscheduled:
        slot = _next_available_slot()
        if not slot:
            logger.error("Could not find a free publish slot. Stopping scheduling.")
            break

        slot_str = slot.isoformat()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO publish_schedule (pin_id, scheduled_time, status)
                VALUES (?, ?, 'pending')
            """, (pin_id, slot_str))
            conn.commit()

        # Format for display in US Eastern
        local_slot = slot.astimezone(TZ).strftime("%Y-%m-%d %I:%M %p %Z")
        logger.info(f"Scheduled pin_id={pin_id} for {local_slot}")


# ──────────────────────────────────────────────
# Execute due publishes
# ──────────────────────────────────────────────

def execute_single_publish(pin_id: int):
    """
    Execute the full publishing chain for a single pin.
    If the blog is already generated, it uses it. Otherwise, it generates it.
    Publishes to WP and then to Pinterest.
    """
    logger.info(f"Executing single publish for pin_id={pin_id}")

    try:
        # Step 1: Check if blog already exists, else generate
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT blog_id FROM blogs WHERE pin_id = ? ORDER BY blog_id DESC LIMIT 1", (pin_id,))
            blog_row = cursor.fetchone()
            
        if blog_row:
            blog_id = blog_row["blog_id"]
            logger.info(f"Using existing blog_id={blog_id} for pin_id={pin_id}")
        else:
            blog = generate_blog(pin_id)
            if not blog:
                raise RuntimeError("Blog generation returned None.")
            blog_id = blog["blog_id"]

        # Step 2: Publish to WordPress
        wp_result = publish_blog_to_wp(blog_id)
        if not wp_result:
            raise RuntimeError("WordPress publishing returned None.")

        # Step 3: Post to Pinterest
        pinterest_result = post_pin_to_pinterest(
            pin_id=pin_id,
            wp_url=wp_result["wp_url"],
            media_url=wp_result["media_url"],
        )
        if not pinterest_result:
            raise RuntimeError("Pinterest posting returned None.")

        now = datetime.now(timezone.utc).isoformat()
        
        # Mark pin as posted in generated_pins
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE generated_pins SET status = 'posted' WHERE pin_id = ?", (pin_id,))
            
            # Update publish_schedule if it exists
            cursor.execute("""
                UPDATE publish_schedule
                SET status = 'published', blog_id = ?, completed_at = ?
                WHERE pin_id = ? AND status = 'pending'
            """, (blog_id, now, pin_id))
            
            conn.commit()

        logger.info(
            f"✅ Published: pin_id={pin_id} | "
            f"blog={wp_result['wp_url']} | "
            f"pinterest_id={pinterest_result['pinterest_id']}"
        )
        
        return True

    except Exception as e:
        logger.error(f"❌ Publish failed for pin_id={pin_id}: {e}", exc_info=True)
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE publish_schedule
                SET status = 'failed', error_message = ?
                WHERE pin_id = ? AND status = 'pending'
            """, (str(e), pin_id))
            conn.commit()
        return False

def run_scheduled_publishes():
    """
    Check for any publish_schedule entries due now and execute the full chain:
        generate blog → publish to WP → post to Pinterest.
    Run this on a cron/loop (e.g. every 5 minutes).
    """
    now_utc = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT schedule_id, pin_id FROM publish_schedule
            WHERE status = 'pending' AND scheduled_time <= ?
            ORDER BY scheduled_time ASC
        """, (now_utc,))
        due = [dict(row) for row in cursor.fetchall()]

    if not due:
        logger.info("No scheduled publishes due right now.")
        return

    for entry in due:
        schedule_id = entry["schedule_id"]
        pin_id = entry["pin_id"]
        logger.info(f"Executing scheduled publish: schedule_id={schedule_id}, pin_id={pin_id}")
        execute_single_publish(pin_id)


if __name__ == "__main__":
    run_scheduled_publishes()
