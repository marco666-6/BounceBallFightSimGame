from __future__ import annotations

import argparse
import math
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "DummyBot-Prototype"))
sys.path.insert(0, str(ROOT / "Prototype-Shared"))
from DummyBot import DummyBot  # noqa: E402
import visuals as shared  # noqa: E402

W, H = 1280, 720
FPS = 120
ARENA = pygame.Rect(72, 112, W - 144, H - 184)
Vec2 = pygame.Vector2

ICE = (90, 220, 255)
ICE_WHITE = (220, 250, 255)
HEAT = (255, 75, 34)
GOLD = (255, 205, 92)
INK = (7, 10, 22)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def vlerp(a: Vec2, b: Vec2, t: float) -> Vec2:
    return a + (b - a) * t


def safe_normal(v: Vec2, fallback=Vec2(1, 0)) -> Vec2:
    return v.normalize() if v.length_squared() > 0.001 else Vec2(fallback)


def mix(c1, c2, t):
    if not isinstance(c1, (tuple, list)) or not isinstance(c2, (tuple, list)):
        c1 = (255, 255, 255) if not isinstance(c1, (tuple, list)) else c1
        c2 = (255, 255, 255) if not isinstance(c2, (tuple, list)) else c2
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1[:3], c2[:3]))


def glow_circle(dst, pos, radius, color, strength=1.0):
    radius = max(2, int(radius))
    size = radius * 4
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    center = size // 2
    for i in range(5, 0, -1):
        r = int(radius * (0.45 + i * 0.32))
        alpha = int(10 * strength * (6 - i))
        pygame.draw.circle(surf, (*color, alpha), (center, center), r)
    pygame.draw.circle(
        surf, (*color, int(110 * strength)), (center, center), max(1, radius // 2)
    )
    dst.blit(surf, (pos[0] - center, pos[1] - center), special_flags=pygame.BLEND_ADD)


def line_glow(dst, a, b, color, width=4, alpha=255):
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    for mul, al in ((5, 18), (3, 35), (2, 65), (1, alpha)):
        pygame.draw.line(surf, (*color, al), a, b, max(1, int(width * mul)))
    dst.blit(surf, (0, 0), special_flags=pygame.BLEND_ADD)


def ray_rect_distance(origin: Vec2, direction: Vec2, rect: pygame.Rect) -> float:
    distances = []
    if direction.x > 0:
        distances.append((rect.right - origin.x) / direction.x)
    elif direction.x < 0:
        distances.append((rect.left - origin.x) / direction.x)
    if direction.y > 0:
        distances.append((rect.bottom - origin.y) / direction.y)
    elif direction.y < 0:
        distances.append((rect.top - origin.y) / direction.y)
    valid = [d for d in distances if d >= 0]
    return min(valid) if valid else 0.0


def ray_circle_hit_distance(origin: Vec2, direction: Vec2, center: Vec2, radius: float):
    rel = center - origin
    along = rel.dot(direction)
    if along <= 0:
        return None
    perpendicular_sq = rel.length_squared() - along * along
    if perpendicular_sq > radius * radius:
        return None
    return along - math.sqrt(max(0, radius * radius - perpendicular_sq))


@dataclass
class Particle:
    pos: Vec2
    vel: Vec2
    life: float
    max_life: float
    size: float
    color: tuple
    kind: str = "orb"
    drag: float = 0.94

    def update(self, dt):
        self.life -= dt
        self.pos += self.vel * dt
        self.vel *= self.drag ** (dt * 60)
        if self.kind == "spark":
            self.vel.y += 170 * dt
        elif self.kind == "frost":
            self.vel.y -= 18 * dt

    def draw(self, dst, offset):
        t = clamp(self.life / self.max_life, 0, 1)
        p = self.pos + offset
        if isinstance(self.color, (tuple, list)) and len(self.color) >= 3:
            color = tuple(self.color[:3])
        else:
            color = (255, 255, 255)
        if self.kind == "spark":
            tail = p - safe_normal(self.vel) * self.size * 3
            pygame.draw.line(
                dst,
                mix(color, (255, 255, 255), 0.35),
                tail,
                p,
                max(1, int(self.size * t)),
            )
        elif self.kind == "wind":
            direction = safe_normal(self.vel)
            tail = p - direction * self.size * (5 + t * 6)
            q = Vec2(-direction.y, direction.x)
            pygame.draw.line(
                dst, (*color, int(150 * t)), tail, p, max(1, int(self.size * 0.35))
            )
            pygame.draw.line(dst, (*ICE_WHITE, int(70 * t)), tail + q * 2, p + q * 2, 1)
        elif self.kind == "ring":
            pygame.draw.circle(
                dst,
                (*color, int(180 * t)),
                p,
                int(self.size * (2 - t)),
                max(1, int(3 * t)),
            )
        elif self.kind == "shard":
            d = safe_normal(self.vel)
            q = Vec2(-d.y, d.x)
            pts = [
                p + d * self.size * 2,
                p - d * self.size,
                p + q * self.size * 0.6,
                p - q * self.size * 0.6,
            ]
            pygame.draw.polygon(dst, (*color, int(220 * t)), pts)
        else:
            glow_circle(dst, p, self.size * (0.4 + t * 0.7), color, t)


@dataclass
class FloatText:
    text: str
    pos: Vec2
    color: tuple
    life: float = 0.9
    big: bool = False

    def update(self, dt):
        self.life -= dt
        self.pos.y -= 42 * dt


@dataclass
class MoroZhar:
    pos: Vec2
    vel: Vec2 = field(default_factory=lambda: Vec2(250, 125))
    radius: float = 48
    hp: float = 5000
    max_hp: float = 5000
    facing: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    attack_timer: float = 0.4
    breath_timer: float = 2.0
    vision_timer: float = 5.2
    redirect_timer: float = 4.0
    redirects: int = 3
    redirect_boost: float = 0
    hit_flash: float = 0
    squash: float = 0
    roll: float = 0
    punch_anim: float = 0
    punch_kind: str = "PUNCH"
    punch_dir: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    punch_target: Vec2 = field(default_factory=Vec2)
    next_punch: str = "ICE PUNCH"

    def update_timers(self, dt):
        boost_before = self.redirect_boost
        self.attack_timer -= dt
        self.breath_timer -= dt
        self.vision_timer -= dt
        self.redirect_timer -= dt
        self.redirect_boost = max(0, self.redirect_boost - dt)
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 5)
        self.punch_anim = max(0, self.punch_anim - dt)
        self.roll += self.vel.length() * dt / self.radius
        if boost_before > 0 and self.redirect_boost <= 0:
            self.vel /= 1.35
        if self.redirect_timer <= 0:
            self.redirect_timer = 10
            self.redirects = 3


class SoundBank:
    def __init__(self, muted=False):
        self.sounds = {}
        self.muted = muted
        if muted:
            return
        try:
            pygame.mixer.init()
            paths = {
                "punch": ROOT / "MoroZhar-SoundEffects" / "MoroZhar-Punch.mp3",
                "ice_punch": ROOT / "MoroZhar-SoundEffects" / "MoroZhar-Ice Punch.mp3",
                "heat_punch": ROOT / "MoroZhar-SoundEffects" / "MoroZhar-HeatPunch.mp3",
                "breath": ROOT
                / "MoroZhar-SoundEffects"
                / "MoroZhar-FreezingBreath.mp3",
                "ice_break": ROOT
                / "MoroZhar-SoundEffects"
                / "MoroZhar-IceBreakForEnemy.mp3",
                "vision1": ROOT
                / "MoroZhar-SoundEffects"
                / "MoroZhar-HeatVisionOneStack.mp3",
                "vision2": ROOT
                / "MoroZhar-SoundEffects"
                / "MoroZhar-HeatVisionTwoStack.mp3",
                "vision3": ROOT
                / "MoroZhar-SoundEffects"
                / "MoroZhar-HeatVisionThreeStack.mp3",
                "dummy_punch": ROOT / "DummyBot-SoundEffects" / "MoroZhar-Punch.mp3",
            }
            for key, path in paths.items():
                sound = pygame.mixer.Sound(path)
                sound.set_volume(0.42 if "vision" not in key else 0.32)
                self.sounds[key] = sound
        except pygame.error:
            self.muted = True

    def play(self, name):
        if not self.muted and name in self.sounds:
            self.sounds[name].play()


class Battle:
    def __init__(self, muted=False):
        self.moro = MoroZhar(Vec2(290, 385))
        self.dummy = DummyBot(Vec2(985, 385))
        self.particles = []
        self.texts = []
        self.sound = SoundBank(muted)
        self.time = 0
        self.shake = 0
        self.hit_stop = 0
        self.vision = 0
        self.vision_duration = 0
        self.vision_tick = 0
        self.vision_hits = 0
        self.vision_angle = 0
        self.vision_end = Vec2()
        self.vision_hit_target = False
        self.breath = 0
        self.breath_dir = Vec2(1, 0)
        self.round_over = 0
        self.winner = ""
        self.banner = "AUTONOMOUS COMBAT PROTOTYPE"
        self.banner_time = 2.8
        self.actions_locked = False
        self.roll_next_punch()

    def burst(self, pos, color, amount=18, speed=280, kind="spark", size=4):
        for _ in range(amount):
            a = random.random() * math.tau
            s = speed * random.uniform(0.25, 1)
            self.particles.append(
                Particle(
                    Vec2(pos),
                    Vec2(math.cos(a), math.sin(a)) * s,
                    random.uniform(0.25, 0.7),
                    0.7,
                    random.uniform(size * 0.5, size * 1.5),
                    color,
                    kind,
                )
            )

    def text(self, text, pos, color, big=False):
        self.texts.append(FloatText(text, Vec2(pos), color, 1.0 if big else 0.75, big))

    def impact(self, pos, color, power=1):
        self.shake = max(self.shake, 5 + power * 4)
        self.hit_stop = max(self.hit_stop, 0.018 + power * 0.018)
        self.burst(pos, color, 12 + power * 7, 220 + power * 100, "spark", 3 + power)
        self.particles.append(
            Particle(Vec2(pos), Vec2(), 0.3, 0.3, 18 + power * 5, color, "ring")
        )

    def damage_dummy(self, amount, label="", color=GOLD, power=1):
        dealt = self.dummy.take_damage(amount)
        self.text(
            f"-{int(dealt)}" + (f"  {label}" if label else ""),
            self.dummy.pos + Vec2(0, -62),
            color,
            power > 1,
        )
        self.impact(self.dummy.pos, color, power)

    def damage_moro(self, amount):
        self.moro.hp = max(0, self.moro.hp - amount)
        self.moro.hit_flash = 0.12
        self.text(f"-{int(amount)}", self.moro.pos + Vec2(0, -62), (220, 225, 235))
        self.impact(self.moro.pos, (200, 210, 220), 1)

    def freeze(self):
        self.text("FROZEN", self.dummy.pos + Vec2(0, -88), ICE_WHITE, True)
        healed = min(100, self.moro.max_hp - self.moro.hp)
        self.moro.hp += healed
        if healed > 0:
            self.text(
                f"+{int(healed)} HP", self.moro.pos + Vec2(0, -72), ICE_WHITE, True
            )
        self.burst(self.dummy.pos, ICE, 42, 360, "shard", 6)
        for _ in range(28):
            p = self.dummy.pos + Vec2(random.uniform(-58, 58), random.uniform(-58, 58))
            self.particles.append(
                Particle(
                    p,
                    safe_normal(self.dummy.pos - p) * random.uniform(55, 150),
                    0.55,
                    0.55,
                    random.uniform(3, 7),
                    ICE_WHITE,
                    "frost",
                )
            )
        self.shake = 12

    def warn_ice_break(self):
        self.dummy.ice_break_warned = True
        self.sound.play("ice_break")
        self.text("ICE CRACKING", self.dummy.pos + Vec2(0, -96), ICE_WHITE, True)
        self.burst(self.dummy.pos, ICE_WHITE, 14, 180, "shard", 4)

    def shatter_ice(self):
        self.text("THAWED", self.dummy.pos + Vec2(0, -90), ICE_WHITE, True)
        self.burst(self.dummy.pos, ICE_WHITE, 58, 520, "shard", 7)
        self.burst(self.dummy.pos, ICE, 25, 260, "frost", 5)
        self.shake = max(self.shake, 10)
        self.hit_stop = max(self.hit_stop, 0.045)

    def burn(self):
        self.text("IGNITED", self.dummy.pos + Vec2(0, -88), HEAT, True)
        self.burst(self.dummy.pos, HEAT, 25, 250, "orb", 6)

    def thermal_shock(self):
        self.damage_dummy(50, "THERMAL SHOCK", (255, 245, 215), 3)
        self.burst(self.dummy.pos, ICE, 20, 410, "shard", 5)
        self.burst(self.dummy.pos, HEAT, 20, 410, "spark", 5)

    def roll_next_punch(self):
        roll = random.random()
        if roll < 0.1:
            self.moro.next_punch = "PUNCH"
        elif roll < 0.45:
            self.moro.next_punch = "ICE PUNCH"
        else:
            self.moro.next_punch = "HEAT PUNCH"

    def punch(self):
        d = self.dummy
        kind = self.moro.next_punch
        if kind == "PUNCH":
            kind, damage, color, sound = "PUNCH", 150, (245, 245, 255), "punch"
        elif kind == "ICE PUNCH":
            kind, damage, color, sound = "ICE PUNCH", 60, ICE, "ice_punch"
        else:
            kind, damage, color, sound = "HEAT PUNCH", 65, HEAT, "heat_punch"
        self.moro.attack_timer = 0.5
        self.moro.punch_anim = 0.52
        self.moro.punch_kind = kind
        self.moro.punch_target = Vec2(d.pos)
        base_angle = math.degrees(
            math.atan2(d.pos.y - self.moro.pos.y, d.pos.x - self.moro.pos.x)
        )
        self.moro.punch_dir = Vec2(1, 0).rotate(
            base_angle + random.choice((-145, -105, -65, 65, 105, 145))
        )
        self.sound.play(sound)
        self.damage_dummy(damage, kind, color, 2)
        if kind == "ICE PUNCH" and d.add_ice(1):
            self.freeze()
        elif kind == "HEAT PUNCH":
            healed = min(12, self.moro.max_hp - self.moro.hp)
            self.moro.hp += healed
            if healed > 0:
                self.text(f"+{healed:g} HP", self.moro.pos + Vec2(0, -72), HEAT)
            if d.add_heat(1):
                self.burn()
        if d.should_thermal_shock():
            self.thermal_shock()
        self.roll_next_punch()

    def cast_breath(self):
        self.moro.breath_timer = 7.5
        self.breath = 0.82
        self.breath_dir = safe_normal(self.moro.vel)
        self.sound.play("breath")
        self.text("FREEZING BREATH", self.moro.pos + Vec2(0, -80), ICE_WHITE, True)
        if self.dummy.pos.distance_to(self.moro.pos) < 430:
            self.damage_dummy(150, "FREEZING BREATH", ICE, 2)
            self.dummy.slowed = 3
            if self.dummy.add_ice(2):
                self.freeze()

    def cast_vision(self):
        stacks = max(1, self.dummy.heat_stacks)
        durations = {1: 2.0, 2: 3.5, 3: 7.0}
        self.vision_duration = durations[stacks]
        self.vision = self.vision_duration
        self.vision_tick = 0.05
        self.vision_hits = 0
        self.moro.vision_timer = 7.5 + self.vision_duration
        self.dummy.heat_stacks = 0
        self.dummy.heat_decay_timer = 0
        self.dummy.thermal_shock_locked = False
        self.sound.play(f"vision{stacks}")
        self.text(
            f"HEAT VISION  //  LEVEL {stacks}", self.moro.pos + Vec2(0, -82), HEAT, True
        )

    def wall_bounce(self, fighter, seek_target, away=False):
        bounced = False
        if (
            fighter.pos.x - fighter.radius < ARENA.left
            or fighter.pos.x + fighter.radius > ARENA.right
        ):
            fighter.pos.x = clamp(
                fighter.pos.x, ARENA.left + fighter.radius, ARENA.right - fighter.radius
            )
            fighter.vel.x *= -1
            bounced = True
        if (
            fighter.pos.y - fighter.radius < ARENA.top
            or fighter.pos.y + fighter.radius > ARENA.bottom
        ):
            fighter.pos.y = clamp(
                fighter.pos.y, ARENA.top + fighter.radius, ARENA.bottom - fighter.radius
            )
            fighter.vel.y *= -1
            bounced = True
        if bounced:
            fighter.squash = 0.45
            self.burst(fighter.pos, (130, 170, 230), 7, 150, "spark", 2)
            if fighter.redirects > 0 and not (
                fighter is self.moro and self.actions_locked
            ):
                direction = safe_normal(seek_target.pos - fighter.pos)
                if away:
                    direction *= -1
                speed = fighter.vel.length()
                if fighter is self.moro:
                    if fighter.redirect_boost <= 0:
                        speed *= 1.35
                    fighter.redirect_boost = 2.5
                fighter.vel = direction * speed
                fighter.redirects -= 1
                label = "REDIRECT  x1.35 SPEED" if fighter is self.moro else "REDIRECT"
                self.text(
                    label,
                    fighter.pos + Vec2(0, -58),
                    ICE if not away else (190, 195, 205),
                )

    def update(self, dt):
        self.time += dt
        self.banner_time -= dt
        self.shake = max(0, self.shake - dt * 30)
        if self.round_over:
            self.round_over -= dt
            if self.round_over <= 0:
                self.__init__(self.sound.muted)
            return
        if self.hit_stop > 0:
            self.hit_stop -= dt
            return

        m, d = self.moro, self.dummy
        m.update_timers(dt)
        frozen_before = d.frozen
        d.update_timers(dt)
        if frozen_before > 2 >= d.frozen and not d.ice_break_warned:
            self.warn_ice_break()
        if frozen_before > 0 and d.frozen <= 0:
            self.shatter_ice()

        to_d = safe_normal(d.pos - m.pos)
        m.facing = vlerp(m.facing, safe_normal(m.vel), min(1, dt * 8)).normalize()
        d.facing = vlerp(d.facing, safe_normal(d.vel), min(1, dt * 8)).normalize()
        m.pos += m.vel * dt
        d.pos += d.vel * d.speed_scale * dt
        self.wall_bounce(m, d)
        self.wall_bounce(d, m, True)

        delta = d.pos - m.pos
        distance = delta.length()
        if distance < m.radius + d.radius:
            n = safe_normal(delta)
            overlap = m.radius + d.radius - distance
            m.pos -= n * overlap * 0.5
            d.pos += n * overlap * 0.5
            m_speed, d_speed = m.vel.length(), d.vel.length()
            m.vel = safe_normal(m.vel.reflect(n)) * m_speed
            d.vel = safe_normal(d.vel.reflect(n)) * d_speed
            m.squash = d.squash = 0.35
            if m.attack_timer <= 0 and not self.actions_locked:
                self.punch()
            if d.punch_timer <= 0 and d.frozen <= 0:
                d.punch_timer = 1.0
                d.punch_anim = 0.42
                d.punch_target = Vec2(m.pos)
                base_angle = math.degrees(
                    math.atan2(m.pos.y - d.pos.y, m.pos.x - d.pos.x)
                )
                d.punch_dir = Vec2(1, 0).rotate(
                    base_angle + random.choice((-125, -75, 75, 125))
                )
                self.sound.play("dummy_punch")
                self.damage_moro(255)

        forward = safe_normal(m.vel)
        in_breath_cone = distance < 430 and forward.dot(to_d) > math.cos(
            math.radians(28)
        )
        if (
            m.breath_timer <= 0
            and self.breath <= 0
            and self.vision <= 0
            and in_breath_cone
            and not self.actions_locked
        ):
            self.cast_breath()
        vision_should_cast = d.heat_stacks == 3 or m.vision_timer <= -2.5
        if (
            m.vision_timer <= 0
            and d.heat_stacks > 0
            and vision_should_cast
            and self.vision <= 0
            and self.breath <= 0
            and not self.actions_locked
        ):
            self.cast_vision()

        if self.breath > 0:
            self.breath -= dt
            origin = m.pos + self.breath_dir * 42
            q = Vec2(-self.breath_dir.y, self.breath_dir.x)
            for _ in range(22):
                along = random.random()
                center = origin + self.breath_dir * (along * 430)
                lateral = random.uniform(-1, 1) * along * 130
                pos = center + q * lateral
                flow = self.breath_dir.rotate(random.uniform(-8, 8)) * random.uniform(
                    220, 480
                )
                flow += q * random.uniform(-55, 55)
                color = ICE_WHITE if random.random() < 0.42 else ICE
                roll = random.random()
                kind = "wind" if roll < 0.72 else ("shard" if roll < 0.86 else "frost")
                self.particles.append(
                    Particle(
                        pos,
                        flow,
                        random.uniform(0.3, 0.75),
                        0.75,
                        random.uniform(2, 6),
                        color,
                        kind,
                    )
                )

        if self.vision > 0:
            self.vision -= dt
            desired = math.atan2(d.pos.y - m.pos.y, d.pos.x - m.pos.x)
            diff = (desired - self.vision_angle + math.pi) % math.tau - math.pi
            self.vision_angle += clamp(diff, -dt * 1.75, dt * 1.75)
            beam_dir = Vec2(math.cos(self.vision_angle), math.sin(self.vision_angle))
            origin = m.pos + beam_dir * 40
            wall_distance = ray_rect_distance(origin, beam_dir, ARENA)
            target_distance = ray_circle_hit_distance(
                origin, beam_dir, d.pos, d.radius + 12
            )
            self.vision_hit_target = (
                target_distance is not None and target_distance <= wall_distance
            )
            beam_distance = target_distance if self.vision_hit_target else wall_distance
            self.vision_end = origin + beam_dir * beam_distance
            if self.vision_hit_target:
                self.vision_tick -= dt
                if self.vision_tick <= 0:
                    self.vision_tick = 0.35
                    self.vision_hits += 1
                    self.damage_dummy(40, "HEAT VISION", HEAT, 1)
                    healed = min(12, m.max_hp - m.hp)
                    m.hp += healed
                    if healed > 0:
                        self.text(f"+{healed:g} HP", m.pos + Vec2(0, -72), HEAT)
                    if self.vision_hits % 2 == 0 and d.add_heat(1):
                        self.burn()
                    if d.should_thermal_shock():
                        self.thermal_shock()
                for _ in range(3):
                    self.particles.append(
                        Particle(
                            Vec2(self.vision_end),
                            Vec2(random.uniform(-150, 150), random.uniform(-150, 150)),
                            0.25,
                            0.25,
                            random.uniform(2, 5),
                            HEAT,
                            "spark",
                        )
                    )
            for _ in range(4):
                p = origin + beam_dir * random.uniform(0, max(1, beam_distance))
                side = Vec2(-beam_dir.y, beam_dir.x) * random.uniform(-18, 18)
                self.particles.append(
                    Particle(
                        p + side,
                        -beam_dir * random.uniform(30, 90),
                        0.22,
                        0.22,
                        random.uniform(2, 5),
                        mix(HEAT, GOLD, random.random()),
                        "orb",
                    )
                )

        if d.burned > 0:
            d.burn_tick -= dt
            if d.burn_tick <= 0:
                d.burn_tick = 0.5
                self.damage_dummy(32, "BURN", HEAT, 1)
                healed = min(7, self.moro.max_hp - self.moro.hp)
                self.moro.hp += healed
                if healed > 0:
                    self.text(f"+{healed:g} HP", self.moro.pos + Vec2(0, -72), HEAT)
            if random.random() < dt * 20:
                self.particles.append(
                    Particle(
                        d.pos + Vec2(random.uniform(-30, 30), random.uniform(-20, 30)),
                        Vec2(random.uniform(-20, 20), random.uniform(-120, -70)),
                        0.5,
                        0.5,
                        random.uniform(4, 8),
                        HEAT,
                        "orb",
                    )
                )
        if d.frozen > 0 and random.random() < dt * 12:
            self.particles.append(
                Particle(
                    d.pos + Vec2(random.uniform(-42, 42), random.uniform(-42, 42)),
                    Vec2(random.uniform(-15, 15), -30),
                    0.6,
                    0.6,
                    random.uniform(3, 6),
                    ICE,
                    "frost",
                )
            )

        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        for t in self.texts:
            t.update(dt)
        self.texts = [t for t in self.texts if t.life > 0]

        if not d.alive() or m.hp <= 0:
            self.winner = "MOROZHAR WINS" if d.hp <= 0 else "DUMMYBOT WINS"
            self.round_over = 5.0
            self.shake = 18

    def draw_background(self, dst, offset):
        shared.draw_arena(dst, ARENA, W, H, self.time, offset)

    def draw_world_effects(self, dst, offset):
        if self.breath > 0:
            origin = self.moro.pos + self.breath_dir * 38 + offset
            q = Vec2(-self.breath_dir.y, self.breath_dir.x)
            wind = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(54):
                along = (i * 0.081 + self.time * (0.28 + i % 4 * 0.025)) % 1
                center = origin + self.breath_dir * along * 430
                lateral = math.sin(i * 8.37 + self.time * (3.3 + i % 3)) * along * 126
                p = center + q * lateral
                length = 10 + along * 34 + i % 5 * 3
                tail = p - self.breath_dir * length
                color = ICE_WHITE if i % 3 else ICE
                pygame.draw.line(
                    wind, (*color, 42 + i % 4 * 12), tail, p, 1 + (i % 7 == 0)
                )
                if i % 4 == 0:
                    pygame.draw.circle(wind, (*ICE_WHITE, 34), p, 2 + i % 4)
            dst.blit(wind, (0, 0))
        if self.vision > 0:
            beam = Vec2(math.cos(self.vision_angle), math.sin(self.vision_angle))
            a = self.moro.pos + beam * 40 + offset
            b = self.vision_end + offset
            line_glow(dst, a, b, (255, 40, 12), 7 + math.sin(self.time * 35) * 1.5)
            pygame.draw.line(dst, (255, 165, 70), a, b, 4)
            pygame.draw.line(dst, (255, 245, 220), a, b, 1)
            beam_q = Vec2(-beam.y, beam.x)
            for side in (-1, 1):
                wave = beam_q * side * (7 + math.sin(self.time * 18 + side) * 2)
                pygame.draw.line(dst, (255, 82, 28, 120), a + wave, b + wave, 2)
            glow_circle(
                dst,
                b,
                18 if self.vision_hit_target else 11,
                HEAT,
                0.8 if self.vision_hit_target else 0.38,
            )
        for particle in self.particles:
            particle.draw(dst, offset)

    def draw_character_aura(self, dst, offset):
        punch_colors = {"PUNCH": (225, 230, 240), "ICE PUNCH": ICE, "HEAT PUNCH": HEAT}
        tell_color = punch_colors[self.moro.next_punch]
        tell_pos = self.moro.pos + offset
        tell_radius = int(self.moro.radius + 10 + math.sin(self.time * 7) * 3)
        glow_circle(dst, tell_pos, 24, tell_color, 0.12)
        start = self.time * 2.8
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.arc(
            layer,
            (*tell_color, 210),
            pygame.Rect(
                tell_pos.x - tell_radius,
                tell_pos.y - tell_radius,
                tell_radius * 2,
                tell_radius * 2,
            ),
            start,
            start + math.pi * 0.85,
            3,
        )
        pygame.draw.arc(
            layer,
            (*tell_color, 120),
            pygame.Rect(
                tell_pos.x - tell_radius - 5,
                tell_pos.y - tell_radius - 5,
                (tell_radius + 5) * 2,
                (tell_radius + 5) * 2,
            ),
            start + math.pi,
            start + math.pi * 1.72,
            2,
        )
        dst.blit(layer, (0, 0))

    def draw_ball(
        self,
        dst,
        pos,
        radius,
        base,
        accent,
        facing,
        roll,
        squash,
        flash,
        frozen=0,
        burned=0,
        moro=False,
    ):
        pos = Vec2(pos)
        shadow = pygame.Surface((int(radius * 3), int(radius)), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 100), shadow.get_rect())
        dst.blit(shadow, (pos.x - radius * 1.5, pos.y + radius * 0.72))
        sx = 1 + squash * 0.18
        sy = 1 - squash * 0.14
        r = int(radius * 1.35)
        ball = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        c = Vec2(r, r)
        for rr in range(int(radius), 0, -2):
            t = rr / radius
            light = clamp(1 - t, 0, 1)
            col = mix(base, (255, 255, 255), light * 0.45)
            pygame.draw.circle(
                ball, col, c + Vec2(-radius * 0.16, -radius * 0.18) * (1 - t), rr
            )
        pygame.draw.circle(
            ball,
            (255, 255, 255, 95),
            c + Vec2(-radius * 0.31, -radius * 0.33),
            int(radius * 0.2),
        )
        pygame.draw.arc(
            ball,
            (*accent, 180),
            pygame.Rect(r - radius, r - radius, radius * 2, radius * 2),
            roll,
            roll + math.pi * 1.25,
            max(2, int(radius * 0.11)),
        )
        eye_center = c + facing * radius * 0.38
        q = Vec2(-facing.y, facing.x)
        for side in (-1, 1):
            eye = eye_center + q * side * radius * 0.18
            eye_col = HEAT if moro else (210, 225, 245)
            pygame.draw.circle(ball, (10, 13, 22), eye, int(radius * 0.13))
            pygame.draw.circle(ball, eye_col, eye, int(radius * 0.075))
        if moro:
            pygame.draw.arc(
                ball,
                ICE,
                pygame.Rect(
                    r - radius * 0.67, r - radius * 0.66, radius * 1.34, radius * 1.34
                ),
                math.pi * 0.5,
                math.pi * 1.5,
                4,
            )
            pygame.draw.arc(
                ball,
                HEAT,
                pygame.Rect(
                    r - radius * 0.67, r - radius * 0.66, radius * 1.34, radius * 1.34
                ),
                -math.pi * 0.5,
                math.pi * 0.5,
                4,
            )
        if flash > 0:
            pygame.draw.circle(ball, (255, 255, 255, 190), c, int(radius))
        if frozen > 0:
            pygame.draw.circle(ball, (*ICE, 80), c, int(radius + 6), 5)
            for a in range(0, 360, 45):
                tip = c + Vec2(radius + 13, 0).rotate(a)
                pygame.draw.line(
                    ball, ICE_WHITE, c + Vec2(radius - 3, 0).rotate(a), tip, 3
                )
        if burned > 0:
            pygame.draw.circle(ball, (*HEAT, 70), c, int(radius + 6), 4)
        scaled = pygame.transform.smoothscale(
            ball, (int(ball.get_width() * sx), int(ball.get_height() * sy))
        )
        dst.blit(
            scaled, (pos.x - scaled.get_width() / 2, pos.y - scaled.get_height() / 2)
        )

    def draw_punch_hand(self, dst, offset):
        remaining = self.moro.punch_anim
        if remaining <= 0:
            return
        progress = clamp(1 - remaining / 0.52, 0, 1)
        if progress < 0.12:
            fade = progress / 0.12
        elif progress < 0.68:
            fade = 1.0
        else:
            fade = (1 - progress) / 0.32
        fade = clamp(fade, 0, 1) ** 0.7
        travel_t = progress * progress * (3 - 2 * progress)

        direction = safe_normal(
            self.moro.punch_dir
        )  # Incoming direction toward the target.
        q = Vec2(-direction.y, direction.x)
        target = self.moro.punch_target + offset
        palm = target + direction * lerp(-135, 135, travel_t)
        wrist = palm - direction * 42
        base = wrist - direction * 43
        kind = self.moro.punch_kind
        alpha = int(255 * fade)
        layer = pygame.Surface((W, H), pygame.SRCALPHA)

        if kind == "ICE PUNCH":
            dark, mid, light = (24, 126, 184), ICE, ICE_WHITE
        elif kind == "HEAT PUNCH":
            dark, mid, light = (145, 24, 12), HEAT, (255, 230, 120)
        else:
            dark, mid, light = (70, 80, 102), (180, 195, 215), (250, 252, 255)

        # Directional afterimages make the random incoming angle immediately readable.
        for i in range(5, 0, -1):
            echo = palm - direction * i * 18
            echo_alpha = int(alpha * 0.045 * (6 - i))
            pygame.draw.ellipse(
                layer, (*mid, echo_alpha), pygame.Rect(echo.x - 25, echo.y - 20, 50, 40)
            )
            pygame.draw.line(
                layer,
                (*light, int(echo_alpha * 0.8)),
                echo - direction * 31 - q * 12,
                echo - q * 12,
                2,
            )

        forearm = [
            base - q * 15,
            wrist - q * 20,
            palm - direction * 20 - q * 23,
            palm - direction * 20 + q * 23,
            wrist + q * 20,
            base + q * 15,
        ]
        pygame.draw.polygon(layer, (*dark, int(alpha * 0.78)), forearm)
        pygame.draw.polygon(
            layer,
            (*mid, int(alpha * 0.32)),
            [base - q * 8, wrist - q * 13, wrist + q * 2, base + q * 5],
        )
        pygame.draw.line(
            layer,
            (*light, int(alpha * 0.52)),
            base - q * 9,
            palm - direction * 19 - q * 15,
            3,
        )

        palm_poly = [
            palm - direction * 25 - q * 25,
            palm + direction * 12 - q * 31,
            palm + direction * 30 - q * 19,
            palm + direction * 31 + q * 19,
            palm + direction * 9 + q * 31,
            palm - direction * 27 + q * 22,
        ]
        pygame.draw.polygon(layer, (*mid, alpha), palm_poly)
        pygame.draw.polygon(
            layer,
            (*light, int(alpha * 0.18)),
            [
                palm - direction * 18 - q * 18,
                palm + direction * 5 - q * 23,
                palm + direction * 19 - q * 13,
                palm - direction * 2 - q * 5,
            ],
        )
        pygame.draw.lines(layer, (*light, int(alpha * 0.8)), True, palm_poly, 3)

        knuckle_offsets = (-21, -7, 7, 21)
        for i, side in enumerate(knuckle_offsets):
            center = palm + direction * (29 + (i in (1, 2)) * 4) + q * side
            pygame.draw.circle(layer, (*dark, alpha), center, 12)
            pygame.draw.circle(layer, (*mid, alpha), center - direction * 2, 10)
            pygame.draw.circle(
                layer, (*light, int(alpha * 0.86)), center - direction * 5 - q * 3, 4
            )
        thumb = palm - direction * 3 + q * 31
        pygame.draw.circle(layer, (*dark, alpha), thumb, 13)
        pygame.draw.circle(layer, (*mid, alpha), thumb - direction * 2, 10)

        if kind == "ICE PUNCH":
            for side, length in ((-29, 28), (-13, 23), (7, 27), (27, 32)):
                root = palm + direction * 22 + q * side
                tip = root + direction * length + q * side * 0.16
                pygame.draw.polygon(
                    layer,
                    (*ICE_WHITE, int(alpha * 0.9)),
                    [root - q * 5, root + q * 5, tip],
                )
            for i in range(9):
                trail = (
                    wrist - direction * (i * 14) + q * math.sin(self.time * 9 + i) * 13
                )
                pygame.draw.polygon(
                    layer,
                    (*ICE_WHITE, int(alpha * 0.38)),
                    [
                        trail + direction * 5,
                        trail - direction * 5 + q * 3,
                        trail - direction * 5 - q * 3,
                    ],
                )
        elif kind == "HEAT PUNCH":
            for side, length in ((-27, 38), (-12, 29), (5, 43), (23, 34)):
                root = wrist - direction * 4 + q * side
                tip = (
                    root - direction * length + q * math.sin(self.time * 18 + side) * 6
                )
                pygame.draw.polygon(
                    layer, (*HEAT, int(alpha * 0.7)), [root - q * 8, root + q * 8, tip]
                )
                inner = vlerp(root, tip, 0.55)
                pygame.draw.circle(layer, (*light, int(alpha * 0.62)), inner, 5)
            for i in range(7):
                ember = (
                    wrist
                    - direction * (i * 16)
                    + q * math.sin(i * 2.7 + self.time * 15) * 16
                )
                pygame.draw.circle(layer, (*light, int(alpha * 0.5)), ember, 2 + i % 3)
        else:
            pygame.draw.line(
                layer, (*light, int(alpha * 0.8)), wrist - q * 15, wrist + q * 15, 5
            )
            for side in (-13, 0, 13):
                pygame.draw.line(
                    layer,
                    (*dark, int(alpha * 0.75)),
                    palm - direction * 17 + q * side,
                    palm + direction * 11 + q * side,
                    2,
                )

        dst.blit(layer, (0, 0))

    def draw_dummy_punch(self, dst, offset):
        shared.draw_dummy_punch(dst, self.dummy, self.time, offset, W, H)

    def draw_ice_cube(self, dst, pos, frozen):
        if frozen <= 0:
            return
        pos = Vec2(pos)
        pulse = math.sin(self.time * 3.5) * 1.5
        seed_points = [
            (-61, -32),
            (-49, -55),
            (-24, -67),
            (3, -61),
            (30, -68),
            (53, -49),
            (65, -20),
            (61, 8),
            (69, 31),
            (48, 57),
            (20, 64),
            (-9, 69),
            (-35, 61),
            (-58, 43),
            (-66, 13),
            (-64, -13),
        ]
        shell = [
            pos + Vec2(x, y).normalize() * (Vec2(x, y).length() + pulse)
            for x, y in seed_points
        ]
        ice = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.polygon(ice, (38, 137, 190, 188), shell)
        pygame.draw.polygon(
            ice,
            (104, 205, 235, 135),
            [
                shell[0],
                shell[1],
                shell[2],
                shell[3],
                pos + Vec2(11, -14),
                pos + Vec2(-31, 7),
            ],
        )
        pygame.draw.polygon(
            ice,
            (18, 91, 150, 120),
            [
                shell[5],
                shell[6],
                shell[7],
                shell[8],
                pos + Vec2(21, 18),
                pos + Vec2(14, -20),
            ],
        )
        pygame.draw.polygon(
            ice,
            (175, 236, 246, 118),
            [
                shell[10],
                shell[11],
                shell[12],
                shell[13],
                pos + Vec2(-27, 12),
                pos + Vec2(4, 25),
            ],
        )
        pygame.draw.lines(ice, (205, 248, 255, 235), True, shell, 4)
        pygame.draw.lines(
            ice, (82, 188, 225, 220), True, [p + Vec2(0, 4) for p in shell], 2
        )

        # Chunky frost patches make the prison read as ice instead of clean glass.
        frost_chunks = [
            (-48, -38, 20),
            (-24, -55, 17),
            (9, -52, 22),
            (39, -39, 19),
            (51, -6, 18),
            (45, 27, 21),
            (21, 48, 19),
            (-13, 53, 23),
            (-43, 37, 20),
            (-52, 5, 18),
            (-20, -12, 15),
            (22, 12, 17),
        ]
        for x, y, radius in frost_chunks:
            p = pos + Vec2(x, y)
            pygame.draw.circle(ice, (190, 239, 247, 115), p, radius)
            pygame.draw.circle(
                ice,
                (238, 253, 255, 115),
                p + Vec2(-radius * 0.25, -radius * 0.3),
                int(radius * 0.45),
            )
        for x, length, base_y in (
            (-48, 18, 55),
            (-24, 29, 58),
            (7, 19, 57),
            (31, 25, 56),
            (49, 15, 54),
        ):
            base = pos + Vec2(x, base_y)
            pygame.draw.polygon(
                ice,
                (137, 222, 240, 220),
                [base + Vec2(-6, 0), base + Vec2(6, 0), base + Vec2(1, length)],
            )
        for angle, length in (
            (-145, 79),
            (-115, 88),
            (-72, 82),
            (-38, 91),
            (12, 77),
            (37, 85),
        ):
            direction = Vec2(1, 0).rotate(angle)
            side = Vec2(-direction.y, direction.x)
            base = pos + direction * 58
            tip = pos + direction * length
            pygame.draw.polygon(
                ice, (119, 213, 237, 220), [base - side * 7, base + side * 7, tip]
            )
        if frozen <= 2:
            crack_count = 3 + int((2 - frozen) * 3)
            for i in range(crack_count):
                angle = i * 2.19 + 0.4
                start = pos + Vec2(math.cos(angle), math.sin(angle)) * (10 + i % 3 * 5)
                mid = start + Vec2(math.cos(angle + 0.45), math.sin(angle + 0.45)) * 22
                end = mid + Vec2(math.cos(angle - 0.28), math.sin(angle - 0.28)) * 27
                pygame.draw.lines(
                    ice, (245, 255, 255, 225), False, [start, mid, end], 2
                )
                pygame.draw.line(
                    ice, (95, 180, 230, 150), mid, mid + Vec2(12, -9).rotate(i * 31), 1
                )
        dst.blit(ice, (0, 0))
        glow_circle(dst, pos, 18, ICE, 0.05)

    def draw_hud(self, dst, fonts):
        def bar(rect, value, max_value, color, flip=False):
            pygame.draw.rect(dst, (12, 17, 31), rect, border_radius=8)
            pygame.draw.rect(dst, (55, 66, 90), rect, 2, border_radius=8)
            fill = rect.inflate(-6, -6)
            fill.width = int(fill.width * clamp(value / max_value, 0, 1))
            if flip:
                fill.right = rect.right - 3
            pygame.draw.rect(dst, color, fill, border_radius=5)

        bar(
            pygame.Rect(75, 42, 430, 23), self.moro.hp, self.moro.max_hp, (75, 190, 235)
        )
        bar(
            pygame.Rect(W - 505, 42, 430, 23),
            self.dummy.hp,
            self.dummy.max_hp,
            (185, 190, 205),
            True,
        )
        dst.blit(fonts["name"].render("MOROZHAR", True, ICE_WHITE), (75, 13))
        name = fonts["name"].render("DUMMYBOT", True, (220, 225, 235))
        dst.blit(name, (W - 75 - name.get_width(), 13))
        dst.blit(
            fonts["small"].render(f"{int(self.moro.hp)} / 5000", True, (205, 235, 255)),
            (80, 70),
        )
        hp = fonts["small"].render(
            f"{int(self.dummy.hp)} / {int(self.dummy.max_hp)}", True, (225, 228, 235)
        )
        dst.blit(hp, (W - 80 - hp.get_width(), 70))
        cx = W // 2
        title = fonts["tiny"].render("ICE  //  HEAT PRESSURE", True, (140, 165, 210))
        dst.blit(title, (cx - title.get_width() // 2, 20))
        for i in range(3):
            pygame.draw.circle(
                dst,
                ICE if i < self.dummy.ice_stacks else (35, 50, 70),
                (cx - 54 + i * 18, 54),
                6,
            )
            pygame.draw.circle(
                dst,
                HEAT if i < self.dummy.heat_stacks else (55, 42, 45),
                (cx + 20 + i * 18, 54),
                6,
            )
        status = []
        if self.dummy.frozen > 0:
            status.append(f"FROZEN {self.dummy.frozen:.1f}s")
        if self.dummy.burned > 0:
            status.append(f"BURN {self.dummy.burned:.1f}s")
        if self.dummy.slowed > 0:
            status.append(f"SLOWED {self.dummy.slowed:.1f}s")
        st = fonts["tiny"].render("   ".join(status), True, (225, 235, 250))
        dst.blit(st, (cx - st.get_width() // 2, 74))
        punch_colors = {"PUNCH": (225, 230, 240), "ICE PUNCH": ICE, "HEAT PUNCH": HEAT}
        next_punch = self.moro.next_punch
        tell = fonts["small"].render(
            f"NEXT: {next_punch}", True, punch_colors[next_punch]
        )
        dst.blit(tell, (cx - tell.get_width() // 2, H - 43))
        stored = fonts["tiny"].render(
            f"HEAT VISION STORED LEVEL: {self.dummy.heat_stacks}",
            True,
            HEAT if self.dummy.heat_stacks else (105, 82, 82),
        )
        dst.blit(stored, (cx - stored.get_width() // 2, 94))

        skills = [
            ("FREEZING BREATH", self.moro.breath_timer, 7.5, ICE),
            ("HEAT VISION", self.moro.vision_timer, 7.5, HEAT),
            ("REDIRECTION", self.moro.redirect_timer, 10, GOLD),
        ]
        for i, (name, cd, total, color) in enumerate(skills):
            x = 82 + i * 208
            y = H - 52
            dst.blit(fonts["tiny"].render(name, True, color), (x, y - 18))
            pygame.draw.rect(dst, (20, 26, 43), (x, y, 170, 7), border_radius=4)
            ready = 1 - clamp(cd / total, 0, 1)
            pygame.draw.rect(dst, color, (x, y, int(170 * ready), 7), border_radius=4)
        info = fonts["tiny"].render(
            "R  RESTART     M  MUTE     ESC  EXIT", True, (105, 125, 160)
        )
        dst.blit(info, (W - 82 - info.get_width(), H - 40))

    def draw(self, dst, fonts):
        offset = (
            Vec2(
                random.uniform(-self.shake, self.shake),
                random.uniform(-self.shake, self.shake),
            )
            if self.shake
            else Vec2()
        )
        self.draw_background(dst, offset)
        # Movement trails.
        for fighter, color in ((self.moro, ICE), (self.dummy, (155, 165, 185))):
            for i in range(1, 5):
                p = fighter.pos - safe_normal(fighter.vel) * i * 13 + offset
                pygame.draw.circle(
                    dst, (*color, 18), p, max(2, int(fighter.radius - i * 8))
                )

        self.draw_world_effects(dst, offset)
        punch_colors = {"PUNCH": (225, 230, 240), "ICE PUNCH": ICE, "HEAT PUNCH": HEAT}
        tell_color = punch_colors[self.moro.next_punch]
        tell_pos = self.moro.pos + offset
        tell_radius = int(self.moro.radius + 10 + math.sin(self.time * 7) * 3)
        glow_circle(dst, tell_pos, 24, tell_color, 0.12)
        start = self.time * 2.8
        tell_layer = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.arc(
            tell_layer,
            (*tell_color, 210),
            pygame.Rect(
                tell_pos.x - tell_radius,
                tell_pos.y - tell_radius,
                tell_radius * 2,
                tell_radius * 2,
            ),
            start,
            start + math.pi * 0.85,
            3,
        )
        pygame.draw.arc(
            tell_layer,
            (*tell_color, 120),
            pygame.Rect(
                tell_pos.x - tell_radius - 5,
                tell_pos.y - tell_radius - 5,
                (tell_radius + 5) * 2,
                (tell_radius + 5) * 2,
            ),
            start + math.pi,
            start + math.pi * 1.72,
            2,
        )
        dst.blit(tell_layer, (0, 0))
        self.draw_ball(
            dst,
            self.moro.pos + offset,
            self.moro.radius,
            (28, 85, 130),
            (185, 235, 255),
            self.moro.facing,
            self.moro.roll,
            self.moro.squash,
            self.moro.hit_flash,
            moro=True,
        )
        self.draw_ball(
            dst,
            self.dummy.pos + offset,
            self.dummy.radius,
            (84, 91, 108),
            (180, 190, 205),
            self.dummy.facing,
            self.time * 2,
            self.dummy.squash,
            self.dummy.hit_flash,
            self.dummy.frozen,
            self.dummy.burned,
        )
        self.draw_punch_hand(dst, offset)
        self.draw_dummy_punch(dst, offset)
        self.draw_ice_cube(dst, self.dummy.pos + offset, self.dummy.frozen)
        for t in self.texts:
            font = fonts["impact"] if t.big else fonts["small"]
            img = font.render(t.text, True, t.color)
            shadow = font.render(t.text, True, (5, 7, 12))
            p = t.pos + offset
            dst.blit(shadow, (p.x - img.get_width() / 2 + 2, p.y + 2))
            dst.blit(img, (p.x - img.get_width() / 2, p.y))
        tell = fonts["tiny"].render(self.moro.next_punch, True, tell_color)
        tell_bg = pygame.Surface(
            (tell.get_width() + 14, tell.get_height() + 6), pygame.SRCALPHA
        )
        pygame.draw.rect(tell_bg, (5, 8, 18, 190), tell_bg.get_rect(), border_radius=7)
        tell_bg.blit(tell, (7, 3))
        dst.blit(
            tell_bg,
            (tell_pos.x - tell_bg.get_width() / 2, tell_pos.y - self.moro.radius - 34),
        )
        self.draw_hud(dst, fonts)

        if self.banner_time > 0:
            alpha = int(255 * clamp(self.banner_time / 0.5, 0, 1))
            img = fonts["banner"].render(self.banner, True, (220, 240, 255))
            img.set_alpha(alpha)
            dst.blit(img, (W / 2 - img.get_width() / 2, H / 2 - 100))
        if self.round_over:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((3, 5, 12, 145))
            dst.blit(veil, (0, 0))
            img = fonts["winner"].render(self.winner, True, GOLD)
            dst.blit(img, (W / 2 - img.get_width() / 2, H / 2 - img.get_height() / 2))
            sub = fonts["small"].render(
                "NEXT EXHIBITION STARTING...", True, (220, 230, 245)
            )
            dst.blit(sub, (W / 2 - sub.get_width() / 2, H / 2 + 50))


def make_fonts():
    return shared.make_fonts()


def main():
    parser = argparse.ArgumentParser(description="MoroZhar autonomous combat prototype")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--seconds", type=float, default=0)
    parser.add_argument("--screenshot", type=str, default="")
    parser.add_argument("--mute", action="store_true")
    args = parser.parse_args()
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("MoroZhar // Autonomous Combat Prototype")
    clock = pygame.time.Clock()
    fonts = make_fonts()
    battle = Battle(args.mute or args.headless)
    elapsed = 0.0
    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000, 1 / 30)
        elapsed += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    battle = Battle(battle.sound.muted)
                elif event.key == pygame.K_m:
                    battle.sound.muted = not battle.sound.muted
        battle.update(dt)
        battle.draw(screen, fonts)
        pygame.display.flip()
        if args.seconds and elapsed >= args.seconds:
            if args.screenshot:
                pygame.image.save(screen, args.screenshot)
            running = False
    pygame.quit()


if __name__ == "__main__":
    main()
