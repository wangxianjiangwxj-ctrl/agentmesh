# CHANGELOG

## v0.3.0 (2026-05-28)

### Added
- A2A Provider abstraction layer (A2AProvider, MemoryProvider, HttpProvider)
- A2A Task Manager with state machine (A2ATaskManager, A2ATaskState)
- A2A Facade unified entry point (A2AFacade)
- A2A Result and Error handling (A2AResult, A2AError)
- GitHub Actions CI/CD (lint, typecheck, test on 3.10/3.11/3.12, docs deploy)
- A2A bridge examples (MemoryProvider + HTTP Server)
- LangGraph integration example
- CrewAI integration example
- English blog post

### Changed
- SDK restructuring: modular provider/adapter/task layers
- CI: trunk-based workflow (main + feature/*)

### Fixed
- CI publish_dir and mkdocs build paths
- SDK test paths for ruff and mypy
