# rtsp-ndi

## Versioning

This project follows [semantic versioning](https://semver.org/)
(`MAJOR.MINOR.PATCH`), tracked in `pyproject.toml`'s `version` field. That's
the single source of truth — the GUI (title bar and status bar) and CLI
(`rtsp-ndi --version`, `rtsp-ndi status`) both read it at runtime via
`importlib.metadata.version("rtsp-ndi")` (see `src/rtsp_ndi/__init__.py`),
so it always reflects whatever was actually installed, not just what's in
the source tree.

**Bump the version as part of every change that ships user-visible
behavior — not just when the user asks for a version bump specifically.**
Since installs are done straight from `main` via git (`pip install
git+https://...@main`, no PyPI releases), the version number is the only
way to confirm a reinstall actually picked up new code — if it isn't
bumped, two different installs can show the same version and look
identical while behaving differently.

- **PATCH** (`0.4.0` → `0.4.1`): bug fixes, no behavior change otherwise.
- **MINOR** (`0.4.0` → `0.5.0`): new features/commands/GUI elements,
  backward compatible.
- **MAJOR** (`0.x.y` → `1.0.0`): breaking changes — config file format,
  CLI flags/output, or removed behavior.

When a change is a pure bug fix, bump PATCH even if it feels minor — the
goal is that the version number always moves when the code does.
