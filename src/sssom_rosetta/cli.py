"""Typer CLI for sssom-rosetta, installed as the `rosetta` console script.

Subcommands are grouped under two sub-apps, ``ontology`` and ``mapping``,
matching the workflow described in AGENTS.md:

- ``rosetta ontology fetch <name>`` — download and cache a registered
  ontology source (see ``ontology.sources``/``ontology.loader``).
- ``rosetta mapping validate <csv> <metadata>`` — parse an authored CSVW
  mapping pair and check schema conformance + referential integrity
  against both ontology graphs.
- ``rosetta mapping build <csv> <metadata>`` — same parsing, then write the
  derived SSSOM/TSV and RDF/Turtle artifacts.
- ``rosetta mapping report`` — thin wrapper around ``mapping.report``
  (implemented separately); degrades gracefully if that module doesn't
  exist yet.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rdflib import Graph

from sssom_rosetta.mapping.docs_pages import generate_mapping_pages
from sssom_rosetta.mapping.io import read_mapping_set_csvw, write_sssom_tsv, write_ttl
from sssom_rosetta.mapping.protege import write_owl_restrictions
from sssom_rosetta.mapping.report import (
    diff_mapping_sets,
    load_mapping_set_tsv,
    render_html,
    render_markdown,
)
from sssom_rosetta.mapping.validate import SchemaConformanceError, validate_mapping_set
from sssom_rosetta.models.sssom import MappingSet
from sssom_rosetta.ontology.loader import (
    DEFAULT_CACHE_DIR,
    ChecksumMismatchError,
    OntologyFetchError,
    fetch_ontology,
    load_ontology,
)
from sssom_rosetta.ontology.sources import (
    ONTOLOGY_SOURCES,
    UnknownOntologySourceError,
    get_source,
)
from sssom_rosetta.vocabulary import loinc_snomed, merge, omop, snomed_international
from sssom_rosetta.vocabulary.fetch import (
    DEFAULT_CACHE_DIR as VOCAB_CACHE_DIR,
    VocabularyChecksumMismatchError,
    VocabularyIngestError,
    cache_dir_for,
    ingest_zip,
)
from sssom_rosetta.vocabulary.sources import (
    UnknownVocabularySourceError,
    get_vocabulary_source,
)

logger = logging.getLogger(__name__)

app = typer.Typer(
    help="Author, validate, and build SSSOM mappings between RDF ontologies."
)
ontology_app = typer.Typer(help="Fetch and cache ontology sources.")
mapping_app = typer.Typer(help="Author, validate, and build SSSOM mapping sets.")
docs_app = typer.Typer(help="Generate the Zensical docs site's generated pages.")
protege_app = typer.Typer(
    help="Build a combined ontologies + mappings OWL file for exploring in Protege."
)
vocabulary_app = typer.Typer(
    help="Ingest large terminology releases (LOINC-SNOMED RF2, OMOP/Athena) and "
    "build a merged vocabulary Turtle graph."
)
app.add_typer(ontology_app, name="ontology")
app.add_typer(mapping_app, name="mapping")
app.add_typer(docs_app, name="docs")
app.add_typer(protege_app, name="protege")
app.add_typer(vocabulary_app, name="vocabulary")

# The two ontology sources every mapping set is validated against. The CLI
# currently only supports the first ontology pair described in AGENTS.md
# (ONZ-G <-> OMOP CDM); ``subject_source``/``object_source`` options let a
# future multi-pair increment override these.
_DEFAULT_SUBJECT_SOURCE = "omop-cdm"
_DEFAULT_OBJECT_SOURCE = "onz-g"


@ontology_app.command("fetch")
def ontology_fetch(
    name: Annotated[
        str, typer.Argument(help="Registry key, e.g. 'onz-g' or 'omop-cdm'.")
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-download even if a cached copy exists."),
    ] = False,
    cache_dir: Annotated[
        Path,
        typer.Option(help="Base directory ontologies are cached under."),
    ] = DEFAULT_CACHE_DIR,
) -> None:
    """Download and cache a registered ontology source, printing the cached path."""
    try:
        source = get_source(name)
    except UnknownOntologySourceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        path = fetch_ontology(source, cache_dir, force=force)
    except (OntologyFetchError, ChecksumMismatchError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(str(path))


def _read_and_validate_csvw(
    csv_path: Path,
    metadata_path: Path,
    *,
    mapping_set_id: str,
    license: str,  # noqa: A002 - matches the SSSOM field name
    curie_map: str,
    subject_source: str,
    object_source: str,
    cache_dir: Path,
) -> tuple[MappingSet, dict[str, str]]:
    """Parse a CSVW mapping pair and validate it against both ontology graphs.

    Shared by ``mapping validate`` and ``mapping build`` so both subcommands
    read/validate identically before diverging (validate reports issues;
    build additionally writes derived artifacts).

    Returns:
        The validated ``MappingSet`` and the ``curie_map`` used to validate it.

    Raises:
        typer.Exit: On any parsing/validation failure, after printing a
            clear error message.
    """
    try:
        parsed_curie_map: dict[str, str] = json.loads(curie_map)
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: --curie-map is not valid JSON: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        mapping_set = read_mapping_set_csvw(
            csv_path,
            metadata_path,
            mapping_set_id=mapping_set_id,
            license=license,
            curie_map=parsed_curie_map,
        )
    except SchemaConformanceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    curie_map_dict = {
        prefix: str(iri) for prefix, iri in (mapping_set.curie_map or {}).items()
    }
    if not curie_map_dict:
        typer.echo(
            "Error: mapping set has no curie_map; cannot resolve CURIEs against "
            'ontology graphs. Pass --curie-map \'{"prefix": "https://...", ...}\'.',
            err=True,
        )
        raise typer.Exit(1)

    try:
        subject_ontology = get_source(subject_source)
        object_ontology = get_source(object_source)
    except UnknownOntologySourceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    subject_graph = load_ontology(subject_ontology, cache_dir)
    object_graph = load_ontology(object_ontology, cache_dir)

    try:
        result = validate_mapping_set(
            mapping_set,
            prefix_map=curie_map_dict,
            subject_graph=subject_graph,
            object_graph=object_graph,
        )
    except SchemaConformanceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    mappings = result.mapping_set.mappings or []
    typer.echo(f"Parsed {len(mappings)} mapping(s).")
    if not result.is_valid:
        typer.echo(f"Found {len(result.issues)} referential integrity issue(s):")
        for issue in result.issues:
            typer.echo(
                f"  [{issue.mapping_index}] {issue.field}={issue.curie!r}: {issue.reason}"
            )
        raise typer.Exit(1)

    return result.mapping_set, curie_map_dict


@mapping_app.command("validate")
def mapping_validate(
    csv_path: Annotated[Path, typer.Argument(help="Authored mapping CSV.")],
    metadata_path: Annotated[Path, typer.Argument(help="Paired CSVW metadata JSON.")],
    mapping_set_id: Annotated[
        str, typer.Option(help="MappingSet.mapping_set_id (not row data).")
    ],
    license: Annotated[  # noqa: A002 - matches the SSSOM field name
        str, typer.Option(help="MappingSet.license (not row data).")
    ],
    curie_map: Annotated[
        str,
        typer.Option(
            "--curie-map",
            help=(
                "MappingSet.curie_map as a JSON object string, e.g. "
                '\'{"omop": "https://w3id.org/omop/ontology/", '
                '"onz-g": "http://purl.org/ozo/onz-g#"}\'. Not row data, and '
                "not currently read from the CSVW metadata document (which has "
                "no standard slot for it)."
            ),
        ),
    ],
    subject_source: Annotated[
        str,
        typer.Option(help="Ontology source name subject_id CURIEs resolve against."),
    ] = _DEFAULT_SUBJECT_SOURCE,
    object_source: Annotated[
        str,
        typer.Option(help="Ontology source name object_id CURIEs resolve against."),
    ] = _DEFAULT_OBJECT_SOURCE,
    cache_dir: Annotated[
        Path,
        typer.Option(help="Base directory ontologies are cached under."),
    ] = DEFAULT_CACHE_DIR,
) -> None:
    """Validate an authored CSVW mapping set: schema + referential integrity.

    ``mapping_set_id``, ``license``, and ``curie_map`` are required options
    rather than read from the CSVW metadata document, since they're
    ``MappingSet``-level metadata (not row data) and the CSVW Metadata
    Vocabulary has no standard slot for them; this keeps parsing unambiguous
    and matches ``mapping.io.read_mapping_set_csvw``'s own signature.
    """
    _read_and_validate_csvw(
        csv_path,
        metadata_path,
        mapping_set_id=mapping_set_id,
        license=license,
        curie_map=curie_map,
        subject_source=subject_source,
        object_source=object_source,
        cache_dir=cache_dir,
    )
    typer.echo("Validation passed.")


@mapping_app.command("build")
def mapping_build(
    csv_path: Annotated[Path, typer.Argument(help="Authored mapping CSV.")],
    metadata_path: Annotated[Path, typer.Argument(help="Paired CSVW metadata JSON.")],
    mapping_set_id: Annotated[
        str, typer.Option(help="MappingSet.mapping_set_id (not row data).")
    ],
    license: Annotated[  # noqa: A002 - matches the SSSOM field name
        str, typer.Option(help="MappingSet.license (not row data).")
    ],
    curie_map: Annotated[
        str,
        typer.Option(
            "--curie-map",
            help=(
                "MappingSet.curie_map as a JSON object string. See "
                "'rosetta mapping validate --help' for details."
            ),
        ),
    ],
    output_dir: Annotated[
        Path, typer.Option(help="Directory derived TSV/TTL artifacts are written to.")
    ] = Path("build/mappings"),
    subject_source: Annotated[
        str,
        typer.Option(help="Ontology source name subject_id CURIEs resolve against."),
    ] = _DEFAULT_SUBJECT_SOURCE,
    object_source: Annotated[
        str,
        typer.Option(help="Ontology source name object_id CURIEs resolve against."),
    ] = _DEFAULT_OBJECT_SOURCE,
    cache_dir: Annotated[
        Path,
        typer.Option(help="Base directory ontologies are cached under."),
    ] = DEFAULT_CACHE_DIR,
) -> None:
    """Validate an authored CSVW mapping set, then write derived SSSOM/TSV + TTL."""
    mapping_set, curie_map_dict = _read_and_validate_csvw(
        csv_path,
        metadata_path,
        mapping_set_id=mapping_set_id,
        license=license,
        curie_map=curie_map,
        subject_source=subject_source,
        object_source=object_source,
        cache_dir=cache_dir,
    )

    tsv_path = output_dir / f"{csv_path.stem}.sssom.tsv"
    ttl_path = output_dir / f"{csv_path.stem}.ttl"
    write_sssom_tsv(mapping_set, tsv_path)
    write_ttl(mapping_set, ttl_path, prefix_map=curie_map_dict)

    typer.echo(str(tsv_path))
    typer.echo(str(ttl_path))


@mapping_app.command("report")
def mapping_report(
    head: Annotated[
        Path,
        typer.Option(help="Generated head '.sssom.tsv' (e.g. from `mapping build`)."),
    ],
    base: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Generated base '.sssom.tsv' to diff against, if any. Omit "
                "(or point at a nonexistent path) to render every head "
                "mapping as 'added', e.g. for a docs page or a PR that adds "
                "the mapping set for the first time."
            ),
        ),
    ] = None,
    title: Annotated[str, typer.Option(help="Report title.")] = "Mapping report",
    output_markdown: Annotated[
        Path | None, typer.Option(help="Write the rendered Markdown here, if given.")
    ] = None,
    output_html: Annotated[
        Path | None, typer.Option(help="Write the rendered HTML here, if given.")
    ] = None,
) -> None:
    """Render a Markdown (+ optional HTML) diff report from generated SSSOM/TSV file(s).

    Reads from the *generated* ``.sssom.tsv`` (see ``mapping build``), not
    the hand-authored CSV, so the report reflects fully resolved/validated
    data (see ``mapping.report``'s module docstring). If neither
    ``--output-markdown`` nor ``--output-html`` is given, the Markdown is
    printed to stdout.
    """
    head_mapping_set = load_mapping_set_tsv(head)
    base_mapping_set = (
        load_mapping_set_tsv(base) if base is not None and base.exists() else None
    )

    diff = diff_mapping_sets(base_mapping_set, head_mapping_set)
    markdown_text = render_markdown(diff, mapping_set=head_mapping_set, title=title)

    if output_markdown is not None:
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(markdown_text)
    if output_html is not None:
        output_html.parent.mkdir(parents=True, exist_ok=True)
        output_html.write_text(render_html(markdown_text))
    if output_markdown is None and output_html is None:
        typer.echo(markdown_text)


@docs_app.command("generate-mapping-pages")
def docs_generate_mapping_pages(
    build_dir: Annotated[
        Path,
        typer.Option(help="Directory containing generated <name>.sssom.tsv files."),
    ] = Path("build/mappings"),
    docs_dir: Annotated[
        Path,
        typer.Option(
            help="Directory generated docs/mappings/<name>.md pages are written to."
        ),
    ] = Path("docs/mappings"),
) -> None:
    """Regenerate `docs/mappings/*.md` from `build/mappings/*.sssom.tsv`.

    Reuses `mapping.report`'s renderer (`load_mapping_set_tsv` +
    `diff_mapping_sets(None, ...)` + `render_markdown`) via
    `mapping.docs_pages.generate_mapping_pages`, so the published docs site
    and the PR report share one rendering code path, per AGENTS.md.
    """
    written = generate_mapping_pages(build_dir, docs_dir)
    if not written:
        typer.echo(
            f"No .sssom.tsv files found under {build_dir}; nothing generated.",
            err=True,
        )
        raise typer.Exit(1)

    for page_path in written:
        typer.echo(str(page_path))


@protege_app.command("build")
def protege_build(
    csv_path: Annotated[Path, typer.Argument(help="Authored mapping CSV.")],
    metadata_path: Annotated[Path, typer.Argument(help="Paired CSVW metadata JSON.")],
    mapping_set_id: Annotated[
        str, typer.Option(help="MappingSet.mapping_set_id (not row data).")
    ],
    license: Annotated[  # noqa: A002 - matches the SSSOM field name
        str, typer.Option(help="MappingSet.license (not row data).")
    ],
    curie_map: Annotated[
        str,
        typer.Option(
            "--curie-map",
            help=(
                "MappingSet.curie_map as a JSON object string. See "
                "'rosetta mapping validate --help' for details."
            ),
        ),
    ],
    output_path: Annotated[
        Path,
        typer.Option(help="Combined OWL/Turtle file path written for Protege to open."),
    ] = Path("build/protege/omop-onz-g.combined.ttl"),
    subject_source: Annotated[
        str,
        typer.Option(help="Ontology source name subject_id CURIEs resolve against."),
    ] = _DEFAULT_SUBJECT_SOURCE,
    object_source: Annotated[
        str,
        typer.Option(help="Ontology source name object_id CURIEs resolve against."),
    ] = _DEFAULT_OBJECT_SOURCE,
    cache_dir: Annotated[
        Path,
        typer.Option(help="Base directory ontologies are cached under."),
    ] = DEFAULT_CACHE_DIR,
) -> None:
    """Merge both source ontologies with the mapping set into one Protege-ready OWL file.

    Unlike ``mapping build``'s ``.ttl`` output (one flat triple per mapping,
    correct SSSOM/RDF), mappings here are emitted as OWL class-level axioms
    (``owl:equivalentClass`` for ``skos:exactMatch``, existential
    restrictions for every other predicate) via
    ``mapping.protege.write_owl_restrictions``, so OntoGraf in Protege can
    render them as edges between the OMOP CDM and ONZ-G class nodes. See
    ``README.md``'s "Exploring the combined graph in Protege" section.
    """
    mapping_set, curie_map_dict = _read_and_validate_csvw(
        csv_path,
        metadata_path,
        mapping_set_id=mapping_set_id,
        license=license,
        curie_map=curie_map,
        subject_source=subject_source,
        object_source=object_source,
        cache_dir=cache_dir,
    )

    subject_ontology = get_source(subject_source)
    object_ontology = get_source(object_source)
    subject_graph = load_ontology(subject_ontology, cache_dir)
    object_graph = load_ontology(object_ontology, cache_dir)

    combined = Graph()
    for prefix, namespace in curie_map_dict.items():
        combined.bind(prefix, namespace)
    for graph in (subject_graph, object_graph):
        for triple in graph:
            combined.add(triple)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_owl_restrictions(mapping_set, output_path, prefix_map=curie_map_dict)

    mapping_graph = Graph()
    mapping_graph.parse(str(output_path), format="turtle")
    for triple in mapping_graph:
        combined.add(triple)

    combined.serialize(destination=str(output_path), format="turtle")
    typer.echo(str(output_path))


DEFAULT_VOCAB_OUTPUT_DIR = Path("build/vocabularies")


@vocabulary_app.command("ingest")
def vocabulary_ingest(
    name: Annotated[
        str,
        typer.Argument(
            help="Registry key: 'loinc-snomed', 'snomed-international' or 'omop'."
        ),
    ],
    zip_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the locally-downloaded, licence-gated release ZIP."
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-extract even if a cached copy exists."),
    ] = False,
    cache_dir: Annotated[
        Path,
        typer.Option(help="Base directory releases are extracted under."),
    ] = VOCAB_CACHE_DIR,
) -> None:
    """Verify and extract a curator-provided release ZIP into the local cache."""
    try:
        source = get_vocabulary_source(name)
    except UnknownVocabularySourceError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        target_dir = ingest_zip(source, zip_path, cache_dir, force=force)
    except (VocabularyIngestError, VocabularyChecksumMismatchError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(str(target_dir))


@vocabulary_app.command("build-loinc-snomed")
def vocabulary_build_loinc_snomed(
    output_dir: Annotated[
        Path, typer.Option(help="Directory the Turtle graph is written to.")
    ] = DEFAULT_VOCAB_OUTPUT_DIR,
    cache_dir: Annotated[
        Path, typer.Option(help="Base directory releases are extracted under.")
    ] = VOCAB_CACHE_DIR,
) -> None:
    """Build ``loinc-snomed.ttl`` from the ingested LOINC-SNOMED RF2 release."""
    source = get_vocabulary_source("loinc-snomed")
    release_dir = cache_dir_for(source, cache_dir)
    if not release_dir.is_dir():
        typer.echo(
            f"Error: no ingested release at {release_dir}. Run "
            "'rosetta vocabulary ingest loinc-snomed <zip>' first.",
            err=True,
        )
        raise typer.Exit(1)

    graph = loinc_snomed.build_from_release(release_dir)
    output_path = loinc_snomed.write_ttl(graph, output_dir / "loinc-snomed.ttl")
    typer.echo(str(output_path))


@vocabulary_app.command("build-snomed-international")
def vocabulary_build_snomed_international(
    output_dir: Annotated[
        Path, typer.Option(help="Directory the Turtle graph is written to.")
    ] = DEFAULT_VOCAB_OUTPUT_DIR,
    cache_dir: Annotated[
        Path, typer.Option(help="Base directory releases are extracted under.")
    ] = VOCAB_CACHE_DIR,
) -> None:
    """Build ``snomed-international.ttl`` from the ingested International release."""
    source = get_vocabulary_source("snomed-international")
    release_dir = cache_dir_for(source, cache_dir)
    if not release_dir.is_dir():
        typer.echo(
            f"Error: no ingested release at {release_dir}. Run "
            "'rosetta vocabulary ingest snomed-international <zip>' first.",
            err=True,
        )
        raise typer.Exit(1)

    graph = snomed_international.build_from_release(release_dir)
    output_path = snomed_international.write_ttl(
        graph, output_dir / "snomed-international.ttl"
    )
    typer.echo(str(output_path))


@vocabulary_app.command("build-omop")
def vocabulary_build_omop(
    output_dir: Annotated[
        Path, typer.Option(help="Directory the Turtle graph is written to.")
    ] = DEFAULT_VOCAB_OUTPUT_DIR,
    cache_dir: Annotated[
        Path, typer.Option(help="Base directory releases are extracted under.")
    ] = VOCAB_CACHE_DIR,
) -> None:
    """Build ``omop.ttl`` from the ingested OMOP/Athena vocabulary bundle."""
    source = get_vocabulary_source("omop")
    release_dir = cache_dir_for(source, cache_dir)
    if not release_dir.is_dir():
        typer.echo(
            f"Error: no ingested release at {release_dir}. Run "
            "'rosetta vocabulary ingest omop <zip>' first.",
            err=True,
        )
        raise typer.Exit(1)

    graph = omop.build_from_release(release_dir)
    output_path = omop.write_ttl(graph, output_dir / "omop.ttl")
    typer.echo(str(output_path))


@vocabulary_app.command("merge")
def vocabulary_merge(
    output_dir: Annotated[
        Path, typer.Option(help="Directory the merged Turtle graph is written to.")
    ] = DEFAULT_VOCAB_OUTPUT_DIR,
) -> None:
    """Merge the vocabulary graphs into ``rosetta-vocabularies.ttl``.

    Combines whichever of ``omop.ttl``, ``snomed-international.ttl`` and
    ``loinc-snomed.ttl`` are present. OMOP is the base layer and is normally the
    only input; the native SNOMED/LOINC RF2 graphs are optional (deferred
    OWL-DL follow-up). Because all mint identical ``sct:`` IRIs, when the
    optional graphs are present the OMOP concept_ids and any native concepts
    attach to each other automatically once unioned.
    """
    candidates = [
        output_dir / "omop.ttl",
        output_dir / "snomed-international.ttl",
        output_dir / "loinc-snomed.ttl",
    ]
    inputs = [path for path in candidates if path.exists()]
    if not inputs:
        typer.echo(
            "Error: no input graphs found to merge. Run 'build-omop' "
            "(and optionally 'build-snomed-international' / "
            "'build-loinc-snomed') first.",
            err=True,
        )
        raise typer.Exit(1)

    output_path = merge.merge_ttl_files(inputs, output_dir / "rosetta-vocabularies.ttl")
    typer.echo(str(output_path))


__all__ = ["app", "ONTOLOGY_SOURCES"]


if __name__ == "__main__":
    app()
