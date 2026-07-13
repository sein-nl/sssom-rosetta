"""Read authored CSV+CSVW mapping sets, write derived SSSOM/TSV + RDF/Turtle.

Per AGENTS.md's design principles, the CSV+CSVW metadata pair under
``mappings/`` is the only hand-authored, PR-reviewed mapping source. The
canonical SSSOM/TSV (YAML metadata header + TSV rows) and an RDF/Turtle graph
of the same mappings are *derived* artifacts written to ``build/mappings/``
(gitignored, regenerated on demand): the direction is strictly
CSVW -> {TSV, TTL}, never the reverse.

``read_mapping_set_csvw`` uses the ``csvw`` library to parse the CSV against
its paired CSVW metadata JSON (https://csvw.org) -- this gives us
machine-checked column datatypes/shape (including multivalued columns via
CSVW's ``separator`` property, e.g. ``author_id``) for free, rather than
hand-rolling CSV parsing. Mapping-set-level metadata (``mapping_set_id``,
``license``, ``curie_map``, ...) isn't row data, so it's supplied by the
caller rather than inferred from the CSVW metadata document.

``write_sssom_tsv`` uses ``sssom-py``'s public ``MappingSetDataFrame`` +
``write_tsv`` API so we don't reimplement the SSSOM/TSV YAML-header format
ourselves.

``write_ttl`` builds an RDF/Turtle graph directly with ``rdflib``, asserting
one triple per mapping (subject predicate object, CURIEs expanded via the
same ``prefix_map`` convention as ``mapping.author.expand_curie``). The
original idea (AGENTS.md/plan.md) of deriving the TTL from CSVW's ``csv2rdf``
output was superseded: a straightforward rdflib triple-per-mapping
serialization aligned with the SSSOM model is simpler and sufficient, and
still respects the "CSVW -> {TSV, TTL} only, never the reverse" principle,
since the TTL is generated from the already-parsed ``MappingSet``, not
hand-derived from anything downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pandas as pd
from csvw import CSVW, Table
from curies import Converter
from linkml_runtime.utils.metamodelcore import URI
from rdflib import Graph, URIRef
from sssom.util import MappingSetDataFrame
from sssom.writers import write_tsv

from sssom_rosetta.mapping.author import expand_curie
from sssom_rosetta.mapping.validate import validate_schema_conformance
from sssom_rosetta.models.sssom import MappingSet


def read_mapping_set_csvw(
    csv_path: Path,
    metadata_path: Path,
    *,
    mapping_set_id: str,
    license: str,  # noqa: A002 - matches the SSSOM field name
    curie_map: dict[str, str] | None = None,
    **mapping_set_fields: Any,
) -> MappingSet:
    """Parse an authored CSV + CSVW metadata JSON pair into a ``MappingSet``.

    Each CSV row is expected to use SSSOM core column names (``subject_id``,
    ``predicate_id``, ``object_id``, ``mapping_justification``, ...) matching
    the generated ``Mapping`` model's field names; the CSVW metadata document
    declares each column's datatype (and, for multivalued columns such as
    ``author_id``, its ``separator``), so `csvw` yields already-typed values.

    Args:
        csv_path: Path to the authored mapping CSV.
        metadata_path: Path to the paired CSVW metadata JSON
            (``<csv_path stem>-metadata.json`` by convention).
        mapping_set_id: The ``MappingSet.mapping_set_id`` (not row data).
        license: The ``MappingSet.license`` (not row data).
        curie_map: Optional ``MappingSet.curie_map`` (CURIE prefix -> IRI).
        **mapping_set_fields: Any other ``MappingSet`` fields (e.g.
            ``mapping_set_version``, ``mapping_set_title``).

    Returns:
        A validated ``MappingSet`` containing every row as a ``Mapping``.

    Raises:
        SchemaConformanceError: If the parsed rows plus supplied mapping-set
            metadata don't conform to the generated SSSOM Pydantic schema.
    """
    csvw_table = CSVW(str(csv_path), md_url=str(metadata_path))
    rows: list[dict[str, Any]] = []
    for table in csvw_table.tables:
        table = cast(Table, table)
        for row in table.iterdicts():
            row_dict = cast(dict[str, Any], row)
            # Drop empty/None cells so optional Mapping fields fall back to
            # their model defaults instead of being set to "" or None.
            rows.append(
                {
                    key: value
                    for key, value in row_dict.items()
                    if value not in (None, "")
                }
            )

    payload: dict[str, Any] = {
        "mapping_set_id": URI(mapping_set_id),
        "license": URI(license),
        "curie_map": curie_map,
        "mappings": rows,
        **mapping_set_fields,
    }
    return validate_schema_conformance(payload)


def write_sssom_tsv(mapping_set: MappingSet, output_path: Path) -> None:
    """Write the canonical SSSOM/TSV (YAML header + TSV rows) via ``sssom-py``.

    Args:
        mapping_set: The mapping set to serialize.
        output_path: Destination ``.sssom.tsv`` path (parent directories are
            created if missing, e.g. ``build/mappings/``).
    """
    mappings = mapping_set.mappings or []
    df = pd.DataFrame([_mapping_row(mapping.model_dump()) for mapping in mappings])

    metadata = mapping_set.model_dump(
        exclude={"mappings", "curie_map"}, exclude_none=True
    )
    prefix_map = {
        prefix: str(iri) for prefix, iri in (mapping_set.curie_map or {}).items()
    }
    converter = (
        Converter.from_prefix_map(prefix_map)
        if prefix_map
        else Converter.from_prefix_map({})
    )

    msdf = MappingSetDataFrame(df=df, converter=converter, metadata=metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_tsv(msdf, str(output_path))


def _mapping_row(mapping_dict: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None``-valued fields from a dumped ``Mapping`` for a tidy TSV row.

    Multivalued ``Mapping`` fields (e.g. ``author_id``) are Python lists once
    dumped; SSSOM/TSV represents these as a single ``|``-separated string per
    cell (see ``sssom-schema``'s ``multivalued`` slots), not a raw list, so
    each list value is joined here before it reaches the TSV writer.
    """
    return {
        key: "|".join(value) if isinstance(value, list) else value
        for key, value in mapping_dict.items()
        if value is not None
    }


def write_ttl(
    mapping_set: MappingSet, output_path: Path, *, prefix_map: dict[str, str]
) -> None:
    """Write an RDF/Turtle graph of the mapping set's triples.

    Each ``Mapping`` becomes exactly one triple: ``subject_id predicate_id
    object_id``, all three CURIEs expanded to full IRIs via ``prefix_map``
    (the same convention as ``mapping.author.expand_curie``). This is a
    deliberate simplification over reifying each mapping's metadata
    (confidence, justification, author) as RDF too -- see the "RDF/Turtle
    shape" open item in ``.agents/plan.md`` -- sufficient for the current
    increment's needs.

    Args:
        mapping_set: The mapping set to serialize.
        output_path: Destination ``.ttl`` path (parent directories are
            created if missing, e.g. ``build/mappings/``).
        prefix_map: Maps CURIE prefixes (for both subject, predicate, and
            object) to namespace IRIs.
    """
    graph = Graph()
    for prefix, namespace in prefix_map.items():
        graph.bind(prefix, namespace)

    for index, mapping in enumerate(mapping_set.mappings or []):
        if mapping.subject_id is None or mapping.object_id is None:
            raise ValueError(
                f"Mapping at index {index} is missing subject_id/object_id required to emit a triple"
            )
        subject_iri = expand_curie(mapping.subject_id, prefix_map)
        predicate_iri = expand_curie(mapping.predicate_id, prefix_map)
        object_iri = expand_curie(mapping.object_id, prefix_map)
        graph.add((URIRef(subject_iri), URIRef(predicate_iri), URIRef(object_iri)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(output_path), format="turtle")
