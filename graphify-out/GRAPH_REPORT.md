# Graph Report - workspace  (2026-08-23)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 27 nodes · 25 edges · 4 communities
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3a88b1d9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3

## God Nodes (most connected - your core abstractions)
1. `scripts` - 3 edges
2. `engines` - 2 edges
3. `dotenv` - 2 edges
4. `express` - 2 edges
5. `playwright` - 2 edges
6. `node` - 1 edges
7. `license` - 1 edges
8. `main` - 1 edges
9. `app` - 1 edges
10. `{ chromium }` - 1 edges

## Surprising Connections (you probably didn't know these)
- None detected - all connections are within the same source files.

## Import Cycles
- None detected.

## Communities (4 total, 0 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.22
Nodes (8): description, engines, node, license, main, name, type, version

### Community 1 - "Community 1"
Cohesion: 0.25
Nodes (5): app, { chromium }, express, fs, path

### Community 2 - "Community 2"
Cohesion: 0.29
Nodes (7): dotenv, express, dependencies, dotenv, express, playwright, playwright

### Community 3 - "Community 3"
Cohesion: 0.67
Nodes (3): scripts, dev, start

## Knowledge Gaps
- **17 isolated node(s):** `description`, `node`, `license`, `main`, `name` (+12 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `dependencies` connect `Community 2` to `Community 0`?**
  _High betweenness centrality (0.258) - this node is a cross-community bridge._
- **Why does `scripts` connect `Community 3` to `Community 0`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **What connects `description`, `node`, `license` to the rest of the system?**
  _17 weakly-connected nodes found - possible documentation gaps or missing edges._