from wiki.parser import PageBlock
from wiki.repair import MAX_STUBS_PER_INGEST, repair_dangling_links


def _block(slug: str, md: str) -> PageBlock:
    return PageBlock(slug=slug, markdown=md)


def test_links_to_known_or_touched_pages_untouched():
    blocks = [_block("a", "Vedi [[b]] e [[esistente]].")]
    repaired, stubs = repair_dangling_links(blocks, {"esistente", "b"})
    assert stubs == []
    assert repaired[0].markdown == "Vedi [[b]] e [[esistente]]."


def test_dangling_link_becomes_stub():
    blocks = [_block("a", "Vedi [[pasta-madre]].")]
    repaired, stubs = repair_dangling_links(blocks, set())
    assert [s.slug for s in stubs] == ["pasta-madre"]
    assert "Pasta madre" in stubs[0].markdown
    assert "[[pasta-madre]]" in repaired[0].markdown


def test_dangling_links_beyond_cap_demoted():
    targets = [f"slug-{i}" for i in range(MAX_STUBS_PER_INGEST + 3)]
    md = " ".join(f"[[{t}]]" for t in targets)
    repaired, stubs = repair_dangling_links([_block("a", md)], set())
    assert len(stubs) == MAX_STUBS_PER_INGEST
    for demoted in targets[MAX_STUBS_PER_INGEST:]:
        assert f"[[{demoted}]]" not in repaired[0].markdown
        assert demoted in repaired[0].markdown
