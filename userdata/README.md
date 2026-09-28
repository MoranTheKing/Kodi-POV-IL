# Build-config pack (`userdata/`)

This folder is the **source of truth for the build's identity** — the settings
that make a clean Kodi look and behave like "Kodi POV IL", separately from the
addon *code* (which lives in the `plugin.*/`, `script.*/`, `service.*/`,
`skin.*/` folders and ships as its own zips).

CI packages this folder into a versioned, deterministic `config-<version>.zip`,
lists it in `manifest.json` under `"config"`, and publishes it to the rolling
release. The wizard (`resources/libs/config_apply.py`) downloads it, verifies
its sha256, and applies each file per `config_policy.json`.

## Why a separate pack (Option 3)

* **Fresh install** can be fully configured from the addon zips + this pack —
  no monolithic build zip required.
* **Updates** apply at the `<setting id=...>` / `<source><name>` level, so a
  user's Real-Debrid / Trakt keys, widgets, and personal tweaks are **never**
  clobbered — which is what used to force people to re-link every update.

## Files

| File | What it is | fresh | update |
|------|------------|-------|--------|
| `guisettings.xml` | Curated build-identity Kodi settings (active skin, Hebrew locale, subtitle config, player/cache). **Not** a full dump — only the settings the build changes, minus machine-specific ones. | `merge_id` | `merge_id` |
| `addon_data/skin.fentastic/settings.xml` | The FENtastic ("Twilight") look + Hebrew menu labels. | `replace` | `merge_id` |
| `favourites.xml` | Build's default favourites / home shortcuts. | `replace` | `seed_if_absent` |
| `sources.xml` | Build's repository file-sources (kodifitzwell, Fishenzon, Otaku, CocoScrapers) — cleaned to match the hybrid provisioning repos. | `replace` | `merge_name` |
| `advancedsettings.xml` | Cache/network performance tuning. | `replace` | `replace` |
| `config_policy.json` | Declarative apply policy (modes, `exclude_ids`, cleanup). | — | — |

### Apply modes

* `replace` — overwrite the whole file.
* `merge_id` — per `<setting id=...>`: the build value wins; every other user
  setting in the file is left untouched. ids in `exclude_ids` are never written
  (machine-specific: `services.deviceuuid`, display resolutions, …).
* `merge_name` — per `<source><name>`: add the build's sources, keep the user's.
* `seed_if_absent` — write only if the destination does not already exist.

## How to change the build's identity

1. Edit the relevant file(s) here (e.g. add a `<setting>` to
   `guisettings.xml`, or a repo to `sources.xml`).
2. **Bump `config_version`** in `config_policy.json` (e.g. `1.0.0` → `1.0.1`).
   That bump is what makes the wizard detect and apply the change — exactly like
   bumping an `addon.xml` version drives an addon update.
3. Push to `main`. CI rebuilds `config-<version>.zip`, refreshes `manifest.json`,
   and publishes it. Devices apply it on their next update check.

> Never put real secrets (RD/Trakt/Premiumize keys, device UUIDs) in here — the
> curated `guisettings.xml` deliberately omits them, and `exclude_ids` guards
> the machine-specific ones.
