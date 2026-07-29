from __future__ import annotations

import pytest

from src.domain.models.enums import WorkflowStatus
from src.domain.models.state import TripState
from src.domain.state_repository_errors import StateConflictError, StateNotFoundError
from src.infrastructure.persistence.in_memory import InMemoryStateRepository
from src.ports.state_repository import StateRepository


def _state(*, trip_id: str = "trip-1", version: int = 1) -> TripState:
    return TripState(trip_id=trip_id, session_id=f"session-{trip_id}", version=version)


def test_in_memory_repository_implements_port_and_isolates_state_copies() -> None:
    repository = InMemoryStateRepository()
    assert isinstance(repository, StateRepository)

    created = repository.create(_state())
    loaded = repository.get("trip-1")

    assert loaded == created
    assert loaded is not created
    assert loaded.model_dump() == created.model_dump()


def test_in_memory_repository_rejects_duplicate_create_and_missing_state() -> None:
    repository = InMemoryStateRepository()
    repository.create(_state())

    with pytest.raises(StateConflictError, match="expected 0, actual 1"):
        repository.create(_state())
    with pytest.raises(StateNotFoundError, match="trip-unknown"):
        repository.get("trip-unknown")
    with pytest.raises(StateNotFoundError, match="trip-unknown"):
        repository.list_checkpoints("trip-unknown")


def test_in_memory_repository_saves_only_the_expected_next_version() -> None:
    repository = InMemoryStateRepository()
    repository.create(_state())
    next_state = repository.get("trip-1").transition_to(WorkflowStatus.CLARIFYING)

    saved = repository.save(next_state, expected_version=1)

    assert saved.version == 2
    assert saved.status is WorkflowStatus.CLARIFYING
    with pytest.raises(ValueError, match="expected_version \\+ 1"):
        repository.save(_state(version=3), expected_version=1)


def test_in_memory_repository_rejects_stale_concurrent_save() -> None:
    repository = InMemoryStateRepository()
    repository.create(_state())
    first_update = repository.get("trip-1").transition_to(WorkflowStatus.CLARIFYING)
    second_update = repository.get("trip-1").transition_to(WorkflowStatus.CLARIFYING)
    repository.save(first_update, expected_version=1)

    with pytest.raises(StateConflictError, match="expected 1, actual 2"):
        repository.save(second_update, expected_version=1)


def test_in_memory_repository_retains_configured_number_of_checkpoints() -> None:
    repository = InMemoryStateRepository(max_checkpoints_per_trip=3)
    repository.create(_state())

    for _ in range(4):
        repository.checkpoint("trip-1")

    checkpoints = repository.list_checkpoints("trip-1")
    assert len(checkpoints) == 3
    assert all(item.trip_id == "trip-1" for item in checkpoints)
    assert all(item.state.version == 1 for item in checkpoints)
    assert len({item.checkpoint_id for item in checkpoints}) == 3


def test_in_memory_repository_checkpoint_is_a_detached_snapshot() -> None:
    repository = InMemoryStateRepository()
    repository.create(_state())
    checkpoint = repository.checkpoint("trip-1")
    repository.save(
        repository.get("trip-1").transition_to(WorkflowStatus.CLARIFYING),
        expected_version=1,
    )

    loaded = repository.list_checkpoints("trip-1")[0]
    assert loaded is not checkpoint
    assert loaded.state.version == 1
    assert loaded.state.status is WorkflowStatus.COLLECTING


def test_repositories_are_isolated_instances() -> None:
    first = InMemoryStateRepository()
    second = InMemoryStateRepository()
    first.create(_state())

    with pytest.raises(StateNotFoundError):
        second.get("trip-1")


def test_in_memory_repository_requires_positive_checkpoint_retention() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        InMemoryStateRepository(max_checkpoints_per_trip=0)

