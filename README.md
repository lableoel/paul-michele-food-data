# Swiss and European food data

Data-only regional derivative of [Open Food Facts](https://world.openfoodfacts.org/data). This repository contains public product facts, licence notices, country tags and standalone dataset maintenance tools. It contains no mobile application source, user profiles, diary/history, camera frames, contributor identities, credentials or product photos.

Current snapshot: **2,839,458 products**,45 immutable gzip JSONL parts,112,096,112 compressed bytes. Market eligibility is based on Open Food Facts country tags (see markets.json), not barcode prefixes. Names/nutrition can be incomplete or outdated; compare the product label. Europe includes Switzerland, the EU, UK, Norway and other geographical European/transcontinental markets listed in markets.json.

## Download protocol

The app reads manifest.json and validates every referenced part by SHA256, exact byte size and row count before atomic publication. Each filename includes its content hash. Raw files must be served as their original gzip bytes, without an extra Content-Encoding:gzip transformation. No authentication/API key is needed for these public files. This repository is not an official Open Food Facts service and does not guarantee complete coverage.

New parts and their manifest publish in one Git commit. Old immutable parts remain in the current tree for at least120days, then in Git history. The app checks the latest manifest when retrying an unavailable part. Do not use Git LFS, paid runners, artifact uploads or paid storage. Standard public-repository GitHub Actions runners are free; repository size/service limits still apply.

## Monthly refresh

The scheduled workflow runs on the second day of each month using a standard public Ubuntu runner, plus an optional manual dispatch (validation only by default; choose refresh to regenerate). It streams the official full export once on the build host; phones download only this regional pack. Source and intermediate SQLite remain in temporary runner storage and are never committed. The workflow validates the full pack and commits only public outputs. Existing immutable chunks stay available for interrupted clients; unreferenced current-tree files older than120days may be pruned. Git history retains older versions. No workflow runs on ordinary pushes, avoiding duplicate regeneration. Future scheduled execution depends on GitHub availability and workflow policy.

To reproduce with Python3.10+ and no third-party packages:

```
python scripts/build_dataset.py --download --source /temporary-cache/openfoodfacts.csv.gz --output .
python scripts/validate_dataset.py
```

A build host needs several GB of temporary storage. The raw export and intermediate SQLite must never be put in this repository. Product API crawling is not used.

## Licences and privacy

See [LICENSE.md](LICENSE.md): database ODbL1.0; individual contents DbCL1.0. The standalone build tools are MIT. Manufacturer names and trademarks retain their owners' rights. GitHub receives ordinary connection metadata when clients download files; see [GitHub privacy](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). No app records are sent here.

## Compact mobile format (v2)

The app v2.2.1+ uses `manifest-v2.json`: a pre-indexed, read-only SQLite snapshot split into independently SHA-256 verified gzip chunks. All 2,839,458 original regional labels are retained losslessly. Current installed size is 227,557,376 bytes (about217MiB), down84.6% from the previous Android database; initial transfer is165,179,673bytes (about158MiB). No product photos are included.

The snapshot stores fixed-field product arrays in small zlib blocks and a contentless SQLiteFTS4 token index. Android/iOS do not parse or index millions of product rows. Unchanged versions fetch only the manifest; changed builds can reuse unchanged4MiB slices from the installed snapshot. Interrupted installation resumes at verified slice boundaries. No compressed second copy remains installed.

`manifest.json` and its JSONL files remain available for v2.2.0 clients. Both formats are refreshed by the same free standard public GitHub Actions job. The build/validation tools operate on public facts only; they never receive personal app data. New SQLite files are temporary build intermediates and must not be committed; only attributed compressed chunks/manifests are published.

SQLite compatibility: affected system SQLite3.44–3.53 versions incorrectly report an absent-content comparison error for healthy contentlessFTS4 indexes ([upstream defect/fix](https://sqlite.org/src/info/ca8de9a304)). Validation accepts only that exact diagnostic after confirming the exact contentless schema; all physical-page errors, unexpected schemas, SHA mismatches and failed MATCH probes remain fatal.
