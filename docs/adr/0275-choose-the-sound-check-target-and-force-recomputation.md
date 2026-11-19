# ADR-0275: Choose the Sound Check target and force recomputation

- Status: Accepted
- Date: 2026-11-18

## Context

Sound Check stores one native loudness value per Track. iOpenPod computes a
missing gain from FFmpeg EBU R128 integrated loudness and the Original iOpenPod
used a fixed -16.5 LUFS reference, derived empirically from iTunes. That value
was hardcoded. Users need to align a library with ReplayGain 2.0 (-18 LUFS), a
streaming reference, or another common target. The Compute Sound Check setting
also promised to analyze only missing values, but the shared media preparation
path re-measured every prepared Track regardless of an existing tag.

## Decision

Add a device-overridable **Sound Check target** setting. Its default is -16.5
LUFS, which preserves the Original iOpenPod behavior exactly. The offered choices
are -23 (broadcast), -18 (ReplayGain 2.0), -16.5 (Apple Sound Check), -16 (Apple
Music), -14 (streaming), -12 (loud), and -10 (very loud) LUFS. Only newly computed
values use the selected target; existing native values are never rewritten
automatically.

Add a default-off, device-overridable **Force Sound Check** setting. Compute
Sound Check now skips a Track whose Host metadata already supplies a usable
Sound Check or ReplayGain value. Force Sound Check re-analyzes Tracks whose media
is prepared during the Sync and replaces their computed value. Unchanged Tracks,
Tracks excluded from the Sync, and metadata-only updates keep their current
values. Force requires Compute Sound Check to be on and does not imply a
library-wide analysis pass.

The target selects the gain in the existing native conversion
`value = 1000 * 10 ** (-gain / 10)`. It does not add a new field, database
version, or migration.

## Consequences

Changing the target changes the absolute playback level of values computed after
the change. Relative normalization between Tracks computed with the same target
is preserved, but a library containing values from different targets can play
Tracks at different levels. Users should choose one target for a library and use
Force Sound Check, or re-add affected media, when they want to replace existing
values. Force adds one decode of integrated loudness per prepared Track. The native
encoding represents at most a 30 dB boost, so a very quiet Track with a loud
target is limited to 30 dB and reported as a warning instead of failing the
write.

The setting remains portable per iPod, and every Sync captures its value with the
other options before execution starts. Host files remain unchanged. No device
format behavior changes, so native byte preservation and existing verification
rules continue to apply.
