# sssom-rosetta

## What the project does

sssom-rosetta produces [SSSOM](https://mapping-commons.github.io/sssom/) mappings between RDF ontologies used in Dutch healthcare. Unlike the earlier LinkML-Rosetta prototype (https://docs.plugin.dhd.nl/linkml-rosetta/), which mapped between LinkML schemas, this project starts from existing RDF/OWL ontologies as the source of truth and treats SSSOM as the interchange format for the mappings themselves.

The first pair of ontologies mapped:

- ONZ-G 2.8.1 (Een Ontologie voor de Nederlandse Zorg — Generiek), IRI `http://purl.org/ozo/onz-g`, published at https://kik-v-publicatieplatform.nl/ontologie/onz-g/2.8.1. TTL/OWL/JSON-LD downloads are linked from that page (`ontology.ttl`, `.owl`, `.jsonld`).
- OMOP CDM OWL, IRI-namespaced ontology generated from the OMOP CDM v5.4 schema, published at https://plugin-healthcare.github.io/omop-cdm-owl/, source and `ontology.ttl` at https://github.com/plugin-healthcare/omop-cdm-owl.

Example mapping: `omop:Person skos:exactMatch onz-g:Client`.

The `rosetta` CLI (installed from this package) drives the whole workflow: fetching and caching ontologies, authoring and validating mapping sets, and building derived SSSOM/TSV and RDF/Turtle artifacts plus a published documentation site.

## Why the project is useful

Healthcare data integration in the Netherlands regularly needs crosswalks between reference models like OMOP CDM and domain ontologies like ONZ-G, but hand-maintained mapping spreadsheets drift from the ontologies they describe and are hard to validate or review. sssom-rosetta addresses this with a small set of design principles:

1. **Ontologies are the source of truth.** Entity lists are never hand-authored. Classes, properties, and labels used in a mapping must be resolvable in the source ontology graphs, enforced by validating every `subject_id`/`object_id` against a loaded RDF graph before a mapping is accepted.
2. **SSSOM is the wire format, Pydantic is the authoring interface.** Mappings are authored as Python objects (`Mapping`, `MappingSet`) and serialized to SSSOM/TSV (plus a YAML metadata header) for storage, review, and exchange with other SSSOM tooling (`sssom-py`, the SSSOM Toolkit).
3. **CSVW is the human-authored source of truth; TSV and TTL are derived.** Curators edit CSV files under `mappings/`, each paired with a [CSVW](https://csvw.org) metadata file. Naming convention: a table `mappings/<name>.csv` is always paired with `mappings/<name>.metadata.json` (e.g. `mappings/omop-onz-g.csv` + `mappings/omop-onz-g.metadata.json`, `mappings/contributors.csv` + `mappings/contributors.metadata.json`), dot-separated, not `<name>-metadata.json`, per the [CSVW Metadata Vocabulary](https://www.w3.org/TR/tabular-metadata/). The metadata file declares column datatypes and URI templates for the SSSOM core columns (`subject_id`, `predicate_id`, `object_id`, ...), giving machine-checkable typing/shape for the raw CSV via a standard, tool-agnostic mechanism, and a standard `csv2rdf` path from CSV to RDF rather than a bespoke one. `rosetta mapping build` reads CSV+CSVW metadata, validates it, and generates the canonical SSSOM/TSV file (with YAML metadata header) and an RDF/Turtle representation of the same mappings as build artifacts. The CSV/CSVW pair is never hand-derived from TSV/TTL; the direction is strictly CSVW → {TSV, TTL}.
4. **Ontology-first, code-generated models.** The SSSOM data model isn't hand-written. LinkML's `gen-pydantic` generates `Mapping` and `MappingSet` BaseModels directly from the canonical `sssom-schema` LinkML YAML (https://github.com/mapping-commons/sssom-schema), keeping the project aligned with upstream SSSOM releases and avoiding drift.
5. **Validation over convention.** Every mapping is checked against: the SSSOM LinkML schema (via the generated Pydantic models), existence of subject/object IRIs in the respective ontology graphs, and the full `mapping_predicate` value space defined by the SSSOM spec (the `semapv`/SKOS/OWL/RDFS predicates enumerated in the `sssom-schema` `predicate_id` range), not a curated subset. Schema conformance alone enforces this, since the generated Pydantic models carry that range.
6. **Reproducible ontology fetch.** Ontology sources are pinned by version/commit and cached locally; nothing is scraped from HTML at mapping time.
7. **Reproducible schema.** `sssom-schema` is pinned to a released version tag in `pyproject.toml` (not tracked against `main`), so `gen-pydantic` output only changes on a deliberate version bump.

## How users can get started with the project

### Install

```
uv sync --all-groups
```

`just` (a command runner) is installed as a dev dependency (`rust-just` on PyPI), so `uv sync` alone is enough to get it; run recipes via `uv run just <recipe>`, or `just <recipe>` directly if `just` is also on your `PATH`. Run `just` (no arguments) to list every available recipe, e.g. `just build-all` runs the full local pipeline (fetch ontologies, validate + build + report the mapping set, build the Protege export, regenerate docs, build the site), or `just check` runs lint + typecheck + tests. See the `justfile` for the full list.

### Architecture

```
src/sssom_rosetta/
  models/
    sssom.py                  # generated Pydantic models (gen-pydantic output, checked in, regenerated via task)
    generated/                # raw gen-pydantic output before curation, gitignored
  ontology/
    sources.py                # registry: name, IRI, version, download URL, local cache path
    loader.py                 # rdflib.Graph loader with caching under data/ontologies/
    catalog.py                # queries a loaded graph for classes/properties/labels
  mapping/
    author.py                 # helpers to build Mapping/MappingSet Pydantic objects
    validate.py               # cross-checks mappings against ontology catalogs + SSSOM schema
    io.py                     # read CSV+CSVW metadata (source), generate SSSOM/TSV + TTL (derived)
    report.py                 # renders a mapping set diff to Markdown/HTML for PR review
  cli.py                      # typer app, installed as the `rosetta` console script

data/
  ontologies/                 # cached TTL downloads, one subdir per source + version
mappings/
  omop-onz-g.csv              # curated mapping set data, hand-authored, one CSV per ontology pair
  omop-onz-g.metadata.json    # CSVW table metadata: column datatypes + URI templates (csv2rdf)
  contributors.csv            # lookup: ORCID -> contributor name, for author_id/reviewer_id/creator_id columns
  contributors.metadata.json  # CSVW table metadata for contributors.csv
build/
  mappings/
    omop-onz-g.sssom.tsv      # generated: canonical SSSOM/TSV (YAML header + sssom-py)
    omop-onz-g.ttl            # generated: RDF/Turtle representation of the same mappings
                              # (gitignored; regenerated by `rosetta mapping build`)
docs/
  index.md                    # Zensical site: project overview, links to mapping sets
  ontologies/                 # one page per source ontology (provenance, version, IRI)
  mappings/                   # one page per mapping set, rendered from the generated TSV
  zensical.toml (repo root)   # Zensical site config (nav, theme); see below
tests/
  ontology/
  mapping/
```

### Workflow

1. **Fetch**: `rosetta ontology fetch <name>` downloads and caches the pinned ontology version into `data/ontologies/<name>/<version>/ontology.ttl` and records checksum + source URL in `ontology/sources.py`. `just fetch` fetches both registered sources (`omop-cdm`, `onz-g`) in one step.
2. **Catalog**: the loader parses the TTL into an `rdflib.Graph`; `catalog.py` exposes `list_classes()`, `list_properties()`, `resolve_label(iri)` used both by authoring helpers and by validation.
3. **Author**: mappings are hand-edited as rows in `mappings/*.csv` (one row per mapping, columns matching the SSSOM core fields: `subject_id`, `subject_label`, `predicate_id`, `object_id`, `object_label`, `mapping_justification`, `author_id`, `confidence`, `comment`, ...), paired with a CSVW metadata file `mappings/*.metadata.json` declaring each column's datatype and, for the `*_id` columns, a `valueUrl` URI template so the pair is directly usable with the standard `csv2rdf` algorithm. `mapping/author.py` also exposes `build_mapping(...)` for programmatic/scripted authoring, which resolves CURIEs against the ontology catalogs and constructs a generated `Mapping` Pydantic object, e.g.:

   ```python
   from sssom_rosetta.models.sssom import Mapping
   from sssom_rosetta.mapping.author import build_mapping

   mapping = build_mapping(
       subject_curie="omop:Person",
       predicate="skos:exactMatch",
       object_curie="onz-g:Client",
       mapping_justification="semapv:ManualMappingCuration",
       author_id="orcid:0000-0000-0000-0000",
       confidence=0.9,
   )
   ```

   `build_mapping` rejects unresolvable IRIs before the object is constructed; the CLI uses it to validate every row loaded via the CSVW metadata.
4. **Validate**: `rosetta mapping validate mappings/omop-onz-g.csv mappings/omop-onz-g.metadata.json` loads the CSV through its CSVW metadata (`csvw` library, column datatype/shape conformance), maps rows into `Mapping`/`MappingSet` Pydantic objects (SSSOM schema conformance), and re-checks every subject/object IRI against the cached ontology graphs (referential integrity). All three must pass before merge. `just validate` runs this with the project's pinned `mapping-set-id`, `license`, and `curie-map` already filled in.
5. **Build**: `rosetta mapping build mappings/omop-onz-g.csv mappings/omop-onz-g.metadata.json` re-validates the CSV+CSVW pair, then writes `build/mappings/omop-onz-g.sssom.tsv` (canonical SSSOM/TSV with YAML metadata header, curie map, license, mapping_set_id, via `sssom-py`) and `build/mappings/omop-onz-g.ttl` (an RDF/Turtle graph asserting each mapping as a triple `subject predicate object`, annotated with the mapping's metadata). Generated files are gitignored and rebuilt on demand (CI, docs build, releases); the CSV+CSVW pair is the only source reviewed in PRs. `just build` runs this step.
6. **Report**: on every PR touching `mappings/*.csv` or `mappings/*.metadata.json`, CI runs `rosetta mapping report` to render a Markdown (and HTML) summary of the diff, added/removed/changed mappings, per-predicate counts, subject/object labels resolved from the ontology catalogs for readability, and posts/attaches it to the PR so reviewers don't have to read raw CSV/TSV. `just report` renders the same report locally from the generated TSV, writing Markdown and HTML to `build/mappings/`.

`just build-all` runs the whole pipeline in order (fetch, validate, build, report, the Protege export from the section below, regenerate `docs/mappings/*.md`, and build the Zensical site), so a single command reproduces everything CI does. See the `justfile` for every available recipe (`just` with no arguments lists them), and `just check` to run lint, type-check, and tests together.

## Authoring of SSSOM mappings with `broadMatch`, `narrowMatch` and `exactMatch`

- To assert that one concept is broader in meaning (i.e. more general) than another, the skos:broadMatch property is used. The skos:narrower property is used to assert the inverse, namely when one concept is narrower in meaning (i.e. more specific) than another. For example:

```
ex:animals rdf:type skos:Concept;
  skos:prefLabel "animals"@en;
  skos:narrowMatch ex:mammals.
ex:mammals rdf:type skos:Concept;
  skos:prefLabel "mammals"@en;
  skos:broadMatch ex:animals.
```

- Note on skos:broadMatch direction: for historic reasons, the name of the skos:broadMatch property does not provide an explicit indication of its direction. The word "broadMatch" should read here as "has broader concept"; the subject of a skos:broader statement is the more specific concept involved in the assertion and its object is the more generic one.
- As is often the case in KOS, a SKOS concept can be attached to several broader concepts at the same time. For example, a concept ex:dog could have both ex:mammals and ex:domesticatedAnimals as broader concepts.
- Prefer use of `broadMatch`, `narrowMatch` and `exactMatch` over `relatedMatch`

### Key dependencies

- `rdflib` — load and query ONZ-G / OMOP CDM OWL graphs (SPARQL for class/property existence checks and label lookups).
- `csvw` — parses `mappings/*.csv` against its paired `*.metadata.json` (CSVW Metadata Vocabulary): typed row access and standard `csv2rdf` conversion, so CSV validation and the CSV→RDF path follow the W3C standard instead of bespoke parsing.
- `linkml` — provides the `gen-pydantic` generator used to build `models/sssom.py` from the `sssom-schema` LinkML YAML. Regenerate with a pinned `sssom-schema` version; don't hand-edit generated fields.
- `sssom` (sssom-py) — reference implementation; used for SSSOM/TSV read/write and for validation parity with the wider SSSOM ecosystem, so the TSV/YAML-header format isn't reimplemented.
- `pydantic` — runtime validation for authored mappings (already the gen-pydantic output base class).
- `typer` — CLI, consistent with the rest of the plugin-healthcare tooling; the app is installed as the `rosetta` console script (`[project.scripts] rosetta = "sssom_rosetta.cli:app"`).
- `polars` — any tabular analysis of mapping sets (coverage stats, diffs); also used to read/validate the authored CSV files, and to parse the large LOINC-SNOMED RF2 and OMOP/Athena terminology tables in the `rosetta vocabulary` pipeline.
- `zensical` — static documentation site generator for `/docs`, published to GitHub Pages.

### Documentation site

Project documentation is a static site built with [Zensical](https://zensical.org) (the MkDocs-Material successor), sourced from Markdown in `/docs`:

- `docs/index.md` — project overview, links to the ontology pair(s) covered.
- `docs/ontologies/<name>.md` — one page per source ontology: pinned version, IRI, download URL, license, short description.
- `docs/mappings/<pair>.md` — one page per mapping set, generated (not hand written) from the corresponding generated `build/mappings/*.sssom.tsv` using the same rendering used for the PR report (`mapping/report.py`), so the published site and PR reports share one code path. The rendered page links to the generated `.sssom.tsv` and `.ttl` as downloads.
- Site configuration lives in the Zensical config file at the repo root (`zensical.toml` or `mkdocs.yml`-equivalent per current Zensical convention); `zensical build` outputs to `site/` (gitignored).
- Published via GitHub Pages on merge to the default branch (CI step after the mapping-report job, only on `main`).

### Testing

```
uv run pytest
```

Or `just test` / `just check` (lint + typecheck + test), see the "Install" section above.

Follows TDD per repo conventions:

- `tests/ontology/`: fixtures are small extracted subgraphs (a handful of triples per ontology), not the full downloaded TTL, so tests run offline and fast.
- `tests/mapping/`: given a fixture catalog for OMOP + ONZ-G, asserts that `build_mapping` accepts valid CURIE pairs, rejects unknown IRIs, rejects disallowed predicates, that CSV+CSVW-metadata parsing (via `csvw`) round-trips through the generated Pydantic models, and that `mapping build` produces `.sssom.tsv` and `.ttl` output matching expected fixture files.
- Tests never hit the network; `ontology fetch` itself is tested against a mocked HTTP response.

### CI: mapping report on PRs

A GitHub Actions workflow triggers on PRs that change `mappings/**` (CSV + CSVW metadata files):

1. Checkout base and head refs.
2. Run `rosetta mapping validate` on the head ref's CSV+CSVW mapping sets (CSVW shape conformance + SSSOM schema conformance + ontology referential integrity); fail the check on any violation.
3. Run `rosetta mapping build` to generate `.sssom.tsv` and `.ttl` for both base and head, then `rosetta mapping report --base <base-ref> --head <head-ref>` to render the Markdown/HTML diff report from those generated files.
4. Post the Markdown report as a PR comment (upsert, not duplicate on re-runs) and upload the generated `.sssom.tsv`/`.ttl`/HTML report as build artifacts.

On merge to the default branch, a separate CI job re-runs `rosetta mapping build` to regenerate `build/mappings/*.{sssom.tsv,ttl}`, regenerates `docs/mappings/*.md` from those files, runs `zensical build`, and publishes `site/` to GitHub Pages.

## Integrating vocabularies & ontologies into one graph

Alongside the curated SSSOM mapping sets, the `rosetta vocabulary` sub-app builds
a single merged RDF/Turtle graph that integrates the reference terminologies and
domain ontologies this project maps between. RF2/CSV tables are parsed with
**polars** and the graph is built with **rdflib**. This is a *vocabulary graph*
built from the terminology releases directly, distinct from the hand-authored
SSSOM mappings under `mappings/`.

### Scope & architecture: OMOP as the base, plus Dutch domain ontologies

**We start from the OHDSI/OMOP Standardized Vocabularies as the base layer.**
OMOP has already done the cross-vocabulary harmonisation we need: it ingests and
unifies SNOMED CT (International), LOINC, RxNorm, ICD-10/ICD-10-CM and others into
one concept space with pre-computed hierarchy (`Is a` / `Subsumes`) and a
transitive-closure `CONCEPT_ANCESTOR` table. For our purpose — cross-vocabulary
mapping and hierarchical rollups — that is sufficient, and it means:

- **We do *not* separately ingest SNOMED CT International.** It is already
  included, mapped and hierarchically connected inside OMOP.
- **We do *not* separately ingest the LOINC (or LOINC-SNOMED) Ontology.** LOINC
  is likewise already included in OMOP.

This is a deliberate consequence of having **deferred full OWL-DL reasoning**
(see `.agents/plan/2026-07-21-owl-dl-classification-deferral-note.md`). OMOP is a
faithful base *when you do not need*:

- **Description-Logic reasoning / classification** — OMOP flattens SNOMED and
  drops the OWL axioms, so an ELK/HermiT reasoner cannot re-classify concepts
  from it.
- **SNOMED relationship grouping** — OMOP strips role groups, so it can't tell
  you that *finding-site 1 + method 1* belong together as one group distinct from
  *site 2 + method 2*.
- **Post-coordination / dynamic SNOMED expressions** — OMOP only carries
  pre-coordinated, static `concept_id`s.
- **Native SNOMED refsets/subsets** (GP subsets, language refsets, national
  extensions) that OHDSI does not distribute via ATHENA.

We need none of these for cross-vocabulary mapping and cohort-style hierarchical
queries, so **native SNOMED CT / LOINC ingestion stays out of scope** until a
consumer requires OWL reasoning, relationship groups, post-coordination, or
native refsets — at which point the deferred OWL-DL follow-up is revisited.

**On top of the OMOP base we add vocabularies and ontologies specific to the
Dutch healthcare domain**, which OMOP does *not* contain:

| Vocabulary / ontology | Status | Notes |
|-----------------------|--------|-------|
| **KIK-V ONZ-G** | **available** | Een Ontologie voor de Nederlandse Zorg — Generiek (`onz-g`), the first ontology mapped in this repo. |
| **Z-Index (G-Standaard)** | *to be added* | Dutch drug/product database. |
| **DHD Diagnosethesaurus** | *to be added* | Dutch Hospital Data diagnosis thesaurus. |
| **DHD Verrichtingenthesaurus** | *to be added* | Dutch Hospital Data procedures thesaurus. |

The end state is one graph in which OMOP `concept_id`s (cross-linked to SNOMED,
LOINC, RxNorm, ICD-10/CM) are joined to the Dutch domain ontologies via the
curated SSSOM mappings — OMOP providing the international backbone, the Dutch
ontologies providing the local domain coverage OMOP lacks.

Output artifacts (all under `build/vocabularies/`, gitignored, regenerated on
demand):

- `omop.ttl` — OMOP concept graph, each `concept_id` a hub node cross-linked to
  its native source-vocabulary concept (SNOMED, LOINC, RxNorm, ICD-10/CM).
- `rosetta-vocabularies.ttl` — the merged graph.

### What you need to download first

The OMOP bundle is **licence-gated**, so there is no open download URL to fetch
automatically. You must download the release archive manually (accepting the
relevant licences) and then *ingest* it locally:

- **OHDSI/OMOP Standardized Vocabularies** (registry key `omop`).
  - Download a vocabulary bundle ZIP from <https://athena.ohdsi.org/> (Athena
    account required). When selecting vocabularies, tick at least: **SNOMED,
    LOINC, RxNorm, RxNorm Extension, ICD10, ICD10CM**. (Do *not* select CPT4
    unless you have a UMLS licence and are prepared to run its `cpt4.jar`
    reconstitution step; it is not needed here.)
  - The bundle is a ZIP of tab-delimited files with a `.csv` extension
    (`CONCEPT.csv`, `CONCEPT_RELATIONSHIP.csv`, ...).

> **Note.** The `rosetta vocabulary` sub-app also retains a `loinc-snomed` /
> `snomed-international` RF2 ingest path (SNOMED CT extension + International
> Edition, both licence-gated). These are **not part of the default merged
> graph** described above — OMOP already includes that content — and are kept
> only for the future OWL-DL / native-SNOMED follow-up. Use them only if you
> explicitly need native RF2 content OMOP does not carry.

### How to start the ingest

Ingesting verifies the ZIP's SHA-256 checksum (when one is pinned in
`vocabulary/sources.py`) and extracts it under `data/vocabularies/<name>/<version>/`
(gitignored). It's idempotent — an already-extracted release is reused unless you
pass `--force`.

```
# Ingest the downloaded OMOP bundle (path is wherever you saved it):
uv run rosetta vocabulary ingest omop ~/Downloads/athena_vocabularies.zip

# or via just:
just vocab-ingest omop ~/Downloads/athena_vocabularies.zip
```

### Build and merge

Once the OMOP bundle is ingested, build the graph:

```
uv run rosetta vocabulary build-omop   # -> build/vocabularies/omop.ttl
uv run rosetta vocabulary merge        # -> build/vocabularies/rosetta-vocabularies.ttl

# or the whole chain in one step:
just vocab-build
```

The `vocab-*` recipes are intentionally **not** part of `just build-all`, since
they depend on a manually-downloaded, licence-gated ZIP being ingested first.

### How the graph is shaped

- SNOMED/LOINC-extension concepts use IRIs `http://snomed.info/id/{sctid}` (`sct:` prefix); OMOP concepts use `https://w3id.org/omop/concept/{concept_id}` (`omopconcept:` prefix); source codes use `loinc:`, `rxnorm:`, `icd10:`, `icd10cm:` namespaces.
- Each OMOP concept carries `skos:prefLabel` (concept name), `skos:notation` (source code), and a `skos:exactMatch` to its native source IRI (e.g. an OMOP SNOMED concept → `sct:<sctid>`). Concepts with no native code (e.g. `RxNorm Extension`) stay OMOP-minted.
- Relationships map to SKOS: OMOP `Maps to` → `skos:exactMatch`, `Is a` → `skos:broadMatch` (child → parent), OMOP `Subsumes` → `skos:narrowMatch`. `broadMatch` direction follows the project convention (subject is the more specific concept).
- The graph is a lightweight SKOS/RDFS representation. Materialising the full OWL-DL logical definitions (via native SNOMED RF2 + `snomed-owl-toolkit` + ELK) is a deliberately deferred follow-up — see `.agents/plan/2026-07-21-owl-dl-classification-deferral-note.md`.

> [!IMPORTANT]
> **OMOP relationship → SKOS mapping, and why transitivity matters**
>
> The `rosetta vocabulary` graph maps OMOP `CONCEPT_RELATIONSHIP` rows onto SKOS
> mapping properties:
>
> | OMOP `relationship_id` | SKOS predicate | Direction | Transitive? |
> |------------------------|----------------|-----------|-------------|
> | `Maps to` | `skos:exactMatch` | symmetric | **yes** |
> | `Is a` | `skos:broadMatch` | subject = more specific (child → parent) | **no** |
> | `Subsumes` | `skos:narrowMatch` | subject = more generic (parent → child) | **no** |
>
> **Transitive vs. non-transitive SKOS properties.** SKOS distinguishes two
> families of linking properties:
>
> - **Within a single vocabulary**, the hierarchical properties `skos:broader` /
>   `skos:narrower` have explicit transitive super-properties
>   `skos:broaderTransitive` / `skos:narrowerTransitive`. A chain of `broader`
>   links can therefore be safely followed to infer indirect ancestry, and
>   `skos:exactMatch` is defined as **transitive** (and symmetric): if
>   `A exactMatch B` and `B exactMatch C`, then `A exactMatch C`.
> - **Across vocabularies**, the mapping properties `skos:closeMatch`,
>   `skos:broadMatch` and `skos:narrowMatch` are **not** transitive. Crucially,
>   the W3C Semantic Web Deployment Working Group **deliberately omitted** any
>   `skos:broadMatchTransitive` / `skos:narrowMatchTransitive` equivalents from
>   the [W3C SKOS Reference](https://www.w3.org/TR/skos-reference/) — precisely
>   to **discourage unsafe automated reasoning across different vocabularies**,
>   where chaining cross-walk links tends to accumulate meaning drift and produce
>   false equivalences.
>
> **`exactMatch` (transitive) vs. `closeMatch` (not transitive) when authoring
> mappings.** This distinction is the single most important choice when creating
> a mapping:
>
> - Use **`skos:exactMatch`** only when two concepts can be used
>   interchangeably across a wide range of information-retrieval applications.
>   Because it is transitive, an `exactMatch` you assert can be **chained** with
>   others by downstream tooling — so an incorrect `exactMatch` propagates.
> - Use **`skos:closeMatch`** when two concepts are *sufficiently similar* to be
>   linked but are **not** guaranteed interchangeable. It is intentionally **not**
>   transitive, so it will **not** be chained, containing the link to exactly the
>   two concepts you asserted.
>
> When in doubt, prefer `closeMatch` (or the directional `broadMatch` /
> `narrowMatch`) over `exactMatch`: it is always safe to weaken an equivalence
> claim, but an over-stated transitive `exactMatch` can silently corrupt
> inferred equivalences several hops away.

See `docs/vocabularies/index.md` for the full provenance, IRI, and relationship reference.

## Using Protege as the default viewer for the full ontology

`rosetta protege build` merges both source ontologies (`data/ontologies/omop-cdm/<version>/ontology.ttl`, `data/ontologies/onz-g/<version>/ontology.ttl`) with the mapping set into a single Turtle file, written to `build/protege/omop-onz-g.combined.ttl` (gitignored, regenerated on demand), so [Protege](https://protege.stanford.edu) can be used as the single tool for reading, querying, and analyzing the whole graph (both source ontologies plus every mapping), rather than switching between the raw TTL files, the SSSOM/TSV, and the rendered docs pages:

```
uv run rosetta protege build mappings/omop-onz-g.csv mappings/omop-onz-g.metadata.json \
  --mapping-set-id "https://raw.githubusercontent.com/plugin-healthcare/sssom-rosetta/main/build/mappings/omop-onz-g.sssom.tsv" \
  --license "https://creativecommons.org/publicdomain/zero/1.0/" \
  --curie-map '{"omop": "https://w3id.org/omop/ontology/", "onz-g": "http://purl.org/ozo/onz-g#", "skos": "http://www.w3.org/2004/02/skos/core#", "semapv": "https://w3id.org/semapv/vocab/", "orcid": "https://orcid.org/"}'
```

Then open `build/protege/omop-onz-g.combined.ttl` in Protege via *File → Open*.

**Why the mapping predicates need special handling.** SKOS mapping properties (`skos:exactMatch`, `skos:broadMatch`, `skos:narrowMatch`, `skos:relatedMatch`) are defined as annotation properties. In OWL 2 DL, an object property may only connect individuals, never two classes directly, so if a mapping is written as a flat triple (`omop:Provider skos:broadMatch onz-g:Caregiver`) between two classes, Protege treats the whole statement as an annotation assertion, no matter how the predicate is typed elsewhere. OntoGraf only draws edges for structural relationships (subclassing and object-property restrictions between classes), so it silently ignores annotation assertions, and the mapping edges never appear in the graph view even though the triples are present in the data.

`rosetta protege build` avoids this by emitting each mapping as an OWL class-level axiom instead of a flat triple (see `mapping/protege.py`), specifically for this combined export; the canonical `build/mappings/omop-onz-g.ttl` produced by `rosetta mapping build` is unaffected and keeps using flat triples, which is correct SSSOM/RDF:

- `skos:exactMatch` mappings become `owl:equivalentClass` axioms, a native OWL DL class-to-class construct.
- every other predicate becomes an existential restriction: `Class_A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty <predicate> ; owl:someValuesFrom Class_B ]`.
- every predicate actually used is also declared `rdf:type owl:ObjectProperty` in the combined file, since SKOS itself declares them as annotation properties and OntoGraf only renders edges for typed object properties.

**Configuring OntoGraf to show the mapping edges.** After opening the combined file, open *Window → Views → Ontology views → OntoGraf* (or *Window → Tabs → OntoGraf* depending on your Protege version). In OntoGraf's filter/arc-types panel, make sure `skos:exactMatch`, `skos:broadMatch`, `skos:narrowMatch`, and `skos:relatedMatch` are checked among the visible object properties; OntoGraf will then draw a direct edge between an OMOP CDM class and its ONZ-G counterpart for every mapping, alongside the two ontologies' own class hierarchies and object properties.

- **Reading.** Use the *Entities* tab's *Classes* view to browse the merged class hierarchy: OMOP CDM classes and ONZ-G classes appear together, since both ontologies were merged into one graph. Select any class to see its annotations (labels, definitions, provenance) in the *Annotations* view, and its restrictions (including the mapping axioms added by `rosetta protege build`) in the *Description* view. Use the *Search* box (magnifying glass icon, or `Ctrl/Cmd+K`) to jump straight to a class by name, e.g. `Provider` or `Caregiver`, without navigating the tree manually.
- **Querying.** The bundled *DL Query* tab (*Window → Tabs → DL Query*) runs description-logic queries against the merged ontology, e.g. entering `Provider and (broadMatch some Caregiver)`-style expressions to find classes reachable via a specific mapping predicate, with results shown directly in the tab, no reasoner setup required for simple queries. For full SPARQL over the merged graph, install the SPARQL Query tab plugin once (*File → Check for plugins...*, select *SPARQL Query*, install, restart Protege), then use it to run the same style of cross-ontology queries shown above, e.g. selecting every OMOP CDM class that has a mapping to ONZ-G.
- **Analyzing.** Run a reasoner (*Reasoner* menu → e.g. *HermiT*, bundled with Protege → *Start reasoner*) to check the merged ontology is consistent and to compute the inferred class hierarchy, including any additional subclass relationships implied by the existential-restriction mapping axioms. Combine this with OntoGraf (configured above) to visually inspect how a given OMOP CDM class relates to the rest of the ONZ-G hierarchy, not just its direct mapping target.
- **Keeping the view current.** The combined file is a generated artifact (gitignored, rebuilt by `rosetta protege build` / `just protege`), so after any change to `mappings/omop-onz-g.csv` or a re-fetch of either ontology, rebuild it and reload the file in Protege (*File → Reload* if the same window is still open, or re-open it) rather than editing the combined file directly, since any edits made in Protege itself will be overwritten on the next `rosetta protege build`.

## Where users can get help with the project

Open an issue in this repository for bugs, questions, or mapping proposals. Design rationale and open decisions are tracked in the decisions log below and in `.agents/plan.md`; check there first before re-litigating a settled choice.

Key decisions:

- **Predicates**: no curated allowlist. Any `predicate_id` value permitted by the `sssom-schema` LinkML range is accepted; validation relies on schema conformance rather than an app-level list.
- **sssom-schema version**: pinned to a specific released tag in `pyproject.toml` (e.g. `sssom-schema==<x.y.z>`); `models/sssom.py` is regenerated only on a deliberate version bump, never against `main`.
- **PR review**: a rendered Markdown/HTML report is generated per PR (see CI section above) in addition to the raw TSV diff.
- **Documentation site**: static site under `/docs`, built with Zensical, published to GitHub Pages on merge to `main`. Mapping pages are generated from the same renderer as the PR report, not hand-maintained.
- **CLI name**: the console script is `rosetta` (not `sssom-rosetta`), configured via `[project.scripts]` in `pyproject.toml`; the Python package/import path remains `sssom_rosetta`.
- **CSV as authored source**: mapping sets are hand-edited as CSV under `mappings/*.csv`, each paired with a CSVW metadata file `mappings/*.metadata.json` (https://csvw.org, W3C Tabular Metadata), declaring column datatypes and `valueUrl` URI templates for the `*_id` columns. `rosetta mapping build` derives the canonical SSSOM/TSV (with YAML header) and an RDF/TTL representation into `build/mappings/`, using the CSVW `csv2rdf` conversion as the basis for the TTL; these are generated artifacts, gitignored, never hand-edited, and never the source for the CSV+CSVW pair.

## Who maintains and contributes to the project

Contributors and their ORCID identifiers are listed in `mappings/contributors.csv` (paired with `mappings/contributors.metadata.json`), referenced from the `author_id`/`reviewer_id`/`creator_id` columns of mapping set CSVs under `mappings/`.

Contributions follow standard GitHub flow: fork or branch, make changes to the CSV+CSVW mapping sets or the `sssom_rosetta` package, run `uv run pytest`, and open a pull request. Every PR touching `mappings/**` gets an automated validation check and a rendered mapping diff report, per the CI workflow described above.
