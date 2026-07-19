from blackbox.events import SessionRegistry


def test_add_usage_accumulates_across_calls():
    registry = SessionRegistry()
    registry.add_usage("s1", input_tokens=100, output_tokens=50, cache_write_tokens=0,
                        cache_read_tokens=0, cost_usd=0.01, bucket_now=1000.0)
    registry.add_usage("s1", input_tokens=200, output_tokens=25, cache_write_tokens=10,
                        cache_read_tokens=5, cost_usd=0.02, bucket_now=1000.0)

    info = registry.get("s1")
    assert info.input_tokens == 300
    assert info.output_tokens == 75
    assert info.cache_write_tokens == 10
    assert info.cache_read_tokens == 5
    assert round(info.cost_usd, 4) == 0.03


def test_add_usage_creates_session_if_not_seen_via_hook_events_yet():
    registry = SessionRegistry()
    assert registry.get("s1") is None
    registry.add_usage("s1", 10, 5, 0, 0, 0.001, bucket_now=1000.0)
    assert registry.get("s1") is not None


def test_tokens_per_minute_series_buckets_by_minute():
    registry = SessionRegistry()
    now = 1_000_000.0  # arbitrary epoch, minute-aligned math only matters relatively
    registry.add_usage("s1", 100, 0, 0, 0, 0.0, bucket_now=now)
    registry.add_usage("s1", 50, 0, 0, 0, 0.0, bucket_now=now)  # same minute
    registry.add_usage("s1", 20, 0, 0, 0, 0.0, bucket_now=now - 60)  # previous minute

    series = registry.tokens_per_minute_series("s1", now, window_minutes=5)
    assert series[-1] == 150  # current minute
    assert series[-2] == 20  # previous minute
    assert series[0] == 0  # empty older minute


def test_tokens_per_minute_series_unknown_session_is_all_zero():
    registry = SessionRegistry()
    series = registry.tokens_per_minute_series("nope", 1000.0, window_minutes=10)
    assert series == [0.0] * 10
