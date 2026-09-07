# Android compatibility and release status

Last verified: 2026-09-07

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
| Expo SDK | 57.0.20 | `mobile/package-lock.json` |
| React Native | 0.86.3 | `mobile/package-lock.json` |
| Android package | `com.cypher65.warroom` | `mobile/app.config.js` |
| Orientation | phone/tablet rotation enabled | Shared cross-platform requirement; physical Android regression test pending |
| Native colors | platform notification default; black native splash | Exact DSv2 native colors require a reviewed Expo-compatible token bridge |
| Claimed Android OS range | Not certified | No emulator or physical-install campaign has passed |
| minSdk / targetSdk / compileSdk | Expo SDK defaults | Must be recorded from a generated native project before release |

Do not claim Android-version or device compatibility until the release APK has
been installed and tested on that version/profile.

## Dependency audit

`npm audit` currently reports no high or critical vulnerability. The `qs`
denial-of-service advisory reachable through the development-only Stryker
toolchain is pinned to the patched `6.16.0` release through an npm override.

The SDK-compatible patch update also moves `@xmldom/xmldom` to the patched
`0.9.12` release. The remaining 15 moderate findings are two transitive risk
families repeated through their parent packages:

- Expo build/configuration tooling → `xcode@3.0.1` → `uuid@7.0.3`;
- React Navigation → `query-string` → `decode-uri-component`.

The application does not configure React Navigation deep-link parsing, so the
second family is not currently exposed to untrusted URL input. The first family
runs while generating native projects, not in the shipped JavaScript runtime.
They still remain supply-chain/release advisories until compatible upstream
trees are published. The automated npm recommendations downgrade Expo 57 to 46
or React Navigation 6 to 3, so `npm audit fix --force` is explicitly rejected.
No override may be added if `npm ls` marks the dependency tree invalid.

This triage means **zero high/critical and zero currently reachable moderate
runtime findings**, not “zero advisories”. It is not evidence that a future APK
is safe; APK inspection and malicious deep-link tests are still mandatory.

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
