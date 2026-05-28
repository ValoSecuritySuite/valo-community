"""Tests for the YAML-backed governance policy store."""

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from app.core.config import settings
from app.schemas import Policy, PolicyAction, PolicyCondition
from app.services import policy_store as store


@pytest.fixture(autouse=True)
def _isolated_policies_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the store at a temp directory and reset its cache for every test."""
    target = tmp_path / "policies"
    monkeypatch.setattr(settings, "policies_path", target)
    store.clear_policies_cache()
    yield target
    store.clear_policies_cache()


def _make_policy(policy_id: str = "p1", decision: str = "warn") -> Policy:
    return Policy(
        id=policy_id,
        name=f"Policy {policy_id}",
        when=[PolicyCondition(field="x", op="eq", value=1)],
        then=PolicyAction(decision=decision, severity=4, message="match"),
        tags=["test"],
    )


def test_list_policies_empty_when_dir_missing(_isolated_policies_dir: Path) -> None:
    assert store.list_policies() == []


def test_save_and_get_round_trip(_isolated_policies_dir: Path) -> None:
    saved = store.save_policy(_make_policy("alpha"))
    assert saved.id == "alpha"
    assert isinstance(saved.updated_at, datetime)

    fetched = store.get_policy("alpha")
    assert fetched is not None
    assert fetched.id == "alpha"
    assert fetched.then.decision == "warn"


def test_save_writes_yaml_file_at_expected_path(_isolated_policies_dir: Path) -> None:
    store.save_policy(_make_policy("on-disk"))
    expected = _isolated_policies_dir / "on-disk.yml"
    assert expected.exists()
    payload = yaml.safe_load(expected.read_text(encoding="utf-8"))
    assert payload["id"] == "on-disk"
    assert payload["then"]["decision"] == "warn"


def test_list_policies_returns_all_saved(_isolated_policies_dir: Path) -> None:
    store.save_policy(_make_policy("a"))
    store.save_policy(_make_policy("b", decision="deny"))
    ids = sorted(p.id for p in store.list_policies())
    assert ids == ["a", "b"]


def test_delete_policy_removes_file(_isolated_policies_dir: Path) -> None:
    store.save_policy(_make_policy("doomed"))
    assert (_isolated_policies_dir / "doomed.yml").exists()
    assert store.delete_policy("doomed") is True
    assert not (_isolated_policies_dir / "doomed.yml").exists()
    assert store.get_policy("doomed") is None


def test_delete_missing_policy_returns_false(_isolated_policies_dir: Path) -> None:
    assert store.delete_policy("ghost") is False


def test_get_policy_fingerprints_changes_when_decision_changes(
    _isolated_policies_dir: Path,
) -> None:
    store.save_policy(_make_policy("fp", decision="warn"))
    before = store.get_policy_fingerprints(store.load_policies(use_cache=False))

    store.save_policy(_make_policy("fp", decision="deny"))
    after = store.get_policy_fingerprints(store.load_policies(use_cache=False))

    assert before["fp"] != after["fp"]


def test_save_invalidates_cache(_isolated_policies_dir: Path) -> None:
    store.save_policy(_make_policy("cached"))
    first = store.load_policies(use_cache=True)
    assert {p.id for p in first.policies} == {"cached"}

    store.save_policy(_make_policy("second", decision="deny"))
    second = store.load_policies(use_cache=True)
    assert {p.id for p in second.policies} == {"cached", "second"}


def test_invalid_yaml_in_directory_raises_service_error(
    _isolated_policies_dir: Path,
) -> None:
    _isolated_policies_dir.mkdir(parents=True, exist_ok=True)
    (_isolated_policies_dir / "broken.yml").write_text(": : :", encoding="utf-8")
    from app.core.exceptions import ServiceError

    with pytest.raises(ServiceError):
        store.load_policies(use_cache=False)
