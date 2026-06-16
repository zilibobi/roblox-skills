"""Unit tests for robloxdocs.py (no network/clone needed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import robloxdocs as rd  # noqa: E402


# --------------------------- tokenize --------------------------- #
def test_tokenize_keeps_api_form_and_components():
    terms = rd.tokenize("TweenService:Create")
    assert "TweenService:Create" in terms  # full colon form preserved verbatim
    assert "TweenService" in terms          # plus components
    assert "Create" in terms                # never dropped — no stopword list


def test_tokenize_drops_single_chars_only():
    terms = rd.tokenize("how do i anchor a part")
    assert "anchor" in terms and "part" in terms
    assert "how" in terms          # not filtered — IDF will down-weight it
    assert "i" not in terms        # 1-char tokens carry no signal
    assert "a" not in terms


def test_tokenize_dedupes_case_insensitively():
    assert rd.tokenize("Part part PART") == ["Part"]


# --------------------------- cache path --------------------------- #
def test_cache_root_is_platform_path(monkeypatch):
    monkeypatch.delenv("ROBLOX_DOCS_CACHE", raising=False)
    assert rd.cache_root().name == "roblox-docs-explorer"


def test_cache_root_respects_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ROBLOX_DOCS_CACHE", str(tmp_path / "custom"))
    assert rd.cache_root() == tmp_path / "custom"


# --------------------------- IDF ranking --------------------------- #
def _make_corpus(tmp_path):
    """A tiny docs tree: a rare term in one file, a ubiquitous term everywhere."""
    base = tmp_path / "content" / "en-us"
    cls = base / "reference" / "engine" / "classes"
    cls.mkdir(parents=True)
    # Part.yaml: the rare term "Anchored" appears once; "part" a few times.
    (cls / "Part.yaml").write_text(
        "name: Part\nThe Anchored property fixes a part in place.\n"
        "A part is a part of the world.\n",
        encoding="utf-8",
    )
    # Many guide files mention "part" a lot but never "Anchored".
    guides = base / "building"
    guides.mkdir(parents=True)
    for i in range(8):
        (guides / f"g{i}.md").write_text("part part part part\n", encoding="utf-8")


def test_idf_ranks_rare_term_file_first(tmp_path, monkeypatch):
    # Force the pure-Python path so the test is independent of rg/git presence.
    monkeypatch.setattr(rd, "_have", lambda tool: False)
    _make_corpus(tmp_path)

    results = rd.search(tmp_path, "anchored part", top_k=5, context=1)
    top_path = results[0][0]
    # Part.yaml wins on the rare, high-IDF "anchored" despite the guides being
    # saturated with the common, low-IDF "part".
    assert top_path.endswith("Part.yaml")


def test_idf_exact_filename_boost(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, "_have", lambda tool: False)
    _make_corpus(tmp_path)
    results = rd.search(tmp_path, "Part", top_k=5, context=1)
    assert results[0][0].endswith("Part.yaml")  # doc named after the term wins
