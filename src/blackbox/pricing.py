"""Per-model USD-per-million-token pricing, editable in
~/.blackbox/config.toml (design doc Phase 5).

These default rates are approximate and WILL go stale — blackbox does not
fetch live pricing. Edit config.toml against current Anthropic pricing.
"""

import tomllib
from pathlib import Path

from blackbox.transcript import Usage

CONFIG_PATH = Path.home() / ".blackbox" / "config.toml"

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
    "default": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
}

DEFAULT_CONFIG_TOML = """\
# Blackbox pricing config — USD per MILLION tokens.
# These are approximate defaults and will go stale; verify against current
# Anthropic pricing and edit as needed. blackbox does not fetch live pricing.
# "default" applies to any model id not listed explicitly below.

[pricing."claude-opus-4-8"]
input = 15.0
output = 75.0
cache_write = 18.75
cache_read = 1.50

[pricing."claude-sonnet-5"]
input = 3.0
output = 15.0
cache_write = 3.75
cache_read = 0.30

[pricing."claude-haiku-4-5-20251001"]
input = 0.80
output = 4.0
cache_write = 1.0
cache_read = 0.08

[pricing.default]
input = 3.0
output = 15.0
cache_write = 3.75
cache_read = 0.30

# Desktop notifications on Notification events / long-task completion.
# Off by default — enable explicitly if you want them.
[notifications]
enabled = false
"""


def load_pricing(config_path: Path = CONFIG_PATH) -> dict[str, dict[str, float]]:
    if not config_path.exists():
        return DEFAULT_PRICING
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return DEFAULT_PRICING
    pricing = data.get("pricing")
    if not isinstance(pricing, dict) or "default" not in pricing:
        return DEFAULT_PRICING
    return pricing


def ensure_config_exists(config_path: Path = CONFIG_PATH) -> None:
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(DEFAULT_CONFIG_TOML)


def _rates_for_model(pricing: dict[str, dict[str, float]], model: str | None) -> dict[str, float]:
    if model and model in pricing:
        return pricing[model]
    return pricing.get("default", DEFAULT_PRICING["default"])


def estimate_cost_usd(usage: Usage, pricing: dict[str, dict[str, float]]) -> float:
    rates = _rates_for_model(pricing, usage.model)
    return (
        usage.input_tokens * rates.get("input", 0)
        + usage.output_tokens * rates.get("output", 0)
        + usage.cache_creation_input_tokens * rates.get("cache_write", 0)
        + usage.cache_read_input_tokens * rates.get("cache_read", 0)
    ) / 1_000_000
