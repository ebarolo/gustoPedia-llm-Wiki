from gnammyWiki.wiki.chunker import (
    MAX_CHARS,
    MIN_CHARS,
    OVERLAP_CHARS,
    TARGET_CHARS,
    build_embed_text,
    chunk_markdown,
)


def test_short_page_single_chunk():
    md = "## Origini\nBreve testo sotto un heading."
    chunks = chunk_markdown(md)
    assert len(chunks) == 1
    assert chunks[0].heading_path == "## Origini"
    assert chunks[0].index == 0


def test_constants_ported_from_llm_wiki():
    assert (TARGET_CHARS, MAX_CHARS, MIN_CHARS, OVERLAP_CHARS) == (1000, 1500, 200, 200)


def test_long_section_split_with_overlap():
    sentences = " ".join(f"Frase numero {i} del paragrafo di prova." for i in range(80))
    md = f"## Sezione\n{sentences}"
    chunks = chunk_markdown(md)
    assert len(chunks) > 1
    for c in chunks:
        assert c.heading_path == "## Sezione"
    # overlap: l'inizio di ogni chunk successivo ripete la coda del precedente
    for prev, curr in zip(chunks, chunks[1:]):
        head = curr.text[:50]
        assert head.strip() and head in prev.text + curr.text


def test_heading_path_breadcrumb():
    md = (
        "## Usi in cucina\nTesto introduttivo.\n\n"
        "### Cottura\nTesto sulla cottura."
    )
    chunks = chunk_markdown(md)
    paths = [c.heading_path for c in chunks]
    assert "## Usi in cucina" in paths
    assert "## Usi in cucina > ### Cottura" in paths


def test_code_fence_indivisible():
    fence = "```\n" + "\n".join("riga di codice" for _ in range(200)) + "\n```"
    md = f"## Codice\nIntro.\n\n{fence}"
    chunks = chunk_markdown(md)
    fence_chunks = [c for c in chunks if "```" in c.text]
    assert len(fence_chunks) == 1
    assert fence_chunks[0].text.count("```") == 2
    assert fence_chunks[0].oversized


def test_small_trailing_chunk_merged():
    big = " ".join(f"Frase {i} abbastanza lunga per riempire." for i in range(40))
    md = f"## Sezione\n{big}\n\nCoda corta."
    chunks = chunk_markdown(md)
    assert all(len(c.text) >= MIN_CHARS or len(chunks) == 1 for c in chunks[:-1])
    assert "Coda corta." in chunks[-1].text


def test_frontmatter_stripped():
    md = "---\ntype: ingrediente\n---\n## Corpo\nTesto."
    chunks = chunk_markdown(md)
    assert all("type: ingrediente" not in c.text for c in chunks)


def test_build_embed_text():
    out = build_embed_text("Guanciale", "## Usi in cucina", "Testo del chunk.")
    assert out == "Guanciale\n\n## Usi in cucina\n\nTesto del chunk."
    assert build_embed_text("Guanciale", "", "Testo.") == "Guanciale\n\nTesto."
