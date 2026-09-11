# v7 Alpha: log_id Validation Bug Fix

## Error

```
Bot stopped or encountered an error: 1 validation error for WebcastPushFrame
log_id
  Input should be greater than or equal to 0 [type=greater_than_equal, input_value=-1, input_type=int]
```

## Cause

`TikTokLiveProto` v3 `WebcastPushFrame.log_id` has Pydantic `Field(ge=0)` but TikTok's servers sometimes send `-1` for this field.

## Fix

File: `TikTokLiveProto/v3/webcast/im/__init__.py` line 1625

**Before:**
```python
log_id: "typing.Annotated[int, pydantic.Field(ge=0, le=2**64 - 1)]" = (
```

**After:**
```python
log_id: "typing.Annotated[int, pydantic.Field(ge=-1, le=2**64 - 1)]" = (
```

## One-liner (run from Windows terminal)

```bash
python -c "import TikTokLiveProto, os; f=os.path.join(os.path.dirname(TikTokLiveProto.__file__),'v3/webcast/im/__init__.py'); c=open(f).read(); open(f,'w').write(c.replace('ge=0, le=2','ge=-1, le=2')); print('PATCHED')"
```

## Status

- GitHub issue: https://github.com/isaackogan/TikTokLive/issues/361 (open as of 2026-04-30)
- Remove this monkey-patch after upgrading to a version that includes the fix.
