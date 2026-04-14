# Basketball Simulator - Complete Architecture Plan

## Vision
The world's most realistic basketball simulator. Text-based with architecture ready for 2D pixel art frontend. More realistic than 2K by modeling the basketball that happens between the ears -- psychology, fatigue, chemistry, coaching intelligence, player identity -- not just physics.

## Core Design Principles
1. **Event Bus as backbone** -- sim engine emits typed events, everything else subscribes. No module-to-module coupling.
2. **Modifier Pipeline** -- every realism layer is an independent function. No layer knows other layers exist. Adding depth = adding files, not modifying existing code.
3. **Data over code** -- dribble moves, badges, narration templates, plays, rosters are JSON data files. Adding content = adding data.
4. **Everything pluggable** -- rules, AI, narration, rendering all implement typed interfaces via ABCs.
5. **Mod system** -- auto-discovered from `mods/` folder. JSON for data, Python files for logic. Zero existing code modified to add a mod.

## Technology
- **Language:** Python
- **Type enforcement:** Type hints + dataclasses + Pydantic for runtime validation of plugin contracts
- **Project management:** uv or poetry
- **Package structure:** Python packages with `__init__.py`

---

## Architecture Overview

```
Player Tendencies ---+
Mental State --------+
Fatigue -------------+
Chemistry -----------+----> Modifier Pipeline ----> State Resolver ----> Events ----> Event Bus
Coaching ------------+                                    |                              |
History -------------+                                    |                              |
Situational ---------+                                    v                              v
                                                    Tags Generated              +--------+--------+
                                                                                |        |        |
                                                                           Narration  Stats  Rendering
                                                                           Pipeline  Tracker  (future)
```

---

## Court Model: Chess-Style Grid (7x9)

Half-court grid, 63 cells. Each cell is ~7 feet wide by ~5 feet deep (1-2 dribbles per cell).

```
    A      B      C      D      E      F      G
  far-L  L-wing L-elbow center R-elbow R-wing far-R

9  [A9]  [B9]  [C9]   [D9]   [E9]   [F9]  [G9]   backcourt
8  [A8]  [B8]  [C8]   [D8]   [E8]   [F8]  [G8]   halfcourt
7  [A7]  [B7]  [C7]   [D7]   [E7]   [F7]  [G7]   above the arc
6  [A6]  [B6]  [C6]   [D6]   [E6]   [F6]  [G6]   three-point line
5  [A5]  [B5]  [C5]   [D5]   [E5]   [F5]  [G5]   free throw extended
4  [A4]  [B4]  [C4]   [D4]   [E4]   [F4]  [G4]   elbow area
3  [A3]  [B3]  [C3]   [D3]   [E3]   [F3]  [G3]   post / block
2  [A2]  [B2]  [C2]   [D2]   [E2]   [F2]  [G2]   low baseline
1  [A1]  [B1]  [C1]   [D1]   [E1]   [F1]  [G1]   under basket
```

Each cell has basketball metadata: `is_three`, `corner_three`, `distance_to_basket`, `in_paint`, `post_area`, etc.

Grid enables:
- **Distance calculations:** Manhattan distance between cells for pass difficulty, help defense range, closeout speed
- **Passing lanes:** Trace cells between passer and receiver, check for defenders in the lane
- **Movement cost:** Players move 1 cell per action-tick, creating timing-dependent basketball
- **Help defense:** Spatial logic for rotations based on cell proximity
- **Future 2D game:** Each cell = a sprite tile position. Grid IS the coordinate system.

---

## Matchup System: Multi-Axis State + Tags

### The Five Axes

Every matchup between an offensive player and their defender tracks five independent state machines:

**1. Defender Positioning** -- spatial relationship to attacker
- `LOCKED_UP` | `TRAILING` | `HALF_STEP_BEHIND` | `BEATEN` | `BLOWN_BY`

**2. Defender Balance** -- physical stability
- `SET` | `SHIFTING` | `OFF_BALANCE` | `STUMBLING` | `ON_FLOOR`

**3. Defender Stance** -- what the defender is physically doing
- `GUARDING` | `CLOSING_OUT` | `IN_AIR` | `REACHING` | `RECOVERING` | `HEDGING` | `FLAILING`

**4. Ball Handler Rhythm** -- attacker's current mode
- `SURVEYING` | `GATHERING` | `ATTACKING` | `ELEVATED` | `COMMITTED`

**5. Help Defense Status** -- nearby help defenders
- `NO_HELP` | `HELP_AVAILABLE` | `HELP_ROTATING` | `HELP_COMMITTED` | `HELP_RECOVERED`

A matchup at any moment is a combination across all axes. Hundreds of unique situations from simple, readable states per axis.

### Tags

Tags are string labels that accumulate during a possession describing what specifically happened:
- `["jab_step", "weight_tested", "hesitation", "defender_frozen", "crossover", "direction_switch", "ankle_breaker"]`

Tags serve dual purpose:
1. **Narration reads them directly** -- `ankle_breaker` becomes "ANKLE BREAKER!" in prose
2. **Badges and modifiers hook into them** -- a Showtime badge triggers on `ankle_breaker` tag

### How a Dribble Move Resolves

1. Check current state across all axes
2. Run modifier pipeline (fatigue, psychology, chemistry, coaching, history, etc.)
3. Roll state transitions on EACH axis independently (probabilities from move's JSON data, adjusted by modifiers)
4. Generate tags based on the transitions that occurred
5. Emit event with new states + tags to event bus

### Move Data Format (JSON)

```json
{
  "id": "crossover",
  "display_name": "Crossover",
  "category": "crossover",
  "transitions": {
    "positioning": {
      "from_LOCKED_UP": { "TRAILING": 0.20, "HALF_STEP_BEHIND": 0.08, "LOCKED_UP": 0.72 },
      "from_TRAILING": { "HALF_STEP_BEHIND": 0.35, "BEATEN": 0.10, "TRAILING": 0.40, "LOCKED_UP": 0.15 }
    },
    "balance": {
      "from_SET": { "SHIFTING": 0.25, "SET": 0.75 },
      "from_SHIFTING": { "OFF_BALANCE": 0.30, "SHIFTING": 0.45, "SET": 0.25 },
      "from_OFF_BALANCE": { "STUMBLING": 0.20, "OFF_BALANCE": 0.50, "SHIFTING": 0.30 }
    },
    "stance": {
      "from_GUARDING": { "REACHING": 0.15, "GUARDING": 0.85 },
      "from_REACHING": { "RECOVERING": 0.40, "REACHING": 0.35, "GUARDING": 0.25 }
    }
  },
  "cross_axis_boosts": {
    "balance_OFF_BALANCE_boosts_positioning": 0.12,
    "stance_RECOVERING_boosts_positioning": 0.08
  },
  "tags_on_success": ["crossover", "direction_switch"],
  "tags_on_critical": ["ankle_breaker"],
  "energy_cost": 0.04,
  "required_attributes": { "ball_handling": 70 },
  "effective_grid_regions": ["perimeter", "midrange"],
  "combo_bonus_after": ["hesitation", "jab_step"]
}
```

---

## Modifier Pipeline

Every realism layer is an independent function: context in, modifier out. No layer knows other layers exist.

### Layers (each is one file in `modifiers/`):

1. **Fatigue** -- multi-dimensional: cardiovascular, muscular, mental, accumulated load
2. **Psychology** -- confidence, frustration, focus, momentum, intimidation, composure
3. **Chemistry** -- pairwise player chemistry, system fit, trust, communication
4. **Coaching** -- defensive scheme adjustments, matchup hunting, timeout IQ
5. **History** -- this-game matchup history (used this move before? defender expects it)
6. **Tendencies** -- player-specific habits (drive direction preference, ISO frequency, shot selection)
7. **Situational** -- clutch time, home court, playoff intensity, crowd energy, score differential

### Pipeline Execution

```python
class ModifierPipeline:
    def __init__(self):
        self.modifiers: list[Callable] = []

    def register(self, modifier_fn):
        self.modifiers.append(modifier_fn)

    def apply(self, context: ActionContext) -> AggregatedModifier:
        result = AggregatedModifier()
        for modifier_fn in self.modifiers:
            mod = modifier_fn(context)
            result.combine(mod)
        return result
```

Adding a new realism layer = creating one new Python file + registering it. Zero existing code changes.

---

## Narration Pipeline (4 Stages)

### Stage 1: Event Aggregator
Groups raw events into narrative beats. A dribble sequence + drive + shot = one beat, not six separate events.

### Stage 2: Context Enricher
Tags each beat with excitement level, momentum context, streak info, game situation. Reads the tags to determine tone.

### Stage 3: Template Selector
Picks from data-driven templates based on tag combinations + excitement level. Templates are keyed to specific tag patterns:
- `["crossover", "ankle_breaker"]` has different templates than `["hesitation", "ankle_breaker"]`

### Stage 4: Prose Renderer
Fills templates with player-specific fragments, applies announcer personality, handles pacing and rhythm.

### Announcer Profiles (JSON)

```json
{
  "announcer_id": "hype_caster",
  "personality": {
    "excitement_baseline": 0.6,
    "signature_phrases": ["OH MY GOODNESS", "ARE YOU KIDDING ME", "BANG"],
    "style": "excitable"
  },
  "templates": {
    "tags:crossover+ankle_breaker": [
      "{player} with the crossover... OH MY GOODNESS, {defender} is on the FLOOR!",
      "{player} crosses {defender} into ANOTHER DIMENSION!"
    ]
  }
}
```

---

## Player Identity Model

### Attributes (~30 core ratings)
Standard ratings: ball_handling, speed, three_point, mid_range, driving_layup, dunk, passing_vision, perimeter_defense, interior_defense, strength, vertical, stamina, basketball_iq, etc.

### Shooting Profile
- **Hot zones:** per grid cell shooting percentages
- **Shot type splits:** catch_and_shoot_pct, off_dribble_pct, pull_up_deep_pct
- **Contest resistance:** how much shooting drops when contested
- **Release speed:** affects closeout window

### Tendencies
- Drive direction preference (left/right split)
- ISO frequency, post-up frequency
- Three vs midrange preference
- Pass-first vs score-first mentality
- Clutch usage tendency
- Defensive effort tendency
- Off-ball movement quality

### Mental State (changes during game)
- Confidence, frustration, focus, momentum
- Intimidation (LeBron driving at you)
- Composure (veterans vs young players under pressure)

### Move Repertoire
Each player has a specific list of dribble moves they can attempt. Hot Sauce has shamgod; a center doesn't.

---

## Mod System

### Structure

```
mods/
  streetball_pack/
    mod.json                    # metadata
    data/
      moves/streetball.json     # new dribble moves (JSON)
      badges/streetball.json    # new badges (JSON)
      rosters/legends.json      # new players (JSON)
      plays/streetball.json     # new plays (JSON)
      narration/crowd.json      # new templates (JSON)
    modifiers/
      crowd_energy.py           # new modifier layer (Python)
    updaters/
      crowd_updater.py          # new post-possession updater (Python)
```

### Mod Loader
On startup, discovers all folders in `mods/`, loads JSON into registries, imports Python files and registers them in pipelines. ~30 lines of code.

### Conflict Resolution (Detailed)

Mod conflicts happen when two mods define the same ID. The system handles four conflict types:

**1. Same-ID data entries (two mods define a "shamgod" dribble move):**

Each data entry has a globally unique key: `mod_id:item_id`. Internally, the streetball pack's shamgod is `streetball_pack:shamgod`. If the classic pack also has one, it's `classic_pack:shamgod`. Player rosters reference the full qualified ID.

If a mod omits the namespace prefix, the loader auto-prefixes with the mod ID. If two mods use the exact same qualified ID (unlikely), the loader raises a `ModConflictError` at startup listing both mods -- fail fast, don't silently overwrite.

**2. Modifier ordering (two mods both add modifier functions):**

Doesn't matter. Modifiers are additive and order-independent by design. Two mod modifiers compose the same way core modifiers do.

**3. Template collisions (two mods define templates for the same tag combination):**

Templates are additive -- both sets merge into the pool. The template selector picks randomly from all matching templates. More mods = more narration variety. No conflict.

**4. Player data overrides (a mod wants to change an existing player's attributes):**

Mods can include an `overrides/` folder with patch files:

```json
{
  "target": "base:james_harden",
  "patch": {
    "attributes.ball_handling": 99,
    "badges+": ["streetball_pack:street_handles:hall_of_fame"],
    "move_repertoire+": ["streetball_pack:shamgod", "streetball_pack:around_the_world"]
  }
}
```

`+` suffix means append (don't replace). Plain key means overwrite. Patches apply in mod load order (alphabetical by mod ID, or explicit priority in mod.json).

### Error Handling and Validation

Three validation boundaries, each with a different strategy:

**Boundary 1: Mod loading (startup)**

All JSON data files are validated against Pydantic schemas at load time. If a mod's dribble move JSON is missing `state_transitions` or has a negative `energy_cost`, the loader:
1. Logs a detailed error with the exact file, field, and expected type
2. Skips that specific entry (not the whole mod)
3. Reports all validation failures at the end of loading as a summary
4. The game still starts -- one broken move doesn't prevent playing

```python
class MoveSchema(BaseModel):
    id: str
    display_name: str
    transitions: dict[str, dict[str, dict[str, float]]]
    tags_on_success: list[str]
    energy_cost: float = Field(ge=0, le=0.5)
    required_attributes: dict[str, int] = {}

    @validator('transitions')
    def transitions_sum_to_one(cls, v):
        for axis, from_states in v.items():
            for from_state, probs in from_states.items():
                total = sum(probs.values())
                if not (0.99 <= total <= 1.01):
                    raise ValueError(f'{axis}.{from_state} probabilities sum to {total}, not 1.0')
        return v
```

**Boundary 2: Modifier execution (runtime)**

Each modifier function is wrapped in a try/except. If a modifier throws an exception:
1. The error is logged with the modifier name and context
2. That modifier returns a neutral Modifier (no effect) for this action
3. The game continues -- one broken modifier doesn't crash the sim
4. After 10 consecutive failures from the same modifier, it's disabled for the rest of the game with a warning

```python
def safe_apply(modifier_fn, context):
    try:
        return modifier_fn(context)
    except Exception as e:
        log.warning(f"Modifier {modifier_fn.__name__} failed: {e}")
        return Modifier()  # neutral, no effect
```

**Boundary 3: State integrity (runtime)**

After each action resolution, a lightweight sanity check runs:
- All state enum values are valid (no corrupted state)
- Transition probabilities sum to ~1.0 after modifier application
- No player is in two cells simultaneously
- Shot clock is non-negative
- Score is non-negative

If a sanity check fails, the engine logs the full possession state for debugging and forces the possession to end (turnover to the other team). This prevents cascading corruption.

---

## File Structure

```
basketball_sim/
  core/                     # The skeleton. ~500 lines total. Rarely changes.
    engine.py               # Game loop: get action, resolve, emit event, repeat
    event_bus.py            # Pub/sub system
    pipeline.py             # ModifierPipeline class
    types.py                # All dataclasses: Action, Modifier, Event, State, etc.
    grid.py                 # Court grid definition and distance calculations
    mod_loader.py           # Discovers and loads mods

  resolvers/                # State transition logic. One file per action type.
    dribble.py              # resolve_dribble()
    shoot.py                # resolve_shot()
    pass_action.py          # resolve_pass()
    screen.py               # resolve_screen()
    rebound.py              # resolve_rebound()
    foul.py                 # resolve_foul()
    turnover.py             # resolve_turnover()

  modifiers/                # Realism layers. Each is ONE independent file.
    fatigue.py
    psychology.py
    chemistry.py
    coaching.py
    history.py
    tendencies.py
    situational.py

  narration/                # 4-stage pipeline. Each stage is one file.
    aggregator.py           # Groups events into beats
    enricher.py             # Adds excitement/context
    templates.py            # Template selection engine
    renderer.py             # Fills templates, outputs prose

  ai/                       # Decision-making. Pluggable.
    offensive_ai.py         # What does the ball handler do next?
    defensive_ai.py         # How does the defense react?
    coach_ai.py             # Scheme adjustments, rotations, timeouts

  data/                     # ALL basketball content. Pure JSON. No code.
    moves/                  # dribble_moves.json, post_moves.json
    badges/                 # badges.json
    plays/                  # pick_and_roll.json, motion_offense.json
    narration/              # templates_default.json, announcer_profiles.json
    rosters/                # nba_2024.json
    rules/                  # nba_rules.json, ncaa_rules.json
    grid/                   # court_cells.json (cell metadata)

  mods/                     # User mods. Same structure. Auto-discovered.
    modifiers/
    narration/
    data/
    ai/

  tests/                    # Unit tests, one per module
```

---

## Implementation Phases

### Phase 1: Foundation
- Core types (dataclasses for all states, events, actions, players)
- Chess grid with cell metadata
- Event bus (pub/sub)
- Modifier pipeline skeleton
- Basic game loop (possession cycle: action -> resolve -> emit -> repeat)

### Phase 2: Action Resolution
- Dribble move resolver with multi-axis state transitions
- Shot resolver using matchup state for contest calculation
- Pass resolver with grid-based passing lanes and defender interception
- Screen resolver (pick and roll state manipulation)
- Rebound resolver
- Turnover and foul resolution
- Load moves, badges from JSON data files

### Phase 3: AI Decision Making
- Offensive AI: ball handler reads matchup state + grid + help defense to pick next action
- Defensive AI: coverage decisions, help rotation triggers, closeout logic
- Play calling: basic play structures (ISO, PnR, post-up) defined in JSON
- Coach AI: rotation management, timeout logic

### Phase 4: Narration Pipeline
- Event aggregator (groups actions into narrative beats)
- Context enricher (excitement level, momentum, streak detection)
- Template selector (matches tag combinations to templates)
- Prose renderer (fills templates, announcer personality)
- Default announcer profile with 200+ templates
- Box score generation from accumulated stats

### Phase 5: Realism Layers
- Fatigue modifier (multi-dimensional: cardio, muscular, mental, accumulated)
- Psychology modifier (confidence, frustration, focus, momentum)
- Tendencies modifier (player-specific habits)
- History modifier (this-game scouting)
- Situational modifier (clutch, home court)
- Chemistry modifier (pairwise chemistry, system fit)
- Coaching modifier (scheme adjustments, matchup hunting)

### Phase 6: Content and Polish
- Full NBA roster data
- Expanded dribble move library (50+ moves)
- Badge system with 80+ badges
- Play library (20+ offensive sets)
- Defensive schemes (man, zone variations, press)
- Multiple announcer profiles
- Season simulation: schedule, standings, playoff bracket

### Phase 7: Expansion Targets
- NCAA rules module + D1 roster data + March Madness bracket
- Custom league creation
- Draft system
- Mod loader and mod API documentation
- 2D pixel art rendering layer (consumes events from event bus)

---

## Game Loop and Possession Flow

The simulation is **action-based, not time-based**. There are no ticks. The game advances when someone does something.

### Quarter Structure

```python
def simulate_quarter(quarter: int, game_state: GameState, rng: random.Random):
    clock = game_state.rules.quarter_length  # 720.0 seconds (12 min NBA)
    
    while clock > 0:
        # Determine who has the ball and start a possession
        possession = start_possession(game_state, clock, rng)
        result = simulate_possession(possession, game_state, rng)
        
        # Update clock, score, stats
        clock -= result.time_elapsed
        game_state.apply(result)
        
        # Check for timeouts, end-of-quarter, etc.
        if result.triggers_timeout:
            handle_timeout(game_state)
        
        # Swap possession (unless offensive rebound)
        if not result.offensive_rebound:
            game_state.swap_possession()
```

### Possession Flow (the core loop)

A possession is a sequence of actions that ends when one of these happens:
- Shot made or missed (and defensive rebound)
- Turnover (steal, out of bounds, violation)
- Foul (shooting or non-shooting)
- Shot clock violation
- End of quarter

```python
def simulate_possession(possession: PossessionState, game: GameState, rng: random.Random) -> PossessionResult:
    shot_clock = game.rules.shot_clock  # 24.0 seconds NBA
    action_count = 0
    events = []
    
    while not possession.is_resolved:
        # 1. Off-ball players move (1 cell per action for movers)
        off_ball_results = resolve_off_ball_movement(possession, rng)
        events.extend(off_ball_results.events)
        
        # 2. Ball handler's AI decides next action
        action = offensive_ai.decide(possession, game)
        # Returns one of: DribbleMove, Shot, Pass, Drive, Screen, PostMove, HoldBall
        
        # 3. Defense reacts to the chosen action
        defensive_reactions = defensive_ai.react(action, possession, game)
        events.extend(defensive_reactions.events)
        
        # 4. Resolve the action through the state resolver
        result = resolve_action(action, possession, game.modifier_pipeline, rng)
        events.extend(result.events)
        
        # 5. Update possession state
        possession.apply(result)
        
        # 6. Check possession-ending conditions
        if result.ends_possession:
            # Shot attempt, turnover, foul, etc.
            possession.is_resolved = True
        
        # 7. Advance shot clock
        # Each action consumes time based on action type:
        #   DribbleMove: 1.0-2.0 seconds
        #   Pass: 0.5-1.5 seconds
        #   Shot: 1.0-2.0 seconds
        #   Drive: 1.5-3.0 seconds
        #   HoldBall: 2.0-4.0 seconds (running clock, waiting for play to develop)
        shot_clock -= action.time_cost(rng)
        
        if shot_clock <= 0:
            events.append(ShotClockViolationEvent())
            possession.is_resolved = True
        
        # 8. Safety valve: max actions per possession (prevent infinite loops)
        action_count += 1
        if action_count > 30:
            # Force a shot attempt
            action = offensive_ai.force_shot(possession, game)
            result = resolve_action(action, possession, game.modifier_pipeline, rng)
            events.extend(result.events)
            possession.is_resolved = True
    
    # Calculate total time elapsed for this possession
    time_elapsed = game.rules.shot_clock - shot_clock
    
    return PossessionResult(
        events=events,
        time_elapsed=time_elapsed,
        score_change=calculate_score(events),
        offensive_rebound=check_offensive_rebound(events),
    )
```

### Who Has the Ball?

`possession.ball_handler` tracks the current ball handler. It changes when:
- A pass is completed (ball_handler = receiver)
- A steal occurs (possession ends)
- An offensive rebound is grabbed (new possession, ball_handler = rebounder)

The ball handler is the ONLY player whose AI runs the full `offensive_ai.decide()` function each action. Off-ball players follow play assignments or basketball IQ defaults.

### Possession Transitions

```
Made basket ──> Inbound play (other team, ball at D1 baseline)
Missed shot + defensive rebound ──> Transition check: fast break or half-court?
Turnover ──> Transition check: fast break or half-court?
Foul ──> Free throws or side-out depending on type
End of quarter ──> Jump ball / alternating possession
```

Fast break detection:
```python
def check_transition(trigger_event, game_state, rng):
    # Count how many defenders are behind the ball
    offense_speed = avg_speed(game_state.offense_on_court)
    defense_recovery = calculate_recovery(game_state.defense_on_court, trigger_event)
    
    if defense_recovery < 0.4:   # most defenders caught out of position
        return FastBreakState(type="numbers_advantage")  # 2v1, 3v2, etc.
    elif defense_recovery < 0.7:
        return SecondaryBreakState()  # semi-transition
    else:
        return HalfCourtState()  # walk it up
```

---

## Offensive AI: Decision Making

The ball handler's AI uses a **utility scoring system**, not a decision tree. Every possible action gets a score, and the highest-scoring action is chosen (with some randomness to prevent robotic play).

### Action Candidates

Each action, the AI generates a list of candidates:

```python
def decide(possession: PossessionState, game: GameState) -> Action:
    candidates = []
    ball_handler = possession.ball_handler
    matchup = possession.get_matchup(ball_handler)
    
    # Generate all possible actions:
    
    # 1. Dribble moves (from player's repertoire)
    for move_id in ball_handler.move_repertoire:
        move = MOVE_REGISTRY[move_id]
        if meets_requirements(ball_handler, move):
            candidates.append(DribbleMoveCandidate(move=move))
    
    # 2. Shots (if in reasonable position)
    if can_shoot(ball_handler, possession):
        for shot_type in get_available_shots(ball_handler, possession.ball_handler_cell):
            candidates.append(ShotCandidate(shot_type=shot_type))
    
    # 3. Passes (to each teammate)
    for teammate in possession.off_ball_offense:
        if passing_lane_exists(ball_handler, teammate, possession):
            candidates.append(PassCandidate(target=teammate))
    
    # 4. Drives (toward basket)
    for direction in get_drive_lanes(ball_handler, possession):
        candidates.append(DriveCandidate(direction=direction))
    
    # 5. Hold ball (run clock, wait for play to develop)
    candidates.append(HoldBallCandidate())
    
    # Score each candidate
    scored = [(c, score_action(c, possession, game)) for c in candidates]
    
    # Pick with weighted randomness (not always the best -- adds human imperfection)
    return weighted_pick(scored, ball_handler.basketball_iq, game.rng)
```

### Utility Scoring Function

Each candidate is scored on 0-1 scale by combining multiple factors:

```python
def score_action(candidate: ActionCandidate, possession: PossessionState, game: GameState) -> float:
    score = 0.0
    
    if isinstance(candidate, ShotCandidate):
        # Expected points = make_probability * point_value
        make_pct = estimate_shot_probability(candidate, possession)
        expected_points = make_pct * candidate.point_value  # 2 or 3
        score = expected_points / 3.0  # normalize: a wide-open three = ~0.40 * 3 / 3 = 0.40
        
        # Adjustments
        score += shot_clock_pressure(possession)    # boost shots when clock is low
        score += hot_hand_bonus(possession)          # boost when player is hot
        score -= bad_shot_penalty(candidate)          # penalize contested mid-range, etc.
        
    elif isinstance(candidate, PassCandidate):
        teammate = candidate.target
        # How open is the teammate?
        openness = teammate.openness
        # How good a shooter are they?
        teammate_expected = estimate_teammate_shot_value(teammate, possession)
        # Pass risk (turnover chance based on passing lane traffic)
        turnover_risk = estimate_pass_risk(candidate, possession)
        
        score = openness * teammate_expected * (1 - turnover_risk)
        score += hockey_assist_value(teammate, possession)  # teammate might drive, not shoot
        
    elif isinstance(candidate, DribbleMoveCandidate):
        # Value of improving the matchup state
        current_advantage = matchup_advantage_score(possession.get_matchup(possession.ball_handler))
        expected_improvement = estimate_move_improvement(candidate.move, possession)
        
        score = expected_improvement * 0.5  # dribble moves are means to an end, not the end
        score -= turnover_risk(candidate.move, possession) * 0.3
        score += style_tendency(possession.ball_handler, candidate.move)  # player personality
        
    elif isinstance(candidate, DriveCandidate):
        # Can we get to the rim?
        lane_quality = evaluate_driving_lane(candidate.direction, possession)
        finish_probability = estimate_finish_at_rim(possession.ball_handler, possession)
        help_defense_threat = evaluate_help_defense(candidate.direction, possession)
        
        score = lane_quality * finish_probability * (1 - help_defense_threat * 0.5)
        
    elif isinstance(candidate, HoldBallCandidate):
        # Value of waiting: are teammates still moving into position?
        play_development = possession.play_phase_progress  # 0-1, how far into the play call
        score = 0.15 if play_development < 0.5 else 0.05  # worth waiting early, not late
        score += 0.1 if possession.shot_clock > 14 else 0.0  # no rush
    
    return max(0.0, min(1.0, score))
```

### Weighted Pick (Human Imperfection)

The AI doesn't always pick the highest-scoring action. basketball_iq determines how optimal the choice is:

```python
def weighted_pick(scored: list[tuple], basketball_iq: float, rng: random.Random) -> Action:
    # Higher IQ = more likely to pick the best option
    # Lower IQ = more random / prone to bad decisions
    
    # Temperature: low IQ = high temperature (more random), high IQ = low temperature (more greedy)
    temperature = 1.5 - (basketball_iq / 100)  # IQ 90 -> temp 0.6, IQ 60 -> temp 0.9
    
    # Apply softmax-like weighting
    weights = []
    for candidate, score in scored:
        weights.append(score ** (1 / temperature))
    
    total = sum(weights)
    probabilities = [w / total for w in weights]
    
    return rng.choices([c for c, _ in scored], weights=probabilities, k=1)[0]
```

A player with IQ 95 almost always picks the best action. A player with IQ 65 frequently makes suboptimal choices -- taking contested mid-range jumpers, forcing passes into traffic, holding the ball too long. This is how player intelligence manifests in gameplay, not just as a modifier on success rates.

### Tendency Override Layer

After scoring, player tendencies can override the utility calculation:

```python
# Harden has iso_frequency=0.75 and score_first_vs_pass=0.70
# If Harden's AI scores a pass at 0.55 and an ISO move at 0.45,
# the tendency layer can boost the ISO move:
if player.tendencies.iso_frequency > 0.6:
    for candidate in candidates:
        if is_iso_action(candidate):
            candidate.score *= (1 + player.tendencies.iso_frequency * 0.3)

# This means Harden might ISO even when passing is "smarter"
# which is... realistic.
```

---

## State Resolver: The Core Math

The State Resolver is the most critical component -- it takes transition probabilities from JSON, applies the aggregated modifier, rolls dice, and produces new states + tags.

### AggregatedModifier (the most important type in the system)

```python
@dataclass
class Modifier:
    """Output of a single modifier layer."""
    # Per-axis transition boosts: positive = attacker advantage, negative = defender advantage
    # These are ADDITIVE to transition probabilities
    positioning_boost: float = 0.0    # e.g., +0.05 means 5% more likely to advance positioning
    balance_boost: float = 0.0        # e.g., +0.08 means 8% more likely to disrupt balance
    stance_boost: float = 0.0
    rhythm_boost: float = 0.0
    help_boost: float = 0.0
    
    # Shot-specific
    shot_pct_boost: float = 0.0       # direct addition to shot percentage
    
    # Tags contributed by this modifier
    tags: list[str] = field(default_factory=list)

@dataclass
class AggregatedModifier:
    """Combined output of all modifier layers. Simple additive combination."""
    positioning_boost: float = 0.0
    balance_boost: float = 0.0
    stance_boost: float = 0.0
    rhythm_boost: float = 0.0
    help_boost: float = 0.0
    shot_pct_boost: float = 0.0
    tags: list[str] = field(default_factory=list)
    
    def combine(self, mod: Modifier):
        """Additive combination. Order does NOT matter."""
        self.positioning_boost += mod.positioning_boost
        self.balance_boost += mod.balance_boost
        self.stance_boost += mod.stance_boost
        self.rhythm_boost += mod.rhythm_boost
        self.help_boost += mod.help_boost
        self.shot_pct_boost += mod.shot_pct_boost
        self.tags.extend(mod.tags)
```

### Key Design Decisions for Modifier Math

1. **All modifiers are additive.** Fatigue says -0.05 positioning, psychology says +0.03 positioning. Combined: -0.02. Order doesn't matter. No multiplicative chains, no ordering dependency.

2. **Modifiers adjust transition probabilities, not outcomes.** A +0.05 positioning_boost means "add 5 percentage points to the favorable transition probabilities." It doesn't mean "5% more likely to score."

3. **Clamping:** After all modifiers are combined, the total boost per axis is clamped to [-0.25, +0.25]. No combination of modifiers can shift a transition by more than 25 percentage points. This prevents degenerate cases where stacking 7 small boosts produces a guaranteed outcome.

### How Modifiers Apply to Transition Tables

```python
def apply_modifier_to_transitions(
    base_transitions: dict[str, float],  # e.g., {"TRAILING": 0.20, "LOCKED_UP": 0.80}
    boost: float,                         # e.g., +0.07
    favorable_states: list[str],          # e.g., ["TRAILING", "HALF_STEP_BEHIND", "BEATEN", "BLOWN_BY"]
) -> dict[str, float]:
    """
    Redistributes probability from unfavorable to favorable states.
    boost > 0: attacker advantage (more probability flows to favorable states)
    boost < 0: defender advantage (probability flows back to unfavorable states)
    """
    clamped_boost = max(-0.25, min(0.25, boost))
    
    # Split states into favorable (attacker wants) and unfavorable (defender wants)
    favorable_total = sum(base_transitions[s] for s in favorable_states if s in base_transitions)
    unfavorable_states = [s for s in base_transitions if s not in favorable_states]
    unfavorable_total = sum(base_transitions[s] for s in unfavorable_states)
    
    # Redistribute: move probability mass from unfavorable to favorable
    shift = clamped_boost  # direct percentage point shift
    
    result = {}
    for state, prob in base_transitions.items():
        if state in favorable_states:
            # Proportionally distribute the boost among favorable states
            share = prob / favorable_total if favorable_total > 0 else 1.0 / len(favorable_states)
            result[state] = max(0.0, prob + shift * share)
        else:
            # Proportionally remove from unfavorable states
            share = prob / unfavorable_total if unfavorable_total > 0 else 1.0 / len(unfavorable_states)
            result[state] = max(0.0, prob - shift * share)
    
    # Renormalize to sum to 1.0
    total = sum(result.values())
    return {s: p / total for s, p in result.items()}
```

### Full Resolver Flow

```python
def resolve_dribble(move: MoveData, matchup: MatchupState, context: ActionContext, pipeline: ModifierPipeline) -> ActionResult:
    # 1. Get combined modifier (order-independent, additive)
    agg = pipeline.apply(context)
    
    # 2. Resolve each axis independently
    new_positioning = roll_axis(
        base_transitions=move.transitions["positioning"][f"from_{matchup.positioning}"],
        boost=agg.positioning_boost + move.cross_axis_boosts.get(matchup),  # cross-axis from JSON
        favorable_states=["TRAILING", "HALF_STEP_BEHIND", "BEATEN", "BLOWN_BY"],
        rng=context.rng,  # seeded RNG for reproducibility
    )
    new_balance = roll_axis(
        base_transitions=move.transitions["balance"][f"from_{matchup.balance}"],
        boost=agg.balance_boost,
        favorable_states=["SHIFTING", "OFF_BALANCE", "STUMBLING", "ON_FLOOR"],
        rng=context.rng,
    )
    # ... same for stance, rhythm, help
    
    # 3. Generate tags
    tags = list(agg.tags)  # tags from modifiers
    if new_positioning != matchup.positioning:
        tags.extend(move.tags_on_success)
    if new_balance in ["STUMBLING", "ON_FLOOR"]:
        tags.extend(move.tags_on_critical)
    
    # 4. Apply defender recovery (each axis naturally pulls back toward neutral)
    # Recovery is a separate mini-roll that happens AFTER the move resolves
    new_balance = maybe_recover(new_balance, defender.defensive_consistency, context.rng)
    
    # 5. Return result
    return ActionResult(
        new_matchup=MatchupState(new_positioning, new_balance, new_stance, new_rhythm, new_help),
        tags=tags,
        events=[DribbleMoveEvent(move=move.id, result=new_positioning, tags=tags)],
    )
```

---

## Defensive AI Design

Defensive AI is a multi-layered system. Unlike offensive AI which makes one decision at a time (ball handler picks next action), defensive AI involves 5 players making coordinated decisions.

### Architecture: Scheme -> Assignments -> Reactions

```
Coach sets scheme ──> Each defender gets assignment ──> Defenders react to offensive actions
     (pregame)            (each possession)                 (each action within possession)
```

### Layer 1: Defensive Scheme (set by Coach AI)

The scheme is a JSON-defined strategy that determines base behavior for all 5 defenders:

```json
{
  "id": "switch_heavy",
  "name": "Switch Everything",
  "on_screen": "switch",
  "help_threshold": 2,
  "closeout_aggression": 0.7,
  "paint_protection_priority": 0.6,
  "perimeter_priority": 0.8,
  "trap_triggers": ["star_player_iso", "post_mismatch"]
}
```

The coach can change the scheme mid-game based on what's working (this is the coaching modifier's job).

### Layer 2: Individual Assignments (set each possession)

Each defender is assigned:
- **Primary assignment:** which offensive player they guard
- **Help responsibility:** which zone they're responsible for helping in
- **Rotation priority:** if they help, who rotates to cover their man

```python
@dataclass
class DefensiveAssignment:
    defender: Player
    guarding: Player
    help_zone: str           # grid cell or region they help from
    rotation_partner: str    # player_id who covers if this defender helps
    scheme_overrides: dict   # per-player tweaks: "on_screen": "go_over" for this matchup
```

### Layer 3: Reactive Decisions (each action)

When the offense acts, each defender whose situation changed must react. This is NOT 5 independent AI calls -- it's a cascade:

```python
def resolve_defensive_reactions(offensive_action: Action, possession: PossessionState, scheme: DefenseScheme):
    affected = get_affected_defenders(offensive_action, possession)
    
    reactions = []
    for defender_state in affected:
        reaction = pick_reaction(
            defender=defender_state,
            action=offensive_action,
            scheme=scheme,
            grid=possession.grid_state,
        )
        reactions.append(reaction)
    
    # Process help chains: if defender A helps, defender B must rotate
    help_chain = resolve_help_chain(reactions, possession, scheme)
    
    return reactions + help_chain
```

### Help-and-Recover Chains

This is the hardest part. When Harden drives past Thybulle:

1. **Primary defender (Thybulle):** State is BEATEN. Reaction: `RECOVERING` (chasing from behind)
2. **Nearest help (Gobert at D3, 2 cells away):** Checks `help_threshold` from scheme. Harden is in ADVANTAGE state + driving toward paint = triggers help. Reaction: `HELP_ROTATING` toward ball handler's cell.
3. **Gobert's rotation partner (Tucker's defender at G5):** Gobert left Capela. Rotation partner moves toward Capela's cell. Reaction: `ROTATING_TO_COVER`.
4. **Weak-side defender (Gordon's man at F4):** Checks if anyone is now uncovered. Tucker's defender rotated to Capela, so Tucker is now open. Reaction: `SCRAMBLE_TO_COVER` Tucker if close enough, otherwise stays.

This chain is resolved as a sequence, not simultaneously. Each step checks "who's now uncovered?" and assigns the next rotation.

The result updates off-ball openness values:
- Capela: openness goes from 0.2 to 0.5 (Gobert left but rotation partner is coming)
- Tucker: openness goes from 0.3 to 0.7 (his defender rotated, weak-side might not get there)
- Gordon: openness stays at 0.3 (nobody left him)

### Defensive Decision Table

| Offensive Action | Primary Defender Reaction | Help Trigger? | 
|-----------------|--------------------------|---------------|
| Dribble move (no state change) | Hold position | No |
| Dribble move (ADVANTAGE+) | Switch to RECOVERING | Yes, if ball handler near paint |
| Screen set | Scheme lookup: switch/go-over/go-under/trap | Yes, screener's defender adjusts |
| Drive toward paint | Contest or concede based on positioning state | Yes, nearest paint defender |
| Pass to open player | Closest defender CLOSING_OUT | Rotation chain adjusts |
| Shot attempt | Contest if within 1-2 cells | No (too late) |

---

## Off-Ball Player System

The 8 off-ball players (4 offense, 4 defense) are not ghosts. They make decisions between each ball-handler action.

### Off-Ball Offensive Actions

After each ball-handler action resolves, off-ball offensive players evaluate:

```python
@dataclass
class OffBallDecision:
    player: Player
    action: str        # "hold", "relocate", "cut", "screen", "post_up", "space"
    from_cell: str     # current grid cell
    to_cell: str       # target grid cell (if moving)
    priority: float    # how urgent this movement is

def decide_off_ball(player: PlayerOnCourt, possession: PossessionState, play: PlayData) -> OffBallDecision:
    # Priority 1: Follow the play call (if a play is active)
    if play and play.has_assignment(player, possession.phase):
        return play.get_movement(player, possession.phase)
    
    # Priority 2: React to the ball handler's action
    if ball_handler_driving():
        return space_away_from_drive(player, possession)  # clear the lane
    if ball_handler_in_trouble():
        return offer_safety_valve(player, possession)      # get open nearby
    
    # Priority 3: Basketball IQ-driven movement
    if player.tendencies.off_ball_movement_quality > 0.7:
        return find_best_spot(player, possession)  # cut, relocate to open cell
    else:
        return OffBallDecision(action="hold", ...)  # stand and watch (low IQ)
```

### Movement Speed on the Grid

Players move 1 cell per ball-handler action. If the ball handler takes 4 dribble moves, off-ball players can move up to 4 cells. Fast players (speed > 85) can move 2 cells per action in transition/fast break situations.

### Off-Ball Defensive Reactions

Defensive off-ball movement is driven by the help chain system described in the Defensive AI section. After each offensive action:

1. Each defender checks: is my assignment still in the same cell?
2. If assignment moved, defender follows (1 cell per action)
3. If help is needed, scheme determines who helps and rotation chain executes
4. Defenders also track "ball awareness" -- shifting slightly toward the ball side for help positioning

### Off-Ball State Tracking

```python
@dataclass
class OffBallState:
    player: Player
    cell: str                    # grid position
    defender: Player
    defender_cell: str           # defender's grid position
    openness: float              # 0.0 = locked up, 1.0 = wide open
    catch_readiness: float       # 0.0 = moving, 1.0 = set and ready to shoot
    is_cutting: bool
    is_screening: bool
    movement_target: str | None  # cell they're moving toward
    turns_stationary: int        # how long they've been in one spot (affects catch_readiness)
```

Openness is derived from grid distance between the player and their defender:
- Same cell: openness = 0.1 (locked up)
- 1 cell apart: openness = 0.3-0.5 (depending on defender stance)
- 2+ cells apart: openness = 0.6-0.9 (depending on help nearby)

catch_readiness increases each action the player is stationary (feet get set), decreases when moving.

---

## Testing Strategy

### Deterministic Seeding

Every random roll in the engine uses a seeded RNG passed through context, never `random.random()` globally:

```python
@dataclass
class ActionContext:
    rng: random.Random    # seeded per-game, passed everywhere
    # ... other context
    
# Game setup:
rng = random.Random(seed=12345)  # reproducible
context = ActionContext(rng=rng, ...)
```

Same seed = same game, every time. This is non-negotiable for debugging and testing.

### Test Layers

1. **Unit tests (per module):** Each resolver, modifier, AI function tested in isolation. Mock the context, verify output.

2. **Statistical validation:** Run 10,000 actions with known inputs, verify the distribution matches expected probabilities within tolerance:
   ```python
   def test_crossover_transitions():
       results = Counter()
       rng = random.Random(42)
       for _ in range(10000):
           result = resolve_dribble(crossover_move, locked_up_matchup, neutral_context, rng)
           results[result.new_matchup.positioning] += 1
       # Should be ~72% LOCKED_UP, ~20% TRAILING, ~8% HALF_STEP_BEHIND (from JSON)
       assert 0.70 < results["LOCKED_UP"] / 10000 < 0.74
   ```

3. **Integration tests:** Full possession cycle -- action, resolve, emit event, narration produces output, stats update. Verify the pipeline works end-to-end.

4. **Balance regression tests:** After any modifier or data change, run 1,000 games and check that aggregate stats (points per game, FG%, turnovers, etc.) stay within expected NBA ranges. This catches degenerate tuning.

5. **Narration smoke tests:** Every tag combination that can be generated has at least one matching template. No "template not found" errors in production.

---

## Performance Considerations

### Single Game: No Concerns

A single game has ~200 possessions, each with ~5-10 actions. That's ~1,000-2,000 action resolutions per game. Each resolution runs 7 modifiers + 5 axis rolls + tag generation + event emission. On modern hardware, this completes in under 1 second in Python. Narration adds negligible overhead.

### Season Simulation (1,230+ games)

For season mode (Phase 6), two strategies:

1. **Narration-off mode:** Skip the narration pipeline entirely. Just resolve actions, accumulate stats, emit minimal events. This cuts per-game cost significantly. Most season games don't need play-by-play -- just box scores and standings.

2. **Simplified resolution for background games:** For games the user isn't watching, use a simplified resolver that skips the per-action loop entirely and simulates possession-level outcomes based on team strength differentials. This is ~100x faster. The full action-by-action engine only runs for games the user watches.

3. **Future optimization:** If Python becomes a bottleneck for bulk simulation (tens of thousands of seasons for analysis), the resolver math is pure numerical logic that can be ported to a Cython/Rust extension without changing the architecture. The modifier pipeline interface stays the same.

### Profiling Requirement

Phase 1 includes a simple timing harness: log time per action resolution, per game, per possession. This catches performance regressions early before they compound.

---

## Save/Load and Serialization

### Design Requirement

All game state must be serializable for:
- Season mode persistence (save mid-season, resume later)
- Replay system (save game events, replay them through narration later)
- Mod sharing (export/import game states)

### Approach

All state objects are frozen dataclasses or Pydantic models. Serialization is built in:

```python
from dataclasses import dataclass, asdict
import json

@dataclass
class GameState:
    home_team: TeamState
    away_team: TeamState
    quarter: int
    clock: float
    possession: PossessionState
    score: dict[str, int]
    events: list[GameEvent]
    rng_state: tuple      # save RNG state for reproducibility
    
    def save(self, path: str):
        json.dump(asdict(self), open(path, 'w'))
    
    @classmethod
    def load(cls, path: str) -> 'GameState':
        data = json.load(open(path))
        return cls(**data)  # Pydantic handles nested deserialization
```

### What Gets Saved

- **Mid-game save:** Full GameState including RNG state (can resume and get identical results)
- **Season save:** All team records, player stats, schedule, playoff bracket, player mental states, fatigue accumulation
- **Replay save:** Just the seed + roster data. Replay deterministically regenerates the entire game.

---

## Key Architectural Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Modder accessibility, data science ecosystem, bridges to game engines later |
| Court model | 7x9 chess grid | Spatial reasoning without physics. Maps to 2D sprite tiles. Modders can draw plays on the grid. |
| Matchup system | Multi-axis State + Tags | States model how basketball is perceived. Tags drive narration directly. Multiple axes capture nuance without continuous float tuning. |
| Maintainability | Modifier pipeline + event bus | Every layer is independent. Adding depth = adding files. No layer knows other layers exist. |
| Realism approach | Deep input layers feeding simple resolver | Realism comes from psychology, fatigue, chemistry, coaching, tendencies -- not from physics. This is how you beat 2K. |
| Mod system | Auto-discovered JSON + Python from mods/ folder | Zero existing code modified to add a mod. JSON for data, Python for logic. |
| Narration | 4-stage pipeline with tag-driven templates | Tags ARE narration fragments. No translating abstract numbers to words. Announcers are JSON profiles. |
