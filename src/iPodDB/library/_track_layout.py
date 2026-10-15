"""Which MHIT fields a retained Track header can encode."""

from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ParsedChunk

_FIELD_ENDS = {
    f.attribute_name: f.schema.offset + f.schema.size for f in binary_fields(MhitHeader)
}


def holds_field(chunk: ParsedChunk[MhitHeader], name: str) -> bool:
    """Original-format headers (e.g. 156 bytes) end before the browse references."""
    return _FIELD_ENDS[name] <= chunk.generic_header.header_length


def predates_browse_references(chunk: ParsedChunk[MhitHeader]) -> bool:
    """Original-format headers end before album_id and carry no browse references.

    Only these may leave an album or artist group unreferenced. A browse-aware
    layout that cannot fit a required reference is expanded or blocked instead
    (ADR-0148).
    """
    return not holds_field(chunk, "album_id")
