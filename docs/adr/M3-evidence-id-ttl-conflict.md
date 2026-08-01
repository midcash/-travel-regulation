# M3 Evidence ID、TTL 与冲突策略

## 状态

Accepted for M3 offline implementation; live provider acceptance remains a manual gate.

## Context

M3 must make external facts traceable without passing raw supplier payloads downstream.
The Registry also needs deterministic stale, missing, and conflict behavior so a later
planning stage cannot treat an unavailable fact as a normal success.

## Decision

1. `EvidenceRegistration` is the typed input boundary. It contains `entity_id`,
   `fact_type`, typed `value`, provider/source references, observation time, TTL category,
   confidence, raw payload reference, query fingerprint, schema version, and constraint
   references.
2. `InMemoryEvidenceRepository` derives `evidence:<sha256>` from the canonical JSON form of
   the complete registration. The ID is stable for the same normalized registration and
   does not embed the raw payload.
3. `EvidenceTtlPolicy` is injected once. The effective `valid_until` is the earlier of the
   provider expiry and the policy expiry. A `FakeClock` or `Clock` decides stale status;
   the exact boundary (`valid_until <= now`) is stale.
4. A snapshot selects evidence by entity, fact type, and query fingerprint. It preserves
   every selected source and derives a separate immutable snapshot ID from the selected
   content, statuses, coverage, freshness, conflicts, and missing requirements.
5. Current, non-stale evidence with the same entity/fact/query but different typed values
   is marked `CONFLICTING`. Conflicting, stale, and unavailable items are not `VERIFIED`.
   Missing fact types are calculated only from current `VERIFIED` items.
6. Candidate Pool and later stages may reference only evidence IDs and snapshot IDs. They
   must not infer a value from the last writer or from a raw supplier response.

## Consequences

- Registry behavior is deterministic and reproducible with `FakeClock`.
- Conflicting sources remain auditable instead of being overwritten.
- Coverage and freshness can be measured without high-cardinality metric labels.
- The in-memory implementation is intentionally not a cache fallback or persistent store;
  persistence and production resilience remain out of scope for M3.

## Verification

- `tests/unit/test_evidence_repository.py`
- `tests/unit/test_evidence_ttl_snapshot.py`
- `tests/unit/test_candidate_pool.py`
- Default offline suite has passed after the M3 changes; the real-provider contract is
  reported separately by `evaluation/reports/live-tool-contract.json`.
