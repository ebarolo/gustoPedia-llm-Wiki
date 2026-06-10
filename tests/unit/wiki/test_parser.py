from wiki.parser import (
    demote_link,
    extract_wikilinks,
    is_safe_slug,
    parse_page_blocks,
    split_page_block,
)

TWO_BLOCKS = """---PAGE: guanciale---
Guanciale
Salume non affumicato ricavato dalla guancia del maiale.

Il [[guanciale]] è il grasso nobile della [[carbonara]].
---END---
---PAGE: carbonara---
Carbonara
Primo piatto romano a base di uova, guanciale e pecorino.

Corpo della pagina.
---END---
"""


def test_parse_two_clean_blocks():
    result = parse_page_blocks(TWO_BLOCKS)
    assert [b.slug for b in result.blocks] == ["guanciale", "carbonara"]
    assert "grasso nobile" in result.blocks[0].markdown
    assert result.warnings == []


def test_parse_crlf_normalized():
    result = parse_page_blocks(TWO_BLOCKS.replace("\n", "\r\n"))
    assert [b.slug for b in result.blocks] == ["guanciale", "carbonara"]


def test_parse_marker_variants():
    text = "--- PAGE: guanciale ---\nGuanciale\nSintesi.\n\nCorpo.\n--- end ---\n"
    result = parse_page_blocks(text)
    assert [b.slug for b in result.blocks] == ["guanciale"]


def test_truncated_last_block_dropped_with_warning():
    text = TWO_BLOCKS.rsplit("---END---", 1)[0]
    result = parse_page_blocks(text)
    assert [b.slug for b in result.blocks] == ["guanciale"]
    assert len(result.warnings) == 1
    assert "carbonara" in result.warnings[0]


def test_end_marker_inside_code_fence_is_content():
    text = (
        "---PAGE: formato-wiki---\n"
        "Formato wiki\n"
        "Sintesi.\n"
        "\n"
        "```\n"
        "---END---\n"
        "```\n"
        "Dopo il fence.\n"
        "---END---\n"
    )
    result = parse_page_blocks(text)
    assert len(result.blocks) == 1
    assert "Dopo il fence." in result.blocks[0].markdown
    assert "---END---" in result.blocks[0].markdown


def test_unsafe_slugs_rejected():
    for bad in ["../etc", "Guanciale", "con spazi", "accentè", "", "a" * 81]:
        assert not is_safe_slug(bad), bad
    assert is_safe_slug("reazione-maillard")
    assert is_safe_slug("guanciale")


def test_unsafe_slug_block_dropped_with_warning():
    text = "---PAGE: ../evil---\nTitolo\nSintesi.\n\nCorpo.\n---END---\n"
    result = parse_page_blocks(text)
    assert result.blocks == []
    assert len(result.warnings) == 1


def test_oversized_block_dropped_with_warning():
    text = f"---PAGE: lungo---\nTitolo\nSintesi.\n\n{'x' * 31000}\n---END---\n"
    result = parse_page_blocks(text)
    assert result.blocks == []
    assert "lungo" in result.warnings[0]


def test_extract_wikilinks():
    md = "Il [[guanciale]] e la [[pasta-alla-gricia|gricia]] sono [[guanciale]]."
    assert extract_wikilinks(md) == {"guanciale", "pasta-alla-gricia"}


def test_demote_link():
    md = "Vedi [[pasta-madre|la pasta madre]] e [[guanciale]]."
    out = demote_link(md, "pasta-madre")
    assert "[[pasta-madre" not in out
    assert "la pasta madre" in out
    assert "[[guanciale]]" in out
    out2 = demote_link(out, "guanciale")
    assert "[[" not in out2
    assert "guanciale" in out2


def test_split_page_block():
    title, summary, body = split_page_block(
        "Guanciale\nSalume di guancia.\n\n## Origini\nCorpo."
    )
    assert title == "Guanciale"
    assert summary == "Salume di guancia."
    assert body.startswith("## Origini")
