# Android compatibility and release status

Last verified: 2026-08-30

## Architecture

CYPHER65 Mobile is a React Native application managed with Expo SDK 57. Native
projects are generated through Expo Continuous Native Generation and are not
committed to this repository.

The current `npm run build:android` command runs `expo export --platform
android`. It validates the JavaScript bundle only. It does **not** create,
install, sign, or exercise an APK or AAB.

## Supported configuration

| Property | Current value | Evidence |
|---|---:|---|
| Expo SDK | 57.0.18 | `mobile/package-lock.json` |
| React Native | 0.86.3 | `mobile/package-lock.json` |
| Android package | `com.cypher65.warroom` | `mobile/app.json` |
| Claimed Android OS range | Not certified | No emulator or physical-install campaign has passed |
| minSdk / targetSdk / compileSdk | Expo SDK defaults | Must be recorded from a generated native project before release |

Do not claim Android-version or device compatibility until the release APK has
been installed and tested on that version/profile.

## Dependency audit

`npm audit` currently reports no high or critical vulnerability. The `qs`
denial-of-service advisory reachable through the development-only Stryker
toolchain is pinned to the patched `6.16.0` release through an npm override.

The remaining 11 moderate findings are in the Expo build/configuration
toolchain, including the `uuid` version constrained by Expo's `xcode` parser.
The automated npm recommendation is a downgrade to Expo 46, which is not a safe
or compatible fix for an SDK 57 application. They remain release advisories
until Expo publishes a compatible dependency tree. They are build-time risks,
not evidence that the runtime APK is safe; APK inspection is still mandatory.

## Gates not yet satisfied

- Generate a native Android project in a clean, controlled build environment.
- Record effective `minSdk`, `targetSdk`, and `compileSdk`.
- Produce signed release APK and AAB without committing signing material.
- Verify signature and SHA-256 checksums.
- Install the exact release APK, launch it, and complete human E2E.
- Inspect the APK for server secrets and insecure manifest/WebView settings.
- Test lifecycle, offline recovery, network transitions, upgrade and supported
  Android/device-size matrix.

Until these gates pass, Android status is **NOT READY** and any generated Expo
export must be described as a bundle, never as a release APK.
