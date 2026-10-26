# Issue345 Qwen-first continuation — October26

Status: STARTED; source/measurement preparation only, no new installed acceptance.

Owner authorized issue-related merge/deploy and requested Qwen first, bounded Codex escalation and Qwen fallback on quota exhaustion.

Source baseline f03c48198ce30d07c6e26a8d12241c9281fdf51f; directly verified Pi25dc3ea4e004719852b08853f707697b93a4017f, service active, existing timing flag enabled.

Carry forward popup/offline logging/deployment/recovery acceptance already recorded in issue345 and infrastructure. Fine-grained probePR363 is merged but absent from installed Pi release. Recent unlabeled rolling refresh p95 sample23–28ms does not explain prior multi-second stalls.

Remaining: physical popup/control acceptance, labeled receive-only radar comparison, precise FT8 correlation, measured-vs-inferred ranked findings. Pi idle state is unconfirmed; no production restart or RF test performed.

This file will be completed by the bounded worker. No closure, performance fix, merge or deployment is claimed.
