# Orchard of the Last Season

[![CI](https://github.com/stageor/orchard-of-the-last-season/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/stageor/orchard-of-the-last-season/actions/workflows/ci.yml)
[![Security](https://github.com/stageor/orchard-of-the-last-season/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/stageor/orchard-of-the-last-season/actions/workflows/security.yml)
[![Nightly regression](https://github.com/stageor/orchard-of-the-last-season/actions/workflows/nightly-regression.yml/badge.svg?branch=main)](https://github.com/stageor/orchard-of-the-last-season/actions/workflows/nightly-regression.yml)

## CI, tests and releases

- **Tests:** real Unity EditMode coverage for A*, Shambler utility AI, Pip's
  behaviour tree, Thistle's FSM, map generation and gameplay, plus a PlayMode
  bootstrap smoke test. See [`docs/TESTING.md`](docs/TESTING.md).
- **Required checks:** `Required checks` aggregates repository health, C# contract
  analysis, EditMode, PlayMode, Windows x64 and WebGL. A failed, cancelled or
  unexpectedly skipped mandatory job blocks the merge. See
  [`docs/CI_CD.md`](docs/CI_CD.md).
- **Review policy:** Stanley, Zian and Manu. A member-authored PR needs the other
  two approvals and an author `/signoff <head-sha>`; an external PR needs all
  three. See [`docs/APPROVAL_POLICY.md`](docs/APPROVAL_POLICY.md).
- **Builds:** download `orchard-windows-x64` or `orchard-webgl` from the CI run's
  **Artifacts** section, or from **Releases** for tagged versions. WebGL
  compression is Disabled so the build runs from any static host. See
  [`docs/BUILD_AND_RELEASE.md`](docs/BUILD_AND_RELEASE.md).
- **Unity version:** CI reads the exact editor version from
  `ProjectSettings/ProjectVersion.txt`. Do not silently upgrade it.
- **Contributing and security:** [`CONTRIBUTING.md`](CONTRIBUTING.md) and
  [`SECURITY.md`](SECURITY.md).

## How to open and play
1. Unzip this folder anywhere.
2. Open Unity Hub, click Add, then "Add project from disk", and select the
   `OrchardOfTheLastSeason` folder.
3. Open it with Unity 6000.3.25f1 (any Unity 6 version works for local play; CI
   uses the exact version in `ProjectSettings/ProjectVersion.txt`).
4. Press Play. No scene setup is needed: the game builds itself in whatever scene is open.

## Sharp picture (no blur)
The board is rendered at exactly the pixels it covers on screen, and the pixel-art sprites use
hard pixel edges. In the Game view also make sure Unity itself is not scaling the picture:
- open the aspect dropdown (says "Free Aspect") and UNTICK "Low Resolution Aspect Ratios" (Mac Retina)
- pick "Full HD (1920x1080)" and drag the Scale slider all the way left (smallest value), or use Play Maximized

## Sharp picture (important on a Mac)
The board is drawn at your screen's real resolution, so it is crisp at any size. What makes it blurry
is Unity's Game view option "Low Resolution Aspect Ratios" (it shows as "Scale 2x" on Retina screens:
the game is drawn at half resolution and zoomed). The project turns it off for you on open and on
Play (menu Orchard > Make Game View Sharp does it again). If it is still on: Game view aspect menu
(the "Free Aspect" dropdown) > untick "Low Resolution Aspect Ratios", then drag Scale fully left (1x).

## Recording a 16:9 video
The game is laid out for exactly 16:9: a slim sidebar of 188 px (15%) plus the landscape board
(1064 x 704, 85%; 24 x 16 cells) make 1252 x 704, so it fills a 1920 x 1080 frame edge to edge.
1. In the Game view, open the resolution dropdown (top left, "Free Aspect") and pick
   "Full HD (1920x1080)" (or add it with + as a Fixed Resolution 1920 x 1080).
2. Set the Game view to "Play Maximized" (or "Play Focused" then maximise the tab with Shift+Space).
3. Press Play and record the screen (e.g. Cmd+Shift+5 on a Mac), or use Unity's free Recorder
   package (Window > Package Manager > Unity Registry > Recorder), Movie output, 1920 x 1080, 60 fps.

## AI-focus build
Kept on purpose because they show the AI working: mud (A* weights), fallen logs (A* re-plans),
shambler intent bubbles and Tab bars, Stalker sight ring, Pip's repair line, pack lines, sidebar chips and log.
- Tested on 300 random maps: no tree within 2 cells of an edge, no tree cut off, 5 logs every night.
<img width="2940" height="1912" alt="image" src="https://github.com/user-attachments/assets/cb6ae03c-d8fd-463f-a383-3d7df0d7d474" />

<img width="2920" height="1636" alt="image" src="https://github.com/user-attachments/assets/ad04aad3-e8e1-4a98-90b3-24c989426ae8" />


## Scatterlings
- A scatterling caught by a bad bird is gone for good: next night only the survivors fly.
  Protect them by hitting bad birds with the scythe; they also dodge bad birds by themselves
  (predator avoidance), and a bad bird rests 10 s after a catch.
- Removed in this build: tree revival (200 fruit), farmer knockback/daze, the sunrise scene.
  Between nights you just see a plain "Night N" card. The 4th sidebar card now counts tornados.

## Shambler: utility AI (desirability)
Before, the Shambler only walked to the nearest tree (A to B). Now every 0.25 s it scores how much it
WANTS each option (0 to 1) and does the best one. Each score multiplies a few considerations, with a
compensation factor so options with more considerations are not unfairly punished. The option it is
already doing gets +0.12 so it does not flip-flop.

| Option | What it does | Considerations |
|---|---|---|
| Raid tree | walk to a tree and gnaw it | distance, how weak the tree is, is it guarded (farmer or Thistle near), my health |
| Eat fruit | eat a fallen fruit, heals +3 hp | distance, how hurt I am, is it safe |
| Pack a dog | gang up on Pip or Thistle | can I see the dog, distance, how many shamblers are already on it (0, 1, 2+), can another join me, is the dog in our way (Pip repairing my tree, Thistle biting us), dog weakness, my health |
| Hit farmer | grudge swipe at the farmer (log only, no knockback) | did he hit me in the last 2 s, how close he is, my health |
| Flee | run to the safest reachable spot (A*), heal slowly | how hurt I am, how close danger is |
| Whirl (from night 2) | 2+ Shamblers walk in a circle together; after 1.4 s a dust tornado rises | yellow birds right above me or flying on a line that crosses mine (or seen further off, weaker), a partner Shambler within 6 cells or one already circling, no tornado already out, my health |

Rules that tie it to the other characters:
- A dog only takes damage while 2 or more Shamblers bite it at the same time (pack rule). One alone does nothing.
- Shamblers only know about dogs, the farmer and other Shamblers they can SEE (7 cells, no hill in the way).
  They read each other's current choice, so one that sees another already on a dog comes to help.
- Pip's behaviour tree has a new top branch: when a pack has hurt him he runs to the farmer to recover,
  so trees stop being repaired until you rescue him.
- Thistle is only hurt one-on-one by Stalkers; Shamblers must pack her. A pack can push her into Flee.

What it looks like in play: a bubble over each Shambler shows its choice (green tree = raid,
orange apple = eat, amber paw = pack, red ! = hit farmer, blue drop = flee, spinning swirl = whirl). Amber dotted lines join a
pack to its dog and a red ring shows when 2+ are biting. Press Tab to show six bars over each Shambler:
how much it wants each option right now (the chosen one is underlined).

Measured over 8 seeded games with the same scripted player: Shamblers spend about 85% of their time
raiding, 9% hunting dogs in packs, 7% fleeing; about 13 packs form and 33 retreats happen per game, and
difficulty stayed level (scripted player reaches night 11.6, before 10.8). Numbers to tune are at the
top of each option in ShamblerUtilityAI.cs.

## Shamblers' dust tornado (team move against the scatterlings)
From night 2 the Shambler utility AI has a sixth option, **Whirl**. When two Shamblers are close together
and yellow birds are right above them, or flying on a path that will cross theirs, whirling becomes the
most desirable thing to do:
- One Shambler picks a centre between itself and a partner. The partner reads that choice (like pack
  attacks) and joins. Both walk round the same circle, the same way round. A dust ring on the ground
  grows as they spin up.
- After 1.4 s of 2+ Shamblers circling, a **dust tornado** forms (5 s). It drifts slowly toward the
  nearest yellow bird it has not caught yet.
- A yellow bird that flies into it becomes **dizzy for 5 s** (crossed apple over its head, it spins round
  the tornado and dodges black birds badly) and **cannot eat fruit for 10 s** (small crossed-out apple).
  Black birds are not affected.
- Only one tornado at a time. Each Shambler rests 16 s after making one (6 s if no partner came), and a
  started circle gets a bigger commitment bonus (+0.2) so they finish it unless hurt.
- You can break it up: hit a circling Shambler and it may flee instead, and the tornado never forms.
- The sidebar Shambler chip shows "2 whirling" / "Tornado!", and the log says
  "Shamblers spun a dust tornado!" and "N scatterlings dizzy: no fruit for 10s".

Tuning numbers are in Core.cs (WHIRL_SPIN, TORNADO_LIFE, CONFUSE_T, NO_EAT_T, WHIRL_COOLDOWN).
In tests a tornado forms about once a night while yellow birds are still alive. Once the black birds
have caught all the yellow birds there is nothing to confuse, so the Shamblers stop whirling.
