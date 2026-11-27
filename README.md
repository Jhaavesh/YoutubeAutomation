# DON OF VICE CITY — YouTube Automation Pipeline

A Windows-first, configuration-driven YouTube automation pipeline. It builds
one 16:9 long video and the configured number of 9:16 Shorts, schedules them
through the official YouTube Data API, and records enough state to avoid
duplicate processing.

**Phase 3 status:** stabilized and covered by offline regression tests. The
pipeline still uses third-party gameplay footage from YouTube; see
[Content and source compliance](#content-and-source-compliance) before
publishing at scale.

---

## What Phase 3 changed

| Area | Change |
|------|--------|
| Configuration | `config_version: 2`; all sections load through `config_loader.py`; `config.example.yaml` is safe to commit |
| Scheduling | Timezone-aware (`Asia/Kolkata` by default); no naive `datetime.now()` scheduling |
| Uploads | Pre-upload FFprobe validation, retries with backoff, Pacific-time quota tracking, duplicate protection |
| Duplicate safety | SHA-256 upload ledger (`upload_ledger.json`) ties file bytes + channel to an existing video ID |
| Quota | Correct 1,600-unit cost per upload plus a separate upload-count cap; alerts at the configured threshold |
| OAuth | `setup_auth.py` requests upload, metadata/thumbnail, and Analytics scopes; verifies granted scopes |
| Approval | `approval.required: true` forces a private draft and refuses public/unlisted metadata changes |
| Rendering | Removed double trimming; output FPS is enforced from config; thumbnail seek is duration-aware |
| Reliability | Single-instance lock; honest exit codes; no fake fallback video URL on failure |
| Diagnostics | New read-only `doctor.py`; `health_check.py` reports real package names, FFmpeg path, and token scopes |
| Launchers | `run_daily.ps1` no longer executes Python twice or recurses in its event-log helper; batch and Python logs are separated |
| Tests | `tests/test_phase3.py` covers config, time, locks, ledger, quota, approval, duplicate uploads, and real FFmpeg output |

---

## Repository structure

```
Youtube/
├── config.yaml               # Local configuration (git-ignored)
├── config.example.yaml       # Committable template
├── config_loader.py          # Schema, path resolution, validation
├── utils.py                  # Logging, locks, ledger, quota, timezone, FFmpeg
├── upload_video.py           # OAuth, validation, upload, metadata, thumbnails
├── long_video_engine.py      # Long-video download/render/upload
├── auto_pilot_bot.py         # Shorts download/render/upload
├── master_autopilot.py       # Main orchestrator and CLI
├── continuous_autopilot.py   # Daemon / scheduled single-cycle wrapper
├── setup_auth.py             # OAuth setup per channel
├── doctor.py                 # Read-only preflight diagnostics
├── health_check.py           # Read-only system health report
├── run_daily.bat             # Batch launcher used by the current task
├── run_daily.ps1             # PowerShell launcher (optional)
├── launch_silent.vbs         # Silent startup launcher
├── tests/test_phase3.py      # Offline regression suite
├── assets/audio/             # Background music
├── daily_generated/          # Rendered media (auto-cleaned)
├── autopilot_db.json         # Runtime state (git-ignored)
├── upload_ledger.json        # Upload idempotency ledger (git-ignored)
├── autopilot.log             # Python rotating log (git-ignored)
└── backups/                  # Local backups (git-ignored)
```

---

## Quick start

### 1. Install dependencies

```powershell
pip install -r requirements.txt
```

FFmpeg and FFprobe must be installed. Leave `paths.ffmpeg_exe` and
`paths.ffprobe_exe` empty to auto-detect from `PATH`, or set explicit paths in
`config.yaml`.

### 2. Configure YouTube API

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Create an **OAuth 2.0 Client ID** of type **Desktop app**.
3. Download it as `client_secret.json` in the project root.

### 3. Authenticate

```powershell
python setup_auth.py --list
python setup_auth.py --channel donofvicecity2026
```

Requested scopes:

- `youtube.upload` — upload videos
- `youtube.force-ssl` — edit metadata, delete videos, set thumbnails
- `yt-analytics.readonly` — read Analytics in later phases

The existing token in this workspace only has `youtube.upload` and
`youtube.readonly`. Uploads work, but metadata updates, deletions, and
Analytics will fail until the channel is re-authenticated. Custom thumbnails
also require a channel verified for custom thumbnails; otherwise YouTube
returns `403` and the pipeline logs a warning without failing the upload.

### 4. Preflight

```powershell
python doctor.py
python master_autopilot.py --quota
```

`doctor.py` is read-only. It checks imports, config sections, audio/font
assets, FFmpeg/FFprobe, OAuth scopes, quota, state files, the Windows task, and
the latest rendered media.

### 5. First real run

```powershell
python master_autopilot.py --verify
python master_autopilot.py --long-only
python master_autopilot.py --shorts-only
python master_autopilot.py
```

A full run uploads and schedules real videos. Use `--quota`/`--verify` for
non-publishing checks.

---

## Configuration

`config.yaml` is the local source of truth. `config.example.yaml` is generated
from it with machine-specific binary paths blanked.

Key sections:

```yaml
config_version: 2

channels:
  default: "donofvicecity2026"
  accounts:
    donofvicecity2026:
      name: "DON OF VICE CITY"
      token_file: "token.pickle"
      client_secret_file: "client_secret.json"

video:
  long:
    resolution: "2560x1440"
    fps: 60
    duration_range_seconds: [150, 180]
  short:
    resolution: "1080x1920"
    fps: 60
    duration_seconds: 26

schedule:
  timezone: "Asia/Kolkata"
  long_video:
    target_hour: 18
    target_minute: 0
    min_lead_minutes: 15
    round_to_minutes: 5
  shorts:
    standard_slots:
      - {slot_id: 1, name: "Slot 1", hour: 13, minute: 0}
      - {slot_id: 2, name: "Slot 2", hour: 16, minute: 30}
      - {slot_id: 3, name: "Slot 3", hour: 19, minute: 30}
      - {slot_id: 4, name: "Slot 4", hour: 22, minute: 30}
    min_first_lead_minutes: 20
    end_of_day_hour: 23
    end_of_day_minute: 30

quota:
  daily_limit: 10000
  upload_daily_limit: 100
  search_daily_limit: 100
  reset_timezone: "America/Los_Angeles"
  costs:
    video_upload: 1600
    video_update: 50
    video_list: 1
    search_list: 100
    thumbnail_set: 50
  alert_threshold_percent: 80
  reserve_buffer: 2000

approval:
  required: false       # true = private draft, never auto-publish
  auto_approve: true    # used only when required is false

source_policy:
  allow_external_downloads: true
  rights_confirmed: false
```

### Scheduling behavior

- If a standard slot is still far enough in the future, it is used.
- If the machine starts late, past slots are skipped and remaining Shorts are
  spread between now and the configured end-of-day time.
- A long video whose target time has passed is scheduled at
  `now + min_lead_minutes`, rounded to the configured interval.
- Scheduling depends on a successful upload; quota exhaustion, network
  failures, or API errors can still prevent a video from being scheduled.

---

## Quota

YouTube grants **10,000 general quota units per day**, reset at midnight
Pacific Time. A video upload costs **1,600 units**, and YouTube also applies a
separate cap of **100 uploads/day**. Search has its own 100-calls/day cap.

| Operation | Units | Daily count | Total |
|-----------|------:|------------:|------:|
| Long video upload | 1,600 | 1 | 1,600 |
| Shorts uploads | 1,600 | 4 | 6,400 |
| Thumbnail set | 50 | 1 | 50 |
| **Estimated total** | | | **8,050 / 10,000** |

That leaves roughly **1,950 units**, not a guarantee. Metadata updates,
retries, manual calls, and other tools consume the same bucket. The tracker
blocks an upload when the projected cost would exceed 10,000 units and warns
at the configured threshold.

```powershell
python upload_video.py --quota
python master_autopilot.py --quota
```

`daily_limit`, upload/search caps, costs, and `reset_timezone` are configurable,
but keep them aligned with Google's current published limits.

---

## Approval mode

Default behavior preserves the current zero-touch pipeline:
`approval.required: false` and `approval.auto_approve: true`. Videos are
uploaded with `privacyStatus: private` plus `publishAt`, so YouTube publishes
them at the scheduled time.

If `approval.required: true`:

- the upload is forced to a **private draft**;
- `publishAt` is never attached;
- `update_video_metadata()` refuses to set `public` or `unlisted`;
- the ledger marks the response with `_approval_required: true`.

There is no automatic approval CLI in Phase 3. Review the draft in YouTube
Studio, then either publish it manually or set `approval.required: false` and
re-run the metadata step deliberately.

---

## CLI reference

### Master orchestrator

```powershell
python master_autopilot.py                    # Full daily run
python master_autopilot.py --channel KEY      # Specific channel
python master_autopilot.py --all-channels     # All configured channels
python master_autopilot.py --long-only        # Long video only
python master_autopilot.py --shorts-only      # Pending Shorts only
python master_autopilot.py --quota            # Quota report, no upload
python master_autopilot.py --verify           # Verify OAuth/channel
```

Exit code is `0` only when the requested work is actually scheduled. A failed
long video, a Shorts shortfall, or another exception returns non-zero.

### Long video

```powershell
python long_video_engine.py
python long_video_engine.py --topic ID --channel KEY
python long_video_engine.py --quota
```

### Shorts

```powershell
python auto_pilot_bot.py
python auto_pilot_bot.py --slot 2
python auto_pilot_bot.py --topic physics
python auto_pilot_bot.py --quota
```

### Uploads and auth

```powershell
python upload_video.py --quota
python upload_video.py --verify
python upload_video.py --scopes
python setup_auth.py --list
python setup_auth.py --scopes
python setup_auth.py --channel KEY
```

### Diagnostics

```powershell
python doctor.py
python doctor.py --json
python doctor.py --skip-task
python health_check.py
python health_check.py -v
python health_check.py --recent 7
python health_check.py --fix-duplicates
```

### Tests

```powershell
python -m unittest tests.test_phase3 -v
```

The suite is offline except for a one-second locally generated FFmpeg test
clip. It does not upload anything.

---

## Windows automation

The current machine uses the task **`DonOfViceCity_DailyShorts`**, which runs
`run_daily.bat` daily at 13:00 IST. The laptop does **not** need to be on at
exactly 13:00:

- **Daily trigger:** 13:00 IST.
- **Logon trigger:** runs 2 minutes after the user logs in. If the laptop was
  off at 13:00, the day's upload is scheduled as soon as the user logs in.
- **StartWhenAvailable:** a run missed because the PC was asleep starts when
  the PC wakes.
- **Battery:** starting and continuing on battery are both allowed.
- **Retry:** up to 3 restarts, 10 minutes apart, if a run fails.
- **Single instance:** `MultipleInstances=IgnoreNew`; `master_autopilot.py`
  also takes a lock.

Runs are idempotent: if today's Short or long video is already scheduled, the
next run logs `Daily Short limit ... already reached` and exits without
uploading a duplicate.

The startup VBS shortcut (`DonOfViceCity_Daily.vbs.disabled`) remains disabled;
the task's logon trigger replaces it, so only one launcher exists.

Do not change the task or startup entry without an explicit decision.

### Log files

| File | Purpose |
|------|---------|
| `autopilot.log` | Python rotating log (owned by Python only) |
| `autopilot_launcher.log` | `run_daily.ps1` launcher messages |
| `autopilot_console.log` | `run_daily.bat` stdout/stderr |
| `autopilot_errors.log` | Failed batch runs |
| `last_run_health.txt` | Last batch-launcher run status |
| `last_run_health.json` | Last PowerShell-launcher health record |
| `autopilot_db.json` | Runtime state and daily slots |
| `upload_ledger.json` | File-hash → video-ID deduplication ledger |

### Optional PowerShell launcher

```powershell
.\run_daily.ps1
.\run_daily.ps1 -Channel donofvicecity2026
.\run_daily.ps1 -QuotaOnly
.\run_daily.ps1 -VerifyOnly
```

`-QuotaOnly` and `-VerifyOnly` do not overwrite the last full-run health
record.

---

## Content and source compliance

This repository currently downloads gameplay footage from YouTube with
`yt-dlp` and re-uploads edited clips. **Downloading and re-uploading
third-party footage can infringe copyright or violate YouTube policy.** The
code deduplicates source IDs, but deduplication is not a license.

- `source_policy.rights_confirmed` defaults to `false` and the engines log a
  warning on every run.
- Only publish footage you own, have licensed, or can use under an applicable
  exception. Consult a qualified professional for your jurisdiction and use
  case.
- Background music must also be licensed for monetized use.
- Titles, thumbnails, and descriptions must not claim that footage is official
  GTA VI gameplay when it is not.

This project does **not** guarantee views, watch time, monetization, or
copyright safety. It automates publishing mechanics only.

---

## Troubleshooting

### FFmpeg not found

Set `paths.ffmpeg_exe` and `paths.ffprobe_exe` in `config.yaml`, or add the
FFmpeg `bin` directory to `PATH`. `python doctor.py` prints the resolved paths.

### Quota exceeded or upload blocked

- Check `python upload_video.py --quota`.
- The general bucket resets at midnight **America/Los_Angeles** by default.
- Reduce uploads or metadata operations; do not raise the configured limit
  above Google's actual limit.

### Token cannot update metadata or read Analytics

The current token only has upload/read-only scopes. Re-authenticate:

```powershell
python setup_auth.py --channel donofvicecity2026
python upload_video.py --scopes
```

### Custom thumbnail rejected with 403

YouTube requires channel verification for custom thumbnails. The upload still
succeeds; the thumbnail step is logged as a warning.

### Duplicate run or locked process

If a run is interrupted, `autopilot.lock` may remain. The next run checks the
stored PID and removes a stale lock automatically. If the PID is still alive,
stop that process first.

### No internet at startup

Increase `network.internet_check.max_wait_seconds` in `config.yaml`, then
re-run `python doctor.py`.

---

## Known limitations

- Custom thumbnails depend on channel verification.
- Analytics and metadata updates require re-authentication with broader scopes.
- The AI layer is disabled (`ai.enabled: false`, provider `none`); no API key
  is required.
- The current footage pipeline is a compliance risk, not a licensed content
  library.
- `run_daily.bat` appends to `autopilot_console.log` without rotation; archive
  or delete it periodically.
- The scheduled task and startup entry are unchanged in Phase 3.

---

## License and credits

- Code: custom automation pipeline.
- Music: use only tracks you have licensed; the bundled file is a local asset,
  not a license grant.
- Footage: see [Content and source compliance](#content-and-source-compliance).
