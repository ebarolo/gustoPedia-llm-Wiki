"""Chunker markdown ricorsivo per la pipeline di embedding.

Port di text-chunker.ts di llm_wiki: ogni chunk porta un breadcrumb
heading_path ("## Usi in cucina > ### Cottura"), priorità di split
heading > paragrafi > righe > frasi > spazi > taglio duro, code fence e
tabelle mai spezzati, frontmatter YAML scartato, overlap tra chunk
adiacenti della stessa sezione, chunk piccoli fusi col successivo.
Puro e deterministico.
"""
import re
from dataclasses import dataclass

TARGET_CHARS = 1000
MAX_CHARS = 1500
MIN_CHARS = 200
OVERLAP_CHARS = 200

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SENTENCE_SEP = re.compile(r"([。！？!?；;]+\s*|(?:\.\s+))")
_LINE_SEP = re.compile(r"(\n+)")
_SPACE_SEP = re.compile(r"(\s+)")
_PARA_SEP = re.compile(r"(\n{2,})")


@dataclass
class Chunk:
    index: int
    text: str
    heading_path: str
    oversized: bool


def build_embed_text(title: str, heading_path: str, chunk_text: str) -> str:
    """Testo arricchito per l'embedding: titolo + breadcrumb + chunk."""
    parts = [p for p in (title, heading_path, chunk_text) if p]
    return "\n\n".join(parts)


def chunk_markdown(content: str) -> list[Chunk]:
    body = _strip_frontmatter(content)
    if not body.strip():
        return []

    chunks: list[Chunk] = []
    for heading_path, text in _split_into_sections(body):
        for piece in _chunk_section(text):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    heading_path=heading_path,
                    oversized=len(piece) > MAX_CHARS,
                )
            )
    return chunks


def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        return content
    rest = content[4:]
    m = re.search(r"(^|\n)---\s*(\n|$)", rest)
    if not m:
        return content
    return rest[m.end():]


def _split_into_sections(body: str) -> list[tuple[str, str]]:
    """Sezioni delimitate dagli heading, fence trattati come opachi."""
    sections: list[tuple[str, str]] = []
    headings: dict[int, str] = {}
    current_lines: list[str] = []
    current_path = ""
    in_fence = False
    fence_marker = ""

    def flush() -> None:
        text = "\n".join(current_lines)
        if text.strip():
            sections.append((current_path, text))

    for line in body.split("\n"):
        fence = _FENCE_RE.match(line)
        if fence:
            if not in_fence:
                in_fence = True
                fence_marker = fence.group(1)
            elif line.startswith(fence_marker) and line.strip() == fence_marker:
                in_fence = False
            current_lines.append(line)
            continue

        heading = None if in_fence else _HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            headings[level] = heading.group(2).strip()
            for deeper in range(level + 1, 7):
                headings.pop(deeper, None)
            current_path = " > ".join(
                f"{'#' * lvl} {headings[lvl]}" for lvl in sorted(headings)
            )
            current_lines = [line]
            continue

        current_lines.append(line)

    flush()
    return sections


def _chunk_section(text: str) -> list[str]:
    if len(text) <= TARGET_CHARS:
        return [text]
    atoms = _tokenize_atoms(text)
    pieces = _split_atoms(atoms)
    sized = _pack_pieces(pieces)
    merged = _merge_small(sized)
    return _apply_overlap(merged)


def _tokenize_atoms(text: str) -> list[tuple[str, bool]]:
    """Atomi (testo, indivisibile): fence e tabelle indivisibili, paragrafi no."""
    atoms: list[tuple[str, bool]] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            block = [line]
            j = i + 1
            while j < len(lines):
                block.append(lines[j])
                if lines[j].startswith(marker) and lines[j].strip() == marker:
                    j += 1
                    break
                j += 1
            atoms.append(("\n".join(block), True))
            i = j
            continue

        if line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            if j - i >= 2:
                atoms.append(("\n".join(lines[i:j]), True))
                i = j
                continue

        if not line.strip():
            i += 1
            continue

        block = []
        while i < len(lines) and lines[i].strip() and not _FENCE_RE.match(lines[i]):
            block.append(lines[i])
            i += 1
        atoms.append(("\n".join(block), False))

    return atoms


def _split_atoms(atoms: list[tuple[str, bool]]) -> list[str]:
    pieces: list[str] = []
    for text, indivisible in atoms:
        if indivisible or len(text) <= TARGET_CHARS:
            pieces.append(text)
        else:
            pieces.extend(_recursive_split(text))
    return pieces


def _recursive_split(text: str) -> list[str]:
    """Scala di split: paragrafi > righe > frasi > spazi > taglio duro."""
    out: list[str] = []
    for para in _split_keeping_sep(text, _PARA_SEP):
        if len(para) <= TARGET_CHARS:
            out.append(para)
            continue
        split_done = False
        for sep in (_LINE_SEP, _SENTENCE_SEP, _SPACE_SEP):
            subs = _split_keeping_sep(para, sep)
            if len(subs) > 1 and all(len(s) <= TARGET_CHARS for s in subs):
                out.extend(subs)
                split_done = True
                break
        if not split_done:
            out.extend(
                para[k:k + TARGET_CHARS] for k in range(0, len(para), TARGET_CHARS)
            )
    return out


def _split_keeping_sep(text: str, sep: re.Pattern) -> list[str]:
    """Split che tiene il separatore attaccato al frammento precedente."""
    out: list[str] = []
    last = 0
    for m in sep.finditer(text):
        out.append(text[last:m.end()])
        last = m.end()
    if last < len(text):
        out.append(text[last:])
    return [s for s in out if s]


def _pack_pieces(pieces: list[str]) -> list[str]:
    """Packer greedy fino a TARGET_CHARS; pezzi oversize emessi da soli."""
    out: list[str] = []
    buf = ""
    for piece in pieces:
        if not piece:
            continue
        if len(piece) > TARGET_CHARS:
            if buf:
                out.append(buf)
                buf = ""
            out.append(piece)
            continue
        if buf and len(buf) + len(piece) > TARGET_CHARS:
            out.append(buf)
            buf = piece
            continue
        buf = buf + ("\n" if buf and not buf.endswith(("\n", " ")) else "") + piece
    if buf:
        out.append(buf)
    return out


def _merge_small(pieces: list[str]) -> list[str]:
    if len(pieces) < 2:
        return pieces
    out: list[str] = []
    for piece in pieces:
        if out and len(out[-1]) < MIN_CHARS and len(out[-1]) + len(piece) <= MAX_CHARS:
            out[-1] = out[-1] + "\n" + piece
        else:
            out.append(piece)
    return out


def _apply_overlap(pieces: list[str]) -> list[str]:
    if len(pieces) < 2:
        return pieces
    out = [pieces[0]]
    for prev, curr in zip(pieces, pieces[1:]):
        tail = prev[-OVERLAP_CHARS:]
        out.append(_snap_overlap_head(tail) + curr)
    return out


def _snap_overlap_head(tail: str) -> str:
    """Allinea l'overlap all'inizio di una frase o parola, mai a metà."""
    sent = re.search(r"[。！？!?.;；]\s*", tail)
    if sent and 0 < sent.end() < len(tail):
        return tail[sent.end():]
    ws = re.search(r"\s", tail)
    if ws and ws.start() < len(tail) - 1:
        return tail[ws.start() + 1:]
    return tail
