from __future__ import annotations


def clsx(*tokens: object) -> str:
    chunks: list[str] = []
    for token in tokens:
        if token is None or token is False:
            continue
        if token is True:
            continue
        if piece := str(token).strip():
            chunks.append(piece)
    return " ".join(chunks)
