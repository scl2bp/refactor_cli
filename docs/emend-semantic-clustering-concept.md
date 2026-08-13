# Emend + LLM Semantic Clustering Concept

## Objective

Build a deterministic code-intelligence pipeline that:

- extracts consistent module and function signatures with Emend
- generates two LLM summaries per symbol/module
- stores summary embeddings in a vector database
- clusters similar code units
- incorporates expected call dependencies
- identifies cohesive code clusters, interconnects, and architectural constructs

This extends the low-LLM principle: deterministic extraction first, LLM enrichment second.

## Summary Types

For each symbol and module, produce:

1. Detailed description:
- rich technical explanation
- inputs, outputs, side effects, invariants
- dependency context and expected callers/callees

2. Extended verb-noun short description:
- compact action-centric phrase describing who does what with what
- format guideline:
  - Actor -> Verb -> Noun/Object -> Context/Constraint
- example:
  - Parser builds ChargerStatus from raw endpoint payload with EVSE normalization

## High-Level Pipeline

1. Deterministic extraction (Emend)
- discover files/modules/symbols
- extract signatures, symbol metadata, and structural location
- compute or collect call references

2. Enrichment (LLM)
- generate detailed and short verb-noun summaries from extracted artifacts
- keep source snippets bounded and deterministic

3. Embedding and indexing
- embed both summary forms and selected structural features
- store vectors + metadata in a vector DB

4. Dependency-aware clustering
- cluster by semantic similarity
- blend vector similarity with expected call dependency graph proximity

5. Architecture mining
- detect clusters that map to domain modules, utility hubs, anti-pattern hotspots
- detect high fan-in/fan-out interconnects and potential orchestration layers

## Emend Role

Use Emend as the deterministic analysis/extraction layer:

- search and symbol discovery:
  - emend find ... --kind function --output metadata|summary|json
- dependency/call context:
  - emend analyze refs ...
  - emend analyze graph ...
  - emend analyze impact ...
- optional safe transforms for iterative architecture improvements:
  - emend edit mv / rename / replace / batch

## Data Model (Conceptual)

### Symbol record

- symbol_id: stable identifier (path::symbol)
- module_path
- kind (function/class/method)
- signature
- decorators
- line span
- references_out
- references_in
- expected_callers
- expected_callees
- detailed_summary
- short_verb_noun_summary
- embedding_detailed
- embedding_short
- tags (domain, infra, io, parser, orchestrator)

### Module record

- module_id
- exported_symbols
- dependency_modules_out
- dependency_modules_in
- module_detailed_summary
- module_short_summary
- embeddings

## Expected Call Dependency Layer

Model two edges:

- observed edges: extracted from static analysis/call graph
- expected edges: inferred from naming, folder boundaries, or architecture rules

Example expected rules:

- cli layer may call service/orchestrator layer
- parser layer should not call network/io layer directly
- domain models should not depend on cli

Use violations and anomaly scores to identify architectural drift.

## Clustering Strategy

Use hybrid clustering features:

- semantic vectors:
  - detailed summary embedding
  - short verb-noun summary embedding
- structural features:
  - signature shape (arity, optional args, return type family)
  - module path/domain prefix
- graph features:
  - in-degree, out-degree, betweenness
  - dependency neighborhood overlap

Suggested methods:

- baseline: HDBSCAN or Agglomerative on concatenated vectors/features
- graph-aware: Leiden/Louvain community detection on weighted graph
- hybrid score:
  - score = alpha * semantic_similarity + beta * graph_proximity + gamma * signature_similarity

## Output Artifacts

- symbol_catalog.jsonl
- module_catalog.jsonl
- dependency_graph.graphml
- cluster_assignments.json
- architecture_findings.md
- drift_report.md

## Suggested Implementation Phases

Phase 1: Extraction MVP
- Emend-based symbol and signature catalog
- basic call/reference graph

Phase 2: Summary generation
- prompt templates for detailed and short summaries
- deterministic chunking and caching

Phase 3: Vector indexing
- embed summaries
- persist in vector DB (Qdrant, pgvector, or Milvus)

Phase 4: Clustering and findings
- semantic and graph-aware clustering
- generate architecture findings and candidate refactor maps

Phase 5: Closed-loop refactoring support
- convert selected findings into deterministic refactor plans
- apply through Emend or refactor-cli workflows

## Prompt Contract (LLM)

Input:

- symbol signature
- local docstring/comments
- bounded body excerpt
- incoming/outgoing dependency context

Output JSON:

- detailed_summary
- short_verb_noun_summary
- confidence
- rationale_keywords
- inferred_role

Require strict JSON schema validation before indexing.

## Quality Gates

- extraction completeness: coverage of symbols vs parser output
- summary consistency: style/schema checks
- embedding integrity: no null vectors, stable dimensions
- clustering stability: silhouette / modularity / repeated-run stability
- architectural validity: sampled human review on top clusters

## Candidate Architectural Discoveries

- latent bounded contexts (clusters by domain action)
- cross-cutting utilities hidden inside domain modules
- orchestration hubs with excessive coupling
- parser/adapter/service layer violations
- duplicate implementation families with near-identical signatures

## Alignment to SWE Principles

- Cohesion: clusters reveal natural module boundaries
- Decoupling: dependency-layer analysis highlights coupling violations
- Composition: deterministic extraction + LLM summaries + clustering compose cleanly
- Maintainability: repeatable pipeline with measurable outputs

## External Reference Benchmarks (Provided Search Results)

1. Graph-based and dependency-first analysis
- JonnoC/CodeRAG: repository graph representation with dependency-aware AI context
- JohT/code-graph-analysis-pipeline: Neo4j + analysis pipeline for architecture pattern detection

2. LLM repository summarization
- cyanheads/repo-map: repository structure summaries for LLM consumption
- Aider repo-map concept: tree-sitter/tag based structural compression for model context

3. AST clustering and memory/indexing
- pmorvalho/InvAASTCluster: AST-oriented clustering research direction
- DeusData/codebase-memory-mcp: indexed code memory and graph-aware retrieval pattern

Repository links:

- https://github.com/jonnoc/coderag
- https://github.com/JohT/code-graph-analysis-pipeline
- https://github.com/cyanheads/repo-map
- https://github.com/pmorvalho/InvAASTCluster
- https://github.com/DeusData/codebase-memory-mcp

## Repository And Package Fit Evaluation

Scoring legend:

- 5 = strong direct fit
- 3 = partial fit / useful subsystem
- 1 = weak fit for production target

| Candidate | Signature and AST extraction | Call dependency modeling | LLM summaries | Embeddings and vector retrieval | Clustering and architecture mining | Maturity and operational fit | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| codebase-memory-mcp | 5 | 5 | 2 | 5 | 4 | 5 | Strongest end-to-end graph and semantic retrieval backbone; no built-in summary generation, but ideal as deterministic graph substrate. |
| CodeRAG | 4 | 4 | 4 | 4 | 3 | 3 | Good multi-project AI-ready graph stack with semantic search and metrics; lower observed ecosystem traction and smaller maintainer base than codebase-memory-mcp. |
| code-graph-analysis-pipeline | 4 | 5 | 2 | 3 | 5 | 3 | Strong architecture and graph data science depth (Leiden, embeddings, anomalies), but heavier Neo4j/jQAssistant operational footprint. |
| repo-map | 2 | 1 | 5 | 1 | 1 | 3 | Very good LLM narrative summaries; weak native graph/dependency/clustering depth. Best as summary-layer inspiration, not as core engine. |
| InvAASTCluster | 3 | 1 | 1 | 1 | 5 | 1 | Strong research signal for AST/invariant clustering; specialized to education datasets and older stack, not production-ready for general repositories. |

## Source Reliability Notes

- Primary reliability: GitHub repository READMEs and docs pages (direct maintainer claims).
- Secondary reliability: arXiv abstracts for Codebase-Memory (arXiv:2603.27277) and InvAASTCluster (arXiv:2206.14175).
- Lower reliability for implementation decisions: trend and opinion articles (for example analytics and commentary blogs), useful for discovery but not for technical validation.
- One linked source (preprints page) was not machine-readable through automated fetch and should not be used as evidence until manually verified.

## Recommended Adoption Pattern

1. Deterministic extraction and dependency graph
- Prefer codebase-memory-mcp as external reference architecture for graph depth and scale claims.
- Keep Emend as local deterministic symbol extraction/edit integration in this repository.

2. LLM summary layer
- Follow repo-map style outputs for human-readable summaries, but enforce strict JSON contracts and schema validation.

3. Vector and clustering layer
- Reuse ideas from code-graph-analysis-pipeline for graph-aware clustering (community detection + embeddings).
- Use InvAASTCluster only as methodological inspiration for signature/structure-aware clustering features.

4. Pilot fit criteria for go/no-go
- Must recover expected caller-callee structure for a known module slice.
- Must produce stable cluster assignments across repeated runs.
- Must support both long-form and verb-noun summaries per symbol.

## Python-Focused Refined Research

This section narrows recommendations to Python-centric implementation paths and
corrects source-level claim drift.

### Correctness Notes Before Tool Selection

- Python as an orchestration language is an excellent fit for this pipeline
  (parsing, embeddings, clustering, graph analytics).
- Some shortlisted repositories are Python projects but do not rely primarily on
  Python built-in ast for cross-language parsing; most use tree-sitter.
- Some repositories are strong references but not ideal drop-in dependencies
  because of maturity or scope mismatch.

### Evidence-Ranked Python-Relevant Candidates

1. Graphify-Labs/graphify (Python implementation, high momentum)
- Strong fit for semantic graph extraction, path queries, and community-oriented
  architecture views.
- Practical value: local-first graph artifacts, query/path/explain workflows,
  cluster/community outputs, and Python-native packaging.
- Caveat: broader multimodal scope than needed for strict code-only pipelines,
  so integration should select only code-graph subsets.

2. DeusData/codebase-memory-mcp (best graph depth, not Python-native core)
- Strongest structural graph and dependency analysis benchmark in capability
  breadth.
- Practical value: rich graph schema, call tracing, impact analysis, and
  mature operational model.
- Caveat: implementation core is native (C/C++), so use as architecture
  benchmark and interoperability target rather than Python-embedded library.

3. al1-nasir/codegraph-cli (Python CLI, medium maturity)
- Useful Python-first reference for tree-sitter + SQLite/LanceDB + embedding
  workflow and impact/search UX.
- Practical value: rapid local experimentation in a pure Python toolchain.
- Caveat: smaller contributor/release footprint and less validation depth than
  top-tier graph engines.

4. simonw/llm-cluster (focused clustering utility)
- Good lightweight component for post-embedding grouping and optional cluster
  labeling.
- Practical value: simple operational model for clustering + LLM summaries.
- Caveat: limited scope and older maintenance cadence; use as a component,
  not as architecture backbone.

5. brandondocusen/CntxtPY (historical Python context compressor)
- Useful ideas for compressed context outputs and dependency summaries.
- Caveat: older update cadence and lower operational maturity; treat as
  inspiration rather than production dependency.

### Recommended Python Stack By Pipeline Stage

1. Structural extraction and graph base
- Primary: Emend outputs + local Python orchestration.
- Optional benchmark/comparison harness: graphify and codebase-memory-mcp
  outputs for quality checks.

2. Summary generation
- Python orchestration with strict JSON schema contracts.
- Keep dual outputs: detailed technical summary and verb-noun short summary.

3. Embeddings and storage
- sentence-transformers for local embedding generation.
- Local vector persistence with either SQLite-sidecar + numpy artifacts,
  or pgvector/Qdrant when scale requires indexed retrieval.

4. Clustering and graph-aware mining
- Baseline: UMAP + HDBSCAN in Python.
- Graph enrichment: networkx-derived structural features and community signals
  blended into clustering score.

### Corrected Interpretation Of The Earlier Python Draft

- Keep: Python is a strong implementation language for the orchestration and ML
  layers.
- Correct: codebase-memory-mcp should not be described as a Python-ast-native
  engine; it is a high-performance native graph system with tree-sitter and
  hybrid semantic resolution.
- Refine: graphify and codegraph-cli are useful references for graph workflow and
  DX, but should be adopted selectively, not wholesale.
- Narrow: llm-cluster and CntxtPY are best treated as tactical components or
  idea sources, not end-to-end platforms.

### Python Suitability Clarifications (Repository-Level)

Use this as a guardrail against incorrect language/parser assumptions.

1. Clearly not suitable as a native Python source parser for this workflow
- pmorvalho/InvAASTCluster:
  - Focuses on introductory programming assignment clustering with C-oriented
    datasets and tooling.
  - Requires pycparser and C-focused invariant tooling; not a native parser for
    Python source modules/functions in this pipeline context.

2. Partially suitable with caveats (not Python-native parser core)
- JohT/code-graph-analysis-pipeline:
  - Core pipeline is centered on Neo4j + jQAssistant Java/TypeScript workflows.
  - Also supports multi-language import via SCIP, including Python, but this is
    an ingestion/integration path, not a lightweight native Python AST workflow.
- JonnoC/CodeRAG:
  - Implemented in TypeScript with Neo4j-first architecture.
  - README claims Python language support; still better treated as a
    cross-language graph platform than as a Python-native AST refactoring stack.

3. Python-based tools that are still not "Python ast only"
- Graphify-Labs/graphify:
  - Implemented in Python.
  - Code extraction is primarily tree-sitter based (not built-in ast only).
- al1-nasir/codegraph-cli:
  - Implemented in Python.
  - Parser is explicitly tree-sitter based for Python/JS/TS.
- cyanheads/repo-map:
  - Implemented in Python (not Node.js/TypeScript).
  - Emphasizes repository summaries and LLM descriptions; not a deep call-graph
    refactoring parser.

4. Python-oriented but maturity-limited
- brandondocusen/CntxtPY:
  - Python-focused context compression and graph-style summaries.
  - Useful for ideas/prototyping, but limited evidence for production-grade,
    large-scale architectural mining compared with stronger graph platforms.



## Practical Next Step for This Repository

Implement a small pilot on one cohesive area (for example parser functions in src/mobiliti/api/parsers.py):

- extract signatures and call graph with Emend
- generate both summary styles
- embed and cluster
- produce a short findings report with candidate class/module boundaries
