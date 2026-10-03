# Databricks notebook source
# MAGIC %md
# MAGIC # 01 - Download MedlinePlus health topics
# MAGIC
# MAGIC Downloads the latest MedlinePlus health topics XML into a Unity Catalog volume, together
# MAGIC with a manifest that records the source URL, file date, and SHA-256 checksum.
# MAGIC
# MAGIC **Source: MedlinePlus, National Library of Medicine.** Only the public-domain health topic
# MAGIC summaries are used downstream; copyrighted content is filtered out before indexing.
# MAGIC
# MAGIC **Not medical advice.** This project provides general information for educational
# MAGIC purposes only.

# COMMAND ----------

CATALOG = "workspace"
SCHEMA = "salud_rag"
VOLUME = "raw"
DEST_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}/medlineplus"

# COMMAND ----------

# `spark` is a Databricks runtime global.
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")  # pyright: ignore[reportUndefinedVariable]
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")  # pyright: ignore[reportUndefinedVariable]

# COMMAND ----------

import json
import os
import re
import sys
from pathlib import Path

# In a Databricks Git folder the working directory is the notebook's own directory.
sys.path.insert(0, os.path.abspath("../src"))

from salud_rag.ingest.medlineplus import download_latest_topics

# COMMAND ----------

result = download_latest_topics(Path(DEST_DIR))
print(f"Skipped (already downloaded): {result.skipped}")
print(f"XML path: {result.xml_path}")
print(f"Source URL: {result.topics_file.url}")

manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
print(json.dumps(manifest, indent=2, ensure_ascii=False))

# COMMAND ----------

# Smoke check only; parsing is a later step.
assert result.xml_path.stat().st_size == manifest["size_bytes"], "XML size differs from manifest"

topic_tag = re.compile(rb"<health-topic [^>]*>")
spanish_topics = 0
tail = b""
with result.xml_path.open("rb") as xml_file:
    while chunk := xml_file.read(1 << 20):
        buffer = tail + chunk
        # Keep a possibly incomplete trailing tag for the next chunk.
        cut = buffer.rfind(b"<")
        if cut != -1 and buffer.find(b">", cut) == -1:
            buffer, tail = buffer[:cut], buffer[cut:]
        else:
            tail = b""
        spanish_topics += sum(b'language="Spanish"' in tag for tag in topic_tag.findall(buffer))

print(f"Spanish health topics: {spanish_topics}")
