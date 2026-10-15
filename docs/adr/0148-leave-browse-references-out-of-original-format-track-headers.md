# ADR-0148: Leave browse references out of original-format Track headers

- Status: Accepted
- Date: 2026-10-15
- Amends: [ADR-0145](0145-select-track-layouts-for-all-library-writes.md)

## Context

ADR-0145 requires a change to an existing album or artist dataset to encode its
required Track references, or fail preparation. Original-format MHIT headers
(156 bytes, `0x9C`) end before `album_id`, `artist_id_ref`, and `composer_id`, so
those Tracks have no browse references at all.

Without an authorized expansion, the ADR-0145 rule blocked every Library write that
touched a browse group on such a database. Deleting one Track from a shared album
reconciled the remaining members and failed with "MhitHeader.album_id cannot fit
the retained 156-byte header". Merely deleting a Track could not be completed.

## Decision

A Track header that cannot hold `album_id` predates browse references. Album and
artist reconciliation leave such Tracks unreferenced, and a group whose members all
predate browse references creates no orphaned group row. Album, artist, and
composer text stay in their MHODs. Verification expects group references only from
members whose output headers do not predate browse references.

ADR-0145 still governs every browse-aware layout. When a header holds `album_id`
but cannot fit a required reference, such as `artist_id_ref` in a 328-byte header,
the write expands the header where the Device Profile authorizes it and otherwise
fails preparation. Authorized expansion takes precedence: a 156-byte header that
the selected profile may grow is expanded and referenced rather than skipped.
Composer handling is unchanged from ADR-0145.

The single predicate `predates_browse_references` in `iPodDB.library._track_layout`
derives this boundary from the shared MHIT Chunk definitions.

## Consequences

Tracks can be deleted and edited on original-format databases without a Device
Profile. Partially browse-aware layouts are not silently stripped of references.
Tests cover deletion and group edits on 156-byte headers, expansion of 156-byte
headers under an authorizing profile, and rejection of an unstorable artist
reference in a 328-byte header. Physical firmware acceptance of unreferenced
original-format Tracks remains untested.
