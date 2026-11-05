"""Compile a .po catalog to .mo without GNU gettext.

CI runners carry no `msgfmt`, and the compiled catalog is a build artifact
absent from a checkout, so tests that read translated copy build their own.
The layout follows CPython's Tools/i18n/msgfmt.py.
"""

from array import array
from ast import literal_eval
from itertools import count, takewhile
from struct import pack
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_MO_MAGIC = 0x950412DE
_HEADER_WORDS = 7


def _entry_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    keyword = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith('"'):
            fields[keyword] += literal_eval(line)
            continue
        keyword, _, literal = line.partition(" ")
        fields[keyword] = literal_eval(literal)
    return fields


def _is_fuzzy(block: str) -> bool:
    return any(line.startswith("#,") and "fuzzy" in line for line in block.splitlines())


def _messages(po_text: str) -> dict[bytes, bytes]:
    messages: dict[bytes, bytes] = {}
    for block in po_text.split("\n\n"):
        fields = _entry_fields(block)
        if "msgid" not in fields or (fields["msgid"] and _is_fuzzy(block)):
            continue
        key = fields["msgid"]
        if "msgctxt" in fields:
            key = f"{fields['msgctxt']}\x04{key}"
        if "msgid_plural" in fields:
            key = f"{key}\0{fields['msgid_plural']}"
            forms = takewhile(
                lambda form: form is not None,
                (fields.get(f"msgstr[{n}]") for n in count()),
            )
            value = "\0".join(form or "" for form in forms)
        else:
            value = fields.get("msgstr", "")
        if value.strip("\0"):
            messages[key.encode()] = value.encode()
    return messages


def compile_po(*, po_path: Path, mo_path: Path) -> None:
    messages = _messages(po_path.read_text(encoding="utf-8"))
    keys = sorted(messages)
    ids = strs = b""
    offsets = []
    for key in keys:
        offsets.append((len(ids), len(key), len(strs), len(messages[key])))
        ids += key + b"\0"
        strs += messages[key] + b"\0"
    key_start = _HEADER_WORDS * 4 + 16 * len(keys)
    value_start = key_start + len(ids)
    key_offsets: list[int] = []
    value_offsets: list[int] = []
    for id_offset, id_length, str_offset, str_length in offsets:
        key_offsets += [id_length, id_offset + key_start]
        value_offsets += [str_length, str_offset + value_start]
    header = pack(
        "Iiiiiii",
        _MO_MAGIC,
        0,
        len(keys),
        _HEADER_WORDS * 4,
        _HEADER_WORDS * 4 + len(keys) * 8,
        0,
        0,
    )
    mo_path.write_bytes(
        header
        + array("i", key_offsets).tobytes()
        + array("i", value_offsets).tobytes()
        + ids
        + strs
    )
