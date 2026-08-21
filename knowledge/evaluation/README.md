# Retrieval evaluation data

`synthetic_queries.json` targets the deterministic synthetic DSP corpus constructed in
`tests/test_knowledge_retrieval.py`. Each entry uses the `RetrievalEvaluationCase` schema and names an
expected document plus an optional page/chunk. The corpus is generated at test time, so running this
file through the CLI requires indexing an equivalent local fixture first. These cases provide a
mechanical baseline and must not be represented as production retrieval quality.
