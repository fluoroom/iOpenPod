# ADR-0147: Share one staging owner lease per process

- Status: Accepted
- Date: 2026-10-15
- Amends: ADR-0117's per-workspace ownership lock

## Context

ADR-0117 has each Host staging workspace hold an OS lock on its own ownership
marker for its entire lifetime. Advisory locks last only while their file is open,
so every live workspace costs one open descriptor. Sync retains every prepared
Track's media workspace until publication. A Sync of about 1,170 Tracks on Linux
retained 980 workspaces and exhausted the desktop session's 1,024-descriptor
soft limit. Qt surface buffers, temporary-directory cleanup, and media tools then
failed with "Too many open files". The default macOS soft limit of 256 fails sooner.
Windows handle limits are large enough that the failure was not observed there.

## Decision

Each process holds one locked owner lease per staging root, named
`.owner-<random>.lease`. The lease is created when the process opens its first
workspace in that root and is unlocked and removed when its last workspace closes.
A workspace marker records the name of the lease that owns it
(`iopenpod-host-staging-v2`). The marker is written once and is not held open.
Lease creation, marker creation, and lease removal occur under the existing root
cleanup lock. A live owner's lease therefore always exists whenever cleanup runs.

Startup cleanup reclaims a v2 workspace only while it holds that workspace's owner
lease, or when the named lease no longer exists. A busy lease means a live owner,
whether that owner is another process or this one. Malformed or unexpected owner
names grant no cleanup authority. After reclaiming workspaces, cleanup removes
leases that it can lock and that no retained workspace references. Workspaces with
v1 markers retain their earlier rule: they are reclaimable when their marker lock
is available. All of ADR-0117's other cleanup restrictions still apply.

At startup on POSIX Hosts, the application raises its soft open-file limit toward
the hard limit, capped at 65,536 and falling back to macOS `OPEN_MAX` (10,240).
It never lowers the limit. This is resource headroom for the whole process, not a
substitute for bounded descriptor use.

## Consequences

Staging descriptor use is constant regardless of how many workspaces a Sync
retains, while crashed owners remain recoverable and live preparations stay
protected. Host disk use for complete preparations is unchanged. Older versions
ignore v2 workspaces because their reaper accepts only v1 markers, and they never
remove lease files. Mixed-version processes therefore cannot reclaim each other's
live workspaces. A workspace whose crashed owner cannot be fully reclaimed keeps its
lease file until a later cleanup can remove both.
