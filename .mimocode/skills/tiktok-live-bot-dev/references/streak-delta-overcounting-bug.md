# Streak Delta Over-Counting Bug

## Problem

When a user sends combo gifts really fast (e.g., 1×→2×→5×→7×→10× Roses), TikTok may send each increment with a **DIFFERENT `group_id`**. The current code in `minecraft_main.py` (line ~967) tracks streak state via:

```python
prev = streak_tracker.get(group_id, 0)
delta = repeat_count - prev
```

When `group_id` changes between events, `prev = 0` (new group = fresh start), so `delta = repeat_count - 0 = full count`.

## Symptom

For 5 ice cream cones sent fast:
- Event 1 (count=1, group=A) → delta = 1-0 = **1** totem ✓
- Event 2 (count=2, group=B) → delta = 2-0 = **2** totems ✗ (should be 1)
- Event 3 (count=5, group=C) → delta = 5-0 = **5** totems ✗ (should be 3)

Result: **6+ totems instead of 5** — hence the over-counting reported.

## Root Cause

The code assumes `group_id` is stable across a combo. TikTok doesn't guarantee this when gifts are sent rapidly.

## Fix

Track by `(user_unique_id + gift_id)` instead of `group_id`:

```python
# Get user unique_id from event.user
uid = getattr(u, 'unique_id', '') if u else ''

# Instead of: prev = streak_tracker.get(group_id, 0)
tracker_key = f"{uid}:{gift_id}"  # e.g., "abc123:5827"
prev = streak_tracker.get(tracker_key, 0)
```

This ensures regardless of what `group_id` TikTok sends, events from the same user+gift combo track together.

Also ensure `streak_tracker.clear()` is called on session reset (currently only `active_streaks` is cleared at lines 574-581).