# iOS release gates 062–077

Last reviewed: 2026-08-31. `PASS` requires reproducible evidence; configuration
or JavaScript export alone is not a native release.

| Gate | State | Current evidence / remaining work |
|---|---|---|
| 062 Architecture | PASS | `IOS_ARCHITECTURE.md`, Expo CNG and four environments documented. |
| 063 Xcode build | FAIL | macOS workflow added; requires first green native run. |
| 064 Simulator install | FAIL | Workflow now installs; no completed CI evidence yet. |
| 065 iOS launch | FAIL | Workflow now launches/screenshots; no completed CI evidence yet. |
| 066 Human E2E | FAIL | Human/native journey is not implemented. |
| 067 Lifecycle | FAIL | Background/foreground/termination matrix not implemented. |
| 068 Networking | FAIL | Latency, packet loss, DNS and recovery matrix not implemented. |
| 069 Security | FAIL | ATS is declared; native artifact/Keychain/entitlement audit remains. |
| 070 No secrets | FAIL | Heuristic `.app` scan is defense-in-depth, not full extraction certification. |
| 071 Digital Twin | FAIL | iOS installed-app journey is absent on this branch. |
| 072 Rentals | FAIL | No installed-app E2E. |
| 073 Device Control | FAIL | No installed-app E2E; ACK must remain distinct from VERIFIED. |
| 074 Performance | FAIL | Cold/warm start and 10/100/500/1000 fleet measurements absent. |
| 075 Archive | FAIL | Archive configuration has not been exercised. |
| 076 IPA | BLOCKED_EXTERNAL | Apple signing certificate/profile/Team ID required. |
| 077 TestFlight | BLOCKED_EXTERNAL | App Store Connect authorization required. |

Do not release publicly until all non-external gates pass and the external gates
have operator-owned evidence.
