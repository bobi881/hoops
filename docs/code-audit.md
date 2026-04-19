# Comprehensive code audit

A line-by-line review of every file in `basketball_sim/`. Grouped by severity and
by module. Every item is either a **bug** (wrong behavior), **dead code**
(defined but not reached), **spec divergence** (differs from
`plans/basketball-simulator-architecture-plan.md`), **design smell**, or a
**smoke-test-level gameplay failure**.

All 163 existing pytest tests pass. Most of the defects below are therefore
**not caught by the current test suite** and only surface when you actually
run the engine end-to-end.

---

## Executive summary

A 4-quarter simulation with the real AI + real resolver (seed 7, default teams)
produces:

| Metric | Observed | Expected (NBA-ish) |
|---|---|---|
| Final score | **10-7** | ~110-110 |
| Shot attempts | **20** | ~190 |
| Shot clock violations | **82** (54% of possessions) | 2-5 |
| REBOUND events | **0** | ~90 |
| BLOCK events | **0** | ~10 |
| PASS_INTERCEPTED events | **0** | (type never emitted) |
| Dribble moves | 1209 | n/a |
| Passes completed | 984 | n/a |

The simulator runs to completion, is deterministic, and every subsystem produces
plausible per-call output, but the integration between subsystems is broken
badly enough that a real game never emerges. See **Gameplay-breaking bugs**
below for the critical chain.

---

## Gameplay-breaking bugs (highest priority)

### 1. `PossessionState.shot_clock` is never updated during a possession

[`basketball_sim/core/engine.py:320-378`](../basketball_sim/core/engine.py:320)
uses a local variable `shot_clock = self.rules.shot_clock` and decrements it in
the loop. It **never writes the new value back to `possession.shot_clock`**. The
field is copied once from `rules.shot_clock` at
[`engine.py:509`](../basketball_sim/core/engine.py:509) and left at 24.0 forever.

This silently disables every subsystem that reads `possession.shot_clock`:

- [`ai/offensive_ai.py`](../basketball_sim/ai/offensive_ai.py:47-56) -
  `if shot_clock <= 4.0: desperate_shot` and `<= 8.0: late_clock_decision`
  branches **never fire**. The AI therefore never forces an end-of-clock shot
  and possessions terminate on 24-second violations.
- [`modifiers/situational.py`](../basketball_sim/modifiers/situational.py) -
  shot-clock-winding tag and penalty **never trigger**.
- Narration templates keyed on `shot_clock_winding` / `shot_clock_low` are dead.

### 2. Engine never calls the rebound resolver

[`engine.py:441-446`](../basketball_sim/core/engine.py:441) hardcodes
`offensive_rebound=False  # TODO: rebound logic`. After every missed shot the
possession flips automatically. [`resolvers/rebound.py`](../basketball_sim/resolvers/rebound.py:19)
is **entirely dead code**. No REBOUND events, no offensive rebounds, no
defensive-rebound stat credit.

### 3. Shot clock violations don't register as turnovers

[`engine.py:379-388`](../basketball_sim/core/engine.py:379) emits
`SHOT_CLOCK_VIOLATION` but not `TURNOVER`. The stats tracker only increments
turnovers on `EventType.TURNOVER`, so 54% of possessions (82 in the test run)
produce neither a shot nor a box-score turnover. The ball handler pays no
statistical price for burning the clock.

### 4. `ball_handler_change` is ignored by the engine

[`resolvers/pass_action.py:126`](../basketball_sim/resolvers/pass_action.py:126)
and [`resolvers/rebound.py:99`](../basketball_sim/resolvers/rebound.py:99) set
`ActionResult.ball_handler_change` but
[`engine.py:358-372`](../basketball_sim/core/engine.py:358) never reads it.
Every pass completion is recorded as a pass but the "new ball handler" stays
on the original passer. All 984 passes in the test run left the ball
conceptually where it started.

### 5. Drives always happen at `D2` regardless of origin

[`resolvers/composite.py:143`](../basketball_sim/resolvers/composite.py:143)
hardcodes `cell="D2"` for the spoofed drive context. Drivers from the top of
the key, the corner, or the wing all end up shooting from the same cell.

### 6. Ball handler never moves on the grid

The engine builds `ball_handler.cell = "D6"` once at
[`engine.py:478`](../basketball_sim/core/engine.py:478) and never updates it.
Every subsequent dribble, pass, or drive leaves the ball at D6 in the state
the AI sees (only the synthetic drive context at `D2` is different).
Off-ball players are similarly frozen at their initial cells. All the spatial
reasoning the AIs try to do ends up operating on a static snapshot.

### 7. `_resolve_drive` skips the modifier pipeline for the shot leg

[`composite.py:146`](../basketball_sim/resolvers/composite.py:146) passes the
**same `agg`** into `resolve_shot`, but builds a synthetic sub-action with
`cell="D2"` and a different `shot_type`. Because `apply_boost_to_transitions`
and `agg.shot_pct_boost` were computed against the *original* drive action,
modifiers specifically registered for drives or rim attempts run against the
wrong action type. The impact is small numerically but conceptually wrong.

### 8. Score and stats diverge for free throws

Free throws add to `PlayerStats.points` in
[`stats_tracker.py`](../basketball_sim/narration/stats_tracker.py) but do not
update `TeamStats.total_points` (only `SHOT_MADE` does). Also, the engine's
`_simulate_quarter` credits `result.score_change` to `GameState.score`, and
`PossessionResult.score_change` at [`engine.py:435-439`](../basketball_sim/core/engine.py:435)
only sums `EventType.SHOT_MADE` points — free throws are excluded from the
game score too. In practice the `_resolve_free_throw` path is never reached
from the real AI, so the break is latent, not visible.

### 9. PASS_COMPLETED "steal" from defensive AI doesn't end possession

[`ai/defensive_ai.py`](../basketball_sim/ai/defensive_ai.py:80-90) emits a
`EventType.STEAL` event during `_react_to_dribble`, but the reaction path
doesn't end the possession. The offense's dribble still resolves afterward.
The steal becomes narration-only noise. 53 STEAL events fired in the test
run; none actually took the ball.

### 10. CoachAI never instantiated

[`ai/coach_ai.py:47`](../basketball_sim/ai/coach_ai.py:47) defines a full
rotation / timeout / scheme-adjustment system. It is not wired into
[`__main__.py`](../basketball_sim/__main__.py). Every method is dead code
from the engine's perspective. Minutes never tracked, subs never happen,
timeouts never called, pace/intensity never adjusted.

### 11. Fatigue never drains

`FatigueState` defaults to `1.0/1.0/1.0/1.0` in
[`types.py:313-319`](../basketball_sim/core/types.py:313). No writer anywhere
in the codebase reduces any of those fields. `MoveData.energy_cost` loaded
from JSON is never subtracted from the player. `fatigue_modifier` always
returns ~neutral. In a 48-minute simulation no one gets tired.

### 12. Mental state is static

Same pattern: `confidence`, `momentum`, `frustration`, `focus` are read by
`psychology_modifier` but never mutated by any event. A missed shot doesn't
lower confidence, a hot streak doesn't raise momentum.

### 13. Chemistry never populated

[`modifiers/chemistry.py`](../basketball_sim/modifiers/chemistry.py) exposes
`set_chemistry()` but nothing calls it. The pairwise map stays empty and
every lookup returns the default 0.5, so chemistry is a no-op modifier.

### 14. Coaching adjustments never populated

Same pattern: [`modifiers/coaching.py`](../basketball_sim/modifiers/coaching.py)
exposes `set_coaching_adjustment()`, only CoachAI calls it, CoachAI is never
instantiated.

### 15. Module-level state leaks across games

`_chemistry_ratings`, `_coaching_adjustments`, `_game_history` are module
globals. `__main__.py` only calls `reset_history()` on start — not
`reset_chemistry()` or `reset_coaching()`. Running two games in the same
process contaminates state.

---

## Engine ([`basketball_sim/core/engine.py`](../basketball_sim/core/engine.py))

- **TODO:** Line 253 - overtime logic missing. Tied games just end tied.
- **TODO:** Line 445 - offensive rebound hardcoded to False (see item 2 above).
- **Stub fallback leaks:** Line 347 defender fallback uses
  `possession.ball_handler.player` if `possession.defense` is empty. The
  attacker becomes their own defender. Every modifier runs self-vs-self.
  Similar on line 400 in the force-shot branch.
- **Dead fields on `PossessionState`:** `shot_clock`, `game_clock`,
  `actions_this_possession` (only appended-to, never read after
  possession ends), `tags_this_possession` (same).
- **Dead copy of `game.score`:** Line 512 does `score=dict(game.score)` into
  the fresh possession, but the possession's own `score` dict is never read
  or written during resolution.
- **Defense events emitted before the offensive action resolves**
  (Line 336-338). Narration order becomes `[help rotates] -> [crossover]`
  even when the crossover is what caused the rotation.
- **Local import of `PlayerOnCourt, OffBallState`** at line 474. Should be
  hoisted to the module header.
- **`_build_possession` assigns default positions but never tracks them
  afterward.** The first on-court player is always the ball handler; there
  is no notion of who should get the ball based on the previous possession.
- **`GameState.events` list is never populated.** Field exists at
  [`types.py:419`](../basketball_sim/core/types.py:419) but the engine only
  accumulates events into a local list inside `_simulate_possession`.
- **Duplicate score calculation:** Line 435-439 sums `SHOT_MADE.data["points"]`
  to produce `score_change`, but the resolver already set `score_change` on
  `ActionResult`. Stub resolver uses the latter, composite/shoot set both.
  The engine uses its own event-sum, so the resolver-level score_change is
  ignored for scoring.
- **Force-shot branch (line 415-416)** reassigns `result = forced_result`
  only when `forced_result.score_change > 0`. Since scoring uses the summed
  event list, this reassignment has no effect. Dead code.
- **`PossessionState.is_fast_break` never set to True** by anything. The
  coaching modifier's "pushing_pace" tag on line 89 of
  [`modifiers/coaching.py`](../basketball_sim/modifiers/coaching.py:89) can
  never fire.
- **No halftime handling.** Timeouts per half are declared in rules but
  halves are not modeled.
- **`quarter_length` default 720.0 but `num_quarters=4` means 48 min NBA;**
  no detection if caller passes NCAA rules (two 20-min halves).

## Types ([`basketball_sim/core/types.py`](../basketball_sim/core/types.py))

- **`AggregatedModifier.CLAMP_MIN / CLAMP_MAX` are regular dataclass fields**
  (lines 220-221), not `ClassVar`. They show up in `__init__`, in `asdict()`,
  in equality comparisons, and can be mutated on individual instances. Should
  be `ClassVar[float] = -0.25`.
- **`AggregatedModifier.clamp()`** hardcodes `-0.15, 0.15` for `shot_pct_boost`
  on line 241 instead of using a named constant. Magic number, inconsistent
  with the `CLAMP_MIN/MAX` pattern.
- **`Action.time_cost`** is a plain float (line 122) but the plan specifies
  it should be a callable returning a randomized value per call
  (`action.time_cost(rng)`). Right now every dribble costs exactly the same
  time. The `BasicOffensiveAI` does randomize it at construction, but the
  engine treats it as deterministic once built.
- **`PossessionState.score` duplicates `GameState.score`** (lines 379, 418).
  Two sources of truth. Code only writes to game.score; possession.score
  silently diverges.
- **`GameState.rng` default** (`random.Random(42)`) silently injects a
  hardcoded seed if the caller forgets. A test that omits `rng` gets a
  reproducible game without meaning to.
- **`PlayerAttributes` has no `free_throw` attribute** -
  `_resolve_free_throw` in `composite.py` proxies `mid_range`, which is
  incorrect (Shaq-Ben-Simmons type shooters have very different FT% vs
  mid-range %).
- **`PlayerAttributes.dunk: int = 50`** default is low (dunks for wings
  should be ~70). Minor.
- **`PlayerAttributes.stamina`** declared but never read anywhere.
- **`PlayerAttributes.vertical`** declared but never read anywhere.
- **`PlayerAttributes.screen_setting`** declared but never read.
- **`PlayerAttributes.post_offense / post_defense`** declared but never read
  (no post-move resolver exists).
- **`RulesConfig.three_point_distance`** is a single float (line 433);
  NBA has corner three at 22 ft and arc at 23.75 ft. Not zone-aware.
- **`RulesConfig` lacks fields present in the JSON rulebooks**:
  `backcourt_violation_seconds`, `defensive_three_seconds`,
  `offensive_three_seconds`, `hack_a_shaq_rules`,
  `team_fouls_for_double_bonus` (NCAA). So the rules loader can't fully
  populate a RulesConfig from the JSON, and those JSON files are
  effectively metadata only.
- **`TeamState.timeouts_remaining: int = 7`** (line 405). NBA allows 7 per
  game, but the comment in `RulesConfig` says `timeouts_per_half`.
  Ambiguity about whether this resets at halftime.
- **`ActionContext.cell: str = ""`** default (line 474) - empty string is
  not a valid grid cell; should be `None` or a mandatory arg.

## Event bus ([`basketball_sim/core/event_bus.py`](../basketball_sim/core/event_bus.py))

- **Unbounded history.** Line 58-59 appends every emit to `_history` with no
  retention policy. A long season would balloon memory. `_record_history`
  flag defaults to True; no way to disable via constructor.
- **`unsubscribe` does not cover global handlers** (line 45-49). `clear()`
  does, but single-handler removal from `_global_handlers` is impossible.
- **`handler.__name__` in logger.exception** (line 68) - fails for
  `functools.partial` callbacks (no `__name__` attribute), silently
  swallowed by `logger.exception`. Fragile.
- **No async / queued mode.** Synchronous only. A slow handler blocks the
  engine. OK for now but will matter for a 2D renderer.

## Pipeline ([`basketball_sim/core/pipeline.py`](../basketball_sim/core/pipeline.py))

- **No duplicate-name check in `register`** (line 44). Two modifiers with
  the same name share a `_failure_counts` entry and one can disable the
  other's error counter.
- **Per-modifier timing not tracked.** Useful for profiling; absent.
- **Zero documentation of which axes each boost affects.**

## Grid ([`basketball_sim/core/grid.py`](../basketball_sim/core/grid.py))

- **`lru_cache` imported but never used** (line 25). Dead import.
- **`D7` (top of key, above the arc) is NOT classified as a three**:
  [line 84](../basketball_sim/core/grid.py:84) `is_arc_three = (row == 5 and
  1 <= col <= 5) or (row == 6 and col in (0, 1, 5, 6))`. Row 6 (label 7) is
  described in the module docstring as "above the arc", but column 3 (D) is
  explicitly excluded. A top-of-the-key three is the most basic NBA shot
  and this misclassifies it as mid-range. **Bug.**
- **Corner three geography:** `is_corner_three = col in (0, 6) and row in
  (4, 5)` includes A6/G6 as corner threes; typically only A5/G5 should
  count. Minor.
- **Post and paint overlap** (lines 68, 74). A cell can satisfy both; the
  `region` string picks paint first so post-region is only reported for
  B/F columns. Confusing semantics.
- **`cells_between`** uses `round()` on float interpolation, which can skip
  cells on steep diagonals. Passing-lane defender counting slightly
  undercounts.
- **`manhattan_distance`** parses cell strings on every call. Small perf
  win from caching since only 63 possible cells.
- **No `cells_within_distance(n)` helper** despite being commonly needed
  for help-defense logic; only `adjacent` (1-step) is provided.

## Mod loader ([`basketball_sim/core/mod_loader.py`](../basketball_sim/core/mod_loader.py))

- **Conflict policy hardcoded** to `"last_wins"` (line 67). The plan called
  for `ModConflictError` on genuine duplicates. Policy is a private string
  with no setter.
- **No Pydantic / schema validation** at load time (the plan specifies
  this explicitly for move JSON). Broken moves silently load with empty
  transitions.
- **`narration_templates` and `modifier_functions` not merged** by
  `merge_into_registry` (line 246). Caller must do it manually.
- **Module name collisions:** `module_name = f"mod_{mod_id}_{path.stem}"` -
  mods with slashes or dots in their IDs produce non-standard module names;
  `sys.modules` accepts them but `import` cycles would fail.
- **No mod dependency resolution / load-order control.** `compatible_with`,
  `depends_on`, explicit priority are not read.
- **No mod unload / reload.**
- **Python file fallback:** lines 227-240 scan for `*_modifier` suffixes if
  the same-named function isn't callable. Multiple `_modifier` functions in
  one file all get loaded silently - may surprise mod authors.
- **Never actually exercised:** no `mods/` directory ships in the repo and
  no example mod exists, so the loader is untested against real content.

## Resolvers

### transitions ([`transitions.py`](../basketball_sim/resolvers/transitions.py))

- **Dead `else` branches** at lines 48 and 52 in `apply_boost_to_transitions`.
  The early-return at line 40 already covers `fav_total == 0` (boost<0) and
  `unfav_total == 0` (boost>0), so the divide-by-zero fallbacks never run.
- **Renormalization doubles work:** `rng.choices` normalizes weights
  itself; the explicit normalization on lines 56-58 is redundant.
- **Silent return of input** when `base` is empty (line 33). The caller
  might expect a dict with particular keys; gets the same empty dict back.

### dribble ([`dribble.py`](../basketball_sim/resolvers/dribble.py))

- **Rhythm never resets.** `_advance_rhythm` on line 186-195 walks forward
  through SURVEYING -> GATHERING -> ATTACKING but never back. Once a
  possession reaches ATTACKING, it stays there until the possession ends.
- **`ankle_breaker` tag race condition:** The auto-transition that sets
  `new_stance = FLAILING` (lines 130-131) happens *after* the ankle-breaker
  tag check (lines 124-126). If the move itself doesn't set
  `tags_on_critical` and the FLAILING state is reached only via
  auto-transition, `ankle_breaker` is never emitted.
- **`help_status` axis ignored.** The docstring says multi-axis, but
  resolve_dribble copies `matchup.help_status` unchanged (line 138).
- **`required_attributes` ignored.** A 40-rated ball handler can still
  attempt a shamgod; only the offensive AI filters these, and not all
  action paths go through the AI.
- **`combo_bonus_after` ignored.** Move-sequence bonuses loaded from JSON
  are unused.
- **`effective_grid_regions` ignored.** Moves that shouldn't work in the
  paint (e.g. shamgod) aren't region-filtered.
- **`energy_cost` not subtracted** from any fatigue dimension.
- **`_STA_FAVORABLE` includes `CLOSING_OUT`** (line 31). A defender
  closing out is typically responding to an offensive action, not
  favorable for the attacker. Questionable classification.
- **Awkward predicate:** Line 124 `if new_stance in (DefenderStance.FLAILING,)`
  should just be `==`.

### shoot ([`shoot.py`](../basketball_sim/resolvers/shoot.py))

- **`cs_mod` sign convention bug.** Line 81:
  `cs_mod = catch_and_shoot_bonus if catch_and_shoot else off_dribble_penalty`.
  `off_dribble_penalty` is named as a penalty but applied *added* to the
  shot percentage. A positive value would help the shooter. Either the
  name or the sign is wrong.
- **Base layup percentage too low.** `driving_layup / 150.0` + 0.08 rim
  bonus = 54.7% for a 70 rating. NBA at-rim is ~65%. Needs calibration.
- **Shot-type classification is substring-based.** Line 45
  `is_three = "three" in shot_type`. A shot type like "deep_heave" or
  "buzzer_beater" wouldn't register as a three even if taken from
  behind the arc.
- **Cell bonus overwrites (not accumulates)** between branches (lines
  65-70). A corner-three cell that is somehow also restricted area would
  only get the restricted-area bonus. Impossible in practice but fragile.
- **No block resolution.** BLOCK is an EventType but the shot resolver
  never emits one. Defensive blocks only come from `defensive_ai._react_to_drive`
  and only when both ball handler and defender are in the paint — which
  never happens because the ball handler never moves.
- **No shooting-foul detection.** Shooters cannot draw fouls.
- **No and-one handling.**
- **No buzzer beater bonus.**
- **Tags include `agg.tags`** (line 104), which then piggyback into the
  shot attempt / shot result events. Modifier tags leak into unrelated
  event streams.

### pass_action ([`pass_action.py`](../basketball_sim/resolvers/pass_action.py))

- **`ball_handler_change` set but ignored** by the engine (see critical
  bug #4).
- **Default `target_cell = "D5"`** (line 39). If the AI omits the target
  cell, every pass goes to D5. AI currently does supply it.
- **`pass_type` overridden silently** at line 56 (`pass_type = "skip_pass"`)
  even if caller specified something else.
- **STEAL event has no `player_id`** (line 79-88). Stats tracker can't
  credit a steal to the defender. In the test run all 53 STEAL events
  were either from defensive_ai (no player) or pass_action (no player).
- **No PASS_INTERCEPTED emission.** The EventType exists, never fires.
- **No ASSIST emission.** Assist credit has to be inferred from pass+shot
  sequence in the stats tracker.
- **Reset matchup on completion** (line 128) - sets MatchupState() on the
  old ball handler because the handler doesn't swap. Subtle state
  corruption.

### rebound ([`rebound.py`](../basketball_sim/resolvers/rebound.py))

- **Entire file is dead** - engine never routes to it.
- **Rebounder event lacks the `rebounder_id` field** the renderer expects
  at [`renderer.py:320`](../basketball_sim/narration/renderer.py:320).
  Data has `rebounder` (display name) instead. Template substitution
  fails silently if it ever runs.

### composite ([`composite.py`](../basketball_sim/resolvers/composite.py))

- **Unhandled action types fall through to TURNOVER** (lines 66-78):
  `SCREEN`, `POST_MOVE`, `HOLD_BALL`, `FOUL`, `TURNOVER` all become
  generic "unhandled" turnovers. Any future AI that emits these loses
  possession.
- **`_resolve_free_throw` skips the modifier pipeline.** `agg` is never
  computed for FT attempts (line 156-186). Clutch / pressure modifiers
  don't apply to free throws.
- **Drive position hardcoded** (line 143 - see critical bug #5).
- **Drive success check uses substring match** (line 149
  `"shot_made" in result.tags`). Fragile; a tag like
  `"contested_shot_made"` would accidentally match.

## Modifiers

### fatigue ([`fatigue.py`](../basketball_sim/modifiers/fatigue.py))

- **Always ~neutral** because nothing writes to fatigue (critical bug #11).
- **No attacker stance penalty.** `stance_boost = def_stance_bonus` only
  accounts for defender mental fatigue helping the attacker. The attacker's
  own fatigue doesn't penalize their stance.
- **`tags` include `gassed` / `winded` / `defender_gassed` / `defender_winded`**
  which can fire, but in practice everyone is fresh so they don't.

### psychology ([`psychology.py`](../basketball_sim/modifiers/psychology.py))

- **`composure_factor` computed but never used** (line ~44). Dead variable.
- **Always ~constant** because mental state never changes (critical bug #12).
- **`total_rhythm` computed but some modifiers (fatigue, psychology,
  chemistry, situational) feed it** while the pipeline has no explicit
  policy for rhythm; `AggregatedModifier.rhythm_boost` is clamped like
  everything else.

### chemistry ([`chemistry.py`](../basketball_sim/modifiers/chemistry.py))

- **Globals never populated** (critical bug #13).
- **`reset_chemistry()` exported but never called** by `__main__.py`
  (critical bug #15).

### coaching ([`coaching.py`](../basketball_sim/modifiers/coaching.py))

- **Globals never populated** (critical bug #14).
- **`reset_coaching()` exported but never called** (critical bug #15).
- **Local `from basketball_sim.core.grid import COURT`** inside a function
  body. Hoist it.

### history ([`history.py`](../basketball_sim/modifiers/history.py))

- **Good:** `reset_history()` is actually called from `__main__.py`.
- **Writes happen inside `history_modifier`** - calling
  `record_action()` at read time couples recording and evaluating.
  If the modifier ever fails and the pipeline skips it, the move goes
  unrecorded but still happened.
- **`record_action` is called on dribble moves only.** Shots, drives,
  passes never enter the history. Defenders never learn a shooter's
  tendencies.

### tendencies ([`tendencies.py`](../basketball_sim/modifiers/tendencies.py))

- **Drive direction dead path.** Reads `action.data.get("direction")`
  (line ~20); `BasicOffensiveAI._pick_dribble_move` never sets
  `direction`. Tendency effect never fires.
- **`heat_check` reads `momentum`** which is never written (cascades
  from critical bug #12).

### situational ([`situational.py`](../basketball_sim/modifiers/situational.py))

- **Shot-clock pressure never triggers** (cascades from critical bug #1).
- **Clutch windows look right** but `is_clutch` uses `game.game_clock` in
  seconds-remaining-in-quarter, not seconds-remaining-in-game. For
  overtime periods the last 2 minutes of each OT period would trigger,
  which is probably what you want.
- **Rubber-banding for trailing teams** (line `if diff < -20: positioning
  += 0.02`). Small but baked-in comeback boost; not present in the plan.

## AI

### BasicOffensiveAI ([`offensive_ai.py`](../basketball_sim/ai/offensive_ai.py))

- **Shot-clock branches disabled** (critical bug #1).
- **Ball-handler cell is stuck at D6** so `_evaluate_shot_opportunity`
  always sees the top of the key. Combined with LOCKED_UP starting
  matchup → openness ~0.05 → three threshold ~0.38 → **AI almost never
  shoots**. Primary cause of the 20-shots-per-game figure.
- **Dribble selection weighting assumes specific move IDs**
  ("crossover", "behind_the_back", "spin_move", "step_back",
  "jab_step", "hesitation"). Mods adding new moves won't get weighted.
- **`_pass_probability` doesn't use chemistry** - a PG with poor
  chemistry with the off-ball players passes the same as one with
  great chemistry.
- **Openness formula divergent from shoot.py contest formula.**
  `offensive_ai._matchup_openness` uses
  `pos_open * (2 - bal_factor) / 2`, while shot resolver uses
  `pos_contest * bal_factor`. Related but not inverses of each other.
  AI's decision to shoot may not line up with actual shot quality.
- **Off-ball `openness` / `catch_readiness` static** - never updated
  after `_build_possession`.

### BasicDefensiveAI ([`defensive_ai.py`](../basketball_sim/ai/defensive_ai.py))

- **Steals in `_react_to_dribble` don't end possessions**
  (critical bug #9).
- **Blocks require both ball handler and defender in the paint** -
  since ball handler is stuck at D6 this branch is almost never true.
  Zero BLOCK events in the test run.
- **Events with `event_type=EventType.DRIBBLE_MOVE` for help-defense
  rotations** (line 75-79, 90-94, 118-124). Narration / stats will see
  these as dribble moves. Should be a new event type or at minimum a
  coverage-adjustment tag on the action's own event.
- **`matchup: HelpDefenseStatus | object` type annotation** on
  `_react_to_dribble` is nonsense and the parameter is shadowed inside
  the function by `matchup_state = possession.ball_handler.matchup`.
  Remove the unused parameter.
- **Help chain single-hop only.** Plan calls for multi-step
  help-and-recover chains (help rotates -> that defender's assignment
  becomes open -> next rotation, etc.). Currently a single boolean
  `help_available` and a flag flip.
- **No scheme awareness.** Defensive schemes are in JSON but no code
  reads `defensive_schemes.json` at runtime.
- **`_calculate_steal_chance`** consumes `rng` argument but doesn't use
  it. The caller does the actual roll. Parameter is misleading; remove.

### CoachAI ([`coach_ai.py`](../basketball_sim/ai/coach_ai.py))

- **Never instantiated** (critical bug #10).
- **Minutes never tracked.** `RotationSlot.minutes_played` field exists
  but no update site.
- **`evaluate_substitution` uses `fatigue_threshold`** but fatigue
  never drains.
- **Timeout / scheme logic written but called from nowhere.** Dead.

## Narration

### aggregator ([`aggregator.py`](../basketball_sim/narration/aggregator.py))

- **`FREE_THROW` in `_BEAT_STARTERS`** - each FT is its own beat, so
  and-one and two-shot sequences never group together.
- **STEAL, TURNOVER, REBOUND not in any sequence set** - they become
  standalone beats via the generic "else" branch. Usually fine, but
  a STEAL directly after a DRIBBLE_MOVE gets rendered as two beats.
- **`is_scoring_play` only set for SHOT_MADE**, not for FREE_THROW makes.

### enricher ([`enricher.py`](../basketball_sim/narration/enricher.py))

- **Tracking state doesn't reset per quarter** - consecutive_makes
  accumulates across the whole game; a hot streak in Q1 keeps counting
  in Q3.
- **`scoring_run_team` field exists but never written** in the code.
  Dead field.
- **Clutch multiplier (x1.5)** applied after tag-based excitement,
  can push excitement above 1.0 before clamp. Fine, but order-sensitive.
- **No "buzzer beater" detection** despite the shot resolver never
  emitting such a tag.

### templates ([`templates.py`](../basketball_sim/narration/templates.py))

- **`TemplateSelector.select` uses global `random` when `rng` is None**
  (line 102). `__main__.py` passes `rng=random` (the module), which is
  also non-deterministic. **Narration output is non-deterministic even
  with a fixed seed.** Game events are deterministic, but which template
  variant fires is not.
- **`_default_profile()` falls back silently** to a 3-template hardcoded
  profile if the JSON file is missing - no warning log.
- **Template intensity filter excludes equal-level templates on
  whisper** (`tmpl_idx <= min_idx`). If beat intensity is "whisper"
  (idx 0) only whisper templates match. If no whisper templates exist
  for a tag set, nothing matches. Most beats on a quiet possession
  would fall through to fallback text.
- **No coverage check.** There is no way to assert every possible tag
  combination the engine can emit has at least one matching template.

### renderer ([`renderer.py`](../basketball_sim/narration/renderer.py))

- **Signature-phrase insertion uses global `random`** (line 281-282),
  again breaking determinism.
- **Placeholder cleanup regex** `r"\{[a-z_]+\}"` (line 330) doesn't
  match uppercase or digit-containing placeholders. A typo like
  `{Player1}` would leak into output.
- **Double-space collapse** doesn't handle cases where an empty
  placeholder leaves ` .` or `, ,` patterns. Punctuation hygiene
  not addressed.
- **`rebounder` resolution** reads `data.get("rebounder_id", "")` but
  the rebound resolver writes `"rebounder": rebounder.display_name`
  (not `rebounder_id`). Name substitution fails silently for rebound
  beats. (Rebounds never fire anyway today, but the wiring is wrong.)
- **Fallback noise filter**: `only_tags <= {"early_game", "home_court",
  "dribble_move"}`. Typical dribble beats have more tags than this
  (e.g. `["dribble_move", "wide_open"]`), so the filter barely activates.

### stats_tracker ([`stats_tracker.py`](../basketball_sim/narration/stats_tracker.py))

- **Column widths misaligned.** `format_line` uses `{:>3d} PTS` (3-wide)
  but header uses `{'PTS':>4s}` (4-wide). Same for `FG` (5 vs 6) and
  `3PT` (5 vs 6). Box score prints crooked.
- **`TeamStats.total_points` only updates on SHOT_MADE** (see critical
  bug #8). Free throws don't add.
- **`TeamStats.fast_break_points / points_in_paint /
  second_chance_points / bench_points`** declared but never updated.
  Dead fields.
- **`PlayerStats.minutes` never updated.** Always 0.0.
- **`_last_shot_player` field set but never read.** Dead.
- **Assist credit window is infinite.** A pass followed by 4 dribbles
  and then a shot still credits an assist to the passer. Realistic
  NBA rule is the receiver must score within ~1-2 touches.
- **No handler for PASS_INTERCEPTED, SHOT_CLOCK_VIOLATION,
  ANKLE_BREAKER, FAST_BREAK** - those events are silently dropped.
- **Assist auto-clears `_last_passer` on first SHOT_MADE** - if two
  successive shots happen after one pass, only the first gets an
  assist. Correct? Yes. But the semantic is fragile.

## Data files ([`basketball_sim/data/`](../basketball_sim/data/))

All JSON validates cleanly:
- 45 dribble moves, transitions all sum to 1.0.
- 80 badges, no duplicate IDs.
- 10 plays, 10 defensive schemes.
- 171 narration templates, no duplicate IDs.
- 3 rulebooks (NBA, NCAA, FIBA).

Issues:

- **`data/plays/plays.json` is never loaded** - no `load_plays()` in
  [`data/loader.py`](../basketball_sim/data/loader.py). Pure decoration.
- **`data/schemes/defensive_schemes.json` is never loaded** - same.
- **`data/rules/*.json` is never loaded** - `RulesConfig` is built from
  kwargs only in `__main__.py`. The rulebooks contain fields not present
  on `RulesConfig`, so even loading wouldn't round-trip.
- **`data/badges/badges.json` is loaded but never applied.**
  `load_badges()` returns the dict; nothing consumes it. No badge
  effect is actually wired into modifiers.
- **No `data/rosters/` directory** despite the plan listing it
  explicitly. Rosters live in `__main__.py` as Python literals.
- **Loader has no Pydantic validation** (see mod_loader issues).
- **Loader uses `logger.exception` in a loop but doesn't abort the
  load** - a single malformed move produces a log message and
  otherwise succeeds with a partial registry; acceptable, but no
  end-of-load error summary.

## `__main__.py` ([`basketball_sim/__main__.py`](../basketball_sim/__main__.py))

- **`reset_history()` called but not `reset_chemistry()` /
  `reset_coaching()`** - repeated in-process invocations bleed state.
- **`CoachAI` never instantiated** so there is no wiring for
  rotations, timeouts, or scheme adjustments.
- **No rule file loaded.** `RulesConfig` uses defaults; NBA/NCAA/FIBA
  switching is impossible from the CLI.
- **No `--rules` flag.**
- **Sample teams are hand-built.** A `--roster` flag pointing at a
  JSON file would be trivial to add.
- **`NarrationListener.handle_event`** uses `rng=random` (the global
  module). Non-deterministic narration even with `--seed` (see
  templates issues).
- **Clock format differences:** `__main__._format_clock` and
  `renderer._format_clock` are duplicated implementations with
  slightly different signatures (one returns `" 0:00"` padded, the
  other `"0:00"`).

## Tests ([`tests/`](../tests/))

The 163 tests exist but under-test the integration layer:

- **`test_engine.py::test_engine_runs_to_completion` wires `StubResolver`
  + `StubOffensiveAI`**, not the real AI + CompositeResolver. So the
  end-to-end scoring breakdown (20 shots in 4 quarters) is not covered.
- **No test asserts sane game aggregate stats** (e.g. "both teams score
  more than 50 points per 48 minutes"). A regression test per the plan's
  "balance regression tests" section is missing.
- **No test of `ball_handler_change` propagation** - which is why the
  engine bug #4 slipped through.
- **No test that the rebound resolver is reached** after a missed shot
  by the real composite engine - explains bug #2.
- **No test that shot_clock in `PossessionState` updates during a
  possession** - explains bug #1.
- **No template-coverage smoke test** asserting every emitted tag has
  a template match.
- **`test_modifiers.py`** tests each modifier in isolation with hand-built
  contexts. Never asserts that mutation occurs (e.g. fatigue decreasing
  over a possession) because no such mutation happens.
- **`test_narration.py::TestStatsTracker`** doesn't assert column
  alignment or that FT points hit `TeamStats.total_points`.
- **`test_phase6.py::TestModLoader`** uses a tmp directory but never
  tests conflict handling (namespacing), Pydantic validation, or the
  `*_modifier` fallback.
- **No tests for `basketball_sim.__main__`** CLI flags.

---

## Recommended remediation order

A minimum-viable path to a believable game:

1. **Fix the shot clock wiring** so `PossessionState.shot_clock`
   decrements. Unblocks bugs #1 and a large part of the possession
   length explosion.
2. **Route misses through `resolve_rebound`** and respect
   `offensive_rebound`. Unblocks #2.
3. **Emit `TURNOVER` alongside `SHOT_CLOCK_VIOLATION`.** Unblocks #3.
4. **Honor `ActionResult.ball_handler_change`** in `_simulate_possession`
   so passes actually swap the ball handler. Unblocks #4 and cascades
   into realistic spatial reasoning.
5. **Track and update the ball handler's `cell`** per action. Unblocks
   #6 and the entire AI shot-selection threshold trap.
6. **Wire `CoachAI` in `__main__.py`** and call `reset_chemistry()` /
   `reset_coaching()` on startup. Unblocks #10, #15.
7. **Decrement fatigue from `MoveData.energy_cost`** after each action.
   Unblocks #11 and makes rotations meaningful.
8. **Update `mental` state** on scoring / misses / turnovers.
   Unblocks #12.
9. **Replace `cs_mod` sign bug** in `shoot.py`.
10. **Correct D7 classification as a three** in `grid.py`.
11. **Add box score alignment test + assist-window constraint**.
12. **Add a "plausibility" integration test**: a 4-quarter game must
    score at least 120 total points and attempt at least 150 shots.

Once those land, balance regression (`test_modifiers.py` distribution
tests over 1000 possessions) becomes the right place to tune numbers.
