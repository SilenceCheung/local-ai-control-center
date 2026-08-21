# Distribution Strategy

## Decision

Local AI uses two deliberately separate distribution tracks. They must not share entitlement files or release gates.

### Track A — Developer ID production build

This is the shipping product for the current architecture.

- Bundle ID: `com.localai.controlcenter.app`
- Hardened Runtime: required
- Developer ID Application signature: required
- Apple notarization and stapling: required
- App Sandbox: intentionally disabled
- Runtime model loading, `launchctl`, the selected model library, and the project/runtime directory remain supported
- Production command: `RELEASE_BUILD=1 bash scripts/build_app.sh`
- Acceptance gate: `bash scripts/release_check.sh`

Normal `bash scripts/build_app.sh` remains a development build and may be ad-hoc signed. It must never be described as a production release.

### Track B — Mac App Store architecture branch

The App Store edition is a separate product architecture, not an entitlement toggle on Track A.

Required boundaries before implementation:

1. Create a dedicated Xcode app target and bundle identifier.
2. Enable App Sandbox only in the App Store target.
3. Bundle the runtime and approved helper executables inside the app package.
4. Replace user LaunchAgents with `SMAppService` and a bundled helper/agent.
5. Replace arbitrary project/model paths with user-selected security-scoped bookmarks.
6. Keep network access limited to declared client/server entitlements.
7. Remove the dependency on the repository checkout and external `.venv`.
8. Regenerate the privacy manifest from the code actually bundled in this target.
9. Add a separate archive, validation, TestFlight/internal testing, and App Review checklist.
10. Confirm that model acquisition and runtime behavior comply with App Review rule 2.5.2 before submission.

## Non-negotiable isolation

- Never add `com.apple.security.app-sandbox` to `LocalAI.entitlements` used by Track A.
- Never reuse Track A's launchd installation path inside the App Store target.
- Never claim App Store readiness until the sandbox target runs without the repository checkout, external Python environment, or user LaunchAgents.
- Shared SwiftUI views and API models are allowed; process supervision, filesystem access, signing, entitlements, and packaging must remain target-specific.

## Production evidence

Every Track A release record must include:

- version and build number
- `codesign --verify --deep --strict` result
- Developer ID authority and Hardened Runtime flags
- notarization submission ID and accepted status
- `stapler validate` result
- Gatekeeper assessment from a Mac with assessments enabled
- clean-launch smoke test and runtime start/stop smoke test
- Light/Dark and minimum-window UI screenshots
