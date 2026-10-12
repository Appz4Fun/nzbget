# PR 87 deferred validation

The maintainer requested squash integration on 2026-10-12 before complete
validation. This records unresolved work; merge does not establish correctness,
performance qualification, review approval, or deployment readiness.

The source preserves PR 87 PatchParts and the corrected SelectProbeParts,
upgrades RequiredCompareFloor to the prepared hybrid/scratch revision 0d72a146,
and preserves existing module, ABI, and benchmark registrations. The floor uses
C++ for small inputs and Rust for nonempty inputs with at least 4096 holes.
PAR CRC production migration and private proof runners are outside this PR.

- [ ] Validate the final combined integrated source with remote Rust, daemon,
  CTest, sanitizer, differential, and mutation checks. Earlier component checks
  passed, but this exact composed tree has not been built or executed.
- [ ] Complete exact-head independent and GitHub review; prior component review
  does not approve the final combined squash. Preserve unresolved findings.
- [ ] Resolve PatchParts performance: the retained dense case was 24.6% slower
  than the matched C++ control. Do not claim a Rust speedup from this integration.
- [ ] Qualify the hybrid floor against production and improved C++ controls.
  The old all-Rust floor had 12 fair-control losses; its performance claims do
  not apply to this hybrid revision. The first new native process retained
  8784 rows, including 741 below the required 5ms duration. Its complete packet
  is INVALID/HOLD. Preserve raw evidence; no replay, filtering, recalibration,
  or replacement timing is authorized by this merge.
- [ ] Keep backend deployment held pending a separate release decision and
  source/artifact/install identity, configuration/queue preservation, and
  relevant live regression checks. No production deployment is asserted.

Historical component tests and reports remain in rust/tests/streamcompare.md
and the retained owner evidence. Unsupported platforms and final integrated
behavior remain unqualified until the appropriate checks actually execute.
