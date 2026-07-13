"""Tests for mapping/report.py: TSV loading, diffing, and Markdown/HTML rendering.

Uses small in-memory ``MappingSet``/``Mapping`` fixtures and ``.sssom.tsv``
fixture files written to ``tmp_path`` via ``mapping.io.write_sssom_tsv`` (the
real ``sssom-py`` writer), never the not-yet-created
``mappings/omop-onz-g.csv`` or any live ontology/network access, per
AGENTS.md's testing conventions.
"""

from __future__ import annotations

from pathlib import Path

from linkml_runtime.utils.metamodelcore import URI

from sssom_rosetta.mapping.io import write_sssom_tsv
from sssom_rosetta.mapping.report import (
    MappingDiff,
    diff_mapping_sets,
    load_mapping_set_tsv,
    predicate_counts,
    render_html,
    render_markdown,
)
from sssom_rosetta.models.sssom import Mapping, MappingSet

MAPPING_SET_ID = URI("https://example.org/mappings/omop-onz-g")
LICENSE = URI("https://creativecommons.org/publicdomain/zero/1.0/")

CURIE_MAP = {
    "omop": "https://w3id.org/omop/ontology#",
    "onz-g": "http://purl.org/ozo/onz-g#",
}


def _mapping(**overrides: object) -> Mapping:
    fields: dict[str, object] = {
        "subject_id": "omop:Person",
        "predicate_id": "skos:exactMatch",
        "object_id": "onz-g:Client",
        "mapping_justification": "semapv:ManualMappingCuration",
        "confidence": 0.9,
        "subject_label": "Person",
        "object_label": "Client",
    }
    fields.update(overrides)
    return Mapping(**fields)


def _mapping_set(*mappings: Mapping) -> MappingSet:
    return MappingSet(
        mapping_set_id=MAPPING_SET_ID,
        license=LICENSE,
        curie_map=CURIE_MAP,
        mappings=list(mappings),
    )


# --- load_mapping_set_tsv -----------------------------------------------


def test_load_mapping_set_tsv_round_trips_written_tsv(tmp_path: Path) -> None:
    mapping_set = _mapping_set(_mapping())
    tsv_path = tmp_path / "omop-onz-g.sssom.tsv"
    write_sssom_tsv(mapping_set, tsv_path)

    loaded = load_mapping_set_tsv(tsv_path)

    assert isinstance(loaded, MappingSet)
    assert str(loaded.mapping_set_id) == str(MAPPING_SET_ID)
    assert len(loaded.mappings or []) == 1
    loaded_mapping = (loaded.mappings or [])[0]
    assert loaded_mapping.subject_id == "omop:Person"
    assert loaded_mapping.object_id == "onz-g:Client"
    assert loaded_mapping.confidence == 0.9


def test_load_mapping_set_tsv_round_trips_multivalued_author_id(
    tmp_path: Path,
) -> None:
    mapping_set = _mapping_set(
        _mapping(
            author_id=["orcid:0000-0000-0000-0001", "orcid:0000-0000-0000-0002"]
        )
    )
    tsv_path = tmp_path / "multi-author.sssom.tsv"
    write_sssom_tsv(mapping_set, tsv_path)

    loaded = load_mapping_set_tsv(tsv_path)

    loaded_mapping = (loaded.mappings or [])[0]
    assert loaded_mapping.author_id == [
        "orcid:0000-0000-0000-0001",
        "orcid:0000-0000-0000-0002",
    ]


def test_load_mapping_set_tsv_drops_missing_optional_fields(tmp_path: Path) -> None:
    mapping_set = _mapping_set(
        Mapping(
            subject_id="omop:Person",
            predicate_id="skos:exactMatch",
            object_id="onz-g:Client",
            mapping_justification="semapv:ManualMappingCuration",
        )
    )
    tsv_path = tmp_path / "no-confidence.sssom.tsv"
    write_sssom_tsv(mapping_set, tsv_path)

    loaded = load_mapping_set_tsv(tsv_path)

    loaded_mapping = (loaded.mappings or [])[0]
    assert loaded_mapping.confidence is None


def test_load_mapping_set_tsv_reads_literal_fixture_file(tmp_path: Path) -> None:
    tsv_path = tmp_path / "literal.sssom.tsv"
    tsv_path.write_text(
        "# curie_map:\n"
        "#   omop: https://w3id.org/omop/ontology#\n"
        "#   onz-g: http://purl.org/ozo/onz-g#\n"
        "# license: https://creativecommons.org/publicdomain/zero/1.0/\n"
        "# mapping_set_id: https://example.org/mappings/omop-onz-g\n"
        "subject_id\tpredicate_id\tobject_id\tmapping_justification\tconfidence\n"
        "omop:Person\tskos:exactMatch\tonz-g:Client\tsemapv:ManualMappingCuration\t0.9\n"
    )

    loaded = load_mapping_set_tsv(tsv_path)

    assert len(loaded.mappings or []) == 1
    assert (loaded.mappings or [])[0].subject_id == "omop:Person"


# --- diff_mapping_sets ---------------------------------------------------


def test_diff_mapping_sets_base_none_reports_all_as_added() -> None:
    head = _mapping_set(_mapping())

    diff = diff_mapping_sets(None, head)

    assert isinstance(diff, MappingDiff)
    assert len(diff.added) == 1
    assert diff.removed == []
    assert diff.changed == []
    assert diff.unchanged_count == 0


def test_diff_mapping_sets_detects_added_removed_unchanged() -> None:
    base = _mapping_set(
        _mapping(),
        _mapping(object_id="onz-g:ToBeRemoved"),
    )
    head = _mapping_set(
        _mapping(),
        _mapping(object_id="onz-g:NewOne"),
    )

    diff = diff_mapping_sets(base, head)

    assert len(diff.added) == 1
    assert diff.added[0].object_id == "onz-g:NewOne"
    assert len(diff.removed) == 1
    assert diff.removed[0].object_id == "onz-g:ToBeRemoved"
    assert diff.unchanged_count == 1
    assert diff.changed == []


def test_diff_mapping_sets_detects_changed_confidence() -> None:
    base = _mapping_set(_mapping(confidence=0.5))
    head = _mapping_set(_mapping(confidence=0.9))

    diff = diff_mapping_sets(base, head)

    assert diff.added == []
    assert diff.removed == []
    assert len(diff.changed) == 1
    before, after = diff.changed[0]
    assert before.confidence == 0.5
    assert after.confidence == 0.9
    assert diff.unchanged_count == 0


def test_diff_mapping_sets_same_key_different_label_is_changed_not_unchanged() -> None:
    base = _mapping_set(_mapping(subject_label="Old Label"))
    head = _mapping_set(_mapping(subject_label="New Label"))

    diff = diff_mapping_sets(base, head)

    assert len(diff.changed) == 1
    assert diff.unchanged_count == 0


# --- predicate_counts ------------------------------------------------------


def test_predicate_counts_counts_per_predicate() -> None:
    mapping_set = _mapping_set(
        _mapping(),
        _mapping(object_id="onz-g:Other", predicate_id="skos:broadMatch"),
        _mapping(object_id="onz-g:Another"),
    )

    counts = predicate_counts(mapping_set)

    assert counts == {"skos:exactMatch": 2, "skos:broadMatch": 1}


def test_predicate_counts_empty_mapping_set() -> None:
    mapping_set = _mapping_set()

    assert predicate_counts(mapping_set) == {}


# --- render_markdown / render_html -----------------------------------------


def test_render_markdown_includes_summary_counts_and_tables() -> None:
    base = _mapping_set(_mapping(object_id="onz-g:ToBeRemoved"))
    head = _mapping_set(_mapping())
    diff = diff_mapping_sets(base, head)

    markdown_text = render_markdown(diff, mapping_set=head, title="Test report")

    assert "# Test report" in markdown_text
    assert "Added: 1" in markdown_text
    assert "Removed: 1" in markdown_text
    assert "Changed: 0" in markdown_text
    assert "Unchanged: 0" in markdown_text
    assert "skos:exactMatch" in markdown_text
    assert "onz-g:Client" in markdown_text
    assert "onz-g:ToBeRemoved" in markdown_text


def test_render_markdown_no_prior_version_shows_everything_added() -> None:
    head = _mapping_set(_mapping())
    diff = diff_mapping_sets(None, head)

    markdown_text = render_markdown(diff, mapping_set=head)

    assert "Added: 1" in markdown_text
    assert "Removed: 0" in markdown_text


def test_render_markdown_changed_table_shows_before_after_values() -> None:
    base = _mapping_set(_mapping(confidence=0.5))
    head = _mapping_set(_mapping(confidence=0.9))
    diff = diff_mapping_sets(base, head)

    markdown_text = render_markdown(diff, mapping_set=head)

    assert "0.5" in markdown_text
    assert "0.9" in markdown_text


def test_render_html_produces_standalone_document_with_table() -> None:
    head = _mapping_set(_mapping())
    diff = diff_mapping_sets(None, head)
    markdown_text = render_markdown(diff, mapping_set=head, title="HTML report")

    html_text = render_html(markdown_text)

    assert html_text.startswith("<!DOCTYPE html>")
    assert "<html" in html_text
    assert "<h1>HTML report</h1>" in html_text
    assert "<table>" in html_text
    assert "omop:Person" in html_text
