# CYPHER65 iOS architecture

Status: foundation implemented; native runtime and Apple distribution remain
subject to the release gates in `IOS_RELEASE_GATES.md`.

## Architecture

The iOS application reuses the existing React Native 0.86 / Expo SDK 57
application in `mobile/`. Expo Continuous Native Generation produces the Xcode
workspace; CYPHER65 does not maintain a second fake Swift application.

- Bundle identifier: `com.cypher65.warroom`
- Application version: `1.0.0`; iOS build number: `1`
- Native source generation: `npm run native:generate:ios`
- JavaScript bundle export: `npm run build:ios` (not an archive or IPA)
- Generated project: `mobile/ios/CYPHER65WarRoom.xcworkspace` after CocoaPods
  (CNG output is ignored and regenerated, not maintained as a second app).
- Minimum deployment target: iOS 16.4, observed in the generated Podfile and
  Xcode project. Certification targets iOS 16.4 through the latest runtime
  supported by the selected release Xcode.
- The current ExpoModulesJSI package declares Swift tools 6.2, so native CI uses
  the macOS 26 runner and rejects Swift toolchains older than 6.2 before build.
  Toolchain observed locally on 2026-08-31: Xcode 26.6, with no installed iOS
  runtime/device.
- Native modules: AsyncStorage, Gesture Handler, Safe Area Context, Screens,
  SVG, Expo Notifications, SecureStore, Local Authentication and Splash Screen.

## Environment isolation

`CYPHER65_APP_ENV` must be one of `development`, `testing`, `staging`, or
`production`. `CYPHER65_API_BASE_URL` selects the backend at build time.
Staging and production require HTTPS and reject localhost, `.local`, loopback
and RFC1918 literals. Production defaults to the public CYPHER65 Render API;
staging deliberately has no default and fails closed.

The app exposes only the environment name and sanitized API host for support.
Server credentials, provider keys, JWT signing keys and wallet private keys do
not belong in Expo `extra`, source code, native resources or release artifacts.

## Declared native security baseline (verification remains gated)

- ATS arbitrary loads are disabled.
- Authentication tokens use Expo SecureStore (Keychain on iOS).
- Face ID has an explicit purpose string.
- Only remote-notification background mode is declared; background work must
  remain server-authoritative.
- Generated permissions are Face ID and remote notifications. CNG currently
  generates the development APNs entitlement; distribution entitlement remains
  unverified.
- No Universal Link authorization flow is enabled. Expo generates the
  `com.cypher65.warroom` URL scheme; it must not authorize a resource and remains
  unverified until malformed/foreign-tenant link tests exist.
- UI restrictions are never authorization boundaries; tenant, license,
  confirmation, idempotency and commands remain backend decisions.

## Signing and release

Simulator builds do not require Apple distribution credentials. Archive export,
IPA and TestFlight require a valid Team ID, Apple Distribution certificate,
provisioning profile and App Store Connect authorization. These must be supplied
outside the repository and are never fabricated or committed.
