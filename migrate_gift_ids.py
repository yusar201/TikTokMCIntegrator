#!/usr/bin/env python3
"""
Migrate TikTokMCIntegrator configs from gift-name keys to gift-ID keys.

This script:
  1. Builds a name -> ID map from available_gifts.json
  2. Scans config.yml and all profiles/*.yml
  3. Converts Gifts, GiftCategories, and StreakDeltaGifts to use IDs
  4. Adds a GiftNames section (id -> display_name) for UI display
  5. Reports any gifts that could not be migrated

Run this once before starting the bot after updating to ID-based lookup.
"""

import json
import os
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# BUILD NAME -> ID MAP
# ==========================================
name_to_id = {}
gifts_file = os.path.join(BASE_DIR, "available_gifts.json")
if os.path.exists(gifts_file):
    with open(gifts_file, "r", encoding="utf-8") as f:
        gifts = json.load(f)
    for g in gifts:
        name = str(g.get("name", "")).lower().strip()
        gid = g.get("id")
        if name and gid is not None:
            # Use first occurrence for duplicates
            if name not in name_to_id:
                name_to_id[name] = str(gid)

# Manual overrides for known close matches
MANUAL_OVERRIDES = {
    "bubblegum": "13087",      # "bubble gum"
    "hand heart": "5660",      # "hand hearts"
}
name_to_id.update(MANUAL_OVERRIDES)

# ==========================================
# MIGRATE A SINGLE CONFIG FILE
# ==========================================
def migrate_config(path):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    original_gifts = dict(data.get("Gifts", {}))
    original_cats = dict(data.get("GiftCategories", {}))
    original_streak = list(data.get("StreakDeltaGifts", []))

    new_gifts = {}
    new_cats = {}
    new_names = dict(data.get("GiftNames", {}))
    new_streak = []
    unmigrated = []

    # Migrate Gifts
    for name, commands in original_gifts.items():
        key = str(name).lower().strip()
        gid = name_to_id.get(key)
        if gid:
            new_gifts[gid] = commands
            new_names[gid] = key  # store original lowercase name for display
            if key in original_cats:
                new_cats[gid] = original_cats[key]
        else:
            unmigrated.append(key)
            new_gifts[key] = commands
            if key in original_cats:
                new_cats[key] = original_cats[key]

    # Migrate StreakDeltaGifts
    for name in original_streak:
        key = str(name).lower().strip()
        gid = name_to_id.get(key)
        if gid:
            new_streak.append(gid)
        else:
            new_streak.append(key)

    # Also migrate any GiftCategories entries that don't have matching Gifts
    # (orphaned categories)
    for name, cat in original_cats.items():
        key = str(name).lower().strip()
        gid = name_to_id.get(key)
        if gid:
            if gid not in new_cats:
                new_cats[gid] = cat
        else:
            if key not in new_cats:
                new_cats[key] = cat

    data["Gifts"] = new_gifts
    data["GiftCategories"] = new_cats
    data["StreakDeltaGifts"] = new_streak
    if new_names:
        data["GiftNames"] = new_names

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    return unmigrated

# ==========================================
# RUN MIGRATION
# ==========================================
files = [os.path.join(BASE_DIR, "config.yml")]
profiles_dir = os.path.join(BASE_DIR, "profiles")
if os.path.exists(profiles_dir):
    for fname in sorted(os.listdir(profiles_dir)):
        if fname.endswith(".yml"):
            files.append(os.path.join(profiles_dir, fname))

all_unmigrated = set()
print("=" * 50)
print("Gift ID Migration Report")
print("=" * 50)

for path in files:
    unmigrated = migrate_config(path)
    fname = os.path.basename(path)
    if unmigrated:
        print(f"\n[{fname}] MIGRATED with {len(unmigrated)} unmigrated gift(s):")
        for g in sorted(set(unmigrated)):
            print(f"    - {g!r}")
        all_unmigrated.update(unmigrated)
    else:
        print(f"\n[{fname}] FULLY MIGRATED (all gifts mapped to IDs)")

print("\n" + "=" * 50)
if all_unmigrated:
    print(f"TOTAL UNMIGRATED: {len(all_unmigrated)}")
    print("These gifts remain as name-based keys and will still work via fallback:")
    for g in sorted(all_unmigrated):
        print(f"    - {g!r}")
    print("\nTo fully migrate them, find their TikTok gift IDs and run this script again")
    print("after adding the mappings to MANUAL_OVERRIDES in this script.")
else:
    print("ALL GIFTS SUCCESSFULLY MIGRATED TO IDs!")
print("=" * 50)
