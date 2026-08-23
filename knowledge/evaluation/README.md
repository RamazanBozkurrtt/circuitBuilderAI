# Retrieval evaluation data

`synthetic_queries.json` targets the deterministic synthetic DSP corpus constructed in
`tests/test_knowledge_retrieval.py`. Each entry uses the `RetrievalEvaluationCase` schema and names an
expected document plus an optional page/chunk. The corpus is generated at test time, so running this
file through the CLI requires indexing an equivalent local fixture first. These cases provide a
mechanical baseline and must not be represented as production retrieval quality.

`real_datasheet_queries.json` is the separate, manually curated manufacturer-corpus regression set.
Its expected pages were selected after examining the immutable ADI and TI PDFs acquired for Phase
3.1. It covers DSP, codec/ADC/DAC, and Class-D facts and intentionally includes table and deeper-page
locations. Keep synthetic and real metrics separate; do not move expected pages to improve scores.
