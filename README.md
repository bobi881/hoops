# hoops

**The world's most realistic basketball simulator.** Text-based, data-driven, mod-friendly.
Architected so the depth of a simulation like 2K can be reached by modeling what happens
between the ears (psychology, fatigue, chemistry, coaching IQ, player identity)
instead of grinding on physics.

> Status: **pre-alpha / playable prototype.** The full seven-phase architecture in
> [`plans/basketball-simulator-architecture-plan.md`](plans/basketball-simulator-architecture-plan.md)
> has scaffolding in place and most subsystems are wired end-to-end, but balance,
> content breadth, and a few correctness bugs still need work before this plays a
> believable game of basketball. See [Status](#status) below for the honest accounting.

---

## Table of contents

- [What this is](#what-this-is)
- [Quick start](#quick-start)
- [How it works (architecture)](#how-it-works-architecture)
- [Repository layout](#repository-layout)
- [Status](#status)
  - [What's finished](#whats-finished)
  - [What's partial](#whats-partial)
  - [What's not started](#whats-not-started)
  - [Known bugs and sharp edges](#known-bugs-and-sharp-edges)
- [Running tests](#running-tests)
- [Roadmap](#roadmap)
- [Design principles](#design-principles)
- [Contributing](#contributing)

---

## What this is

A pure-Python basketball simulation engine. No game loop ticks, no physics sim.
The game advances one *action* at a time (a dribble move, a pass, a shot, a drive)
and every action flows through:

```
Player identity + mental state + fatigue + chemistry + coaching + history + situation
        |
        v
   Modifier Pipeline  ->  State Resolver  ->  Events  ->  Event Bus
                                                             |
                                        +--------------------+--------------------+
                                        |                    |                    |
                                  Narration            Stats Tracker         Future 2D
                                  Pipeline             (box scores)          renderer
```

The matchup between an offensive player and their defender is tracked on **five
independent state machines** (positioning, balance, stance, rhythm, help defense)
plus an accumulating set of **tags** (`crossover`, `ankle_breaker`, `hesitation`, ...).
Tags drive narration directly and are the hook points badges and modifiers
subscribe to. The full matchup/axis/tag design lives in the architecture plan,
section ["Matchup System"](plans/basketball-simulator-architecture-plan.md).

The court is a **7 x 9 chess-style grid** (63 cells) with per-cell basketball
metadata (is_three, corner_three, in_paint, distance_to_basket, etc.). This keeps
spatial reasoning simple and maps cleanly onto 2D sprite tiles whenever a graphical
renderer is added.

---

## Quick start

Requires Python 3.11+.

```bash
# Install in editable mode (optional but recommended)
pip install -e .[dev]

# Simulate a full game with default teams and seed
python -m basketball_sim

# Reproducible run, shorter game, no play-by-play
python -m basketball_sim --seed 42 --quarters 2 --quiet

# One-minute sanity check
python -m basketball_sim --quarters 1 --quarter-length 60
```

CLI flags (see [`basketball_sim/__main__.py`](basketball_sim/__main__.py:200)):

| Flag | Default | Meaning |
|---|---|---|
| `--seed` | `42` | RNG seed (games are fully reproducible from a seed) |
| `--quarters` | `4` | Number of quarters to simulate |
| `--quarter-length` | `720.0` | Seconds per quarter (NBA is 720 = 12 min) |
| `--quiet` | off | Suppress play-by-play narration, box score only |
| `-v` / `--verbose` | off | Debug logging |

You'll see live play-by-play lines like:

```
Q1 11:47 | Marcus Cole sizes up... crossover, Reed is TRAILING!
Q1 11:45 | Cole attacks downhill...
```

followed by per-team box scores and engine timing stats at the end.

---

## How it works (architecture)

Five ideas you need in your head to read the code:

**1. Event bus is the backbone.** Everything that happens is an event
([`basketball_sim/core/event_bus.py`](basketball_sim/core/event_bus.py:1)). Narration,
stats, and future renderers all *subscribe*. No module imports another module's internals.

**2. Modifier pipeline is additive and order-independent.** Each realism layer
(fatigue, psychology, chemistry, coaching, history, tendencies, situational) is one
function in [`basketball_sim/modifiers/`](basketball_sim/modifiers/) that takes an
`ActionContext` and returns a `Modifier`. The pipeline sums them into an
`AggregatedModifier` and hands it to the resolver. Adding a new realism layer = adding
one file and calling `pipeline.register(...)`. The math is in
[`basketball_sim/core/pipeline.py`](basketball_sim/core/pipeline.py:1).

**3. State resolvers do the dice roll.** Per-action resolvers live in
[`basketball_sim/resolvers/`](basketball_sim/resolvers/) (`dribble.py`, `shoot.py`,
`pass_action.py`, `rebound.py`). They read the base transition probabilities from
the move's JSON, apply the aggregated modifier, redistribute probability between
"favorable" and "unfavorable" states, roll, generate tags, and emit events. The core
probability redistribution math is in
[`basketball_sim/resolvers/transitions.py`](basketball_sim/resolvers/transitions.py:1).

**4. Data over code.** Dribble moves, badges, plays, defensive schemes, rules, and
announcer templates are JSON in [`basketball_sim/data/`](basketball_sim/data/).
Loaded once at startup by [`basketball_sim/data/loader.py`](basketball_sim/data/loader.py:1).
Rulebooks for NBA, NCAA, and FIBA already ship.

**5. Narration is a 4-stage pipeline.** `aggregator -> enricher -> templates -> renderer`
in [`basketball_sim/narration/`](basketball_sim/narration/). Events get grouped into
narrative beats, tagged with excitement, matched against templates keyed by tag
combinations, and rendered with announcer personality.

The **mod system** ([`basketball_sim/core/mod_loader.py`](basketball_sim/core/mod_loader.py:1))
auto-discovers folders under `mods/`, loads their JSON into registries, and imports
Python modifier files. No existing code needs to change to add content. The `mods/`
directory doesn't exist in-repo yet; the loader is ready but untested against real mods.

---

## Repository layout

```
basketball_sim/
  __main__.py              Entry point: builds sample teams, wires everything, runs a game
  core/
    engine.py              Game loop (quarter -> possession -> action), abstract interfaces
    event_bus.py           Pub/sub with subscribe / subscribe_all
    pipeline.py            ModifierPipeline, AggregatedModifier combination
    types.py               All dataclasses and enums (Player, MatchupState, Events, etc.)
    grid.py                7x9 court grid with cell metadata and Manhattan distance
    mod_loader.py          Auto-discovers mods/ folder, loads JSON + Python modifiers
  resolvers/
    composite.py           Routes actions to the right resolver, runs pipeline
    dribble.py             Multi-axis state transitions for dribble moves
    shoot.py               Shot resolution with contest / openness / hot-zone logic
    pass_action.py         Pass with grid-based passing-lane interception
    rebound.py             Rebound resolution
    transitions.py         Shared probability redistribution math
  modifiers/
    fatigue.py             Cardio + muscular + mental + accumulated fatigue
    psychology.py          Confidence, frustration, focus, momentum, intimidation
    chemistry.py           Pairwise chemistry, trust, system fit
    coaching.py            Scheme adjustments, matchup hunting
    history.py             This-game scouting (defender remembers your tendencies)
    tendencies.py          Player-specific habits (ISO frequency, drive direction, etc.)
    situational.py         Clutch, home court, crowd energy, score differential
  narration/
    aggregator.py          Groups raw events into narrative beats
    enricher.py            Adds excitement level, momentum, streak context to a beat
    templates.py           Template selector keyed by tag combinations
    renderer.py            Fills templates with player names + announcer personality
    stats_tracker.py       Subscribes to events, builds box scores
  ai/
    offensive_ai.py        Ball handler utility scoring + weighted pick
    defensive_ai.py        Reactive coverage logic
    coach_ai.py            Rotations, timeouts, scheme adjustments (module scaffolding)
  data/
    moves/dribble_moves.json         45 dribble moves
    badges/badges.json               80 badges
    plays/plays.json                 10 offensive sets
    schemes/defensive_schemes.json   10 defensive schemes
    rules/{nba,ncaa,fiba}_rules.json Rule variants
    narration/announcer_default.json Default announcer profile + templates
tests/
  test_ai.py, test_engine.py, test_event_bus.py, test_grid.py,
  test_modifiers.py, test_narration.py, test_phase6.py,
  test_pipeline.py, test_resolvers.py, test_types.py
plans/
  basketball-simulator-architecture-plan.md   The full design doc. Read this.
pyproject.toml                                Python 3.11+, pytest for dev
```

---

## Status

The architecture plan breaks work into seven phases. Here's where each one stands,
checked against the actual code.

### What's finished

**Phase 1 - Foundation.** Core types, enums, the 7x9 grid with cell metadata,
the pub/sub event bus, and the modifier pipeline skeleton are all in and unit-tested.
The game loop in [`basketball_sim/core/engine.py`](basketball_sim/core/engine.py:216)
runs quarters and possessions, enforces a 30-action-per-possession safety valve,
and tracks per-game engine stats.

**Phase 2 - Action resolution.** Dribble, shot, pass, and rebound resolvers are
implemented. The probability-redistribution math in
[`transitions.py`](basketball_sim/resolvers/transitions.py:1) clamps modifier totals
to +/-0.25 per axis so stacked modifiers can't produce degenerate outcomes. Moves
load from JSON via the data loader. A `CompositeResolver` routes action types to
their resolvers and runs the modifier pipeline for each action.

**Phase 3 - AI decision making (basic).** `BasicOffensiveAI` generates action
candidates (dribble moves, shots, passes, drives, hold-ball) and scores them with
a utility function modulated by `basketball_iq` temperature so lower-IQ players
make worse decisions. `BasicDefensiveAI` emits reactions to offensive actions.

**Phase 4 - Narration pipeline.** All four stages exist and are wired into the
CLI: aggregator groups events into beats, enricher tags excitement, templates are
selected by tag combinations, renderer fills with player names and announcer
style. One default announcer profile ships with a starter set of templates.

**Phase 5 - Realism layers.** All seven modifiers from the plan are implemented
as independent files in [`basketball_sim/modifiers/`](basketball_sim/modifiers/)
and registered by [`__main__.py`](basketball_sim/__main__.py:243).

**Phase 6 - Content and polish (partial).**
- 45 dribble moves (target was 50+)
- 80 badges (target hit)
- 10 plays, 10 defensive schemes
- Rulebooks for NBA, NCAA, FIBA

**Phase 7 - Expansion (partial).**
- Mod loader implementation is done. No real mod has been authored against it yet.
- NCAA and FIBA rule configs load.

### What's partial

- **Stats tracker and final score reporting.** The stats tracker subscribes to
  events and builds box scores, but short games currently finish with obviously
  wrong final totals (0-0 scores even when shots were attempted and an assist
  was credited). Event wiring between the shot resolver, the game state's score
  dict, and the stats tracker needs to be reviewed end-to-end.
- **Coach AI** ([`basketball_sim/ai/coach_ai.py`](basketball_sim/ai/coach_ai.py:47)).
  The `CoachAI` class, `RotationSlot`, and `CoachState` are defined but not yet
  plugged into the game loop for timeouts and substitutions.
- **Announcer profiles.** Only one profile (`announcer_default.json`) ships. The
  plan calls for multiple announcer personalities.
- **Narration template coverage.** Many tag combinations will fall through to
  generic templates or render empty strings. There is no smoke test asserting
  every emitted tag combo has at least one matching template.
- **Off-ball player system.** The data structures for off-ball decisions exist
  conceptually but there is no dedicated off-ball AI module yet; off-ball
  movement is approximated inside the possession loop.
- **Help-and-recover defensive chains.** `BasicDefensiveAI` is reactive but does
  not yet execute the multi-step rotation chains described in the plan.

### What's not started

- **Player rosters as data.** No `data/rosters/` directory. Sample rosters are
  hand-built in [`__main__.py`](basketball_sim/__main__.py:69). The plan calls for
  full NBA rosters shipped as JSON.
- **Mods directory.** The loader is ready; no example mod exists in the repo.
- **Season simulation.** Schedule, standings, playoffs, league mode.
- **Save / load and replay.** State serialization is designed (all dataclasses),
  but no save/load API is exposed yet.
- **Draft system** and **custom league creation** (Phase 7 stretch goals).
- **2D pixel-art renderer** (the architecture's end-state consumer of the event
  bus).

### Known bugs and sharp edges

- **Final score renders 0-0** in the current tip even when shots are attempted
  (see above). The stats format output also has column misalignment in the box
  score.
- **TODOs in engine:**
  - [`basketball_sim/core/engine.py:253`](basketball_sim/core/engine.py:253) -
    overtime logic not implemented, tied games just end.
  - [`basketball_sim/core/engine.py:445`](basketball_sim/core/engine.py:445) -
    offensive-rebound branch is stubbed (`offensive_rebound=False`). Every missed
    shot currently swaps possession.
  - [`basketball_sim/core/engine.py:347`](basketball_sim/core/engine.py:347) -
    fallback path left over from the earlier `StubResolver`.
- **Duplicate first commits** on the git history (`24410cc` and `3d4bc8c` both
  titled "first commit") -- harmless, just noisy.
- **No `mods/` runtime directory.** `ModLoader` points at a path that doesn't
  exist in the repo; this is intentional but worth knowing if you plan to exercise it.

---

## Running tests

```bash
pip install -e .[dev]
pytest
```

The test suite covers every module with unit tests and includes statistical
validation tests (for example, in [`tests/test_resolvers.py`](tests/test_resolvers.py:1))
that run many iterations to verify transition distributions match the JSON data
within tolerance. Phase-6 content tests in
[`tests/test_phase6.py`](tests/test_phase6.py:1) assert minimum move/badge counts
and schema correctness.

Deterministic seeding is enforced throughout: every random draw goes through an
`ActionContext.rng: random.Random` that is seeded per game, so a given seed
produces the same game every time.

---

## Roadmap

Short-term (unblock believable play):

1. Fix the stats-tracker / score wiring so box scores and the final score agree.
2. Implement offensive-rebound branch in the possession loop.
3. Add overtime.
4. Wire `CoachAI` into the game loop for substitutions and timeouts.
5. Template coverage sweep: every emitted tag combo has at least one matching
   template; add a CI smoke test.

Medium-term (content + depth):

6. Ship a real NBA roster as JSON under `data/rosters/`.
7. Author a first example mod under `mods/` to exercise `ModLoader` end-to-end.
8. Expand dribble-move library to 50+ and add post-move and screen resolvers.
9. Implement help-and-recover rotation chains in the defensive AI.
10. Add 2-3 additional announcer profiles.

Long-term (Phase 7):

11. Season simulation: schedule, standings, playoffs.
12. Save / load / replay with RNG-state persistence.
13. Draft + custom-league modes.
14. 2D pixel-art renderer consuming the event bus.

---

## Design principles

(Copied from the [architecture plan](plans/basketball-simulator-architecture-plan.md),
because they constrain every change.)

1. **Event bus as backbone.** No module-to-module coupling.
2. **Modifier pipeline.** Every realism layer is independent; adding depth is
   adding files, not modifying existing code.
3. **Data over code.** Moves, badges, narration, plays, rosters are JSON.
4. **Everything pluggable.** Rules, AI, narration, rendering all implement typed
   interfaces via ABCs.
5. **Mod system.** Auto-discovered from `mods/`. JSON for data, Python for logic.
   Zero existing code modified to add a mod.
6. **Deterministic.** All RNG flows through a seeded `random.Random` in
   `ActionContext`. Same seed, same game, always.

---

## Contributing

1. Read [`plans/basketball-simulator-architecture-plan.md`](plans/basketball-simulator-architecture-plan.md)
   end-to-end first. It's the source of truth for every design decision.
2. Keep new realism layers as new files in
   [`basketball_sim/modifiers/`](basketball_sim/modifiers/). Don't modify existing
   modifiers to achieve a new effect.
3. Prefer data (JSON) over code whenever something is tunable.
4. Every new tag that can be emitted needs at least one narration template.
5. Add tests. Statistical resolvers should include distribution tests; modifiers
   should include neutrality tests (a neutral context returns a neutral modifier).
