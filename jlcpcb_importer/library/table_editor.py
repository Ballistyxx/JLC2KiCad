"""S-expression parser and editor for KiCad library table files.

Handles both ``sym-lib-table`` and ``fp-lib-table`` files.  These use a
simple S-expression format::

    (sym_lib_table
      (lib (name "MyLib")(type "KiCad")(uri "/path/to/lib.kicad_sym")(options "")(descr ""))
    )

This module can parse them, add/update entries, and write them back
atomically (write to temp file, then rename).
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile

from ..utils.logger import get_logger

log = get_logger()


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_atomic(path: str, content: str) -> None:
    """Write *content* to *path* atomically via a temp file + rename."""
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        shutil.move(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# ------------------------------------------------------------------
# Library table entry
# ------------------------------------------------------------------


class LibTableEntry:
    """A single ``(lib ...)`` entry."""

    def __init__(
        self,
        name: str,
        lib_type: str = "KiCad",
        uri: str = "",
        options: str = "",
        descr: str = "",
    ) -> None:
        self.name = name
        self.type = lib_type
        self.uri = uri
        self.options = options
        self.descr = descr

    def to_sexpr(self) -> str:
        return (
            f'  (lib (name "{self.name}")(type "{self.type}")'
            f'(uri "{self.uri}")(options "{self.options}")'
            f'(descr "{self.descr}"))\n'
        )

    def __repr__(self) -> str:
        return f"LibTableEntry(name={self.name!r}, uri={self.uri!r})"


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------


def parse_lib_table(content: str) -> list[LibTableEntry]:
    """Parse all ``(lib ...)`` entries from a library table string."""
    entries: list[LibTableEntry] = []
    pattern = re.compile(
        r'\(lib\s+'
        r'\(name\s+"([^"]*)"\)'
        r'\(type\s+"([^"]*)"\)'
        r'\(uri\s+"([^"]*)"\)'
        r'\(options\s+"([^"]*)"\)'
        r'\(descr\s+"([^"]*)"\)'
        r'\)',
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        entries.append(LibTableEntry(
            name=m.group(1),
            lib_type=m.group(2),
            uri=m.group(3),
            options=m.group(4),
            descr=m.group(5),
        ))
    return entries


# ------------------------------------------------------------------
# High-level operations
# ------------------------------------------------------------------


def ensure_lib_in_table(
    table_path: str,
    entry: LibTableEntry,
    table_type: str = "sym_lib_table",
) -> bool:
    """Ensure a library entry exists in a KiCad library table file.

    If the file doesn't exist, it is created.  If the library name is
    already present, its URI is updated if different.

    Args:
        table_path: Path to ``sym-lib-table`` or ``fp-lib-table``.
        entry: The library entry to add or update.
        table_type: Either ``"sym_lib_table"`` or ``"fp_lib_table"``.

    Returns:
        True if the file was modified, False if no changes were needed.
    """
    if not os.path.isfile(table_path):
        log.info("Creating new library table: %s", table_path)
        content = f"({table_type}\n{entry.to_sexpr()})\n"
        os.makedirs(os.path.dirname(table_path), exist_ok=True)
        _write_atomic(table_path, content)
        return True

    # Backup before modification
    backup = table_path + ".bak"
    if not os.path.isfile(backup):
        shutil.copy2(table_path, backup)

    content = _read_file(table_path)
    existing = parse_lib_table(content)

    for e in existing:
        if e.name == entry.name:
            if e.uri == entry.uri:
                log.debug("Library '%s' already in table with correct URI", entry.name)
                return False
            # Update URI
            old_sexpr_pattern = re.compile(
                rf'\(lib\s+\(name\s+"{re.escape(entry.name)}"\).*?\)',
                re.DOTALL,
            )
            new_content = old_sexpr_pattern.sub(
                entry.to_sexpr().strip(), content, count=1
            )
            _write_atomic(table_path, new_content)
            log.info("Updated URI for '%s' in %s", entry.name, table_path)
            return True

    # Entry not found – append before closing paren
    close_idx = content.rfind(")")
    if close_idx == -1:
        log.error("Malformed library table: %s", table_path)
        return False

    new_content = content[:close_idx] + entry.to_sexpr() + ")\n"
    _write_atomic(table_path, new_content)
    log.info("Added '%s' to %s", entry.name, table_path)
    return True


def ensure_symbol_table(
    project_dir: str,
    lib_name: str,
    lib_uri: str,
) -> bool:
    """Convenience: ensure a symbol library is registered in the project."""
    table_path = os.path.join(project_dir, "sym-lib-table")
    entry = LibTableEntry(
        name=lib_name,
        lib_type="KiCad",
        uri=lib_uri,
        descr="JLCPCB imported symbols",
    )
    return ensure_lib_in_table(table_path, entry, "sym_lib_table")


def ensure_footprint_table(
    project_dir: str,
    lib_name: str,
    lib_uri: str,
) -> bool:
    """Convenience: ensure a footprint library is registered in the project."""
    table_path = os.path.join(project_dir, "fp-lib-table")
    entry = LibTableEntry(
        name=lib_name,
        lib_type="KiCad",
        uri=lib_uri,
        descr="JLCPCB imported footprints",
    )
    return ensure_lib_in_table(table_path, entry, "fp_lib_table")
