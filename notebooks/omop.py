import marimo

__generated_with = "0.23.14"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl

    return (pl,)


@app.cell
def _(pl):
    concept_rel = pl.scan_csv("./data/vocabularies/omop/unversioned/CONCEPT_RELATIONSHIP.csv", separator="\t")
    return (concept_rel,)


@app.cell
def _(concept_rel, pl):
    (
        concept_rel
        .group_by("relationship_id")
        .len()
        .sort(descending=True, by=pl.col("len"))
        .collect()
    )
    return


@app.cell
def _(concept_rel, pl):
    concept_rel.filter(pl.col("relationship_id").str.contains("ATC - RxNorm")).collect()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
