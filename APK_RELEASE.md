# APK Release Requirements

The GitHub Pages download pages are ready, but real APK files are not published yet.

To publish working APK downloads, provide one of these:

1. Original signed APK files that can be redistributed as-is.
2. Kodi Android source/build output plus a release keystore for signing.
3. A new APK package name and signing key for a separate app identity.

## Required Files

- Android TV APK, usually 32-bit for many TV boxes.
- Android phone / Shield APK, usually 64-bit.
- Optional Windows installer.

## Signing Notes

- If users already installed an APK signed by another key, Android will not install an update signed by a different key over it.
- If we use a new key, users may need to uninstall the old app before installing the new one.
- Keystore files and passwords must be stored outside the repo or as GitHub Actions secrets.

## Current Download Pages

- `downloads/android-tv/`
- `downloads/android-phone/`
- `downloads/windows/`

These pages currently explain that no signed installers are published yet and point users to the Kodi Wizard install path.

