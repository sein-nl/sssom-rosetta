# AGENTS.md — sssom-rosetta

## Dev environment

- adhere to instructions, skills, prompts and recipse as defined by wingman in `.wingman`

## Authoring of SSSOM mappings

- To assert that one concept is broader in meaning (i.e. more general) than another, the `skos:broadMatch` property is used. The `skos:narrower` property is used to assert the inverse, namely when one concept is narrower in meaning (i.e. more specific) than another. For example:

```
ex:animals rdf:type skos:Concept;
  skos:prefLabel "animals"@en;
  skos:narrowMatch ex:mammals.
ex:mammals rdf:type skos:Concept;
  skos:prefLabel "mammals"@en;
  skos:broadMatch ex:animals.
```

- Note on `skos:broadMatch` direction: for historic reasons, the name of the `skos:broadMatch` property does not provide an explicit indication of its direction. The word "broadMatch" should read here as "has broader concept"; the subject of a `skos:broadMatch` statement is the more specific concept involved in the assertion and its object is the more generic one.
- As is often the case in KOS, a SKOS concept can be attached to several broader concepts at the same time. For example, a concept ex:dog could have both ex:mammals and ex:domesticatedAnimals as broader concepts.
- Prefer use of `broadMatch`, `narrowMatch` and `exactMatch` over `relatedMatch`

## Architectural decisions log

- **Predicates**: no curated allowlist. Any `predicate_id` value permitted by the `sssom-schema` LinkML range is accepted; validation relies on schema   conformance rather than an app-level list.
- **sssom-schema version**: pinned to a specific released tag in `pyproject.toml` (e.g. `sssom-schema==<x.y.z>`); `models/sssom.py` is regenerated only on a deliberate version bump, never against `main`.
- **PR review**: rendered Markdown/HTML report is generated per PR (see CI section above) in addition to the raw TSV diff.
- **Documentation site**: static site under `/docs`, built with Zensical, published to GitHub Pages on merge to `main`. Mapping pages are generated from the same renderer as the PR report, not hand-maintained.
- **CLI name**: the console script is `rosetta` (not `sssom-rosetta`), configured via `[project.scripts]` in `pyproject.toml`; the Python package/import path remains `sssom_rosetta`.
- **CSV as authored source**: mapping sets are hand-edited as CSV under `mappings/*.csv`, each paired with a CSVW metadata file `mappings/*.metadata.json` (https://csvw.org, W3C Tabular Metadata), declaring column datatypes and `valueUrl` URI templates for the `*_id` columns. `rosetta mapping build` derives the canonical SSSOM/TSV (with YAML header) and an RDF/TTL representation into `build/mappings/`, using the CSVW `csv2rdf` conversion as the basis for the TTL; these are generated artifacts, gitignored, never hand-edited, and never the source for the CSV+CSVW pair.
