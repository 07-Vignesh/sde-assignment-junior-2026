from datetime import datetime, timezone

from .normalize import IST

# An "event" here is a plain dict with these keys:
#   event_id, event_type, occurred_at_utc (fixed-width UTC string), code (or None)


def _key(e):
    """Sort key: time first, event_id as a deterministic tie-break.
    An event with no parseable time sorts as the earliest."""
    return (e.get("occurred_at_utc") or "", e["event_id"])


def utc_to_ist(ts):
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def ist_date(ts):
    return utc_to_ist(ts).date().isoformat()


def ist_iso(ts):
    return utc_to_ist(ts).isoformat(timespec="seconds")


def effective_disposition(events, known_codes):
    """Effective disposition of ONE call.
    Latest override wins; otherwise latest set; otherwise None.
    Disposition events with a code not in known_codes are ignored."""
    def usable(kind):
        return [e for e in events
                if e["event_type"] == kind and e.get("code") in known_codes]

    overrides = usable("disposition.override")
    if overrides:
        return max(overrides, key=_key)["code"]
    sets = usable("disposition.set")
    if sets:
        return max(sets, key=_key)["code"]
    return None


def build_call(call_id, events, known_codes):
    """Build one call from its linked events, or None if it must not be counted.
    A call is counted only if it has a call.initiated event with a valid time."""
    initiated = sorted(
        (e for e in events
         if e["event_type"] == "call.initiated" and e.get("occurred_at_utc")),
        key=_key)
    if not initiated:
        return None
    types = {e["event_type"] for e in events}
    return {
        "call_id": call_id,
        "initiated_at": initiated[0]["occurred_at_utc"],   # earliest initiated
        "connected": "call.connected" in types,
        "telephony_failed": "call.telephony_failed" in types,
        "disposition": effective_disposition(events, known_codes),
    }


def bucket(calls, terminal_codes):
    if not calls:
        return "yet_to_reach_out"
    if any(c["disposition"] in terminal_codes for c in calls):
        return "completed"
    if all(c["telephony_failed"] for c in calls):
        return "in_progress_telephony_failed"
    return "in_progress_dialed"


def summarize_lead(calls, terminal_codes, success_codes):
    """Everything lead_report.csv needs, except the lead's own fields."""
    calls = sorted(calls, key=lambda c: (c["initiated_at"], c["call_id"]))
    with_disp = [c for c in calls if c["disposition"] is not None]
    return {
        "bucket": bucket(calls, terminal_codes),
        "total_calls": len(calls),
        "connected_calls": sum(1 for c in calls if c["connected"]),
        "last_call_at": ist_iso(calls[-1]["initiated_at"]) if calls else "",
        "current_disposition": with_disp[-1]["disposition"] if with_disp else "",
        "ever_success": any(c["disposition"] in success_codes for c in calls),
    }