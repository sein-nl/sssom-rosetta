# Plan: Reverse-engineer & implement the OMOPHub backend API

**Date:** 2026-07-21
**Status:** Accepted — decisions locked (see §0)
**Source analyzed:** `github.com/OMOPHub/omophub-python` @ `40fb762`
**Goal:** Reconstruct a backend server that satisfies the contract the official
Python SDK expects, so the SDK (and its tests/examples) work unmodified against
our own implementation.

---

## 0. Locked decisions

1. **Return bare `data`.** Item and list endpoints return their payload directly
   as the `data` field of the envelope — no extra wrapping objects. List
   endpoints still populate `meta.pagination`; item endpoints return the bare
   entity as `data`.
2. **Defer vector/semantic similarity search to a later phase.** Phase 1 (and the
   near-term phases) ship **lexical** search only. `/search/semantic`,
   `/search/semantic-bulk`, and `/search/similar` (embedding-based) are
   explicitly out of scope until a dedicated later phase; no `pgvector`/embedding
   dependency in the initial build.
3. **Versioning = snapshot-per-release.** Each `vocab_release` is a distinct,
   immutable snapshot of the vocabulary tables. `X-Vocab-Version` /
   `vocab_release` selects the snapshot; `meta.vocab_release` echoes the resolved
   one.
4. **Reproduce OHDSI Phoebe recommendations faithfully.** `/concepts/recommended`
   and `/concepts/related` implement the actual OHDSI Phoebe
   (`concept_recommended`) algorithm and sub-scores, not just a heuristic.
5. **DuckDB, not PostgreSQL.** The store is DuckDB (embedded, columnar). This
   fits the read-heavy, analytical vocabulary workload, needs no server, and
   loads the Athena/RF2 CSVs the way this repo already does with polars.

---

## 1. What the SDK tells us about the backend (the contract)

The SDK is a thin, typed HTTP wrapper. Every method maps 1:1 to an HTTP call, so
the client fully specifies the server's REST contract.

### 1.1 Transport & conventions
- **Base URL:** `https://api.omophub.com/v1` (`_config.py`). Server is versioned
  under `/v1`.
- **Auth:** `Authorization: Bearer <api_key>` on every request (`_request.py::
  _get_auth_headers`). Optional `X-Vocab-Version: <release>` header to pin a
  vocabulary release globally.
- **Response envelope (success):**
  ```json
  { "success": true, "data": <payload>, "meta": { ...ResponseMeta } }
  ```
  The SDK's normal `get/post` unwrap `data`; `get_raw` keeps the whole envelope
  (used for pagination, needs `meta.pagination`). **`data` is the bare entity or
  bare list** — no intermediate wrapper object (locked decision §0.1).
- **Response envelope (error):**
  ```json
  { "success": false, "error": { "message": "...", "code": "...", "details": {} } }
  ```
  Returned with the appropriate 4xx/5xx status.
- **Headers the server should emit:** `X-Request-Id` (echoed into errors/meta),
  and on `429`, `Retry-After` (seconds). SDK retries on 429/5xx with backoff.
- **`meta.pagination` shape** (`_types.py::PaginationMeta`):
  ```json
  { "page", "page_size", "total_items", "total_pages", "has_next", "has_previous" }
  ```
- **`meta` also carries:** `request_id`, `timestamp`, `vocab_release`.
- **Pagination inputs:** `page` (1-based), `page_size` (default 20, **max 1000**).
- **List-param encoding:** array filters are sent as **comma-joined query
  strings** (e.g. `vocabulary_ids=SNOMED,ICD10CM`) on GET, but as **JSON arrays**
  in POST bodies. The server must parse both forms.
- **Boolean query params** are the literal strings `"true"` (only sent when
  enabling); absent means false.

### 1.2 Data model (from `types/`)
The domain is the **OHDSI OMOP vocabulary model** (Athena) — the same tables this
`sssom-rosetta` repo already ingests. Core entities & key fields:
- **Concept**: `concept_id, concept_name, domain_id, vocabulary_id,
  concept_class_id, standard_concept ('S'|'C'|null), concept_code,
  valid_start_date, valid_end_date, invalid_reason`; optional `synonyms`,
  `relationships`.
- **Vocabulary / VocabularyStats**: counts (total/standard/classification/
  invalid), `domain_distribution`, `last_updated`, version.
- **Domain / DomainStats**, **Relationship / RelationshipType** (hierarchical/
  defining/symmetric/transitive flags, `reverse_relationship_id`),
  **Mapping** (source→target with `quality.confidence_score`, `relationship_id`),
  **Hierarchy** (`min/max_levels_of_separation`, paths), **Search** results
  (basic, semantic w/ `similarity_score`, suggestions, similar/embeddings).

This maps directly onto the standard OMOP CDM vocabulary tables:
`CONCEPT, CONCEPT_RELATIONSHIP, CONCEPT_ANCESTOR, CONCEPT_SYNONYM,
VOCABULARY, DOMAIN, CONCEPT_CLASS, RELATIONSHIP`.

---

## 2. Complete endpoint inventory (extracted from the SDK)

### Concepts (`resources/concepts.py`)
| Method | Path | Notes |
|--------|------|-------|
| GET | `/concepts/{concept_id}` | `include_relationships,include_synonyms,include_hierarchy,vocab_release` |
| GET | `/concepts/by-code/{vocabulary_id}/{concept_code}` | same includes |
| POST | `/concepts/batch` | body `{concept_ids[≤100], include_*, vocabulary_filter, standard_only}` → `{concepts, failed_concepts, summary}` |
| GET | `/concepts/suggest` | `query(2..100), page, page_size, vocabulary_ids, domain_ids, vocab_release` |
| GET | `/concepts/{id}/related` | `relationship_types, min_score, page_size` (Phoebe relatedness scores) |
| GET | `/concepts/{id}/relationships` | `relationship_ids, vocabulary_ids, domain_ids, include_invalid, standard_only, include_reverse, vocab_release` |
| POST | `/concepts/recommended` | body `{concept_ids[1..100], relationship_types, vocabulary_ids, domain_ids, standard_only, include_invalid, page, page_size}` (OHDSI **Phoebe** recommender) |

### Search (`resources/search.py`)
| Method | Path | Notes |
|--------|------|-------|
| GET | `/search/concepts` | basic: `query, vocabulary_ids, domain_ids, concept_class_ids, standard_concept, exact_match, include_synonyms, include_invalid, sort_by, sort_order, page, page_size` |
| POST | `/search/advanced` | structured boolean query + `relationship_filters` |
| GET | `/search/suggest` | autocomplete |
| GET | `/search/semantic` | vector similarity: `query, threshold, min_score, ...` → `similarity_score` |
| POST | `/search/bulk` | many basic searches keyed by `search_id` + shared `defaults` |
| POST | `/search/semantic-bulk` | bulk semantic |
| POST | `/search/similar` | "more like this" from a `concept_id`/`concept_name`, embedding-based |

### Hierarchy (`resources/hierarchy.py`)
| GET | `/concepts/{id}/hierarchy` | `vocabulary_ids, domain_ids, max_results, relationship_types, include_invalid` |
| GET | `/concepts/{id}/ancestors` | `vocabulary_ids, max_levels, relationship_types, include_paths, include_distance, include_invalid` |
| GET | `/concepts/{id}/descendants` | `+ domain_ids` |

Backed by `CONCEPT_ANCESTOR` (`min/max_levels_of_separation`).

### Relationships (`resources/relationships.py`)
| GET | `/concepts/{id}/relationships` | (alias of concepts.relationships) |
| GET | `/relationships/types` | list `RelationshipType`s |

### Mappings (`resources/mappings.py`)
| GET | `/concepts/{id}/mappings` | `target_vocabulary, include_invalid, vocab_release` |
| POST | `/concepts/map` | body `{source_concepts|source_codes, mapping_type, include_invalid}` — cross-vocabulary crosswalk (Maps to) |

### Vocabularies (`resources/vocabularies.py`)
| GET | `/vocabularies` | list (paginated) |
| GET | `/vocabularies/{id}` | detail |
| GET | `/vocabularies/{id}/stats` | `VocabularyStats` |
| GET | `/vocabularies/{id}/stats/domains/{domain_id}` | per-domain stats |
| GET | `/vocabularies/domains` | domain list |
| GET | `/vocabularies/concept-classes` | concept-class list |
| GET | `/vocabularies/{id}/concepts` | concepts within a vocabulary (paginated) |

### Domains (`resources/domains.py`)
| GET | `/domains` | list |
| GET | `/domains/{id}/concepts` | concepts in a domain (paginated) |

### FHIR interop (`resources/fhir.py`)
| POST | `/fhir/resolve` | resolve a FHIR `Coding` → OMOP concept |
| POST | `/fhir/resolve/batch` | batch codings |
| POST | `/fhir/resolve/codeable-concept` | resolve a `CodeableConcept` |

**Total: ~30 endpoints across 8 resource groups.**

---

## 3. Proposed backend architecture

Recommendation: **Python + FastAPI + DuckDB** (locked §0.5). The data model IS
the OMOP CDM vocabulary schema, which loads cleanly into DuckDB from the Athena
CSVs; FastAPI's Pydantic models mirror the SDK's TypedDicts exactly; DuckDB is
embedded (no server), columnar and fast for the read-heavy/analytical vocabulary
workload, and reads tab-delimited CSVs directly (`read_csv`), matching how this
repo already parses Athena/RF2 with polars. Semantic search is deferred (§0.2),
so **no vector store in the initial build**.

```
omophub-backend/
  app/
    main.py                 # FastAPI app, /v1 router mount, middleware
    config.py               # settings (DuckDB path, API keys, snapshot dir)
    deps.py                 # auth dependency, DuckDB connection, pagination params
    envelope.py             # success/error envelope + ResponseMeta builder
    errors.py               # exception -> {success:false,error} mapping
    pagination.py           # PaginationMeta computation
    db/
      schema.sql            # DuckDB DDL: concept, concept_relationship,
                            #   concept_ancestor, concept_synonym, vocabulary,
                            #   domain, concept_class, relationship
      connection.py         # open per-snapshot DuckDB (read-only), pooling
      queries.py            # parameterised SQL helpers
    schemas/                # Pydantic mirrors of SDK types/*.py
      concept.py vocabulary.py domain.py hierarchy.py mapping.py
      relationship.py search.py common.py
    routers/
      concepts.py search.py hierarchy.py relationships.py
      mappings.py vocabularies.py domains.py fhir.py
    services/
      concept_service.py    # get/batch/by-code/relationships
      search_service.py     # lexical only for now (deferred semantic §0.2)
      hierarchy_service.py  # ancestors/descendants via concept_ancestor
      mapping_service.py    # Maps-to crosswalk
      recommend_service.py  # OHDSI Phoebe relatedness (faithful, §0.4)
    loaders/
      load_athena.py        # bulk-load Athena CSVs into a DuckDB snapshot
      build_ancestors.py    # (re)compute concept_ancestor if absent
      build_snapshot.py     # materialise one immutable per-release DuckDB file
  tests/                    # reuse the SDK's own tests as black-box contract
```

### 3.0 DuckDB snapshot layout (versioning, §0.3)
- Each `vocab_release` is a **separate, immutable DuckDB database file**, e.g.
  `snapshots/2025.2.duckdb`, built once by `build_snapshot.py` and opened
  **read-only** at request time.
- `connection.py` maps a resolved release → its DuckDB file and caches read-only
  connections. A tiny `releases` registry (JSON or a control DB) lists available
  releases and the default.
- New release = new file; old files are never mutated. `meta.vocab_release`
  reports which snapshot served the request.

### 3.1 Cross-cutting middleware/deps
- **Auth dependency** verifying `Authorization: Bearer` against an API-key store
  (start with a table/env allowlist; add rate-limit counters later).
- **Request-ID middleware** setting `X-Request-Id` and threading it into
  envelopes and error bodies.
- **Envelope wrapper**: a response model / dependency that wraps handler return
  values into `{success, data, meta}` and computes `meta.pagination`.
- **Exception handlers** mapping domain errors → the `ErrorResponse` shape with
  correct status codes; `429` sets `Retry-After`.
- **`vocab_release` resolution**: `X-Vocab-Version` header or `vocab_release`
  query param selects a vocabulary snapshot (see §5 versioning).

### 3.2 Query-param parsing
Add reusable parsers for the SDK's encodings: comma-joined lists on GET, JSON
arrays in POST bodies, and `"true"` string booleans.

---

## 4. Data layer & sourcing the vocabulary

The backend needs the OMOP vocabulary content. **This repo already ingests it**
(`vocabulary/omop.py` reads Athena `CONCEPT.csv` / `CONCEPT_RELATIONSHIP.csv`;
`vocabulary/sources.py` registers the OMOP bundle). Reuse that path:

1. **Schema:** create DuckDB tables matching OMOP CDM v5.4 vocabulary tables
   (`db/schema.sql`).
2. **Load:** `loaders/load_athena.py` uses DuckDB's `read_csv` (tab-delimited,
   `quote='' ` to disable quote handling — the same rule as `rf2.py`/`omop.py`
   in this repo) to bulk-`INSERT` the Athena CSVs into a per-release snapshot
   file. Optionally load SNOMED/LOINC via the RF2 pipeline we already have.
3. **concept_ancestor:** if the Athena bundle ships it, load directly; otherwise
   compute the transitive closure of `Is a` edges with a recursive CTE
   (`build_ancestors.py`).
4. **Indexes / performance:** DuckDB is columnar, so this is mostly about
   physical layout and lightweight ART indexes: index `concept_id`,
   `(vocabulary_id, concept_code)`; keep `concept_ancestor` sorted/zoned by
   `ancestor_concept_id` and `descendant_concept_id`; a `concept_synonym`
   index on `concept_id`. For lexical search, precompute a lowercased
   `concept_name` column (and optionally a tokenised helper table) —
   DuckDB supports `ILIKE`/`regexp` and the `fts` extension for full-text.
5. **Semantic search embeddings: deferred (§0.2).** No embedding column or vector
   index in the initial build; added in the dedicated later phase.

---

## 5. Endpoint implementation notes (non-obvious behaviour)

- **`standard_concept` filter:** `'S'` standard, `'C'` classification, `null`
  non-standard. `standard_only=true` → `standard_concept='S'`.
- **`include_reverse` relationships:** union outbound (`concept_id_1=id`) with
  inbound (`concept_id_2=id`), tagging `direction`.
- **Mappings (`/concepts/map`, `/concepts/{id}/mappings`):** follow `Maps to`
  relationships to standard concepts; `quality.confidence_score` can be derived
  (direct=1.0, indirect via intermediate < 1.0).
- **Recommended (`/concepts/recommended`) & related:** implement the OHDSI
  **Phoebe** algorithm faithfully (locked §0.4). Phoebe's `concept_recommended`
  combines: (a) **hierarchical** proximity from `concept_ancestor` (shared
  ancestors / levels of separation), (b) **co-occurrence** counts from the
  published Phoebe `concept_recommended` dataset, (c) **mapping** overlap
  (shared `Maps to` targets), and (d) an optional semantic term. Populate the
  `RelatedConcept` sub-scores (`hierarchical_score`, `co_occurrence_score`,
  `mapping_score`, `semantic_score`) and the combined `relatedness_score`.
  - **Sourcing:** load OHDSI's precomputed Phoebe `concept_recommended` table
    (from the ATLAS/WebAPI reference data) into the DuckDB snapshot rather than
    re-deriving co-occurrence from scratch; compute the hierarchical/mapping
    components on the fly from `concept_ancestor` / `concept_relationship`.
  - Until the semantic term is available (§0.2 deferral), set
    `semantic_score` to 0/absent and combine the remaining components with
    Phoebe's documented weighting.
- **Semantic / similar search: deferred (§0.2).** `/search/semantic`,
  `/search/semantic-bulk`, `/search/similar` return `501 Not Implemented`
  (envelope error) or are simply unmounted until the semantic-search phase.
- **FHIR resolve:** map a FHIR `Coding{system, code}` → OMOP by translating the
  FHIR system URI to `vocabulary_id` (reuse the URI schemes in this repo's
  `vocabulary/namespaces.py`), then `by-code` lookup + optional `Maps to`.
- **Versioning (`vocab_release`): snapshot-per-release (locked §0.3).** Each
  release is a separate immutable DuckDB file opened read-only; the resolver maps
  `X-Vocab-Version`/`vocab_release` → snapshot file, defaulting to the latest;
  echo the resolved release in `meta.vocab_release`.

---

## 6. Testing strategy — use the SDK as the spec

The strongest validation is **black-box conformance**: point the official SDK at
our server and assert behaviour.

1. **Contract tests:** run the SDK's own `tests/` (and `examples/`) against a
   local instance seeded with a small fixture vocabulary.
2. **Golden envelope tests:** assert every response matches `{success, data,
   meta}`, pagination math is correct, and error bodies match `ErrorResponse`.
3. **Per-endpoint unit tests** on the service layer with a seeded test DB.
4. **Auth/rate-limit tests:** missing/invalid bearer → 401; 429 sets
   `Retry-After` and SDK retry succeeds.

---

## 7. Phased delivery

1. **Foundation:** FastAPI skeleton, `/v1` router, auth dep, envelope (bare
   `data`, §0.1) + error handlers, request-id + pagination, DuckDB schema,
   Athena loader, snapshot builder (§0.3), fixture seed. Acceptance: SDK can
   authenticate and get a 401/200.
2. **Core read endpoints:** concepts (get/by-code/batch), vocabularies, domains,
   relationships, relationship types. Wire SDK contract tests for these.
3. **Hierarchy:** ancestors/descendants/hierarchy via `concept_ancestor`
   (+ recursive-CTE closure builder if needed).
4. **Mappings:** `/concepts/map` + `/concepts/{id}/mappings` (Maps-to crosswalk).
5. **Lexical search:** `/search/concepts`, `/search/suggest`, `/concepts/suggest`,
   `/search/bulk`, `/search/advanced` (DuckDB `ILIKE`/`fts`). **No semantic
   search in this phase (§0.2).**
6. **OHDSI Phoebe recommender:** `/concepts/related`, `/concepts/recommended`
   using the loaded Phoebe `concept_recommended` data + hierarchical/mapping
   components (§0.4). Semantic sub-score left absent until phase 8.
7. **FHIR interop:** `/fhir/resolve*`.
8. **Deferred semantic search + hardening:** add embedding store & ANN for
   `/search/semantic`, `/search/semantic-bulk`, `/search/similar` and the Phoebe
   semantic sub-score (§0.2); rate limiting (`429`+`Retry-After`), observability,
   perf tuning.

---

## 8. Open questions / assumptions to confirm
- **Exact envelope for list vs. item:** list endpoints use `meta.pagination`;
  item endpoints return the **bare** entity as `data` (locked §0.1). Verify a
  couple against the SDK tests before locking response models.
- **Phoebe scoring formula & weights:** the SDK exposes the sub-scores but not
  weights; reproduce from the OHDSI Phoebe / `concept_recommended` reference
  implementation and confirm which precomputed dataset/version to load.
- **`/search/advanced` query grammar:** body structure is only partially visible
  (`query, relationship_filters, ...`); capture the full shape from the SDK's
  `search.py::advanced()` signature before implementing.
- **DuckDB snapshot sizing/build cadence:** confirm acceptable snapshot file size
  and rebuild process per release; decide where snapshot files live and how the
  `releases` registry is managed.
- **(Deferred, §0.2) embedding model:** which model powers the hosted semantic
  search is unknown; pick and document one when phase 8 starts — scores won't
  match the hosted API exactly but the contract shape will.
