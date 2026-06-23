# Tournament Character Adapters

`main.py` discovers character folders from `*-Prototype/*-Datas.txt`.
Characters are eligible when their prototype status appears in
`tournament-settings.json`, they are not excluded, and a tournament adapter
exists in `main.py`.

## Required Prototype Contract

Every tournament-ready character needs:

- A character dataclass containing `pos`, `vel`, `radius`, `hp`, `max_hp`,
  `facing`, `hit_flash`, and `squash`.
- A standalone battle/controller class that owns the character's combat
  logic, effects, sounds, and animation state.
- A target field that supports the shared DummyBot status API.
- Character-specific effect drawing methods that can render without drawing
  another arena or HUD.
- Reusable `draw_world_effects()` and character foreground/aura methods so
  the tournament uses the prototype's full VFX rather than approximations.
- A new `make_slot()` adapter entry in `main.py`.
- Character effect branches in `draw_*_effects()`, `draw_fighter()`, and
  `draw_foreground()`.

## Ownership Rules

The tournament runtime owns:

- Eligible-character discovery
- Match selection and championship score
- Shared arena and HUD
- Match clock and round transitions
- Independent randomized opening directions toward the opponent-side wall
- Opponent-state synchronization
- Cross-character HP and status transfer

Character controllers own:

- Basic attacks, skills, and passives
- Cooldowns and character-specific state
- Damage calculations
- Sounds, particles, animations, and VFX

## Shared Status Semantics

- **Freeze and Stun:** Identical activation and normal-movement locks. The
  affected fighter cannot begin a new attack, skill, passive, or other action.
  Anything already deployed before the lock, including channels, projectiles,
  creatures, hazards, portals, dashes, and grab/stab sequences, continues
  updating and finishes normally.
- **Immobilize:** Normal position movement is locked, including collision
  separation, but the fighter may still begin non-position-shifting actions.
  Anything already deployed, including an action's forced movement, continues
  updating and finishes normally.
- **Slow:** Movement distance is reduced to 25%.
- **Burn:** Tournament-authoritative damage prevents duplicated ticks between
  character controllers.
- Status durations are tournament-authoritative, so simultaneous disabled
  fighters cannot deadlock each other's timers.

## Rendering Rules

- Never redraw a simplified tournament copy of a character effect.
- Add reusable render methods to the character prototype and call those from
  the tournament adapter.
- The tournament owns shared status overlays, the arena, match HUD, and screen
  shake composition.

## Current Adapters

- MoroZhar
- DarkLord
- Naruto

DummyBot remains a reusable prototype/testing target and is excluded from
tournaments.
