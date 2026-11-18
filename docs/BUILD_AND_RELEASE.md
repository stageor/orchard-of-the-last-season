# Build and release

Both players are built from the same commit with the exact Unity editor version
in `ProjectSettings/ProjectVersion.txt`. The build entry points live in
`Assets/Orchard/Editor/CI/OrchardBuild.cs` and never modify the project's Unity
version.

## Outputs

| Target | Build method | Output | Artifact |
| --- | --- | --- | --- |
| Windows x64 | `Orchard.CI.OrchardBuild.BuildWindows` | `Build/Windows/OrchardOfTheLastSeason.exe` | `orchard-windows-x64` |
| WebGL | `Orchard.CI.OrchardBuild.BuildWebGL` | `Build/WebGL/index.html` | `orchard-webgl` |

Each build writes `BUILD_INFO.txt` into its output directory with:

```text
product=OrchardOfTheLastSeason
version=1.0
unityVersion=<exact editor version>
target=StandaloneWindows64|WebGL
commit=<git commit>
repository=<owner/repo>
workflowRun=<run id>
builtAtUtc=<timestamp>
sizeBytes=<reported build size>
totalErrors=0
totalWarnings=<count>
webglCompression=Disabled        # WebGL only
```

The file is generated inside the artifact and is never committed.

## Local builds

Use the editor binary that matches `ProjectVersion.txt`. On macOS:

```bash
UNITY="/Applications/Unity/Hub/Editor/<editor-version>/Unity.app/Contents/MacOS/Unity"

"$UNITY" -batchmode -quit -projectPath . \
  -executeMethod Orchard.CI.OrchardBuild.BuildWindows \
  -logFile -

"$UNITY" -batchmode -quit -projectPath . \
  -executeMethod Orchard.CI.OrchardBuild.BuildWebGL \
  -logFile -
```

You can also use **Orchard > CI > Build Windows x64** or **Build WebGL** in the
editor.

Local builds record `commit=local` unless `GITHUB_SHA` is set. Verify a local
build with:

```bash
python3 scripts/verify_build.py --target windows --root Build/Windows --min-size 1
python3 scripts/verify_build.py --target webgl --root Build/WebGL --min-size 1
```

The verifier checks the PE/WebAssembly signature, required engine files, the
generated scene data, the exact editor version against `ProjectVersion.txt`, the
commit when one is supplied, and disabled WebGL compression (including the
absence of `.gz`, `.br`, `.unityweb` and `.zip` payloads).

## Downloading CI builds

1. Open **Actions > CI**.
2. Open the run for the commit you want.
3. Scroll to **Artifacts**.
4. Download `orchard-windows-x64` or `orchard-webgl`.
5. Unzip it. The folder already contains `BUILD_INFO.txt`.

Pull request builds are retained for 14 days. Nightly artifacts are retained for
7–30 days depending on type. Release artifacts are attached to the GitHub
Release permanently.

## Running the Windows build

1. Unzip `orchard-windows-x64.zip` (or the CI artifact).
2. Keep `OrchardOfTheLastSeason.exe`, `UnityPlayer.dll` and the
   `OrchardOfTheLastSeason_Data` folder together.
3. Run `OrchardOfTheLastSeason.exe`.
4. If Windows reports a missing Visual C++ runtime, install the current
   Microsoft Visual C++ Redistributable (x64).

The game is keyboard-only. The controls are documented in the repository
`README.md`.

## Running the WebGL build

The project contract requires **WebGL compression: Disabled**, so the build can
be served by any static host without special `Content-Encoding` headers.

Local check:

```bash
cd Build/WebGL
python3 -m http.server 8000
```

Then open <http://localhost:8000>. Do not open `index.html` with a `file://`
URL; browsers block the required fetches.

For a hosted deployment, upload the entire contents of `Build/WebGL` (not the
parent folder) to any static host. Confirm that:

- `index.html` is the entry point,
- `Build/*.wasm` is served as `application/wasm` (most hosts do this),
- there are no `.gz`, `.br` or `.unityweb` files,
- the host serves the files with their real names.

If your host automatically compresses responses with gzip or Brotli, that is a
transport setting, not the Unity build setting. The Unity build itself remains
uncompressed, which is what the contract and the verifier require.

## Release process

Only release from `main` after the commit's `Required checks` run is green.

1. Update `CHANGELOG.md` and merge it through the normal three-person policy.
2. Confirm the exact commit on `main` is green.
3. Create an annotated semantic-version tag:

   ```bash
   git checkout main
   git pull --ff-only
   git tag -a v1.2.3 -m "Orchard of the Last Season v1.2.3"
   git push origin v1.2.3
   ```

4. The **Release** workflow rebuilds Windows and WebGL from that tag, re-verifies
   both artifacts, creates `orchard-windows-x64.zip`,
   `orchard-webgl.zip` and `SHA256SUMS.txt`, and publishes a GitHub Release.
5. Download the assets from **Releases** and verify the checksums:

   ```bash
   shasum -a 256 -c SHA256SUMS.txt
   ```

6. If the release fails, fix the problem on `main`, delete the failed tag and
   release, and tag the fixed commit. Never move a tag that users may already
   have downloaded.

The release workflow refuses a tag that is not an ancestor of `main` and refuses
a tag that is not semantic (`vMAJOR.MINOR.PATCH` with an optional pre-release
suffix). Pre-release tags such as `v1.2.3-rc.1` are published as pre-releases.

## Why builds are not committed

`Build/`, `Builds/`, `artifacts/`, `.zip`, `.exe`, `.wasm`, `.data` and
`.unitypackage` are ignored. Binary artifacts belong in Actions artifacts and
GitHub Releases, not in Git history. This keeps clones small, avoids stale
players, and prevents an unreviewed binary from bypassing source review.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Build directory does not exist` | The build method failed or wrote somewhere else. Read the Unity log artifact. |
| `Build used Unity X, but ProjectVersion.txt says Y` | The editor image or local editor does not match the pinned version. Do not change the project version to silence it. |
| `Missing OrchardOfTheLastSeason.exe` | The product name or Windows build method changed. Confirm `productName` and `OrchardBuild.WindowsOutput`. |
| `not a PE executable` | The artifact is incomplete or was replaced by an LFS pointer. Check out with LFS disabled and rebuild. |
| `Missing .../level0` | No enabled scene was included. Confirm `EditorBuildSettings.asset` references `Bootstrap.unity`. |
| `Compressed or packaged WebGL artifacts are not allowed` | Unity compression is enabled or a zip was placed inside the build folder. Set `webGLCompressionFormat: 2` and rebuild. |
| `BUILD_INFO webglCompression is 'Gzip'` | The WebGL setting changed. `OrchardBuild` forces Disabled for the build, but the project setting should also stay at 2. |
| PlayMode smoke test cannot create cameras | Re-run without `-nographics`; PlayMode needs a graphics device. |
| Release refuses the tag | The tag is not on `main` or is not semantic. Tag the correct commit with `vMAJOR.MINOR.PATCH`. |

For the CI job layout and required checks, see [`CI_CD.md`](CI_CD.md).
