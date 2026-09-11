# Refactoring Pitfalls — TikTokMCIntegrator

## Variable Scope After Extracting Helper Functions

When extracting code into a helper function, standalone variables defined INSIDE the helper become undefined in the calling scope. Code that runs AFTER the helper call must use the returned dict.

### Example: _extract_user_info refactor bug

**Before refactor (worked):**
```python
@client.on(CommentEvent)
async def on_comment(event):
    u = _ExtendedUser.from_user(event.user)
    nick = mc_safe(getattr(u, 'nickname', ''))
    uid = getattr(u, 'unique_id', '').lower()
    gifter_level = getattr(u, 'gifter_level', 0)
    is_vip = uid in VIP_LIST
    is_superfan = event.user_is_super_fan
    member_level = getattr(u, 'member_level', 0)
    # ... later in same function:
    user_info = {
        "unique_id": uid,
        "is_vip": is_vip,        # ← worked, variable in scope
        "is_superfan": is_superfan,
    }
    sh.check_permission("play", user_info, tags, gifter_level, member_level)
```

**After refactor (BROKEN):**
```python
def _extract_user_info(event):
    # ... extracts everything into a dict
    return u, nick, uid, comment, user_info

@client.on(CommentEvent)
async def on_comment(event):
    u, nick, uid, comment, user_info = _extract_user_info(event)
    # ... later in same function:
    user_info = {
        "unique_id": uid,
        "is_vip": is_vip,        # ← NameError! Not defined in this scope
        "is_superfan": is_superfan,
    }
    sh.check_permission("play", user_info, tags, gifter_level, member_level)  # ← gifter_level undefined!
```

**Fix:**
```python
@client.on(CommentEvent)
async def on_comment(event):
    u, nick, uid, comment, user_info = _extract_user_info(event)
    # ... later — use the returned dict directly:
    if not sh.check_permission("play", user_info, tags, user_info["gifter_level"], user_info["member_level"]):
        return
```

### Rule

After extracting a helper that returns a dict, search for ALL usages of the old standalone variables in the calling function. Replace with `dict["key"]` access. Common culprits:
- `is_vip`, `is_superfan`, `is_member`, `is_friend`, `is_follower`, `is_mod`
- `gifter_level`, `member_level`
- Any variable that was previously defined inline but now lives inside the helper

### Checklist

When refactoring with helper extraction:
1. Identify what the helper returns
2. Find ALL code AFTER the helper call that references variables now inside the helper
3. Replace standalone variable references with dict access
4. Test the affected commands (don't just test the happy path)
