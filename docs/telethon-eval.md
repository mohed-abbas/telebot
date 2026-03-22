# Telethon 1.42.0 Evaluation

**Decision:** Stay on Telethon 1.42.0. No version change required.

## Current Version

Telethon 1.42.0 (November 2025) is the latest stable release. Pinned in `requirements.txt`. This is the current version used in production.

## Python Compatibility

Supports Python 3.9+. Version 1.42.0 specifically added support for Python 3.14. Our Docker image uses Python 3.12-slim, which is fully supported.

## Security Assessment

- No known CVEs specifically targeting Telethon 1.42.0 (verified via Snyk advisory database)
- File download safety improvement in 1.42.0: "removed potential misuse when downloading files using inferred path"
- Connection error handling improvements across recent versions
- Our usage (read-only message listening + string session auth) has minimal attack surface

## Deprecations

- `force_sms` parameter deprecated (not used in this project)
- `sign_up` method deprecated (not used in this project)
- `imghdr` module no longer used internally (Python 3.13+ compatibility fix)
- None of these deprecations affect our codebase

## Telethon 2.x Status

- Telethon 2.x is in alpha/development
- Contains breaking API changes (different client API, different event handling)
- NOT suitable for production use
- Decision: Do not migrate. Re-evaluate when 2.x reaches stable release.

## Recommendations

- Keep `telethon==1.42.0` pinned in `requirements.txt`
- Monitor Telethon releases for security patches to 1.x series
- If a security patch is released for 1.x, update to that patch version
- Re-evaluate Telethon 2.x migration when it reaches stable release (1.0+)

## Evaluation Date

2026-03-22. Valid for 6 months unless security advisory published.
