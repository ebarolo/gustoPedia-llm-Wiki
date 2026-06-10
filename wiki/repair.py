# gnammyWiki/wiki/repair.py
import logging

from wiki.parser import PageBlock, demote_link, iter_wikilinks

logger = logging.getLogger(__name__)

# Gli stub oltre il cap vengono declassati a testo: un ingest non deve
# gonfiare la wiki di pagine vuote (le arricchirà il lint o un ingest futuro).
MAX_STUBS_PER_INGEST = 10

_STUB_SUMMARY = "Pagina stub creata automaticamente: in attesa di contenuto."


def repair_dangling_links(
    blocks: list[PageBlock],
    known_slugs: set[str],
) -> tuple[list[PageBlock], list[PageBlock]]:
    """Risolve i [[wikilink]] verso slug inesistenti.

    Ritorna (blocchi riparati, stub minimi da creare). I primi
    MAX_STUBS_PER_INGEST slug mancanti diventano stub page_type='concetto';
    gli altri vengono declassati a testo semplice nei blocchi sorgente.
    """
    touched = {b.slug for b in blocks}
    dangling: list[str] = []
    for block in blocks:
        for target in iter_wikilinks(block.markdown):
            if target not in known_slugs and target not in touched and target not in dangling:
                dangling.append(target)

    to_stub = dangling[:MAX_STUBS_PER_INGEST]
    to_demote = dangling[MAX_STUBS_PER_INGEST:]

    repaired = blocks
    if to_demote:
        repaired = []
        for block in blocks:
            md = block.markdown
            for slug in to_demote:
                md = demote_link(md, slug)
            repaired.append(PageBlock(slug=block.slug, markdown=md))
        logger.info("Declassati %d wikilink senza destinazione", len(to_demote))

    stubs = [
        PageBlock(slug=slug, markdown=f"{_humanize(slug)}\n{_STUB_SUMMARY}\n")
        for slug in to_stub
    ]
    if stubs:
        logger.info("Creati %d stub per wikilink senza destinazione", len(stubs))
    return repaired, stubs


def _humanize(slug: str) -> str:
    return slug.replace("-", " ").capitalize()
