# FT8 DX intelligence CP1: offline scoring foundation

This versioned model produces relative ordering **only**; it is not a calibrated
probability of QSO success. It never tunes, keys, changes power or selects a CQ.

DX distance is computed from Maidenhead centers, saturating above long paths.
Reachability starts at a *neutral prior*, not a presumed failure. Recent
directional evidence can move priority up or down in proportion to freshness
and independent-receiver count. Local received SNR is only weakly weighted:
hearing a CQ well does not establish reciprocity.

Callers must verify receiver direction, frequency/band, age, and provenance
before supplying evidence. Completed-QSO PSK archives alone cannot stand in
for live actionable coverage. Missing grid, stale data, or absent reports
lower confidence, not rank to zero. Current model score is **not a percentage**.

CP1 deliberately does not sort the live CQ browser, change persistent
selection, integrate Forge APIs, adjust FT8 power, or modify QSO machinery.
Future integration must freeze selection during negotiation, avoid reordering
under the encoder cursor, and verify real-world model calibration before
presenting numeric reachability probabilities.
