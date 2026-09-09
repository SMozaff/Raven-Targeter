# Packaging — Raven-Targeter

Desktop builds via [PyInstaller](https://pyinstaller.org/) (one-file,
windowed). The binary is named **Raven-Targeter**.

> PyInstaller cannot cross-compile. Build each platform's artifact **on
> that platform**. This sandbox (Linux) produces the Linux binary and
> AppImage; Windows and macOS builds run the same commands natively.

## Prerequisites (all platforms)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,packaging]"
```

## Linux

```bash
.venv/bin/pyinstaller packaging/linux.spec
# → dist/Raven-Targeter
```

Optional AppImage (needs `appimagetool`, see below):

```bash
# layout dist/Raven-Targeter into RavenTargeter.AppDir with
# Raven-Targeter.desktop + icon, then:
appimagetool RavenTargeter.AppDir
# → Raven-Targeter-x86_64.AppImage
```

## Windows (on a Windows machine)

```powershell
.venv\Scripts\activate
pip install -e ".[dev,packaging]"
pyinstaller packaging\windows.spec
# → dist\Raven-Targeter.exe  (no console window)
```

## macOS (on a Mac)

```bash
source .venv/bin/activate
pip install -e ".[dev,packaging]"
pyinstaller packaging/macos.spec
# → dist/Raven-Targeter.app
```

## Notes

- No secrets are bundled: the build contains no `.env` and no token.
  At runtime the app reads `.env` / environment from the launch
  directory and falls back to built-in defaults (with the
  unauthenticated rate-limit warning).
- The SQLite database (`data/raven.db` by default) is created next to
  the launch directory on first run.
- Icons: drop `packaging/icon.ico` (Windows) / `packaging/icon.icns`
  (macOS) / `packaging/icon.png` (AppImage `.desktop`) into this folder
  and add the corresponding `icon=` line to the spec to brand the build.
- `build/` and `dist/` are gitignored; only the `.spec` files and this
  README are committed.
