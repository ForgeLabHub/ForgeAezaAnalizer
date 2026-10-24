# Research notes — Aéza cases and related repositories

Date: 2026-10-24. Status: **PARTIAL** (see the blocker below).

This folder records what could be established from sources that actually exist,
and separates that from what could not be established. Nothing here is invented
to fill a gap.

## Blocker: the source list is not in the repository

The task refers to two Aéza cases — «Логовизор» and «SSH-арена» — and to a list
of **11 GitHub repositories**. A search of the whole workspace found neither the
list nor the case descriptions as project artefacts:

```
grep -rli "логовизор|logovizor"  /workspace /home /tmp /root   -> only mission-prompt text
grep -rli "ssh-арена|ssh arena"  /workspace /home /tmp /root   -> only mission-prompt text
grep -rn  "11 репозитор|11 github|одиннадцать репозитор" .      -> nothing
```

The strings «Логовизор» and «SSH-арена» appear **only inside the task prompt
itself** (the conversation event log), never in `docs/`, the deck, the ТЗ, or
any archive in the repository. The ТЗ (`ТЗ.pdf`) describes exactly one case:
«Анализатор рисков оттока», хакатон РНД, уровень Middle.

Per the mission rules, the missing list is **not** replaced with repositories
chosen at random. Instead this folder contains:

1. what the ТЗ itself states about the case we did build (`aeza-case-analysis.md`);
2. the repositories that a GitHub search *does* return for the exact case names
   (`github-repositories.md`), each with its provenance and limits;
3. an explicit statement of what remains unverified.

## What was searched, and with what

| Query | Endpoint | Result |
| --- | --- | --- |
| `ssh-arena` | GitHub search API | **6 hits**, one relevant: `Cricko7/ssh-arena` — "Кейс от компании aeza" |
| `ssh arena aeza` | GitHub search API | **1 hit**: `Cricko7/ssh-arena` |
| `logovizor`, `logvizor`, `logo-vizor` | GitHub search API | 0 hits |
| `логовизор` | GitHub search API (URL-encoded) | 0 hits |
| `aeza hackathon` | GitHub search API | **1 hit**: `yulichump/hackathon-autumn-2026` |
| `aeza in:name,description` | GitHub search API | 330 hits, mostly unrelated ("aezakmi", profiles) |
| `Логовизор кейс Aeza` etc. | DuckDuckGo HTML/lite | 0 parseable results (endpoint returns no `result-link` markup) |
| `aeza`, `aeza-hackathon`, `dgtu`, `umirhack` | GitHub orgs API | all 404 |

Only the GitHub REST API returned usable data. The web-search endpoints returned
no structured results, so no claim rests on them.

## Files

- `aeza-case-analysis.md` — the case we actually built, from `ТЗ.pdf` and the
  organiser dataset, plus the two named cases and their status.
- `github-repositories.md` — every repository the searches returned, with URL,
  stack, licence, currency, and applicability to our product.
