"""Independent roulette prize data. No I/O and never writes gift actions."""
import copy
import math
from urllib.parse import urlsplit


def safe_icon(value):
    value = str(value or '').strip()
    if value.startswith('/static/') and '\\' not in value and '..' not in value:
        return value
    parsed = urlsplit(value)
    return value if parsed.scheme == 'https' and parsed.netloc and not parsed.username else ''


def validate_actions(actions, depth=0):
    if not isinstance(actions, list) or not actions or len(actions) > 200 or depth > 8:
        raise ValueError('Provide 1–200 actions; nested random depth is limited to 8')
    result = []
    for raw in actions:
        action = {'type':'minecraft','command':raw} if isinstance(raw, str) else copy.deepcopy(raw)
        if not isinstance(action, dict):
            raise ValueError('Each action must be an action object')
        kind = action.get('type', 'minecraft')
        if kind not in ('minecraft','sound','webhook','random'):
            raise ValueError(f'Unsupported prize action: {kind}; roulette cannot trigger itself')
        if kind == 'minecraft' and not str(action.get('command') or '').strip():
            raise ValueError('Minecraft action needs a command')
        if kind == 'sound' and not (action.get('file') or action.get('url')):
            raise ValueError('Sound action needs a file or URL')
        if kind == 'webhook' and not action.get('url'):
            raise ValueError('Webhook action needs a URL')
        if kind == 'random':
            action['actions'] = validate_actions(action.get('actions'), depth + 1)
        if 'delay' in action:
            try:
                delay = float(action['delay'])
            except (TypeError, ValueError):
                raise ValueError('Action delay must be a nonnegative number') from None
            if not math.isfinite(delay) or delay < 0:
                raise ValueError('Action delay must be a nonnegative number')
        result.append(action)
    return result


def validate_prizes(prizes):
    if not isinstance(prizes, list) or len(prizes) > 100:
        raise ValueError('Prize pool must be a list of at most 100 prizes')
    result, seen = [], set()
    for raw in prizes:
        if not isinstance(raw, dict):
            raise ValueError('Each prize must be an object')
        pid = str(raw.get('id') or '').strip()
        name = str(raw.get('name') or '').strip()
        if not pid or len(pid) > 100 or not name or len(name) > 160:
            raise ValueError('Each prize needs an ID and a name (up to 160 characters)')
        if pid in seen:
            raise ValueError('Duplicate prize ID')
        seen.add(pid)
        # Disabled repair drafts must round-trip without blocking other edits.
        # Re-enabling requires full validation; resolve_entries never executes them.
        if raw.get('enabled', True) is False:
            actions = copy.deepcopy(raw.get('actions', []))
        else:
            actions = validate_actions(raw.get('actions'))
        try:
            coins = max(0, int(raw.get('diamond_count') or 0))
        except (TypeError, ValueError):
            raise ValueError('Prize coin value must be a whole number') from None
        result.append(dict(id=pid, name=name, icon_url=safe_icon(raw.get('icon_url')),
                           enabled=raw.get('enabled', True) is not False, actions=actions,
                           source_gift_id=str(raw.get('source_gift_id') or ''),
                           source_gift_name=str(raw.get('source_gift_name') or ''), diamond_count=coins))
    return result


def migrate_prize_config(profile, catalog):
    from gift_roulette import normalize_config, resolve_entries, _resolve_gift_key
    cfg = normalize_config(profile.get('Roulette'))
    if 'prizes' in cfg:
        return cfg
    gifts = {str(k): v for k,v in (profile.get('Gifts') or {}).items()}
    names, descriptions = profile.get('GiftNames') or {}, profile.get('GiftDescriptions') or {}
    entries = {e['gift_id']:e for e in resolve_entries(cfg,gifts,names,descriptions,catalog)}
    prizes = []
    for gid in cfg['pool']:
        entry = entries.get(gid)
        key = _resolve_gift_key(gid,gifts,catalog)
        actions = copy.deepcopy(gifts.get(key) or [])
        # Missing/unsupported legacy bundles stay visible and disabled for repair.
        try:
            actions = validate_actions(actions)
            enabled = True
        except ValueError:
            enabled = False
        row = catalog.get(gid) or {}
        prizes.append(dict(id='gift-'+gid, name=(entry or {}).get('label') or names.get(gid) or f'Gift #{gid}',
                           icon_url=safe_icon((entry or {}).get('icon_url')), actions=actions, enabled=enabled,
                           source_gift_id=gid, source_gift_name=names.get(gid) or row.get('name') or f'Gift #{gid}',
                           diamond_count=(entry or {}).get('diamond_count',0)))
    cfg.update(prizes=prizes, schema_version=2)
    if sum(p['enabled'] for p in prizes) < 2:
        cfg['enabled'] = False
    return cfg
