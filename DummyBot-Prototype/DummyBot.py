from __future__ import annotations

from dataclasses import dataclass, field

import pygame


Vec2 = pygame.Vector2


@dataclass
class DummyBot:
    """The intentionally simple sparring partner used by character prototypes."""

    pos: Vec2
    vel: Vec2 = field(default_factory=lambda: Vec2(-190, -95))
    radius: float = 46.0
    hp: float = 5000.0
    max_hp: float = 5000.0
    punch_timer: float = 0.0
    punch_anim: float = 0.0
    punch_dir: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    punch_target: Vec2 = field(default_factory=Vec2)
    redirect_timer: float = 3.0
    redirects: int = 3
    hit_flash: float = 0.0
    squash: float = 0.0
    frozen: float = 0.0
    slowed: float = 0.0
    burned: float = 0.0
    stunned: float = 0.0
    burn_tick: float = 0.0
    ice_stacks: int = 0
    heat_stacks: int = 0
    heat_decay_timer: float = 0.0
    thermal_shock_locked: bool = False
    ice_break_warned: bool = False
    facing: Vec2 = field(default_factory=lambda: Vec2(-1, 0))

    def update_timers(self, dt: float) -> None:
        self.punch_timer = max(0.0, self.punch_timer - dt)
        self.punch_anim = max(0.0, self.punch_anim - dt)
        self.redirect_timer -= dt
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.squash = max(0.0, self.squash - dt * 4.5)
        self.frozen = max(0.0, self.frozen - dt)
        self.slowed = max(0.0, self.slowed - dt)
        self.burned = max(0.0, self.burned - dt)
        self.stunned = max(0.0, self.stunned - dt)
        if self.heat_stacks:
            self.heat_decay_timer -= dt
            if self.heat_decay_timer <= 0:
                self.heat_stacks -= 1
                self.heat_decay_timer = 4.5 if self.heat_stacks else 0.0
                if not self.heat_stacks:
                    self.thermal_shock_locked = False
        if self.redirect_timer <= 0:
            self.redirect_timer = 10.0
            self.redirects = 3

    @property
    def speed_scale(self) -> float:
        if self.frozen > 0 or self.stunned > 0:
            return 0.0
        return 0.25 if self.slowed > 0 else 1.0

    def take_damage(self, amount: float) -> float:
        if self.frozen > 0:
            amount *= 1.1
        self.hp = max(0.0, self.hp - amount)
        self.hit_flash = 0.12
        self.squash = 0.5
        return amount

    def add_ice(self, amount: int) -> bool:
        if self.ice_stacks >= 3:
            self.ice_stacks = 0
            self.frozen = 5.0
            self.ice_break_warned = False
            return True
        self.ice_stacks = min(3, self.ice_stacks + amount)
        return False

    def add_heat(self, amount: int) -> bool:
        previous = self.heat_stacks
        self.heat_stacks = min(3, self.heat_stacks + amount)
        self.heat_decay_timer = 4.5
        if previous < 3 and self.heat_stacks == 3:
            self.burned = 7.0
            self.burn_tick = 0.05
            return True
        return False

    def should_thermal_shock(self) -> bool:
        if not self.ice_stacks or not self.heat_stacks:
            self.thermal_shock_locked = False
            return False
        if self.thermal_shock_locked:
            return False
        self.thermal_shock_locked = True
        return True

    def alive(self) -> bool:
        return self.hp > 0


if __name__ == "__main__":
    print("DummyBot is a shared sparring class. Run a completed character prototype to watch the fight.")
