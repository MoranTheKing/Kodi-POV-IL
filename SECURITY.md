# Security Policy

This repository is maintained by MoranTheKing.

Only trusted maintainers should have write access. Do not add external collaborators unless they are expected to publish build files, APK files, or GitHub Pages content.

## Required GitHub Settings

Enable these settings in GitHub to prevent accidental or unauthorized changes:

1. Settings -> Collaborators and teams:
   Keep only trusted maintainers with write/admin access.

2. Settings -> Branches -> Add branch protection rule for `main`:
   Enable "Require a pull request before merging".
   Enable "Require review from Code Owners".
   Enable "Do not allow bypassing the above settings".
   Disable force pushes.
   Disable deletions.

3. Settings -> Branches -> Add branch protection rule for `gh-pages`:
   Disable force pushes.
   Disable deletions.
   Allow direct pushes only from trusted maintainers.

4. Settings -> Pages:
   Use `Deploy from a branch`, branch `gh-pages`, folder `/`.

5. Settings -> Actions -> General:
   Use "Allow MoranTheKing, and select non-MoranTheKing, actions and reusable workflows" if you want strict workflow control.

## APK Signing

Do not publish unsigned APK files.

A working Kodi Android APK requires the Kodi Android project build output and an Android signing key. If an existing APK is modified, it must be re-signed, and Android treats a different signing key as a different app identity. Users upgrading an already-installed APK generally need the same signing key that signed the previous APK.

Signing keys must not be committed to this repository. Store signing keys in GitHub Actions secrets or keep them offline.

