# Testing

The tests exercise the real game code. They do not reimplement A*, utility
scoring, behaviour trees, the FSM or map generation in the test assembly, and
they do not assert against hand-written copies of production constants.

## Test assemblies

| Assembly | Location | Runs in |
| --- | --- | --- |
| `Orchard.Tests.EditMode` | `Assets/Orchard/Tests/EditMode/` | Unity EditMode |
| `Orchard.Tests.PlayMode` | `Assets/Orchard/Tests/PlayMode/` | Unity PlayMode |

Both reference `Orchard.Runtime` and `nunit.framework`, are marked
`autoReferenced: false`, and use `UNITY_INCLUDE_TESTS`. The EditMode assembly is
editor-only; the PlayMode assembly is included in test players.

## What is covered

### A* and navigation — `AStarTests`

- shortest path on open ground, start equals goal, already-in-goal,
- walls, unreachable goals and out-of-board start/goal,
- mud weights: detour when cheaper, straight through when still cheaper,
- no diagonal corner cutting,
- `FindPathToAny` chooses the cheapest goal, not the nearest straight-line goal,
- bushes/logs/hills are avoided,
- path smoothing keeps a straight route and never cuts through walls,
- line-of-sight is blocked by hills only,
- walkable lines reject bushes/logs/hills but not mud,
- steering slots, separation and hill blocking.

### Shambler utility AI — `ShamblerUtilityTests`

- response curves, clamping and compensation factors,
- every action produces finite, bounded scores,
- raid/flee/retaliate choices from real world state,
- pack attacks require a committed partner and count only other shamblers,
- dog health reads the real Pip/Thistle health,
- eating heals and consumes bait, with a fallback when bait disappears,
- tree chewing damage per second,
- whirl gating by night, partner, bird signal, health and cooldown,
- two circling shamblers form exactly one tornado and both rest,
- bad and confused birds do not trigger whirl.

### Pip behaviour tree — `PipBehaviourTreeTests`

- selector/sequence semantics, empty children and tick stopping,
- weakest-tree selection, dead-tree filtering and repair commitment,
- real repair then target release,
- follow behaviour and one-cell stop distance,
- retreat at low health, abandon repair, hysteresis recovery,
- healing only outside retreat and clamped health.

### Thistle FSM — `ThistleFSMTests`

- starts wandering,
- enters feeding within six cells and leaves beyond 7.5 cells,
- hysteresis band keeps feeding,
- prefers an enemy chewing a tree,
- leaves when the target dies,
- flees at 2 HP toward the farmer and recovers at 4 HP,
- stalker melee and retaliation, no retaliation from shamblers,
- attack range, birds ignored, clamped health,
- wandering stays on the board.

### Procedural map generation — `MapGeneratorTests`

- same seed produces identical static and night terrain,
- different seeds produce different maps,
- six living trees inside the safe area,
- every tree reachable and every board side open,
- centre clear of hills, bushes and mud,
- night terrain keeps static hills/bushes and adds mud on grass,
- fallen logs have a valid two-cell footprint away from trees and the centre,
- the map remains valid after every night.

### Gameplay rules — `GameplayTests`

- start builds the map and starts night one,
- night one keeps exactly five ambient scatterlings,
- tree/farmer/hazard reset between nights,
- wave size scales with the night and spawn times are sorted,
- night advance, final-night win, all-trees-dead loss,
- night end conditions and grace period,
- restart resets counters,
- catch range, scythe cone, fruit plucking, pre-night no-ops,
- flying fruit becomes bait, good/bad birds score correctly,
- dizzy scatterlings cannot eat,
- farmer down ends the run,
- pack bites need two committed shamblers,
- stalker bite and cooldown, farmer invulnerability, clamped health,
- tree damage and fruit floor,
- tornado confusion and expiry,
- edge-cell selection, actor placement, log throttling.

### Deterministic regression — `RegressionTests`

- a fixed seed sweep through static and night map generation, checking tree
  reachability, open sides and the log limit,
- a 240-step real `UpdateGame` simulation run twice with the same seed and
  compared bit-for-bit: positions, health, states, tree health, enemy list,
  tornado/bird counters and the next random value.

The normal pull request run uses 8 seeds. The nightly workflow sets
`ORCHARD_REGRESSION=1`, which expands the sweep to 32 seeds.

### PlayMode smoke — `GameplaySmokeTests`

Boots the real game from an empty scene through `OrchardBoot`, waits for the
player loop, and asserts:

- exactly one `OrchardGame` exists,
- the procedural map, farmer, Pip and Thistle exist,
- the title card is showing and no enemies have spawned,
- both cameras exist; the board camera is orthographic, identity-rotated,
  positioned at `(528, -352, -10)`, orthographic size 352 and rendering to a
  `RenderTexture`,
- `StartClicked` starts night one with five scatterlings and a seven-entry
  spawn queue,
- the night clock advances and the first wave actually spawns,
- no exception or error log occurs during the run.

## Determinism

Production uses an unseeded `System.Random`, so the shipped game is unchanged.
Tests call:

```csharp
U.SetSeed(seed);      // deterministic sequence
U.ResetRandom();      // back to the default unseeded generator
```

`TestWorld` builds a real `OrchardGame`, assigns `OrchardGame.I`, and destroys
the host in `Dispose`. Private methods (`StartNight`, `BuildWave`, `EndNight`,
`UpdateGame`, `PackBites`, `UpdateTornados`, `EdgePos`) are reached through a
small reflection helper rather than by widening production accessibility.

## Running locally

### Unity Test Runner

1. Open the project with the editor version in
   `ProjectSettings/ProjectVersion.txt`.
2. Open **Window > General > Test Runner**.
3. Select **EditMode**, choose **Run All**, and confirm at least 120 tests pass.
4. Select **PlayMode**, choose **Run All**, and confirm the smoke test passes.
5. A skipped or inconclusive test is a failure for CI purposes.

### Command line

Use the matching editor binary for your platform. On macOS:

```bash
UNITY="/Applications/Unity/Hub/Editor/<editor-version>/Unity.app/Contents/MacOS/Unity"

"$UNITY" -batchmode -nographics -projectPath . \
  -runTests -testPlatform EditMode \
  -testResults TestResults/EditMode.xml \
  -logFile -

"$UNITY" -batchmode -projectPath . \
  -runTests -testPlatform PlayMode \
  -testResults TestResults/PlayMode.xml \
  -logFile -
```

PlayMode needs a graphics device in some environments; do not add
`-nographics` if the smoke test cannot create the cameras.

Parse the result exactly as CI does:

```bash
python3 scripts/test_summary.py \
  --results-dir TestResults \
  --label EditMode \
  --min-tests 120 \
  --require-namespace Orchard.Tests
```

The parser fails on:

- any failed or errored case,
- any skipped/inconclusive case,
- a missing or malformed XML file,
- fewer tests than the minimum,
- no case from `Orchard.Tests`,
- an unknown result value.

## What the tests do not cover

- Pixel-perfect visual output, colour, sprite appearance or UI layout.
- Audio, feel, difficulty tuning or fun.
- GPU/WebGL runtime behaviour in a browser. The WebGL build is verified
  structurally, not played in CI.
- Long-run balance or performance. The regression simulation is a fixed
  8-second window, not a full night.
- Unity editor UI menu items.

These are manual checks for the release engineer.

## Pre-existing contract deviations

`scripts/csharp_analysis.py` treats these as known and does not fail on them:

- `KeyCode.F` and `KeyCode.KeypadEnter`,
- `OnGUI` mouse forwarding for the legacy UI,
- `Resources.Load` for the raw sprite bytes.

They are listed with reasons in `.github/csharp-baseline.json`. The tests do not
change or "fix" them, because that would alter gameplay, controls or visuals.
New violations fail CI.

## Current execution status

Recorded on 2026-11-17.

The suite was executed and verified directly using the project's exact pinned Unity **6000.3.25f1 (Apple Silicon)** editor on macOS.

| Run | Editor | Result | NUnit XML |
| --- | --- | --- | --- |
| EditMode | 6000.3.25f1 | **128 / 128 passed**, 0 failed, 0 skipped | `TestResults/EditMode/results.xml` |
| PlayMode | 6000.3.25f1 | **1 / 1 passed**, boot + night one | `TestResults/PlayMode/results.xml` |

Both XML files were parsed and validated by `scripts/test_summary.py` with the exact flags CI uses (`--min-tests 120` for EditMode, `--min-tests 1` for PlayMode).

The first attempt reported **0 tests** because 14 generated `.meta` files
contained doubled braces (`externalObjects: {{}}`, `icon: {{instanceID: 0}}`).
Unity silently ignored those assets. The metas were corrected and are validated
by `scripts/validate_repository.py`; an empty discovery is therefore treated as
a failure, not a pass.

The authoritative run on the exact pinned editor still has to come from the CI
`Unity EditMode tests` and `Unity PlayMode tests` jobs. Do not report an
exact-version pass until those jobs upload accepted NUnit XML. A newer editor
can pass locally while the pinned image differs; the CI result is the release
gate.
