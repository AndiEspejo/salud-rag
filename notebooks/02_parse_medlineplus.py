# Databricks notebook source
# MAGIC %md
# MAGIC # 02 - Parse MedlinePlus health topics
# MAGIC
# MAGIC Parses the MedlinePlus health topics XML downloaded by notebook 01 into a Delta table, one
# MAGIC row per health topic (Spanish and English), with lineage columns that point back to the
# MAGIC source file.
# MAGIC
# MAGIC **Source: MedlinePlus, National Library of Medicine.** Only the MedlinePlus-authored topic
# MAGIC summaries are stored. Third-party site links listed under each topic are dropped.
# MAGIC
# MAGIC **Not medical advice.** This project provides general information for educational
# MAGIC purposes only.

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "salud_rag"
RAW_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/raw/medlineplus"
TABLE = f"{CATALOG}.{SCHEMA}.medlineplus_topics"

# COMMAND ----------

import collections
import datetime
import os
import sys
from pathlib import Path

from pyspark.sql.types import (
    ArrayType,
    DateType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# In a Databricks Git folder the working directory is the notebook's own directory.
sys.path.insert(0, os.path.abspath("../src"))

from salud_rag.ingest.medlineplus import ATTRIBUTION
from salud_rag.ingest.medlineplus_topics import (
    LICENSE,
    find_latest_manifest,
    parse_topics,
    verify_manifest_sha256,
)

# COMMAND ----------

manifest = find_latest_manifest(Path(RAW_DIR))
xml_path = verify_manifest_sha256(manifest, Path(RAW_DIR))  # raises if the file was altered
result = parse_topics(xml_path)

print(f"Source file: {manifest['xml_filename']} (file date {manifest['file_date']})")
print(f"Parsed topics: {len(result.topics)}")
for language, count in sorted(collections.Counter(t.language for t in result.topics).items()):
    print(f"  {language}: {count}")
print(f"Skipped (no usable summary): {list(result.skipped)}")

# COMMAND ----------

SCHEMA_DEF = StructType(
    [
        StructField("topic_id", IntegerType(), nullable=False),
        StructField("language", StringType(), nullable=False),
        StructField("title", StringType(), nullable=False),
        StructField("url", StringType(), nullable=False),
        StructField("date_created", DateType(), nullable=False),
        StructField("meta_desc", StringType(), nullable=True),
        StructField("also_called", ArrayType(StringType(), containsNull=False), nullable=False),
        StructField("see_references", ArrayType(StringType(), containsNull=False), nullable=False),
        StructField("groups", ArrayType(StringType(), containsNull=False), nullable=False),
        StructField(
            "related_topic_ids", ArrayType(IntegerType(), containsNull=False), nullable=False
        ),
        StructField("mapped_topic_id", IntegerType(), nullable=True),
        StructField("mapped_topic_url", StringType(), nullable=True),
        StructField("summary_html", StringType(), nullable=False),
        StructField("summary_text", StringType(), nullable=False),
        StructField("source_url", StringType(), nullable=False),
        StructField("source_file", StringType(), nullable=False),
        StructField("file_date", DateType(), nullable=False),
        StructField("source_sha256", StringType(), nullable=False),
        StructField("license", StringType(), nullable=False),
        StructField("attribution", StringType(), nullable=False),
        StructField("ingested_at", TimestampType(), nullable=False),
    ]
)

ingested_at = datetime.datetime.now(datetime.UTC)  # one value per run
file_date = datetime.date.fromisoformat(manifest["file_date"])

rows = [
    {
        "topic_id": topic.topic_id,
        "language": topic.language,
        "title": topic.title,
        "url": topic.url,
        "date_created": topic.date_created,
        "meta_desc": topic.meta_desc,
        "also_called": list(topic.also_called),
        "see_references": list(topic.see_references),
        "groups": list(topic.groups),
        "related_topic_ids": list(topic.related_topic_ids),
        "mapped_topic_id": topic.mapped_topic_id,
        "mapped_topic_url": topic.mapped_topic_url,
        "summary_html": topic.summary_html,
        "summary_text": topic.summary_text,
        "source_url": manifest["source_url"],
        "source_file": manifest["xml_filename"],
        "file_date": file_date,
        "source_sha256": manifest["sha256"],
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "ingested_at": ingested_at,
    }
    for topic in result.topics
]

# `spark` is a Databricks runtime global.
df = spark.createDataFrame(rows, schema=SCHEMA_DEF)  # pyright: ignore[reportUndefinedVariable]

# COMMAND ----------

# Validate before writing, so bad data never replaces the existing good table.
topic_ids = [row["topic_id"] for row in rows]
spanish_count = sum(1 for row in rows if row["language"] == "Spanish")

if not rows or len(rows) != len(result.topics):
    raise ValueError(f"Expected {len(result.topics)} non-empty rows, got {len(rows)}")
if len(set(topic_ids)) != len(topic_ids):
    raise ValueError("Duplicate topic_id")
if any(not row["summary_text"].strip() for row in rows):
    raise ValueError("Found empty summary_text")
if spanish_count <= 1000:
    raise ValueError(f"Expected more than 1000 Spanish topics, got {spanish_count}")
if df.count() != len(result.topics):
    raise ValueError("DataFrame row count differs from parsed topics")

# COMMAND ----------

df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TABLE)

table_comment = (
    "MedlinePlus health topics (Spanish and English), one row per topic with the summary as "
    f"HTML and plain text. {ATTRIBUTION}. Third-party site links are not stored. "
    "Not medical advice."
)
escaped_comment = table_comment.replace("\\", "\\\\").replace("'", "\\'")  # Databricks SQL
spark.sql(f"COMMENT ON TABLE {TABLE} IS '{escaped_comment}'")  # pyright: ignore[reportUndefinedVariable]

# COMMAND ----------

stored = spark.table(TABLE)  # pyright: ignore[reportUndefinedVariable]

assert stored.count() == len(rows), "Stored row count differs from the rows written"

display(stored.select("topic_id", "language", "title", "url").limit(5))  # pyright: ignore[reportUndefinedVariable]

latest_version = spark.sql(f"DESCRIBE HISTORY {TABLE}").agg({"version": "max"}).first()[0]  # pyright: ignore[reportUndefinedVariable]
print(f"{TABLE}: latest Delta version {latest_version}")
