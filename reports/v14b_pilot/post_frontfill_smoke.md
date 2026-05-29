# Post-Frontfill Smoke Test

Smoke run: `2026-05-29 21:45 CST`

Purpose: verify the downstream value chain on an isolated temporary V14 database while section/OpenAlex frontfill continues. This is not the final scientific output; it is a schema and product-gate test for `Step5c -> Step6 -> Step13 -> Step10`.

## Result

- Step5c limitation extraction completed on a 120-paper limit: `96` limitation atoms and `149` resolution links.
- Step6 fusion completed: `5` future directions.
- Step13 first-principles/history completed: `384` bottleneck lineage triples and `5` Claim Cards.
- Step10 visual graph completed on a 1,000-paper limit: `1,000` visual nodes, `6,167` visual edges, `15` clusters.

## Product Audit

- Runtime/schema gate: passed.
- Value gate: partially passed.
- Remaining risk: the smoke visual graph did not attach Claim Cards to graph details because the 1,000-paper visual limit did not necessarily include the direction anchor papers. Full visual graph should reduce this risk, but the product layer still needs branch-lineage and future-growth cards to be explicitly evidence-bound rather than only node-bound.

## Next Engineering Gate

- P7: branch cards must expose parent branch, split reason, driver papers, and constraint shift; layout-only clusters must be labeled as weak.
- P8: VGAE/GNN future candidates must remain candidate generator output unless Step6 + Step13 produce complete Claim Cards.
- Final run should use full section/OpenAlex frontfill, not this smoke output.
