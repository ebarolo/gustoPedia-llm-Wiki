"""Parser dei blocchi ---PAGE: slug--- emessi dallo step di generazione.

Port di parseFileBlocks di llm_wiki (src/lib/ingest.ts): gestisce CRLF,
varianti di marker, troncamento dell'ultimo blocco e marker END dentro
code fence. Lo slug viene validato qui, al confine del parse, perché
arriva dritto dal testo generato dall'LLM.
"""
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Una pagina oltre questa soglia rischia di sforare il limite di 1MB del
# tsvector sulla colonna fts generata: il prompt chiede max 30k char e il
# parser fa da rete di sicurezza.
MAX_PAGE_CHARS = 30_000

_OPENER_LINE = re.compile(r"^---\s*PAGE:\s*(.+?)\s*---\s*$", re.IGNORECASE)
_CLOSER_LINE = re.compile(r"^---\s*END\s*---\s*$", re.IGNORECASE)
_FENCE_LINE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


@dataclass
class PageBlock:
    slug: str
    markdown: str


@dataclass
class ParseResult:
    blocks: list[PageBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_safe_slug(slug: str) -> bool:
    return bool(slug) and len(slug) <= 80 and bool(_SLUG_RE.match(slug))


def parse_page_blocks(text: str) -> ParseResult:
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")

    result = ParseResult()
    i = 0
    while i < len(lines):
        opener = _OPENER_LINE.match(lines[i])
        if not opener:
            i += 1
            continue
        slug = opener.group(1).strip()
        i += 1

        content_lines: list[str] = []
        fence_char: str | None = None
        fence_len = 0
        closed = False

        while i < len(lines):
            line = lines[i]

            # Stato fence prima del closer: un ---END--- dentro un code
            # fence è testo della pagina, non chiusura del blocco.
            fence = _FENCE_LINE.match(line)
            if fence:
                run = fence.group(1)
                if fence_char is None:
                    fence_char = run[0]
                    fence_len = len(run)
                elif run[0] == fence_char and len(run) >= fence_len:
                    fence_char = None
                    fence_len = 0
                content_lines.append(line)
                i += 1
                continue

            if fence_char is None and _CLOSER_LINE.match(line):
                closed = True
                i += 1
                break

            content_lines.append(line)
            i += 1

        if not closed:
            msg = (
                f'Blocco PAGE "{slug or "(senza slug)"}" non chiuso prima della fine '
                "dello stream: probabile troncamento. Blocco scartato."
            )
            logger.warning(msg)
            result.warnings.append(msg)
            continue

        if not is_safe_slug(slug):
            msg = f'Blocco PAGE con slug non valido "{slug}" scartato (kebab-case minuscolo, max 80 char).'
            logger.warning(msg)
            result.warnings.append(msg)
            continue

        markdown = "\n".join(content_lines).strip("\n")
        if len(markdown) > MAX_PAGE_CHARS:
            msg = f'Blocco PAGE "{slug}" oltre {MAX_PAGE_CHARS} caratteri scartato.'
            logger.warning(msg)
            result.warnings.append(msg)
            continue

        result.blocks.append(PageBlock(slug=slug, markdown=markdown))

    return result


def split_page_block(markdown: str) -> tuple[str, str, str]:
    """Scompone un blocco pagina in (title, summary, body).

    Contratto del prompt wiki_generation: riga 1 titolo, riga 2 sintesi,
    riga vuota, poi il corpo markdown.
    """
    lines = markdown.split("\n")
    title = lines[0].strip() if lines else ""
    summary = lines[1].strip() if len(lines) > 1 else ""
    body = "\n".join(lines[2:]).strip("\n")
    return title, summary, body


def extract_wikilinks(markdown: str) -> set[str]:
    return set(iter_wikilinks(markdown))


def iter_wikilinks(markdown: str) -> list[str]:
    """Destinazioni dei wikilink in ordine di apparizione, senza duplicati."""
    seen: list[str] = []
    for m in _WIKILINK_RE.finditer(markdown):
        target = m.group(1).strip()
        if target not in seen:
            seen.append(target)
    return seen


def demote_link(markdown: str, slug: str) -> str:
    """Declassa i [[wikilink]] verso `slug` a testo semplice."""

    def _replace(m: re.Match) -> str:
        if m.group(1).strip() != slug:
            return m.group(0)
        return m.group(2) or m.group(1).strip()

    return _WIKILINK_RE.sub(_replace, markdown)
