# salud-rag

Spanish informational health assistant built on retrieval-augmented generation
(RAG). It answers general health questions using only public source documents,
cites every source, and abstains when the evidence is insufficient.

> **Not medical advice.** This project provides general information for
> educational purposes. It does not diagnose, recommend treatments, or replace a
> healthcare professional. In an emergency, contact your local emergency number.

## Status

Work in progress. See [`odd/tasks/salud-rag.md`](odd/tasks/salud-rag.md) for the
plan and progress.

## Stack

- **Data and ML platform:** Databricks (Delta tables, Unity Catalog, MLflow)
- **Models:** open models served through Databricks Unity Gateway
  (Qwen3 Next for generation, GPT OSS 120B as evaluation judge)
- **Embeddings:** `intfloat/multilingual-e5-small`
- **API:** FastAPI

## Sources

Health content comes from [MedlinePlus](https://medlineplus.gov/) (U.S.
National Library of Medicine). Only public-domain material is used.

## Data ingestion

Clone this repository as a Databricks Git folder, open
[`notebooks/01_download_medlineplus.py`](notebooks/01_download_medlineplus.py),
and run all cells on serverless compute. The latest health topics XML lands in
the Unity Catalog volume `/Volumes/workspace/salud_rag/raw/medlineplus/`, next
to a manifest that records the source URL, file date, and SHA-256 checksum.
Re-running skips the download when that day's file and manifest already exist.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                  # install dependencies
uv run pytest                            # run tests
uv run ruff check .                      # lint
uv run uvicorn salud_rag.api:app --reload  # run the API locally
```
