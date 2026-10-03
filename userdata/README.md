# Build-config pack (`userdata/`)

This folder is the **source of truth for the build's identity** — the settings
that make a clean Kodi look and behave like "Kodi POV IL", separately from the
addon *code* (which lives in the `plugin.*/`, `script.*/`, `service.*/`,
`skin.*/` folders and ships as its own zips).

CI packages this folder into a versioned, deterministic `config-<version>.zip`,
lists it in `manifest.json` under `"config"`, and publishes it to the rolling
release. The wizard (`resources/libs/config_apply.py`) downloads it, verifies
its sha256, and applies each file per `config_policy.json`.

The Wizard also carries a small published config ZIP at
`resources/bootstrap/config.zip`. It uses this copy only when both the SHA-256
and the declared size match the current manifest. This lets a fresh install
complete when that particular download is unavailable. A newer manifest never
uses a stale seed: it falls back to the verified network download. To refresh
the seed, copy the already published config artifact, verify its manifest hash
and size, and bump the Wizard version before packaging it. Updating this README
alone does not require a config-version bump.

## Why a separate pack (Option 3)

* **Fresh install** can be fully configured from the addon zips + this pack —
  no monolithic build zip required.
* **Updates** follow the per-file policy below. Existing account credentials,
  Kodi GUI choices, widgets and favourites are retained; missing build defaults
  can be added without replacing a user's values.

## Files

| File | What it is | fresh | update |
|------|------------|-------|--------|
| `guisettings.xml` | Curated build-identity Kodi settings. Kodi rewrites this file on shutdown, so an existing device keeps its live choices. | `merge_id` | `seed_if_absent` |
| `addon_data/skin.fentastic/settings.xml` | FENtastic defaults and Hebrew menu labels. | `replace` | `merge_missing_id` |
| `addon_data/plugin.video.pov/settings.xml` | POV defaults, excluding user account credentials on update. | `replace` | `merge_missing_id` |
| `favourites.xml` | Build's default favourites / home shortcuts. | `replace` | `seed_if_absent` |
| `sources.xml` | Build's repository file-sources (kodifitzwell, Fishenzon, Otaku, CocoScrapers) — cleaned to match the hybrid provisioning repos. | `replace` | `merge_name` |
| `advancedsettings.xml` | Cache/network performance tuning. | `replace` | `seed_if_absent` |
| POV navigation/view databases and FENtastic helper cache | Starter data for a new device; existing layouts and view choices remain. | `replace` | `seed_if_absent` |
| `config_policy.json` | Declarative apply policy (modes, `exclude_ids`, cleanup). | — | — |

### Apply modes

* `replace` — overwrite the whole file.
* `merge_id` — per `<setting id=...>`: the build value wins; every other user
  setting in the file is left untouched. ids in `exclude_ids` are never written
  (machine-specific: `services.deviceuuid`, display resolutions, …).
* `merge_missing_id` — add only setting IDs absent from the existing file;
  preserve all existing values. Credential IDs in `exclude_ids` are not added.
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
