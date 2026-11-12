from pipeline.derive import (
    bucket, build_call, effective_disposition, ist_date, ist_iso, summarize_lead,
)

KNOWN = {"renewed", "callback_requested", "not_interested", "dnd"}
TERMINAL = {"renewed", "not_interested", "dnd"}
SUCCESS = {"renewed"}


def e(event_id, etype, ts="2026-10-05T10:00:00.000000Z", code=None):
    return {"event_id": event_id, "event_type": etype,
            "occurred_at_utc": ts, "code": code}


def call(call_id, initiated, disposition=None, connected=False, failed=False):
    return {"call_id": call_id, "initiated_at": initiated, "connected": connected,
            "telephony_failed": failed, "disposition": disposition}


def test_ist_conversion_crosses_midnight():
    assert ist_date("2026-10-04T20:00:00.000000Z") == "2026-10-05"
    assert ist_date("2026-10-04T18:29:59.000000Z") == "2026-10-04"
    assert ist_iso("2026-10-14T12:25:24.000000Z") == "2026-10-14T17:55:24+05:30"


def test_effective_set_only():
    evs = [e("1", "disposition.set", code="callback_requested")]
    assert effective_disposition(evs, KNOWN) == "callback_requested"


def test_effective_latest_set_wins():
    evs = [e("1", "disposition.set", "2026-10-05T10:00:00.000000Z", "dnd"),
           e("2", "disposition.set", "2026-10-05T11:00:00.000000Z", "callback_requested")]
    assert effective_disposition(evs, KNOWN) == "callback_requested"


def test_effective_override_beats_set():
    evs = [e("1", "disposition.set", "2026-10-05T10:00:00.000000Z", "not_interested"),
           e("2", "disposition.override", "2026-10-05T12:00:00.000000Z", "renewed")]
    assert effective_disposition(evs, KNOWN) == "renewed"


def test_effective_override_wins_even_if_older_than_set():
    evs = [e("1", "disposition.override", "2026-10-05T09:00:00.000000Z", "renewed"),
           e("2", "disposition.set", "2026-10-05T10:00:00.000000Z", "not_interested")]
    assert effective_disposition(evs, KNOWN) == "renewed"


def test_effective_latest_of_two_overrides():
    evs = [e("1", "disposition.override", "2026-10-05T12:00:00.000000Z", "dnd"),
           e("2", "disposition.override", "2026-10-05T13:00:00.000000Z", "renewed")]
    assert effective_disposition(evs, KNOWN) == "renewed"


def test_effective_none_and_unknown_ignored():
    assert effective_disposition([e("1", "call.connected")], KNOWN) is None
    evs = [e("1", "disposition.set", code="renewed"),
           e("2", "disposition.override", "2026-10-05T12:00:00.000000Z", "bogus_code")]
    assert effective_disposition(evs, KNOWN) == "renewed"


def test_call_needs_initiated():
    assert build_call("c1", [e("1", "call.connected")], KNOWN) is None


def test_call_flags():
    evs = [e("1", "call.initiated", "2026-10-05T10:00:00.000000Z"),
           e("2", "call.connected"), e("3", "disposition.set", code="renewed")]
    c = build_call("c1", evs, KNOWN)
    assert c["connected"] is True and c["telephony_failed"] is False
    assert c["disposition"] == "renewed"
    assert c["initiated_at"] == "2026-10-05T10:00:00.000000Z"


def test_bucket_yet_to_reach_out():
    assert bucket([], TERMINAL) == "yet_to_reach_out"


def test_bucket_completed_beats_failed():
    calls = [call("a", "t1", failed=True), call("b", "t2", "renewed")]
    assert bucket(calls, TERMINAL) == "completed"


def test_bucket_all_failed():
    calls = [call("a", "t1", failed=True), call("b", "t2", failed=True)]
    assert bucket(calls, TERMINAL) == "in_progress_telephony_failed"


def test_bucket_mixed_failed_and_dialed():
    calls = [call("a", "t1", failed=True), call("b", "t2", connected=True)]
    assert bucket(calls, TERMINAL) == "in_progress_dialed"


def test_bucket_non_terminal_disposition_is_dialed():
    calls = [call("a", "t1", "callback_requested", connected=True)]
    assert bucket(calls, TERMINAL) == "in_progress_dialed"


def test_summary_current_disposition_and_success():
    calls = [call("a", "2026-10-05T10:00:00.000000Z", "renewed", connected=True),
             call("b", "2026-10-06T10:00:00.000000Z", None, connected=False),
             call("c", "2026-10-07T10:00:00.000000Z", "callback_requested", connected=True)]
    s = summarize_lead(calls, TERMINAL, SUCCESS)
    assert s["current_disposition"] == "callback_requested"   # latest call WITH one
    assert s["ever_success"] is True
    assert s["total_calls"] == 3 and s["connected_calls"] == 2
    assert s["bucket"] == "completed"
    assert s["last_call_at"] == "2026-10-07T15:30:00+05:30"


def test_summary_no_calls():
    s = summarize_lead([], TERMINAL, SUCCESS)
    assert s["bucket"] == "yet_to_reach_out"
    assert s["last_call_at"] == "" and s["current_disposition"] == ""
    assert s["ever_success"] is False