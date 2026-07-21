# Design: choice of backend for the vocabulary/knowledge graph

**Date:** 2026-07-21
**Status:** Open — no decision yet; this document frames the options.
**Related:**
- `.agents/plan/2026-07-21-omophub-backend-reverse-engineering.md` (OMOPHub API
  reconstruction; currently assumes DuckDB)
- `.agents/plan/2026-07-21-owl-dl-classification-deferral-note.md` (OWL-DL
  deferral)
- `README.md` → "Integrating vocabularies & ontologies into one graph"

---

## 1. Context & objective

We are building a **single-node, cost-effective** backend that serves the merged
OMOP-base + Dutch-domain vocabulary graph (see README scope). Two workloads sit
on top of it:

1. **The OMOPHub-compatible REST API** — reconstructed from the `omophub-python`
   SDK contract (concepts, hierarchy, mappings, relationships, vocabularies,
   domains, lexical search, Phoebe recommendations, FHIR resolve). This is a
   read-heavy, transactional-lookup + analytical workload over the OMOP
   vocabulary tables.
2. **Knowledge-graph / semantic exploration** — cross-ontology traversal,
   cross-walk querying, and (later) LLM/RAG context expansion over the merged
   graph, including the Dutch domain ontologies (ONZ-G, Z-Index, DHD
   thesauri).

Hard constraints for this decision:

- **Single node, commodity hardware.** No distributed cluster, no managed
  service dependency.
- **Cost-effective.** Embedded / self-hostable, open-source.
- **Fits the existing pipeline.** We already parse Athena/RF2 tables with polars
  and build RDF with rdflib; the OMOP `CONCEPT_ANCESTOR` table gives us a
  pre-computed transitive closure we want to exploit rather than recompute at
  query time.

This document deliberately **does not choose**. It records three valid
single-node options and their trade-offs so the choice can be made later against
concrete requirements.

---

## 2. Shared design considerations (apply to all three)

These hold regardless of the storage paradigm:

- **Global identifiers.** OMOP `concept_id`s become persistent URIs/keys
  (`https://w3id.org/omop/concept/{id}`, `sct:`, `loinc:`, `rxnorm:`, `icd10:`,
  …). This is what lets OMOP concepts line up with the Dutch ontologies and, for
  the RDF option, with external graphs.
- **Materialise `CONCEPT_ANCESTOR`, don't recurse at query time.** OMOP already
  ships the transitive closure of the `Is a` hierarchy. In *every* option we
  ingest it as explicit ancestor edges/rows and query those with plain indexed
  joins, rather than running recursive/transitive path expressions over millions
  of poly-hierarchical SNOMED nodes on each request. This is the single most
  important performance decision and is paradigm-independent.
- **Snapshot-per-release versioning.** Each `vocab_release` is an immutable
  snapshot (a DuckDB file, an RDF graph/named-graph, or an LPG database).
  `X-Vocab-Version` selects it; `meta.vocab_release` echoes it.
- **Edge metadata exists.** OMOP `CONCEPT_RELATIONSHIP` rows carry
  `valid_start_date`, `valid_end_date`, `invalid_reason`. How naturally each
  paradigm represents *properties on an edge* is a key differentiator (see §3).
- **Lexical search first, vectors later.** The near-term API ships lexical
  concept-name/synonym search; embedding/vector similarity is deferred. Whether
  full-text search is *built in* or bolted on differs per option.
- **Faithful OHDSI Phoebe recommendations.** `concept_recommended` +
  hierarchical/mapping components. This is application logic over whichever store
  we pick; all three can serve it.
- **OWL-DL reasoning is out of scope (deferred).** None of these options is being
  chosen to run an OWL reasoner; that stays a separate follow-up. This removes
  "native OWL reasoning" as a differentiator here.

---

## 3. The three single-node options

All three are valid, single-node, cost-effective, open-source. They differ in
data model (relational vs. triples vs. labelled property graph), query language,
and how well they fit the two workloads above.

### Option A — DuckDB (relational / SQL)

Embedded columnar RDBMS. This is what the OMOPHub reconstruction plan currently
assumes.

**Pros**
- **Closest to the source data.** OMOP *is* a relational schema; Athena CSVs load
  into DuckDB tables with almost no impedance mismatch (DuckDB `read_csv`,
  matching how we already parse with polars).
- **Edge metadata is trivial.** `valid_start_date` / `valid_end_date` /
  `invalid_reason` are just columns on `concept_relationship`. No reification, no
  RDF-star, no edge-property modelling gymnastics.
- **Excellent analytical performance on one node.** Columnar, vectorised; fast
  group-bys/joins for the stats endpoints (`vocabulary/{id}/stats`, domain
  distributions) and for `CONCEPT_ANCESTOR` joins.
- **Zero operational overhead.** Embedded, single file per snapshot, read-only
  open; no server to run.
- **Ecosystem familiarity.** Plain SQL; aligns conceptually with the wider OHDSI
  tooling (Atlas/HADES/Achilles) which is all SQL-on-relational-OMOP, easing any
  future bridge to native analytics.
- **Snapshot-per-release is a file.** One `.duckdb` per release; immutable, easy
  to build and cache.

**Cons**
- **Not a graph engine.** Deep/variable-length traversals need recursive CTEs.
  We mitigate the main case by materialising `CONCEPT_ANCESTOR`, but *ad hoc*
  multi-hop cross-ontology exploration is awkward compared to a graph query
  language.
- **No native URI/linked-data alignment.** Cross-graph interoperability
  (Wikidata/PubChem/UniProt federation) is not a first-class capability; you'd
  export to RDF for that.
- **Full-text search is add-on.** DuckDB has an `fts` extension, but it is less
  central/mature than QLever's integrated text index.
- **KG/RAG story is weaker.** Serviceable via SQL, but not the natural shape for
  semantic exploration or graph-native context expansion.

### Option B — QLever (RDF / SPARQL triple store)

High-performance SPARQL engine; the merged graph we already build with rdflib is
its native input.

**Pros**
- **Native fit for the RDF we already produce.** `rosetta vocabulary` already
  emits SKOS/RDFS Turtle; QLever ingests that directly — no separate modelling
  step.
- **Linked-data interoperability is first-class.** Persistent URIs align with
  external biomedical ontologies; **SPARQL 1.1 `SERVICE` federation** lets us join
  OMOP/Dutch concepts with Wikidata, PubChem, UniProt, NCBI without copying data
  locally. Strongest option for cross-ontology / cross-domain querying.
- **Integrated full-text search.** Concept-name/synonym string matching (a very
  common OMOP query entry point) is built into SPARQL pattern matching — no
  external Elasticsearch/Solr.
- **Scale on commodity hardware.** Extreme index compression and fast joins;
  tens–hundreds of billions of triples on a single node — comfortably covers
  OMOP's ~10M concepts plus the Dutch ontologies.
- **Schema-aware autocomplete.** Context-sensitive SPARQL completion eases
  authoring queries over a large concept space.
- **Best KG/RAG substrate.** Triples + text index + federation is the natural
  shape for semantic search and LLM context expansion.

**Cons**
- **Edge metadata needs RDF-star or reification.** RDF 1.1 edges can't carry
  properties, so `valid_start_date`/`invalid_reason` require either reification
  (inflates triple count ~4–5×, verbose SPARQL) or **RDF-star** quoted triples.
  Our conversion pipeline would need to target RDF-star where edge validity
  matters. This is the main added complexity vs. DuckDB.
- **Transitive path cost if misused.** Runtime `:isA+`/`*` property paths over
  poly-hierarchies can be memory-heavy; must be avoided by materialising
  `CONCEPT_ANCESTOR` as explicit `:hasAncestor` triples (see §2).
- **Read-mostly / batch-load engine.** QLever is optimised for bulk-loaded,
  largely static indexes (fits snapshot-per-release well) rather than frequent
  small writes.
- **Isolation from SQL-native OHDSI tools.** Pure RDF means Atlas/HADES/Achilles
  can't run against it directly; fine for KG/semantic/RAG use, but a relational
  DB is still needed for cohort/observational analytics.
- **Operationally a service.** QLever runs as a server/process (still single
  node), so slightly more to operate than an embedded file.

### Option C — LadybugDB (labelled property graph / Cypher-style)

Embeddable labelled-property-graph (LPG) database — a single-node, cost-effective
property-graph option.

**Pros**
- **Edge metadata is native.** LPGs store properties directly on edges:
  `(:Concept)-[:MAPS_TO {valid_start_date, valid_end_date, invalid_reason}]->(:Concept)`.
  The cleanest representation of OMOP's relationship columns — no reification, no
  RDF-star.
- **Ergonomic traversal queries.** ASCII-art pattern matching
  (`()-[]->()`, variable-length `-[:IS_A*]->`) is intuitive for the multi-hop
  cross-ontology exploration the KG workload wants.
- **Graph-native performance for traversals.** Index-free adjacency makes deep
  hierarchy/relationship walks natural and fast — a good fit for
  `CONCEPT_ANCESTOR`-style navigation and relationship-group logic if we ever add
  it.
- **Single-node / embeddable.** Meets the cost/one-node constraint without a
  cluster.

**Cons**
- **Requires an explicit relational→graph modelling step.** We must map
  `CONCEPT`/`CONCEPT_RELATIONSHIP`/`CONCEPT_ANCESTOR` into nodes/edges; more
  up-front modelling than DuckDB (load-as-is) or QLever (load-the-RDF-we-have).
- **Weaker linked-data interoperability.** LPG identifiers are internal to the
  database; no native URI alignment or SPARQL `SERVICE` federation with external
  biomedical graphs (the KG interop story is worse than QLever's).
- **Smaller / less battle-tested ecosystem.** LadybugDB is newer and less proven
  at OMOP scale than DuckDB or QLever; fewer integrations, tooling, and
  operational references. Maturity/risk is the main concern.
- **Analytical/stats queries less natural.** Aggregations for the stats endpoints
  are more idiomatic in SQL than in a traversal language.
- **Not SQL-native for OHDSI tools** (same isolation caveat as QLever).

---

## 4. Comparison matrix

| Criterion | DuckDB (SQL) | QLever (RDF/SPARQL) | LadybugDB (LPG) |
|-----------|--------------|---------------------|-----------------|
| Data-model fit to OMOP source | **Excellent** (relational = native) | Good (needs RDF we already build) | Fair (needs graph modelling) |
| Edge metadata (`valid_*`, `invalid_reason`) | **Native columns** | RDF-star / reification | **Native edge props** |
| Multi-hop / traversal ergonomics | Recursive CTEs (awkward) | SPARQL paths (avoid at runtime) | **Cypher-style, intuitive** |
| `CONCEPT_ANCESTOR` materialised joins | **Fast indexed joins** | **Fast indexed joins** | Fast adjacency |
| Linked-data / external federation | Weak | **First-class (`SERVICE`)** | Weak |
| Integrated full-text search | Add-on (`fts`) | **Built-in** | Add-on |
| Analytical / stats endpoints | **Strong (columnar)** | Adequate | Weaker |
| KG / semantic / RAG substrate | Weaker | **Strongest** | Strong (traversal) |
| Operational footprint | **Embedded file** | Server process (1 node) | Embedded |
| Ecosystem maturity at OMOP scale | **High** | High | **Lower / newer** |
| SQL-native OHDSI tool compatibility | **Yes** | No | No |

---

## 5. How this maps to the two workloads

- **If the priority is the OMOPHub REST API + stats + straightforward
  hierarchy/mapping lookups with clean edge-validity handling** → DuckDB is the
  path of least resistance (and is what the reconstruction plan currently
  assumes).
- **If the priority is a unified knowledge graph for semantic search,
  cross-ontology/cross-domain querying, external federation, and LLM/RAG context
  expansion** → QLever is the strongest fit, at the cost of RDF-star edge
  modelling.
- **If the priority is graph-native traversal with rich edge properties on a
  single embedded node** → LadybugDB (LPG) is attractive, with ecosystem
  maturity as the main risk.

These are not mutually exclusive long-term: a common pattern is **DuckDB as the
relational system of record + an exported RDF snapshot served by QLever** for the
semantic/KG layer. We are **not** deciding that here.

---

## 6. Open questions to resolve before choosing

1. **Primary consumer.** Is the first deliverable the OMOPHub-compatible API
   (favours DuckDB) or the semantic/KG explorer (favours QLever)?
2. **Do edge validity dates matter to consumers?** If yes and we go RDF, we must
   commit to RDF-star in the conversion pipeline.
3. **Is external federation (Wikidata/PubChem/…) an actual requirement** or a
   nice-to-have? It is QLever's biggest differentiator.
4. **Appetite for LadybugDB's maturity risk** vs. the safer DuckDB/QLever
   options.
5. **One store or two?** Accept the DuckDB-of-record + QLever-for-KG split, or
   insist on a single store for everything?
