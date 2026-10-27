import pytest
from pump_sentinel.donations import donation_instructions

ADDRESS = "So11111111111111111111111111111111111111112"


def file(tmp_path, content):
    path = tmp_path / "donations.toml"
    path.write_text(content)
    return str(path)


def test_disabled_has_no_recipient(tmp_path):
    result = donation_instructions(file(tmp_path, 'enabled = false\nrecipient = "suhail777"\n'))
    assert result["enabled"] is False
    assert "recipient" not in result


def test_human_review_required(tmp_path):
    with pytest.raises(ValueError):
        donation_instructions(file(tmp_path, f'enabled = true\nrecipient = "{ADDRESS}"\n'))


def test_enabled_never_executes_or_claims_ownership(tmp_path):
    result = donation_instructions(file(tmp_path, f'enabled = true\nmaintainer_verified = true\nrecipient = "{ADDRESS}"\naccepted_mints = ["{ADDRESS}"]\n'))
    assert result["voluntary"] is True
    assert result["executed_payment"] is False
    assert result["ownership_verified_by_bot"] is False
