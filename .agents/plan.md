# Implementation plan — sssom-rosetta

Derived from AGENTS.md. Tracks the first working increment: fetch ONZ-G 2.8.1
and OMOP CDM OWL, author/validate one example mapping in a CSVW-described CSV
(`omop:Person skos:exactMatch onz-g:Client`), generate the derived SSSOM/TSV
and TTL, and publish the docs site.

## Scope for this increment

In: package scaffolding, ontology fetch/cache/catalog, generated Pydantic
SSSOM models (pinned `sssom-schema`), CSVW-based mapping author/validate/io,
one curated mapping set (CSV + CSVW metadata), PR report renderer + CI
workflow, Zensical docs site + publish workflow, tests for all of the above.

Out (later increments): full predicate documentation pages, coverage/diff
statistics beyond a basic count, multi-ontology-pair support beyond the first
pair, `mapping diff` CLI polish.

## Todos

1. **scaffold-package** — Create `src/sssom_rosetta/` package layout
   (`models/`, `ontology/`, `mapping/`, `cli.py`), update `pyproject.toml`
   (package metadata, `src` layout, build backend `uv_build`), remove/replace
   placeholder `main.py`. No dependencies.

2. **pin-dependencies** — Add pinned dependencies to `pyproject.toml`:
   `rdflib`, `csvw` (CSVW metadata parsing + csv2rdf), `linkml` (dev group,
   for `gen-pydantic`), `sssom-schema==<tag>`, `sssom` (sssom-py), `pydantic`,
   `typer`, `polars`, `zensical` (dev/docs group). Add `[project.scripts]
   rosetta = "sssom_rosetta.cli:app"` so the CLI is invoked as `rosetta`, not
   `sssom-rosetta` (package/import path stays `sssom_rosetta`). Run `uv
   sync`. Depends on: scaffold-package.

3. **generate-sssom-models** — Run `gen-pydantic` against the pinned
   `sssom-schema` LinkML YAML, commit output to
   `src/sssom_rosetta/models/sssom.py`, document the regeneration command in
   a code comment/README. Depends on: pin-dependencies.

4. **ontology-sources-registry** — Implement `ontology/sources.py`: a
   registry of `{name, version, iri, download_url, checksum}` for ONZ-G 2.8.1
   (`ontology.ttl` from the KIK-V widoco download link) and OMOP CDM OWL
   (`ontology.ttl` from plugin-healthcare/omop-cdm-owl). Depends on:
   scaffold-package.

5. **ontology-loader** — Implement `ontology/loader.py`: download-and-cache
   into `data/ontologies/<name>/<version>/ontology.ttl` with checksum
   verification, and load into an `rdflib.Graph`. Unit tests mock HTTP, no
   live network calls. Depends on: ontology-sources-registry.

6. **ontology-catalog** — Implement `ontology/catalog.py`: SPARQL/rdflib
   queries for `list_classes()`, `list_properties()`, `resolve_label(iri)`
   against a loaded graph. Tests use small fixture subgraphs (a handful of
   triples), not full downloads. Depends on: ontology-loader.

7. **mapping-author** — Implement `mapping/author.py`: `build_mapping(...)`
   that resolves CURIEs via the ontology catalogs and constructs a generated
   `Mapping` Pydantic object; raises on unresolved IRIs. Depends on:
   generate-sssom-models, ontology-catalog.

8. **mapping-validate** — Implement `mapping/validate.py`: round-trip a
   `MappingSet` through the generated Pydantic models (schema conformance)
   and re-check every subject/object IRI against the ontology catalogs
   (referential integrity). Depends on: mapping-author.

9. **mapping-io** — Implement `mapping/io.py`: read/parse authored CSV +
   paired CSVW metadata (`mappings/*.csv` + `mappings/*-metadata.json`) via
   the `csvw` library into a generated Pydantic `MappingSet`, and write the
   two derived artifacts from it — canonical SSSOM/TSV (via `sssom-py`, with
   YAML metadata header) and an RDF/Turtle graph of the same mappings
   (starting from the CSVW `csv2rdf` output, then aligned to the SSSOM
   model) — into `build/mappings/`. CSVW → {TSV, TTL} only; never the
   reverse. Depends on: mapping-author.

10. **first-mapping-set** — Author the first curated mapping set as
    `mappings/omop-onz-g.csv` + `mappings/omop-onz-g-metadata.json` (CSVW
    metadata: column datatypes, `valueUrl` URI templates for `subject_id`/
    `object_id`/`predicate_id`), including the example
    `omop:Person skos:exactMatch onz-g:Client`, using the author/validate
    modules; run `mapping-io`'s build step to confirm
    `build/mappings/omop-onz-g.{sssom.tsv,ttl}` generate correctly. Depends
    on: mapping-validate, mapping-io.

11. **cli** — Implement `cli.py` (typer app, installed as `rosetta`):
    `rosetta ontology fetch`, `rosetta mapping validate`, `rosetta mapping
    build` (CSVW → TSV + TTL), `rosetta mapping report`. Depends on:
    mapping-io, mapping-validate.

12. **mapping-report** — Implement `mapping/report.py`: render a
    Markdown + HTML diff of a mapping set (added/removed/changed rows,
    per-predicate counts, resolved labels) between two refs/files, reading
    from the generated `.sssom.tsv` (not the raw CSV) so the report reflects
    the fully resolved/validated data. Depends on: mapping-io.

13. **ci-pr-report** — Add a GitHub Actions workflow triggered on PRs
    touching `mappings/**` (CSV + CSVW metadata): run `rosetta mapping
    validate`, run `rosetta mapping build` to generate TSV/TTL for base and
    head, run `rosetta mapping report`, post/upsert the Markdown as a PR
    comment, upload the generated TSV/TTL/HTML as artifacts. Depends on:
    cli, mapping-report.

14. **docs-site-scaffold** — Add `/docs` (`index.md`,
    `ontologies/onz-g.md`, `ontologies/omop-cdm.md`,
    `mappings/omop-onz-g.md` placeholder) and a Zensical config file at the
    repo root. Depends on: scaffold-package.

15. **docs-mapping-pages** — Generate `docs/mappings/*.md` from the
    generated `build/mappings/*.sssom.tsv` using the same renderer as
    `mapping/report.py` (shared code path, not a separate hand-written
    template); link to the generated `.sssom.tsv`/`.ttl` as downloads.
    Depends on: mapping-report, docs-site-scaffold, first-mapping-set.

16. **ci-docs-publish** — Add a GitHub Actions workflow on merge to `main`:
    run `rosetta mapping build` to regenerate `build/mappings/*.{sssom.tsv,ttl}`,
    regenerate `docs/mappings/*.md`, run `zensical build`, publish `site/`
    to GitHub Pages. Depends on: docs-mapping-pages.

17. **tests-and-gate** — Ensure `tests/ontology/` and `tests/mapping/` cover
    loader (mocked HTTP), catalog (fixture subgraphs), author/validate
    (accept/reject cases), io (CSV+CSVW parse via `csvw` + TSV/TTL
    generation), and report (fixture diff). Run `uv run pytest`, `uv run
    ruff check --fix && uv run ruff format`, `uv run ty check .` clean.
    Depends on: all modules above (7-16).

## Dependency graph (high level)

```
scaffold-package
 ├─ pin-dependencies ─ generate-sssom-models ─┐
 ├─ ontology-sources-registry ─ ontology-loader ─ ontology-catalog ─┤
 └─ docs-site-scaffold                                              │
                                                                      ├─ mapping-author ─ mapping-validate ─┐
                                                                      └─ mapping-io ───────────────────────┤
                                                                                                             ├─ first-mapping-set ─ docs-mapping-pages ─ ci-docs-publish
                                                                                                             ├─ cli
                                                                                                             └─ mapping-report ─ ci-pr-report
tests-and-gate (spans all of the above)
```

## Notes / carried-over decisions (from AGENTS.md)

- No predicate allowlist; validation relies on the generated schema's
  `predicate_id` range.
- `sssom-schema` pinned to a released tag; regenerate models only on
  deliberate bump.
- PR report and published docs mapping pages share one renderer.
- Ontology TTL downloads are cached locally and checksum-verified; tests
  never hit the network.
- CLI console script is `rosetta`; Python package/import path is
  `sssom_rosetta`.
- CSV+CSVW pair (`mappings/*.csv` + `mappings/*-metadata.json`) is the only
  hand-authored, PR-reviewed mapping source (https://csvw.org); `.sssom.tsv`
  and `.ttl` under `build/mappings/` are generated, gitignored, and never
  edited directly.

## Open items to confirm before/while implementing

- Exact `sssom-schema` version tag to pin.
- License and `mapping_set_id` URI scheme for `mappings/omop-onz-g.csv` /
  its generated `build/mappings/omop-onz-g.sssom.tsv`.
- Whether the PR-report GitHub Action needs write permissions configured
  (PR comment upsert) — confirm target repo's Actions permissions.
- RDF/Turtle shape for the generated `.ttl`: plain triples
  (`subject predicate object`) vs. reified statements carrying mapping
  metadata (confidence, justification, author) as RDF too.
- Exact CSVW `valueUrl` URI template conventions for `subject_id`/
  `object_id`/`predicate_id` columns (CURIE expansion vs. full IRI).
