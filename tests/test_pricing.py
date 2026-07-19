from agentdeck.pricing import (
    DEFAULT_CONFIG_TOML,
    DEFAULT_PRICING,
    Usage,
    ensure_config_exists,
    estimate_cost_usd,
    load_pricing,
)


def test_load_pricing_falls_back_to_default_when_missing(tmp_path):
    pricing = load_pricing(tmp_path / "does-not-exist.toml")
    assert pricing == DEFAULT_PRICING


def test_load_pricing_falls_back_on_invalid_toml(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("not valid [[[ toml")
    assert load_pricing(config) == DEFAULT_PRICING


def test_load_pricing_falls_back_when_no_default_rate(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[pricing."claude-sonnet-5"]\ninput = 1.0\noutput = 2.0\n')
    assert load_pricing(config) == DEFAULT_PRICING


def test_load_pricing_reads_custom_rates(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[pricing.default]\ninput = 1.0\noutput = 2.0\ncache_write = 1.5\ncache_read = 0.1\n'
    )
    pricing = load_pricing(config)
    assert pricing["default"]["input"] == 1.0


def test_ensure_config_exists_writes_default_once(tmp_path):
    config = tmp_path / "config.toml"
    assert not config.exists()
    ensure_config_exists(config)
    assert config.exists()
    assert config.read_text() == DEFAULT_CONFIG_TOML

    # doesn't clobber a subsequently user-edited file
    config.write_text("# user edited\n[pricing.default]\ninput = 99.0\n")
    ensure_config_exists(config)
    assert "99.0" in config.read_text()


def test_estimate_cost_uses_known_model_rates():
    usage = Usage(
        model="claude-sonnet-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    cost = estimate_cost_usd(usage, DEFAULT_PRICING)
    expected = DEFAULT_PRICING["claude-sonnet-5"]["input"] + DEFAULT_PRICING["claude-sonnet-5"]["output"]
    assert cost == expected


def test_estimate_cost_falls_back_to_default_for_unknown_model():
    usage = Usage(model="some-future-model-not-in-table", input_tokens=1_000_000)
    cost = estimate_cost_usd(usage, DEFAULT_PRICING)
    assert cost == DEFAULT_PRICING["default"]["input"]


def test_estimate_cost_accounts_for_cache_read_and_write_separately():
    usage = Usage(
        model="claude-sonnet-5",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    cost = estimate_cost_usd(usage, DEFAULT_PRICING)
    rates = DEFAULT_PRICING["claude-sonnet-5"]
    assert cost == rates["cache_write"] + rates["cache_read"]


def test_estimate_cost_zero_usage_is_free():
    usage = Usage(model="claude-sonnet-5")
    assert estimate_cost_usd(usage, DEFAULT_PRICING) == 0.0
