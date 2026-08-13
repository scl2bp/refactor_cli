# Candidate Installation and Capability Evaluation

Date: 2026-08-13

Scope: candidates listed in the concept table in [docs/emend-semantic-clustering-concept.md](docs/emend-semantic-clustering-concept.md).

## Summary

The prior custom semantic-graph implementation was reverted.

Current status:
- Local cloning completed for all five candidates.
- Installation or bootstrap attempts were executed for each candidate.
- Four candidates now have successful install or prerequisite setup in compatible runtimes.
- One candidate remains partially blocked due additional external tooling requirements.

## Candidate Results

1. codebase-memory-mcp
- Source: [.eval/candidates/codebase-memory-mcp](.eval/candidates/codebase-memory-mcp)
- Install result: success
- Evidence:
	- Local installer run with skip-config and custom dir completed successfully.
	- Installed artifacts present in [.eval/tools/cbm](.eval/tools/cbm).
	- Binary help runs and reports version plus graph/call/dependency tooling.
- Logs: [.eval/logs/codebase-memory-mcp-install.log](.eval/logs/codebase-memory-mcp-install.log)

2. CodeRAG
- Source: [.eval/candidates/coderag](.eval/candidates/coderag)
- Install result: success
- Evidence:
	- npm dependency install completed.
	- node_modules exists.
	- Build script completes.
- Notes:
	- npm reports 6 high-severity vulnerabilities in transitive dependencies.
- Logs:
	- [.eval/logs/coderag-npm-install.log](.eval/logs/coderag-npm-install.log)
	- [.eval/logs/coderag-build.log](.eval/logs/coderag-build.log)

3. code-graph-analysis-pipeline
- Source: [.eval/candidates/code-graph-analysis-pipeline](.eval/candidates/code-graph-analysis-pipeline)
- Install result: prerequisites now pass
- Evidence:
	- Java 21 runtime installed locally.
	- Repository compatibility check now passes.
	- Full analysis execution still requires Neo4j and jQAssistant runtime setup for end-to-end workloads.
- Logs:
	- [.eval/logs/code-graph-analysis-pipeline-compat.log](.eval/logs/code-graph-analysis-pipeline-compat.log)
	- [.eval/logs/code-graph-analysis-pipeline-compat-after-java.log](.eval/logs/code-graph-analysis-pipeline-compat-after-java.log)

4. repo-map
- Source: [.eval/candidates/repo-map](.eval/candidates/repo-map)
- Install result: success in uv Python 3.12 environment
- Evidence:
	- Python 3.10 venv attempt fails because package requires Python >=3.12.
	- Python 3.14 attempt fails because tree-sitter-languages wheels are unavailable for cp314 in this environment.
	- uv-managed Python 3.12 environment resolves compatibility and installation succeeds.
- Logs:
	- [.eval/logs/repo-map-pip-install.log](.eval/logs/repo-map-pip-install.log)
	- [.eval/logs/repo-map-pip-install-py314.log](.eval/logs/repo-map-pip-install-py314.log)
	- [.eval/logs/repo-map-uv312-install.log](.eval/logs/repo-map-uv312-install.log)

5. InvAASTCluster
- Source: [.eval/candidates/InvAASTCluster](.eval/candidates/InvAASTCluster)
- Install result: partial success in uv Python 3.8 environment
- Evidence:
	- Initial attempt in default environment fails on numpy==1.19.2 build.
	- uv-managed Python 3.8 environment installs numpy==1.19.2 and pycparser==2.21 successfully.
	- End-to-end workflow still depends on Clara, Daikon, and runsolver external setup.
- Logs:
	- [.eval/logs/invaastcluster-prereqs.log](.eval/logs/invaastcluster-prereqs.log)
	- [.eval/logs/invaast-uv38-prereqs.log](.eval/logs/invaast-uv38-prereqs.log)

## Capability Readout (from repository docs)

1. codebase-memory-mcp
- Strong direct capabilities for call graph, dependency graph, architecture summaries, semantic search, and clustering/community detection.
- Operationally simple here because a native binary is installable and runnable locally.

2. CodeRAG
- Strong graph and semantic-search orientation with enterprise metrics focus.
- Node/Neo4j-oriented stack; install succeeded for the codebase layer, but full feature use still depends on graph backend setup.

3. code-graph-analysis-pipeline
- Deepest graph-data-science and architecture mining surface (domains, embeddings, anomaly detection, cyclic dependencies).
- Heavier operational footprint (Java + Neo4j + jQAssistant).

4. repo-map
- Strong summary-generation and repository overview capabilities.
- Not a strong direct fit as a dependency/call-graph backbone.

5. InvAASTCluster
- Research-oriented clustering framework for educational assignment datasets.
- Not a practical production baseline for repository-scale architecture tooling in this environment.

## Recommendation For Module Foundation

Start module formation from:
1. Primary baseline: codebase-memory-mcp
2. Secondary comparator: CodeRAG
3. Optional advanced mining phase: code-graph-analysis-pipeline after Neo4j and jQAssistant end-to-end enablement

Keep repo-map and InvAASTCluster as inspiration/reference layers only.

## Immediate Next Step

Define Phase A modules that directly wrap candidate capabilities instead of reimplementing from scratch:
- source_index module (index and refresh)
- dependency_graph module (calls/imports/inheritance)
- semantic_retrieval module (semantic query + metadata)
- architecture_report module (clusters, hotspots, boundaries)

These should call candidate tools first, then add thin adapters for normalized outputs.
