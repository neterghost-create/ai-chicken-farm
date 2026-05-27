# AI Chicken Farm

> A self-hosted, low-footprint pipeline that **discovers, cleans, scores, and serves** public free proxy nodes on a single Linux VPS.

[English](README.en.md) · [繁體中文](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-blue.svg)]()
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-green.svg)]()
[![Release](https://img.shields.io/github/v/release/neterghost-create/ai-chicken-farm?label=release&color=orange)](https://github.com/neterghost-create/ai-chicken-farm/releases/latest)
[![Last Commit](https://img.shields.io/github/last-commit/neterghost-create/ai-chicken-farm?color=informational)](https://github.com/neterghost-create/ai-chicken-farm/commits/main)
[![Stars](https://img.shields.io/github/stars/neterghost-create/ai-chicken-farm?style=social)](https://github.com/neterghost-create/ai-chicken-farm/stargazers)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-aicf.duckdns.org-success?logo=googlechrome&logoColor=white)](https://aicf.duckdns.org/ss-monitor/)

## 🌐 Live Demo

**[https://aicf.duckdns.org/ss-monitor/](https://aicf.duckdns.org/ss-monitor/)** — the maintainer's production instance. See the five cards, chicken-themed UI, three-tier table limits, and zh-Hant / zh-Hans / EN switcher in action.

> The dashboard publicly exposes pool stats, scoring trends, the discovery queue, and source rankings, but **subscription files require a 32-hex token**. The demo is for friends only — if you want this kind of subscription, deploy your own.

## What is this?

A complete proxy node pipeline that runs on a 1.8 GB-RAM VPS:

- **Foraging 🐛** — auto-discover new subscription sources from awesome READMEs and GitHub Topics
- **Feed Mill 🏭** — score 200+ subscription sources (v2.3 full-marks-on-entry, monotonic-decay model)
- **Coop 🏠** — [subs-check](https://github.com/beck-8/subs-check) handles liveness probing and speed testing
- **Egg Pool 🥚** — clean nodes are served as four subscription formats (Clash / V2Ray / Base64 / legacy-Clash)
- **Feed 🌽** — node quality scoring with three-level blacklist
- **Dashboard** — Flask backend + plain HTML/CSS/JS frontend, 9 security headers, three languages

Each component is strictly decoupled and can be upgraded or rolled back independently. See [DEPLOYMENT.md](DEPLOYMENT.md) (74 KB / 20 chapters / 2189 lines) for the full guide.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/neterghost-create/ai-chicken-farm.git
cd ai-chicken-farm

# 2. Open the deployment manual
less DEPLOYMENT.md     # jump to §11 "1:1 Deployment Steps (from scratch)"

# 3. Follow the 7 phases
#    Phase 0: System prep (apt + pip)
#    Phase 1: DuckDNS + Telegram + subscription token
#    Phase 2: subs-check binary + config
#    Phase 3: Python maintenance scripts + DB schema
#    Phase 4: ss-monitor dashboard
#    Phase 5: nginx + TLS
#    Phase 6: cron + monitoring
#    Phase 7: Full self-check
```

A fresh deployment takes 1–2 hours.

> The deployment manual itself is in **Traditional Chinese** (繁體中文). The code, comments, and config are largely English-friendly. If you want to follow along in English, lean on the architecture diagrams, file lists, and command blocks — they are language-agnostic. Translation PRs welcome.

## Who is this for?

- You have a spare VPS (≥ 1 GB RAM) and want to run a private free-proxy pool for a few friends
- You want a hands-on tour of Python + SQLite + nginx + systemd + cron in production
- You're curious about how scoring, blacklisting, and source quality decay can be designed (see [snapshots/scripts/SCORING_RULES_v2.md](snapshots/scripts/SCORING_RULES_v2.md), 619 lines of decision history)

## Who is this NOT for?

- People wanting a one-click installer — this project favours "read the docs, then deploy"; there is no `install.sh`
- People wanting to use the maintainer's subscription directly — node sources come from public airport aggregators; this is the framework, not the data
- People who need an LTS commercial-grade product — this is a personal hobby project shared under MIT

## Repository Layout

```
ai-chicken-farm/
├── README.md                  # 中文介紹 (default landing)
├── README.en.md               # English introduction (this file)
├── DEPLOYMENT.md              # Full deployment manual (74 KB, 20 chapters)
├── LICENSE                    # MIT
├── .gitignore                 # excludes *.db, *.bak, *.log, real credentials
└── snapshots/                 # 1:1 restore artefacts (40 files, 600 KB)
    ├── scripts/               # 11 Python maintenance scripts + DB schema + configs
    ├── ss-monitor/            # api.py + index.html + app.css + app.js
    ├── nginx/                 # 2 vhosts + 3 shared snippets
    ├── systemd/               # 2 .service units + drop-in
    └── cron/                  # 5 monitor scripts + crontab snapshot
```

## Core Features

| Feature | Description |
|---|---|
| Scoring v2.3 | Starts at 100, monotonic decay; 4 source-level + 2 node-level blacklist triggers |
| 6-layer filter | domain / IOC / path / response / content-signature / cross-source dedup, plus socket-level SSRF guard |
| Tri-lingual i18n | 134 keys × zh-Hant / zh-Hans / EN, data-driven, no inline JS/CSS |
| 9 security headers | CSP / HSTS / X-Frame / X-Content-Type / Referrer / Permissions / COOP / CORP / X-XSS |
| Token auth | 32-hex subscription token, path-based gating, hot-rotatable |
| Tri-stage table limit | 5 / mid / all rows, persisted via localStorage |
| Chicken theme | emoji-driven worldview (🥚🌽🏭🐛), masked sensitive fields |
| Auto-discovery | Foraging cron at 02:00, 10 awesome + 6 topics + 6-layer filter |
| Full rollback | timestamped backup tag convention, DB + scripts + nginx in lockstep |

## System Requirements

- **OS**: Debian 12 / Ubuntu 22.04+ LTS
- **RAM**: 1 GB minimum, 2 GB recommended
- **Disk**: 5 GB minimum
- **Network**: public IPv4 (CGNAT scenarios covered in DEPLOYMENT §14)
- **Domain**: a free DuckDNS subdomain works fine

## Performance Baseline

- 80 sources per round ≈ 5 hours (measured on a 1.8 GB-RAM VPS)
- ss-monitor RAM: 24.8 M / 50 M (MemoryMax)
- subs-check RAM: 80–320 M / 512 M
- Subscription size: ~80 KB (~600 nodes Clash YAML)

## Contributing

Issues and PRs are welcome. Please read the relevant DEPLOYMENT chapter first:

- Changing the scoring rules → §17.1, then run `dryrun-v2.3.py` to simulate
- Frontend changes → §7 (split rule: HTML/CSS/JS three files, no inline)
- Adding a discovery source → §6, edit `discovery-config.yaml`
- Modifying cron → §9.4 (5 implicit timing constraints you must not break)

## Acknowledgements

- [beck-8/subs-check](https://github.com/beck-8/subs-check) — the core liveness/speed-test binary
- [lza6/free-VPN](https://github.com/lza6/free-VPN) and other public-airport aggregator READMEs
- DuckDNS, Let's Encrypt, Cloudflare, and the rest of the public infrastructure that makes this possible

## License

MIT License — see [LICENSE](LICENSE)

---

> This is a personal learning + friends-only project. **Not for commercial use.** Node data comes from public aggregators; quality is best-effort and not guaranteed.
