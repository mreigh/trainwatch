# TrainWatch backlog

Claude maintains this file. Matt sets priorities; Claude keeps it current, moves items as they finish, and adds new ones as they come up.
Status: `todo` · `doing` · `done` · `blocked`. Top of each phase = next up.

## Phase 0: Lock in v2 (done 2026-10-09)
| # | Item | Status | Notes |
|---|---|---|---|
| 0.1 | Confirm v2 catches real trains on production | done | Check `./ctl.sh today` and snapshots after a full day |
| 0.2 | Stop the old copy on the Air (`./ctl.sh uninstall`) | done | Avoids double alerts. Run on the Air |
| 0.3 | Clean up v1 leftovers (`*.bak`, `zz_test`, `requirements-old.txt`) | done | Kept `~/TrainWatch-v1-backup-2026-10-08.tgz` for now |

## Phase 1: Git + one source of truth (doing)
| # | Item | Status | Notes |
|---|---|---|---|
| 1.1 | Decide where the main repo lives | blocked | Waiting on Matt. Recommended: private GitHub repo. Alternative: bare repo on pickles over Tailscale |
| 1.2 | `git init` on production, `.gitignore` (venv, data, logs, pycache, backups), first commit = current v2 | done | Production is the known-good baseline |
| 1.3 | Split config: shared settings committed, per-machine values (ntfy topic, data_dir) in an uncommitted `config.local.yaml` | done | Needed so test and prod can differ without editing code |
| 1.4 | Turn `TRAINWATCH_PORT.md` into `CLAUDE.md` (context Claude loads every session) + keep `BACKLOG.md` in the repo | done | This is what lets Claude pick up on either laptop |
| 1.5 | Clone the repo onto the Air as the dev copy | todo | |

## Phase 2: Test vs production
| # | Item | Status | Notes |
|---|---|---|---|
| 2.1 | Define environments: **prod** = pickles-data-center (main branch only), **test** = the Air | todo | |
| 2.2 | Test environment settings: own `data_dir` (`test_data/`), own ntfy topic (`...-test`), no launchd jobs, runs on demand | todo | Test alerts never land on the prod topic |
| 2.3 | Replay test set: save short clips of real trains + known false alarms; script runs the detector over them and reports caught/missed | todo | Code already accepts a local video file as `stream_url`. This is the real safety net for detector changes |
| 2.4 | Live smoke test on the Air: run against the real stream for N minutes with `--max-seconds` | todo | Keep it short: two machines on the same home IP double the YouTube bot-check risk |
| 2.5 | `deploy.sh` on prod: pull main → install deps → reinstall jobs if changed → restart → health check (heartbeat fresh, stream open) | todo | |
| 2.6 | Rollback: tag every deploy; `deploy.sh --rollback` returns to the previous tag | todo | |

## Phase 3: Working from two laptops
| # | Item | Status | Notes |
|---|---|---|---|
| 3.1 | Rule: code changes happen on the Air; production only ever gets `deploy.sh` | todo | No hand edits on prod |
| 3.2 | SSH key from the Air to pickles (no password prompts) + a `trainwatch-prod` shortcut | todo | |
| 3.3 | Ops from the Air: one-liners for status/logs/today on prod over SSH | todo | |
| 3.4 | Decide whether Claude Code also runs on pickles (ops/diagnosis only) | todo | |

## Later / ideas
| # | Item | Notes |
|---|---|---|
| L.1 | YouTube cookies fallback (`cookies_file` setting) | Only if bot blocks keep happening |
| L.2 | Health ping if the heartbeat goes stale (dead-man's switch) | Today a dead watcher is silent |
| L.3 | Freight vs passenger classification | Matt mostly cares about freight |
| L.4 | Multi-site support (per-site config, zone, logs, alerts) | Prereq for the I-94 / Hwy 100 location |
| L.5 | Second location camera options | 511wi stills, other railfan cams, own IP camera |
| L.6 | Weekly/monthly stats or dashboard | |

## Done
| Date | Item |
|---|---|
| 2026-10-08 | Diagnosed stream outage (YouTube bot check, cleared on its own after ~14 min) |
| 2026-10-08 | Upgraded production from v1 to v2 detector; v1 backed up |
| 2026-10-08 | Quick reference guide written |
