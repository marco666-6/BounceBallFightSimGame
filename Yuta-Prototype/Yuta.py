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

W, H, FPS = 1280, 720, 120
ARENA = pygame.Rect(72, 112, W - 144, H - 184)
Vec2 = pygame.Vector2

INK = (7, 8, 18)
WHITE = (238, 241, 247)
PINK = (255, 92, 185)
PINK_HOT = (255, 39, 156)
VIOLET = (160, 95, 255)
STEEL = (174, 188, 205)
DARK_STEEL = (47, 54, 66)
RED_WRAP = (142, 18, 35)
GOLD = (255, 205, 92)
BLACK = (9, 10, 15)
RIKA_SKIN = (218, 224, 234)
RIKA_SHADOW = (37, 38, 49)
YUTA_KATANA_RANGE = 175
YUTA_KATANA_INTERVAL = .40
YUTA_PUNCH_INTERVAL = .45
RIKA_CLAW_RANGE = 145
CURSE_ENERGY_GAIN_BONUS = 2.5
YUTA_KATANA_DAMAGE = 35
YUTA_IRON_ARM_DAMAGE = 45
RIKA_CLAW_DAMAGE = 30


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def mix(a, b, t):
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def safe_normal(vector, fallback=Vec2(1, 0)):
    return vector.normalize() if vector.length_squared() > .001 else Vec2(fallback)


def point_segment_distance(point, start, end):
    segment = end - start
    if segment.length_squared() <= .001:
        return point.distance_to(start)
    t = clamp((point - start).dot(segment) / segment.length_squared(), 0, 1)
    return point.distance_to(start + segment * t)


def ray_rect_distance(origin, direction, rect):
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
    return min(valid) if valid else 0


def circle_rect_hit(center, radius, rect):
    x = clamp(center.x, rect.left, rect.right)
    y = clamp(center.y, rect.top, rect.bottom)
    return center.distance_squared_to(Vec2(x, y)) <= radius * radius


def sign(point, a, b):
    return (point.x - b.x) * (a.y - b.y) - (a.x - b.x) * (point.y - b.y)


def point_in_triangle(point, a, b, c):
    d1, d2, d3 = sign(point, a, b), sign(point, b, c), sign(point, c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def circle_triangle_hit(center, radius, a, b, c):
    if point_in_triangle(center, a, b, c):
        return True
    for point in (center + Vec2(radius, 0), center - Vec2(radius, 0),
                  center + Vec2(0, radius), center - Vec2(0, radius)):
        if point_in_triangle(point, a, b, c):
            return True
    return (
        point_segment_distance(center, a, b) <= radius or
        point_segment_distance(center, b, c) <= radius or
        point_segment_distance(center, c, a) <= radius
    )


def glow_circle(dst, pos, radius, color, strength=1):
    shared.glow_circle(dst, pos, radius, color, strength)


@dataclass
class Particle:
    pos: Vec2
    vel: Vec2
    life: float
    max_life: float
    size: float
    color: tuple
    kind: str = "spark"

    def update(self, dt):
        self.life -= dt
        self.pos += self.vel * dt
        self.vel *= .94 ** (dt * 60)
        if self.kind in {"smoke", "hair"}:
            self.vel.y -= 18 * dt

    def draw(self, dst, offset):
        t = clamp(self.life / self.max_life, 0, 1)
        p = self.pos + offset
        if self.kind == "slash":
            direction = safe_normal(self.vel)
            q = Vec2(-direction.y, direction.x)
            pts = [p + direction * self.size * 4, p - direction * self.size * 3 + q * self.size,
                   p - direction * self.size * 2 - q * self.size]
            pygame.draw.polygon(dst, (*self.color, int(190 * t)), pts)
        elif self.kind == "smoke":
            pygame.draw.circle(dst, (*self.color, int(55 * t)), p, int(self.size * (1.8 - t)))
        elif self.kind == "ring":
            pygame.draw.circle(dst, (*self.color, int(185 * t)), p, int(self.size * (2 - t)), max(1, int(3 * t)))
        elif self.kind == "beam_fire":
            pygame.draw.circle(dst, (*self.color, int(130 * t)), p, int(self.size * (1.2 + .5 * math.sin(t * math.pi))))
            pygame.draw.circle(dst, (255, 226, 246, int(90 * t)), p - safe_normal(self.vel) * 3, max(1, int(self.size * .35)))
        else:
            tail = p - safe_normal(self.vel) * self.size * 4
            pygame.draw.line(dst, (*self.color, int(225 * t)), tail, p, max(1, int(self.size * t)))


@dataclass
class FloatText:
    text: str
    pos: Vec2
    color: tuple
    life: float = .85
    big: bool = False

    def update(self, dt):
        self.life -= dt
        self.pos.y -= 42 * dt


@dataclass
class AfterStrike:
    timer: float
    kind: str
    damage: float
    angle_offset: float


@dataclass
class SlashAnim:
    origin: Vec2
    pos: Vec2
    direction: Vec2
    life: float
    max_life: float
    color: tuple
    side: int
    label: str


@dataclass
class ArmAnim:
    target: Vec2
    direction: Vec2
    life: float = .42
    max_life: float = .42


@dataclass
class ShieldPop:
    pos: Vec2
    life: float = .38
    max_life: float = .38


@dataclass
class ChainState:
    life: float = 0
    length: float = 120
    pulse: float = 0


@dataclass
class BeamState:
    phase: str = ""
    timer: float = 0
    direction: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    origin: Vec2 = field(default_factory=Vec2)
    end: Vec2 = field(default_factory=Vec2)
    tick: float = 0
    return_pos: Vec2 = field(default_factory=Vec2)
    source: Vec2 = field(default_factory=Vec2)


@dataclass
class Rika:
    pos: Vec2
    vel: Vec2 = field(default_factory=lambda: Vec2(180, -215))
    radius: float = 84
    hp: float = 550
    max_hp: float = 550
    alive: bool = False
    spawn_timer: float = 10
    reforming: float = 0
    despawning: float = 0
    attack_timer: float = .3
    claw_anim: float = 0
    claw_dir: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    claw_target: Vec2 = field(default_factory=Vec2)
    hit_flash: float = 0
    squash: float = 0
    roll: float = 0
    saved_pure_love_cd: float = 0
    died_after_spawn: bool = False

    def timers(self, dt):
        self.spawn_timer = max(0, self.spawn_timer - dt)
        self.reforming = max(0, self.reforming - dt)
        self.despawning = max(0, self.despawning - dt)
        self.attack_timer -= dt
        self.claw_anim = max(0, self.claw_anim - dt)
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 4.5)
        self.roll += self.vel.length() * dt / max(1, self.radius)


@dataclass
class Yuta:
    pos: Vec2
    vel: Vec2 = field(default_factory=lambda: Vec2(312, 160))
    radius: float = 46
    hp: float = 5000
    max_hp: float = 5000
    ce: float = 0
    max_ce: float = 750
    facing: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    katana_timer: float = .15
    punch_timer: float = .28
    surge_cd: float = 2.6
    surge_active: float = 0
    surge_tier: int = 0
    pure_cd: float = 8
    immobilized: float = 0
    hit_flash: float = 0
    squash: float = 0
    roll: float = 0
    slash_side: int = 1
    redirect_bounces: int = 0

    def timers(self, dt):
        self.katana_timer -= dt
        self.punch_timer -= dt
        if self.surge_active > 0:
            self.surge_active -= dt
            if self.surge_active <= 0:
                self.surge_cd = 10
                self.surge_tier = 0
        else:
            self.surge_cd -= dt
        self.pure_cd -= dt
        self.immobilized = max(0, self.immobilized - dt)
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 5)
        self.roll += self.vel.length() * dt / self.radius


class SoundBank:
    def __init__(self, muted=False):
        self.muted, self.sounds = muted, {}
        self.blast_channel = None
        if muted:
            return
        try:
            pygame.mixer.init()
            pygame.mixer.set_num_channels(max(16, pygame.mixer.get_num_channels()))
            self.blast_channel = pygame.mixer.Channel(0)
            folder = ROOT / "Yuta-SoundEffects"
            names = {
                "chain_attach": "Yuta-ChainAttach.mp3",
                "chain_pull": "Yuta-ChainPull.mp3",
                "surge": "Yuta-CurseEnergySurge.mp3",
                "punch": "Yuta-IronArmPunch.mp3",
                "slash": "Yuta-KatanaSlash.mp3",
                "double": "Yuta-KatanaDoubleSlash.mp3",
                "triple": "Yuta-KatanaTripleSlash.mp3",
                "blast": "Yuta-PureLoveBlast.mp3",
                "charge": "Yuta-PureLoveBlastCharge.mp3",
                "rika_claw": "Yuta-RikaClaw.mp3",
                "rika_death": "Yuta-RikaDeath.mp3",
                "rika_spawn": "Yuta-RikaSpawnAndRevive.mp3",
                "stun": "Yuta-StunProcDizzy.mp3",
                "dummy_punch": str(ROOT / "DummyBot-SoundEffects" / "MoroZhar-Punch.mp3"),
            }
            for key, name in names.items():
                sound = pygame.mixer.Sound(name if key == "dummy_punch" else folder / name)
                sound.set_volume(.30 if key in {"blast", "chain_pull"} else .42)
                self.sounds[key] = sound
        except (pygame.error, FileNotFoundError):
            self.muted = True

    def play(self, key):
        if not self.muted and key in self.sounds:
            if key == "blast" and self.blast_channel:
                self.blast_channel.play(self.sounds[key])
            else:
                self.sounds[key].play()


class Battle:
    def __init__(self, muted=False):
        self.yuta = Yuta(Vec2(290, 385))
        self.dummy = DummyBot(Vec2(985, 385))
        self.rika = Rika(Vec2(225, 310))
        self.sound = SoundBank(muted)
        self.particles, self.texts, self.slashes, self.after_queue = [], [], [], []
        self.arm_anims = []
        self.shield_pops = []
        self.chain = ChainState()
        self.beam = BeamState()
        self.time = self.shake = self.hit_stop = 0
        self.round_over = 0
        self.winner = ""
        self.banner_time = 2.8
        self.actions_locked = False

    def burst(self, pos, color=PINK, amount=16, speed=260, kind="spark", size=4):
        for _ in range(amount):
            direction = Vec2(1, 0).rotate(random.random() * 360)
            self.particles.append(Particle(Vec2(pos), direction * random.uniform(speed * .25, speed),
                                           random.uniform(.25, .75), .75, random.uniform(size * .55, size * 1.45),
                                           color, kind))

    def smoke(self, pos, amount=24, color=(185, 185, 205)):
        for _ in range(amount):
            direction = Vec2(1, 0).rotate(random.random() * 360)
            self.particles.append(Particle(Vec2(pos) + direction * random.uniform(5, 45),
                                           direction * random.uniform(25, 110),
                                           random.uniform(.55, 1.2), 1.2,
                                           random.uniform(12, 30), color, "smoke"))

    def rika_disappear_fx(self, pos):
        self.smoke(pos, 34, (155, 150, 174))
        for i in range(18):
            angle = i / 18 * math.tau
            direction = Vec2(math.cos(angle), math.sin(angle))
            floor = Vec2(pos.x, pos.y + self.rika.radius * .52)
            self.particles.append(Particle(Vec2(pos) + direction * random.uniform(10, 60),
                                           safe_normal(floor - pos - direction * 30) * random.uniform(70, 190),
                                           random.uniform(.45, .95), .95,
                                           random.uniform(9, 24), (95, 83, 116), "smoke"))

    def rika_appear_fx(self, pos):
        self.smoke(pos, 36, (224, 224, 238))
        self.particles.append(Particle(Vec2(pos), Vec2(), .5, .5, 34, PINK, "ring"))

    def text(self, value, pos, color=GOLD, big=False):
        self.texts.append(FloatText(value, Vec2(pos), color, 1 if big else .8, big))

    def impact(self, pos, color=PINK, power=1):
        self.shake = max(self.shake, 4 + power * 4)
        self.hit_stop = max(self.hit_stop, .01 + power * .012)
        self.burst(pos, color, 12 + power * 7, 240 + power * 110, "spark", 3 + power)
        self.particles.append(Particle(Vec2(pos), Vec2(), .28, .28, 18 + power * 6, color, "ring"))

    def heal_yuta_from_basic(self, dealt, source_pos):
        healed = min(dealt * .25, self.yuta.max_hp - self.yuta.hp)
        self.yuta.hp += healed
        if healed:
            self.text(f"+{int(healed)} HP", source_pos + Vec2(0, -82), PINK)

    def add_ce(self, amount, multiplier=True):
        gain = amount + CURSE_ENERGY_GAIN_BONUS
        if multiplier:
            gain *= self.energy_multiplier()
        if self.rika.died_after_spawn and not self.rika.alive:
            gain *= 3
        before = self.yuta.ce
        self.yuta.ce = clamp(self.yuta.ce + gain, 0, self.yuta.max_ce)
        return self.yuta.ce - before

    def damage_dummy(self, amount, label="", color=PINK, power=1):
        dealt = self.dummy.take_damage(amount)
        self.text(f"-{int(dealt)}" + (f"  {label}" if label else ""), self.dummy.pos + Vec2(0, -64), color, power > 1)
        self.impact(self.dummy.pos, color, power)
        self.add_ce(max(4, dealt * .12))
        return dealt

    def damage_yuta(self, amount):
        self.yuta.hp = max(0, self.yuta.hp - amount)
        self.yuta.hit_flash = .12
        self.text(f"-{int(amount)}", self.yuta.pos + Vec2(0, -62), STEEL)
        self.impact(self.yuta.pos, STEEL, 1)

    def damage_rika(self, amount):
        r = self.rika
        if not r.alive:
            return
        if self.beam.phase in {"charge", "blast"}:
            self.shield_pops.append(ShieldPop(Vec2(r.pos)))
            self.text("SHIELDED", r.pos + Vec2(0, -122), PINK)
            self.burst(r.pos, PINK, 16, 240, "spark", 3)
            return
        r.hp = max(0, r.hp - amount)
        r.hit_flash = .12
        r.squash = .45
        self.text(f"-{int(amount)}", r.pos + Vec2(0, -95), RIKA_SKIN)
        if r.hp <= 0:
            r.alive = False
            r.died_after_spawn = True
            r.despawning = 1.25
            r.saved_pure_love_cd = max(0, self.yuta.pure_cd)
            self.sound.play("rika_death")
            self.text("RIKA DISPERSED", r.pos + Vec2(0, -120), RIKA_SKIN, True)
            self.rika_disappear_fx(r.pos)

    def attack_multiplier(self):
        return {0: 1, 5: 1.25, 4: 1.4, 3: 1.6, 2: 1.6, 1: 1.8}.get(self.yuta.surge_tier, 1)

    def energy_multiplier(self):
        return {0: 1, 5: 1.25, 4: 1.25, 3: 1.4, 2: 1.5, 1: 1.5}.get(self.yuta.surge_tier, 1)

    def roll_surge_tier(self):
        costs = [(1, 600), (2, 500), (3, 400), (4, 250), (5, 150)]
        affordable = [(tier, cost) for tier, cost in costs if self.yuta.ce >= cost]
        if not affordable:
            return None
        highest = affordable[0]
        lower = affordable[1] if len(affordable) > 1 else affordable[-1]
        return random.choice((highest, lower))

    def cast_surge(self):
        rolled = self.roll_surge_tier()
        if not rolled:
            return
        tier, cost = rolled
        y = self.yuta
        y.ce -= cost
        y.surge_active = 10
        y.surge_tier = tier
        y.surge_cd = 999
        self.sound.play("surge")
        self.text(f"CURSE ENERGY SURGE  TIER {tier}", y.pos + Vec2(0, -86), VIOLET, True)
        self.burst(y.pos, VIOLET, 36, 420, "spark", 5)
        self.particles.append(Particle(Vec2(y.pos), Vec2(), .5, .5, 38, VIOLET, "ring"))
        if tier == 1:
            self.revive_or_heal_rika(full=True)
        elif tier == 2 and not self.rika.alive:
            self.revive_or_heal_rika(full=False)

    def revive_or_heal_rika(self, full):
        r, y = self.rika, self.yuta
        if r.alive:
            if full:
                r.hp = r.max_hp
                self.text("RIKA RESTORED", r.pos + Vec2(0, -118), RIKA_SKIN, True)
            return
        offset = Vec2(-92 if y.pos.x > (ARENA.centerx) else 92, -42)
        r.pos = y.pos + offset
        r.vel = safe_normal(Vec2(random.choice((-1, 1)), random.uniform(-.8, .8))) * 280
        r.hp = r.max_hp if full else r.max_hp * .5
        r.reforming = 1.25
        r.spawn_timer = 0
        r.alive = True
        r.died_after_spawn = False
        y.pure_cd = max(0, r.saved_pure_love_cd)
        self.sound.play("rika_spawn")
        self.rika_appear_fx(r.pos)

    def spawn_rika_if_ready(self):
        r, y = self.rika, self.yuta
        if not r.alive and r.spawn_timer <= 0 and r.hp > 0:
            side = -1 if y.pos.x > ARENA.centerx else 1
            r.pos = y.pos + Vec2(side * 105, -30)
            r.vel = safe_normal(Vec2(side, random.uniform(-.7, .7))) * 280
            r.alive = True
            r.died_after_spawn = False
            r.reforming = 1.25
            self.sound.play("rika_spawn")
            self.text("RIKA MANIFESTS", r.pos + Vec2(0, -118), RIKA_SKIN, True)
            self.rika_appear_fx(r.pos)

    def wall_bounce(self, fighter, target=None, away=False):
        bounced = False
        if fighter.pos.x - fighter.radius < ARENA.left:
            fighter.pos.x = ARENA.left + fighter.radius
            fighter.vel.x = abs(fighter.vel.x)
            bounced = True
        elif fighter.pos.x + fighter.radius > ARENA.right:
            fighter.pos.x = ARENA.right - fighter.radius
            fighter.vel.x = -abs(fighter.vel.x)
            bounced = True
        if fighter.pos.y - fighter.radius < ARENA.top:
            fighter.pos.y = ARENA.top + fighter.radius
            fighter.vel.y = abs(fighter.vel.y)
            bounced = True
        elif fighter.pos.y + fighter.radius > ARENA.bottom:
            fighter.pos.y = ARENA.bottom - fighter.radius
            fighter.vel.y = -abs(fighter.vel.y)
            bounced = True
        if bounced:
            fighter.squash = .4
            self.burst(fighter.pos, (130, 150, 190), 6, 120, "spark", 2)
            if target and hasattr(fighter, "redirects") and fighter.redirects > 0:
                direction = safe_normal(fighter.pos - target.pos if away else target.pos - fighter.pos)
                fighter.vel = direction * fighter.vel.length()
                fighter.redirects -= 1
        return bounced

    def nearest_hostile_target(self, origin):
        # The standalone prototype has one hostile body. Future adapters can
        # add enemy summons here and the closest valid hostile will be chosen.
        targets = [self.dummy]
        targets.extend(getattr(self, "enemy_summons", []))
        def is_alive(target):
            state = getattr(target, "alive", True)
            return state() if callable(state) else bool(state)

        living = [target for target in targets if is_alive(target)]
        return min(living or targets, key=lambda target: origin.pos.distance_squared_to(target.pos))

    def redirect_to_nearest_hostile(self, fighter):
        target = self.nearest_hostile_target(fighter)
        speed = fighter.vel.length()
        fighter.vel = safe_normal(target.pos - fighter.pos, fighter.vel) * speed

    def maybe_redirect_yuta_on_bounce(self):
        self.yuta.redirect_bounces += 1
        if self.yuta.redirect_bounces >= 2:
            self.yuta.redirect_bounces = 0
            self.redirect_to_nearest_hostile(self.yuta)

    def separate(self, a, b, can_move_a=True, can_move_b=True):
        delta = b.pos - a.pos
        dist = delta.length()
        minimum = a.radius + b.radius
        if 0 < dist < minimum:
            n = delta / dist
            overlap = minimum - dist
            if can_move_a and can_move_b:
                a.pos -= n * overlap * .5
                b.pos += n * overlap * .5
            elif can_move_a:
                a.pos -= n * overlap
            elif can_move_b:
                b.pos += n * overlap
            if can_move_a:
                a.vel = safe_normal(a.vel.reflect(n)) * a.vel.length()
            if can_move_b:
                b.vel = safe_normal(b.vel.reflect(n)) * b.vel.length()
            a.squash = b.squash = .35
            return True
        return False

    def katana_combo_count(self):
        tier = self.yuta.surge_tier
        if tier in (1, 2):
            return 3
        if tier == 3 and random.random() < .35:
            return 3
        if tier == 4 and random.random() < .35:
            return 2
        return 1

    def katana_slash(self, followup=False, angle_offset=0):
        y, d = self.yuta, self.dummy
        direction = safe_normal(d.pos - y.pos)
        base_damage = YUTA_KATANA_DAMAGE * self.attack_multiplier()
        y.katana_timer = YUTA_KATANA_INTERVAL
        y.slash_side *= -1
        self.sound.play("slash" if not followup else random.choice(("double", "triple")))
        label = "AFTER-IMAGE" if followup else "KATANA"
        dealt = self.damage_dummy(base_damage, label, WHITE if followup else PINK, 1 if followup else 2)
        self.heal_yuta_from_basic(dealt, y.pos)
        self.slashes.append(SlashAnim(Vec2(y.pos), Vec2(d.pos), direction.rotate(angle_offset), .34, .34,
                                      WHITE if followup else PINK, y.slash_side, label))
        self.burst(d.pos + direction * -12, WHITE if followup else PINK, 10, 320, "slash", 4)
        if not followup:
            combo = self.katana_combo_count()
            if combo >= 2:
                self.after_queue.append(AfterStrike(.3, "double", base_damage, random.choice((-58, 58))))
            if combo >= 3:
                self.after_queue.append(AfterStrike(.6, "triple", base_damage, random.choice((-112, 112))))

    def iron_punch(self):
        y, d = self.yuta, self.dummy
        direction = safe_normal(d.pos - y.pos)
        damage = YUTA_IRON_ARM_DAMAGE * self.attack_multiplier()
        y.punch_timer = YUTA_PUNCH_INTERVAL
        self.sound.play("punch")
        self.arm_anims.append(ArmAnim(Vec2(d.pos), direction))
        dealt = self.damage_dummy(damage, "IRON ARM", STEEL, 2)
        self.heal_yuta_from_basic(dealt, y.pos)
        tier = y.surge_tier
        if tier == 4 and random.random() < .25:
            d.stunned = max(d.stunned, 2)
            self.sound.play("stun")
            self.text("IMMOBILIZED  2.0s", d.pos + Vec2(0, -92), GOLD, True)
        elif tier == 3 and random.random() < .35:
            d.stunned = max(d.stunned, 3)
            self.sound.play("stun")
            self.text("STUNNED  3.0s", d.pos + Vec2(0, -92), GOLD, True)
        elif tier == 2 and random.random() < .35:
            d.stunned = max(d.stunned, 2)
            self.attach_chain(5)
        elif tier == 1 and random.random() < .45:
            d.stunned = max(d.stunned, 3)
            self.attach_chain(6)

    def attach_chain(self, duration):
        self.chain.life = max(self.chain.life, duration)
        self.chain.pulse = .5
        self.sound.play("chain_attach")
        self.sound.play("chain_pull")
        self.text("CHAIN PULL", self.dummy.pos + Vec2(0, -116), STEEL, True)
        self.burst(self.dummy.pos, STEEL, 18, 280, "spark", 4)

    def update_chain(self, dt):
        if self.chain.life <= 0:
            return
        self.chain.life -= dt
        self.chain.pulse = max(0, self.chain.pulse - dt)
        y, d = self.yuta, self.dummy
        delta = d.pos - y.pos
        max_dist = y.radius + d.radius + self.chain.length
        dist = delta.length()
        if dist > max_dist:
            n = delta / dist
            d.pos = y.pos + n * max_dist
            speed = d.vel.length()
            inward = -n * speed
            d.vel = safe_normal(d.vel.lerp(inward, .55), inward) * speed
            if random.random() < .22:
                self.particles.append(Particle(d.pos - n * d.radius, -n * random.uniform(100, 230),
                                               .35, .35, random.uniform(2, 5), STEEL, "spark"))

    def start_pure_love(self):
        y, r = self.yuta, self.rika
        y.ce -= 200
        y.pure_cd = 30
        side_left = y.pos.x < ARENA.centerx
        stand_x = ARENA.left + y.radius + 8 if side_left else ARENA.right - y.radius - 8
        y.pos = Vec2(stand_x, ARENA.centery)
        y.vel = Vec2()
        y.immobilized = 1.25
        direction = Vec2(1, 0) if side_left else Vec2(-1, 0)
        source = y.pos + direction * 194 + Vec2(0, -4)
        self.beam = BeamState("setup", 1.25, direction, y.pos + direction * 72, Vec2(), 0, Vec2(r.pos), source)
        r.alive = False
        r.despawning = 1.25
        self.sound.play("rika_spawn")
        self.rika_disappear_fx(self.beam.return_pos)
        self.text("PURE LOVE SETUP", y.pos + Vec2(0, -84), PINK, True)

    def beam_triangle(self):
        b = self.beam
        origin = Vec2(b.source)
        wall_x = ARENA.right if b.direction.x > 0 else ARENA.left
        top = Vec2(wall_x, ARENA.top)
        bottom = Vec2(wall_x, ARENA.bottom)
        return origin, top, bottom

    def target_inside_beam(self, target):
        if self.beam.phase != "blast":
            return False
        return circle_triangle_hit(target.pos, target.radius, *self.beam_triangle())

    def pure_love_locks_yuta_position(self):
        return self.beam.phase in {"setup", "charge", "blast", "return"}

    def yuta_can_basic_attack(self):
        return self.yuta.immobilized <= 0 or self.beam.phase in {"charge", "blast"}

    def update_beam(self, dt):
        if not self.beam.phase:
            return
        b, y, r, d = self.beam, self.yuta, self.rika, self.dummy
        b.timer -= dt
        y.facing = Vec2(b.direction)
        y.pos.x = ARENA.left + y.radius + 8 if b.direction.x > 0 else ARENA.right - y.radius - 8
        y.pos.y = ARENA.centery
        y.vel = Vec2()
        if b.phase == "setup":
            r.pos = y.pos + b.direction * 132 + Vec2(0, -4)
            if b.timer <= 0:
                r.alive = True
                r.hp = max(1, r.hp)
                r.reforming = 1.25
                b.phase, b.timer = "charge", 1.5
                b.source = r.pos + b.direction * 62
                self.sound.play("charge")
                self.text("PURE LOVE CHARGE", y.pos + Vec2(0, -108), PINK_HOT, True)
                self.rika_appear_fx(r.pos)
        elif b.phase == "charge":
            r.pos = b.source - b.direction * 62
            for _ in range(5):
                angle = random.random() * math.tau
                p = b.source + Vec2(math.cos(angle), math.sin(angle)) * random.uniform(32, 132)
                self.particles.append(Particle(p, safe_normal(b.source - p) * random.uniform(130, 330),
                                               .42, .42, random.uniform(3, 7), PINK, "beam_fire"))
            if b.timer <= 0:
                b.phase, b.timer, b.tick = "blast", 7, 0
                self.sound.play("blast")
                self.text("PURE LOVE", y.pos + Vec2(0, -132), PINK_HOT, True)
                self.shake = 16
        elif b.phase == "blast":
            r.pos = b.source - b.direction * 62
            b.origin = Vec2(b.source)
            b.end = b.origin + b.direction * ray_rect_distance(b.origin, b.direction, ARENA)
            if self.target_inside_beam(d):
                d.pos += b.direction * 430 * dt
                d.pos.x = clamp(d.pos.x, ARENA.left + d.radius, ARENA.right - d.radius)
                d.pos.y = clamp(d.pos.y, ARENA.top + d.radius, ARENA.bottom - d.radius)
                d.vel = safe_normal(d.vel.lerp(b.direction * d.vel.length(), min(1, dt * 5)), b.direction) * d.vel.length()
            b.tick -= dt
            if b.tick <= 0:
                b.tick = .25
                if self.target_inside_beam(d):
                    self.damage_dummy(40, "PURE LOVE", PINK_HOT, 2)
                    healed = min(10, y.max_hp - y.hp)
                    y.hp += healed
                    self.add_ce(2.5, False)
                    if healed:
                        self.text(f"+{int(healed)} HP", y.pos + Vec2(0, -72), PINK)
                    self.burst(d.pos, PINK_HOT, 12, 190, "beam_fire", 6)
            for _ in range(8):
                along = random.random()
                _, top, bottom = self.beam_triangle()
                center = b.origin.lerp((top + bottom) * .5, along)
                half_height = (ARENA.height * .5) * along
                p = center + Vec2(0, random.uniform(-half_height, half_height))
                self.particles.append(Particle(p, Vec2(random.uniform(-8, 8), random.uniform(-65, 65)),
                                               .24, .24, random.uniform(2, 7), PINK_HOT, "beam_fire"))
            if b.timer <= 0:
                b.phase, b.timer = "return", 1.25
                r.alive = False
                r.despawning = 1.25
                self.rika_disappear_fx(r.pos)
        elif b.phase == "return":
            if b.timer <= 0:
                if r.hp > 0 and not r.died_after_spawn:
                    r.pos = Vec2(b.return_pos)
                    r.alive = True
                    r.reforming = .8
                    self.sound.play("rika_spawn")
                    self.rika_appear_fx(r.pos)
                y.immobilized = 0
                y.vel = safe_normal(Vec2(1, 0).rotate(random.random() * 360)) * 350
                self.beam = BeamState()

    def rika_claw(self):
        r, d = self.rika, self.dummy
        direction = safe_normal(d.pos - r.pos)
        r.attack_timer = .5
        r.claw_anim = .46
        r.claw_dir = direction
        r.claw_target = Vec2(d.pos)
        self.sound.play("rika_claw")
        self.damage_dummy(RIKA_CLAW_DAMAGE, "RIKA CLAW", RIKA_SKIN, 1)
        healed = min(RIKA_CLAW_DAMAGE * .5, r.max_hp - r.hp)
        r.hp += healed
        if healed:
            self.text(f"+{int(healed)} HP", r.pos + Vec2(0, -112), RIKA_SKIN)
        gained = self.add_ce(18)
        if gained:
            self.text(f"+{int(gained)} CE", self.yuta.pos + Vec2(0, -96), VIOLET)

    def dummy_attack_target(self, target=None):
        d = self.dummy
        if target is None:
            target = (self.rika if self.rika.alive
                      and d.pos.distance_to(self.rika.pos) < d.pos.distance_to(self.yuta.pos) + 80
                      else self.yuta)
        d.punch_timer = 1
        d.punch_anim = .42
        d.punch_target = Vec2(target.pos)
        base = math.degrees(math.atan2(target.pos.y - d.pos.y, target.pos.x - d.pos.x))
        d.punch_dir = Vec2(1, 0).rotate(base + random.choice((-125, -75, 75, 125)))
        self.sound.play("dummy_punch")
        if target is self.rika:
            self.damage_rika(255)
        else:
            self.damage_yuta(255)

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

        y, d, r = self.yuta, self.dummy, self.rika
        y.timers(dt)
        d.update_timers(dt)
        r.timers(dt)
        self.spawn_rika_if_ready()
        self.update_beam(dt)
        self.update_chain(dt)

        y.facing += (safe_normal(y.vel, y.facing) - y.facing) * min(1, dt * 9)
        d.facing += (safe_normal(d.vel, d.facing) - d.facing) * min(1, dt * 9)
        yuta_position_locked = self.pure_love_locks_yuta_position()
        if y.immobilized <= 0 and not yuta_position_locked:
            y.pos += safe_normal(y.vel) * 350 * dt
            y.vel = safe_normal(y.vel) * 350
            bounced = self.wall_bounce(y, d)
            if bounced and y.pure_cd <= 0 and y.ce >= 200 and r.alive and not self.actions_locked:
                self.start_pure_love()
            elif bounced and r.alive:
                self.maybe_redirect_yuta_on_bounce()
        if d.stunned <= 0:
            d.pos += d.vel * d.speed_scale * dt
            self.wall_bounce(d, y, True)
        if r.alive and not self.beam.phase:
            r.pos += safe_normal(r.vel) * 280 * dt
            r.vel = safe_normal(r.vel) * 280
            if self.wall_bounce(r, d):
                self.redirect_to_nearest_hostile(r)

        collided_yuta = self.separate(y, d, y.immobilized <= 0 and not yuta_position_locked, d.stunned <= 0)
        rika_manifested_for_pure_love = r.alive and self.beam.phase in {"charge", "blast"}
        collided_rika = False
        if r.alive and (not self.beam.phase or rika_manifested_for_pure_love):
            collided_rika = self.separate(
                r, d, not rika_manifested_for_pure_love, d.stunned <= 0
            )
        if r.alive and not self.beam.phase:
            self.separate(y, r, y.immobilized <= 0, True)

        distance = y.pos.distance_to(d.pos)
        dummy_in_beam = self.target_inside_beam(d)
        yuta_can_basic = self.yuta_can_basic_attack()
        if (distance <= y.radius + d.radius + YUTA_KATANA_RANGE and y.katana_timer <= 0
                and yuta_can_basic and not dummy_in_beam and not self.actions_locked):
            self.katana_slash()
        if (collided_yuta and y.punch_timer <= 0 and yuta_can_basic
                and not dummy_in_beam and not self.actions_locked):
            self.iron_punch()
        if collided_yuta and d.punch_timer <= 0 and d.stunned <= 0:
            self.dummy_attack_target(y)
        if r.alive and not self.beam.phase:
            if (r.pos.distance_to(d.pos) <= r.radius + d.radius + RIKA_CLAW_RANGE
                    and r.attack_timer <= 0 and not self.actions_locked):
                self.rika_claw()
        if collided_rika and d.punch_timer <= 0 and d.stunned <= 0:
            self.dummy_attack_target(r)

        surge_requirement = 500 if r.died_after_spawn and not r.alive else 150
        if (y.surge_active <= 0 and y.surge_cd <= 0 and y.ce >= surge_requirement
                and not self.beam.phase and not self.actions_locked):
            self.cast_surge()

        for strike in self.after_queue:
            strike.timer -= dt
        ready = [strike for strike in self.after_queue if strike.timer <= 0]
        self.after_queue = [strike for strike in self.after_queue if strike.timer > 0]
        for strike in ready:
            self.katana_slash(True, strike.angle_offset)

        for collection in (self.particles, self.texts, self.slashes, self.arm_anims, self.shield_pops):
            for item in collection:
                if hasattr(item, "update"):
                    item.update(dt)
                elif hasattr(item, "life"):
                    item.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        self.texts = [t for t in self.texts if t.life > 0]
        self.slashes = [s for s in self.slashes if s.life > 0]
        self.arm_anims = [a for a in self.arm_anims if a.life > 0]
        self.shield_pops = [p for p in self.shield_pops if p.life > 0]

        if d.hp <= 0 or y.hp <= 0:
            self.winner = "YUTA WINS" if y.hp > d.hp else "DUMMYBOT WINS"
            self.round_over = 4

    def draw_yuta_decor(self, ball, center, radius, facing, roll):
        q = Vec2(-facing.y, facing.x)
        body = center - facing * radius * .05
        pygame.draw.arc(ball, (23, 26, 34), pygame.Rect(center.x - radius * .72, center.y - radius * .70,
                                                        radius * 1.44, radius * 1.4),
                        roll + .2, roll + 2.1, 7)
        pygame.draw.arc(ball, STEEL, pygame.Rect(center.x - radius * .78, center.y - radius * .77,
                                                 radius * 1.56, radius * 1.54),
                        roll + math.pi, roll + math.pi * 1.55, 4)
        arm_root = body + q * radius * .48 + facing * radius * .18
        fist = arm_root + facing * radius * .28
        pygame.draw.line(ball, DARK_STEEL, arm_root, fist, 9)
        pygame.draw.line(ball, STEEL, arm_root - q * 2, fist - q * 2, 4)
        pygame.draw.circle(ball, STEEL, fist, int(radius * .14))
        wrap_start = body - q * radius * .54 + facing * radius * .14
        pygame.draw.line(ball, RED_WRAP, wrap_start, wrap_start + facing * radius * .46, 5)

    def draw_rika(self, dst, offset):
        r = self.rika
        if not r.alive and r.reforming <= 0 and r.despawning <= 0:
            return
        p = r.pos + offset
        alpha_mul = 1
        if r.reforming > 0:
            alpha_mul = 1 - clamp(r.reforming / 1.25, 0, 1) * .55
            grow = 1 - clamp(r.reforming / 1.25, 0, 1)
            p = p + Vec2(0, (1 - grow) * 28)
        if r.despawning > 0 and not r.alive:
            collapse = clamp(r.despawning / 1.25, 0, 1)
            alpha_mul *= collapse
            p = p + Vec2(0, (1 - collapse) * 52)
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        glow_circle(layer, p, 45, PINK, .16 * alpha_mul)
        direction = safe_normal(self.dummy.pos - r.pos, Vec2(1, 0))
        q = Vec2(-direction.y, direction.x)
        base = p - direction * 16
        tail = [base - direction * 30 - q * 38, base - direction * 75, base - direction * 30 + q * 38,
                base + direction * 22 + q * 30, base + direction * 34 - q * 8, base + direction * 20 - q * 35]
        pygame.draw.polygon(layer, (*RIKA_SHADOW, int(245 * alpha_mul)), tail)
        pygame.draw.lines(layer, (12, 12, 20, int(225 * alpha_mul)), True, tail, 5)
        torso = [p - direction * 35 - q * 34, p + direction * 4 - q * 49, p + direction * 55 - q * 24,
                 p + direction * 61 + q * 18, p + direction * 10 + q * 48, p - direction * 44 + q * 31]
        pygame.draw.polygon(layer, (*RIKA_SKIN, int(240 * alpha_mul)), torso)
        pygame.draw.lines(layer, (32, 34, 43, int(230 * alpha_mul)), True, torso, 4)
        head = p + direction * 46 - Vec2(0, 42)
        pygame.draw.ellipse(layer, (*RIKA_SKIN, int(245 * alpha_mul)), pygame.Rect(head.x - 39, head.y - 30, 78, 60))
        pygame.draw.arc(layer, (28, 29, 38, int(245 * alpha_mul)), pygame.Rect(head.x - 40, head.y - 30, 80, 61),
                        .1, math.tau - .1, 4)
        mouth = [head + direction * 36 - q * 21, head + direction * 54, head + direction * 36 + q * 21,
                 head + direction * 19 + q * 12, head + direction * 19 - q * 12]
        pygame.draw.polygon(layer, (26, 9, 18, int(245 * alpha_mul)), mouth)
        for i in range(9):
            side = -1 + i / 4
            root = head + direction * 34 + q * side * 17
            tip = root + direction * (22 + (i % 2) * 10) + q * side * 5
            pygame.draw.line(layer, (235, 235, 230, int(240 * alpha_mul)), root, tip, 3)
        for i in range(13):
            angle = -125 + i * 20 + math.sin(self.time * 3 + i) * 10
            root = head - direction * 12 + q * (-45 + i * 7)
            tendril = Vec2(1, 0).rotate(angle) * (42 + (i % 4) * 10)
            mid = root + tendril * .55 + q * math.sin(self.time * 4 + i) * 12
            tip = root + tendril + Vec2(math.sin(self.time * 5 + i) * 10, math.cos(self.time * 4 + i) * 9)
            pygame.draw.lines(layer, (*RIKA_SKIN, int(230 * alpha_mul)), False, [root, mid, tip], 8)
            pygame.draw.lines(layer, (36, 38, 48, int(160 * alpha_mul)), False, [root, mid, tip], 2)
        for side in (-1, 1):
            shoulder = p + direction * 10 + q * side * 45 - Vec2(0, 18)
            elbow = shoulder - direction * 20 + q * side * 48 + Vec2(0, 34 + math.sin(self.time * 4 + side) * 8)
            hand = elbow + direction * 35 + q * side * 22 + Vec2(0, 42)
            pygame.draw.lines(layer, (*RIKA_SKIN, int(238 * alpha_mul)), False, [shoulder, elbow, hand], 18)
            pygame.draw.lines(layer, (28, 30, 39, int(205 * alpha_mul)), False, [shoulder, elbow, hand], 3)
            for finger in range(4):
                spread = (finger - 1.5) * 8
                tip = hand + direction * (20 + finger % 2 * 8) + q * side * spread + Vec2(0, 18)
                pygame.draw.line(layer, (20, 20, 28, int(230 * alpha_mul)), hand + q * side * spread * .4, tip, 4)
        if r.hit_flash > 0:
            pygame.draw.circle(layer, (255, 255, 255, 130), p, int(r.radius))
        if r.despawning > 0 and not r.alive:
            floor_y = p.y + r.radius * .58
            pygame.draw.ellipse(layer, (22, 18, 31, int(170 * alpha_mul)),
                                pygame.Rect(p.x - 76, floor_y - 15, 152, 30))
            for i in range(8):
                x = p.x - 54 + i * 15 + math.sin(self.time * 9 + i) * 5
                pygame.draw.line(layer, (95, 78, 116, int(180 * alpha_mul)),
                                 (x, p.y + 15), (p.x + math.sin(i) * 22, floor_y), 4)
        dst.blit(layer, (0, 0))
        if r.alive:
            bar = pygame.Rect(p.x - 55, p.y - 116, 110, 8)
            pygame.draw.rect(dst, (12, 13, 20), bar, border_radius=4)
            fill = bar.inflate(-2, -2)
            fill.width = int(fill.width * clamp(r.hp / r.max_hp, 0, 1))
            pygame.draw.rect(dst, RIKA_SKIN, fill, border_radius=3)

    def draw_slashes(self, dst, offset):
        for slash in self.slashes:
            t = clamp(slash.life / slash.max_life, 0, 1)
            progress = 1 - t
            origin = slash.origin + offset
            target = slash.pos + offset
            direction = safe_normal(slash.direction)
            q = Vec2(-direction.y, direction.x)
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            swing_center = origin + direction * 24
            start_angle = math.degrees(math.atan2(direction.y, direction.x)) + slash.side * lerp(-112, 38, progress)
            blade_dir = Vec2(1, 0).rotate(start_angle)
            for i in range(5, 0, -1):
                echo_dir = Vec2(1, 0).rotate(start_angle - slash.side * i * 10)
                echo_tip = swing_center + echo_dir * (YUTA_KATANA_RANGE + 18 + i * 4)
                pygame.draw.line(layer, (*slash.color, int((12 + (6 - i) * 14) * t)),
                                 swing_center, echo_tip, max(1, 8 - i))
            hilt = swing_center - blade_dir * 18
            tip = swing_center + blade_dir * (YUTA_KATANA_RANGE + 34)
            katana_color = WHITE if slash.label == "AFTER-IMAGE" else (42, 45, 54)
            pygame.draw.line(layer, (255, 238, 248, int(185 * t)), hilt, tip, 10)
            pygame.draw.line(layer, (*katana_color, int(245 * t)), hilt, tip, 5)
            pygame.draw.line(layer, (*RED_WRAP, int(230 * t)), hilt - blade_dir * 28, hilt + blade_dir * 15, 9)
            arc_center = origin + direction * 80
            arc_rect = pygame.Rect(arc_center.x - YUTA_KATANA_RANGE, arc_center.y - YUTA_KATANA_RANGE,
                                   YUTA_KATANA_RANGE * 2, YUTA_KATANA_RANGE * 2)
            arc_start = math.radians(start_angle - slash.side * 50)
            pygame.draw.arc(layer, (*PINK, int(118 * t)), arc_rect, arc_start, arc_start + math.pi * .72, 18)
            pygame.draw.arc(layer, (*PINK_HOT, int(235 * t)), arc_rect, arc_start, arc_start + math.pi * .72, 4)
            for i in range(4):
                d = direction.rotate(slash.side * (i - 1.5) * 11)
                start = target - d * (30 + i * 5)
                end = target + d * (45 + i * 10)
                pygame.draw.line(layer, (*WHITE, int(120 * t)), start, end, 2)
            if slash.label == "AFTER-IMAGE":
                for i in range(3):
                    phantom = origin - direction * (18 + i * 10) + q * (i - 1) * 22 + Vec2(0, math.sin(self.time * 16 + i) * 8)
                    pygame.draw.circle(layer, (236, 239, 250, int((42 - i * 8) * t)), phantom, 28)
                    pygame.draw.line(layer, (255, 255, 255, int((150 - i * 22) * t)), phantom, target + q * (i - 1) * 16, 3)
            dst.blit(layer, (0, 0))

    def draw_surge_aura(self, dst, offset):
        y = self.yuta
        if y.surge_active <= 0:
            return
        tier = y.surge_tier
        intensity = {5: .45, 4: .58, 3: .72, 2: .95, 1: 1.15}.get(tier, .45)
        center = y.pos + offset
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(4 + max(0, 3 - tier)):
            radius = y.radius + 16 + i * 10 + math.sin(self.time * (7 + i) + i) * 5
            start = self.time * (2.2 + i * .35) + i
            pygame.draw.arc(layer, (*PINK, int(75 * intensity)),
                            pygame.Rect(center.x - radius, center.y - radius, radius * 2, radius * 2),
                            start, start + math.pi * (1.05 + .15 * i), 3)
        sparks = 5 + (6 - tier) * 2
        for i in range(sparks):
            angle = self.time * (8 + i % 3) + i * math.tau / sparks
            a = center + Vec2(math.cos(angle), math.sin(angle)) * (y.radius + 8)
            b = center + Vec2(math.cos(angle + .28), math.sin(angle + .28)) * (y.radius + 35 + intensity * 18)
            pygame.draw.line(layer, (*PINK_HOT, int(125 * intensity)), a, b, 2)
            pygame.draw.circle(layer, (255, 225, 248, int(155 * intensity)), b, 2 + i % 2)
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_iron_arm(self, dst, offset):
        for anim in self.arm_anims:
            progress = 1 - anim.life / anim.max_life
            fade = clamp(min(progress / .12, (1 - progress) / .28), 0, 1)
            direction = safe_normal(anim.direction)
            q = Vec2(-direction.y, direction.x)
            target = anim.target + offset
            palm = target + direction * lerp(-132, 112, progress * progress * (3 - 2 * progress))
            wrist, base = palm - direction * 42, palm - direction * 90
            alpha = int(245 * fade)
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(5, 0, -1):
                ghost = palm - direction * i * 17
                pygame.draw.ellipse(layer, (*STEEL, int(alpha * .055 * (6 - i))),
                                    pygame.Rect(ghost.x - 28, ghost.y - 20, 56, 40))
            forearm = [base - q * 17, wrist - q * 23, palm - direction * 18 - q * 25,
                       palm - direction * 18 + q * 25, wrist + q * 23, base + q * 17]
            pygame.draw.polygon(layer, (*DARK_STEEL, alpha), forearm)
            pygame.draw.line(layer, (*STEEL, int(alpha * .85)), base - q * 8, palm - direction * 20 - q * 12, 5)
            pygame.draw.line(layer, (248, 252, 255, int(alpha * .7)), wrist - q * 16, palm - direction * 16 - q * 18, 2)
            glove = [palm - direction * 26 - q * 27, palm + direction * 10 - q * 33,
                     palm + direction * 33 - q * 18, palm + direction * 33 + q * 19,
                     palm + direction * 9 + q * 32, palm - direction * 27 + q * 24]
            pygame.draw.polygon(layer, (*STEEL, alpha), glove)
            pygame.draw.lines(layer, (250, 252, 255, int(alpha * .85)), True, glove, 3)
            for side in (-22, -8, 7, 21):
                knuckle = palm + direction * 31 + q * side
                pygame.draw.rect(layer, (*DARK_STEEL, alpha), pygame.Rect(knuckle.x - 9, knuckle.y - 9, 18, 18), border_radius=4)
                pygame.draw.line(layer, (245, 248, 255, int(alpha * .8)), knuckle - q * 5 - direction * 4,
                                 knuckle + q * 5 - direction * 4, 2)
            dst.blit(layer, (0, 0))

    def draw_chain(self, dst, offset):
        if self.chain.life <= 0:
            return
        start = self.yuta.pos + offset
        end = self.dummy.pos + offset
        direction = safe_normal(end - start)
        q = Vec2(-direction.y, direction.x)
        length = start.distance_to(end)
        count = max(4, int(length / 28))
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(count + 1):
            t = i / count
            center = start.lerp(end, t) + q * math.sin(self.time * 9 + i) * 4
            size = 18 + (i % 2) * 4 + self.chain.pulse * 8
            rect = pygame.Rect(center.x - size * .7, center.y - size * .35, size * 1.4, size * .7)
            angle = math.degrees(math.atan2(direction.y, direction.x)) + (90 if i % 2 else 0)
            link = pygame.Surface((int(size * 2.2), int(size * 1.6)), pygame.SRCALPHA)
            lr = link.get_rect()
            pygame.draw.ellipse(link, (42, 46, 55, 230), lr.inflate(-4, -8), 5)
            pygame.draw.ellipse(link, (*STEEL, 245), lr.inflate(-7, -11), 3)
            pygame.draw.ellipse(link, (245, 248, 255, 150), lr.inflate(-13, -16), 2)
            rotated = pygame.transform.rotate(link, -angle)
            layer.blit(rotated, rotated.get_rect(center=center))
        pygame.draw.line(layer, (255, 255, 255, 95), start, end, 2)
        dst.blit(layer, (0, 0))

    def draw_beam(self, dst, offset):
        if not self.beam.phase:
            return
        b = self.beam
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        if b.phase == "charge":
            center = b.source + offset
            for i in range(4):
                radius = 34 + i * 24 + math.sin(self.time * 7 + i) * 5
                pygame.draw.circle(layer, (*PINK, 145 - i * 25), center, int(radius), 3)
            pygame.draw.circle(layer, (255, 230, 248, 205), center, 18)
            pygame.draw.circle(layer, (*PINK_HOT, 230), center, 30, 4)
            for i in range(12):
                angle = self.time * 8 + i / 12 * math.tau
                a = center + Vec2(math.cos(angle), math.sin(angle)) * 22
                c = center + Vec2(math.cos(angle + .22), math.sin(angle + .22)) * (55 + i % 3 * 10)
                pygame.draw.line(layer, (*PINK_HOT, 110), a, c, 2)
        elif b.phase == "blast":
            origin, top, bottom = [p + offset for p in self.beam_triangle()]
            center_far = (top + bottom) * .5
            cone = [origin, top, bottom]
            pygame.draw.polygon(layer, (*PINK_HOT, 38), cone)
            pygame.draw.polygon(layer, (*PINK, 104), [origin, top + Vec2(0, 22), bottom - Vec2(0, 22)])
            pygame.draw.polygon(layer, (255, 210, 238, 54), [origin, top + Vec2(0, 64), bottom - Vec2(0, 64)])
            for edge in (top, bottom):
                points = [origin]
                for i in range(1, 22):
                    t = i / 21
                    base = origin.lerp(edge, t)
                    jitter = Vec2(0, math.sin(self.time * 17 + i * 1.7) * (5 + 18 * t))
                    points.append(base + jitter)
                pygame.draw.lines(layer, (*VIOLET, 210), False, points, 4)
                pygame.draw.lines(layer, (255, 226, 250, 135), False, points, 2)
            for i in range(13):
                t0 = random.Random(i).uniform(.04, .18)
                t1 = .98
                y0 = math.sin(self.time * 8 + i) * 10
                y1 = math.sin(self.time * 5 + i * 2.1) * ARENA.height * random.uniform(.12, .42)
                pygame.draw.line(layer, (255, 255, 255, 88),
                                 origin.lerp(center_far, t0) + Vec2(0, y0),
                                 origin.lerp(center_far, t1) + Vec2(0, y1), 2)
            pygame.draw.circle(layer, (255, 226, 248, 235), origin, 22)
            pygame.draw.circle(layer, (*PINK_HOT, 235), origin, 34, 4)
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_shield_pops(self, dst, offset):
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for pop in self.shield_pops:
            t = clamp(pop.life / pop.max_life, 0, 1)
            p = pop.pos + offset
            radius = 28 + (1 - t) * 52
            pygame.draw.circle(layer, (*PINK, int(125 * t)), p, int(radius), 4)
            pygame.draw.circle(layer, (255, 240, 252, int(150 * t)), p, int(radius * .68), 2)
            for i in range(8):
                angle = self.time * 7 + i * math.tau / 8
                a = p + Vec2(math.cos(angle), math.sin(angle)) * radius * .55
                b = p + Vec2(math.cos(angle + .35), math.sin(angle + .35)) * radius
                pygame.draw.line(layer, (*PINK_HOT, int(120 * t)), a, b, 2)
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_hud(self, dst, fonts):
        def bar(rect, value, maximum, color, flip=False):
            pygame.draw.rect(dst, (12, 13, 24), rect, border_radius=8)
            pygame.draw.rect(dst, (58, 61, 80), rect, 2, border_radius=8)
            fill = rect.inflate(-6, -6)
            fill.width = int(fill.width * clamp(value / maximum, 0, 1))
            if flip:
                fill.right = rect.right - 3
            pygame.draw.rect(dst, color, fill, border_radius=5)
        y, d = self.yuta, self.dummy
        bar(pygame.Rect(75, 42, 430, 23), y.hp, y.max_hp, PINK)
        bar(pygame.Rect(W - 505, 42, 430, 23), d.hp, d.max_hp, STEEL, True)
        dst.blit(fonts["name"].render("YUTA", True, WHITE), (75, 13))
        name = fonts["name"].render("DUMMYBOT", True, (225, 228, 235))
        dst.blit(name, (W - 75 - name.get_width(), 13))
        dst.blit(fonts["small"].render(f"{int(y.hp)} / 5000", True, WHITE), (80, 70))
        hp = fonts["small"].render(f"{int(d.hp)} / {int(d.max_hp)}", True, STEEL)
        dst.blit(hp, (W - 80 - hp.get_width(), 70))
        ce = pygame.Rect(75, 86, 430, 11)
        pygame.draw.rect(dst, (20, 15, 32), ce, border_radius=5)
        pygame.draw.rect(dst, (*VIOLET, 230), (ce.x, ce.y, int(ce.width * y.ce / y.max_ce), ce.height), border_radius=5)
        dst.blit(fonts["tiny"].render(f"CURSE ENERGY {int(y.ce)} / 750", True, VIOLET), (80, 101))
        center = fonts["tiny"].render("KATANA AFTER-IMAGE  //  IRON ARM  //  RIKA  //  PURE LOVE", True, (205, 190, 230))
        dst.blit(center, (W / 2 - center.get_width() / 2, 18))
        status = []
        if y.surge_active > 0:
            status.append(f"SURGE T{y.surge_tier} {y.surge_active:.1f}s")
        if d.stunned > 0:
            status.append(f"TARGET STUNNED {d.stunned:.1f}s")
        if self.chain.life > 0:
            status.append(f"CHAIN {self.chain.life:.1f}s")
        if self.beam.phase:
            status.append(f"PURE LOVE {self.beam.phase.upper()}")
        st = fonts["tiny"].render("   ".join(status), True, GOLD)
        dst.blit(st, (W / 2 - st.get_width() / 2, 76))
        skills = [("SURGE", y.surge_cd if y.surge_active <= 0 else 0, 10, VIOLET),
                  ("PURE LOVE", y.pure_cd, 30, PINK),
                  ("RIKA", 0 if self.rika.alive else self.rika.spawn_timer, 10, RIKA_SKIN)]
        for i, (label, cd, total, color) in enumerate(skills):
            x, yy = 82 + i * 208, H - 52
            dst.blit(fonts["tiny"].render(label, True, color), (x, yy - 18))
            pygame.draw.rect(dst, (24, 21, 34), (x, yy, 170, 7), border_radius=4)
            pygame.draw.rect(dst, color, (x, yy, int(170 * (1 - clamp(cd / total, 0, 1))), 7), border_radius=4)
        info = fonts["tiny"].render("R  RESTART     M  MUTE     ESC  EXIT", True, (110, 122, 150))
        dst.blit(info, (W - 82 - info.get_width(), H - 40))

    def draw(self, dst, fonts):
        offset = Vec2(random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake)) if self.shake else Vec2()
        shared.draw_arena(dst, ARENA, W, H, self.time, offset)
        shared.draw_movement_trail(dst, self.yuta, PINK, offset, 5)
        shared.draw_movement_trail(dst, self.dummy, (155, 165, 185), offset, 4)
        if self.rika.alive:
            shared.draw_movement_trail(dst, self.rika, RIKA_SKIN, offset, 4)
        self.draw_chain(dst, offset)
        self.draw_beam(dst, offset)
        for particle in self.particles:
            particle.draw(dst, offset)
        self.draw_rika(dst, offset)
        self.draw_shield_pops(dst, offset)
        self.draw_surge_aura(dst, offset)
        shared.draw_ball(dst, self.yuta.pos + offset, self.yuta.radius, (26, 30, 42), PINK,
                         self.yuta.facing, self.yuta.roll, self.yuta.squash, self.yuta.hit_flash,
                         0, 0, WHITE, self.draw_yuta_decor)
        shared.draw_ball(dst, self.dummy.pos + offset, self.dummy.radius, (84, 91, 108), (180, 190, 205),
                         self.dummy.facing, self.time * 2, self.dummy.squash, self.dummy.hit_flash,
                         self.dummy.frozen, self.dummy.burned)
        self.draw_slashes(dst, offset)
        self.draw_iron_arm(dst, offset)
        if self.rika.alive and self.rika.claw_anim > 0:
            self.draw_rika_claw(dst, offset)
        shared.draw_dummy_punch(dst, self.dummy, self.time, offset, W, H)
        self.draw_status_icons(dst, offset)
        for text in self.texts:
            font = fonts["impact"] if text.big else fonts["small"]
            image = font.render(text.text, True, text.color)
            shadow = font.render(text.text, True, (5, 5, 10))
            p = text.pos + offset
            dst.blit(shadow, (p.x - image.get_width() / 2 + 2, p.y + 2))
            dst.blit(image, (p.x - image.get_width() / 2, p.y))
        self.draw_hud(dst, fonts)
        if self.banner_time > 0:
            image = fonts["banner"].render("YUTA // AUTONOMOUS COMBAT PROTOTYPE", True, WHITE)
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - 100))
        if self.round_over:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((5, 5, 14, 150))
            dst.blit(veil, (0, 0))
            image = fonts["winner"].render(self.winner, True, PINK)
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - image.get_height() / 2))

    def draw_rika_claw(self, dst, offset):
        r = self.rika
        progress = 1 - r.claw_anim / .46
        fade = clamp(min(progress / .12, (1 - progress) / .25), 0, 1)
        direction = safe_normal(r.claw_dir)
        q = Vec2(-direction.y, direction.x)
        target = r.claw_target + offset
        shoulder_center = r.pos + offset + direction * 18
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        reach = progress * progress * (3 - 2 * progress)
        for side in (-1, 1):
            shoulder = shoulder_center + q * side * 42 - Vec2(0, 18)
            elbow = shoulder.lerp(target - direction * 48 + q * side * 42, reach)
            hand = shoulder.lerp(target + q * side * 18, min(1, reach * 1.25))
            pygame.draw.lines(layer, (*RIKA_SKIN, int(230 * fade)), False, [shoulder, elbow, hand], 18)
            pygame.draw.lines(layer, (25, 26, 34, int(225 * fade)), False, [shoulder, elbow, hand], 4)
            for finger in range(4):
                spread = (finger - 1.5) * 7
                claw_tip = hand + direction * (22 + finger % 2 * 8) + q * (side * 14 + spread)
                pygame.draw.line(layer, (12, 13, 20, int(245 * fade)), hand + q * spread * .35, claw_tip, 5)
                pygame.draw.line(layer, (245, 246, 250, int(125 * fade)), hand + q * spread * .35, claw_tip, 1)
        for side in (-1, 0, 1):
            center = target - direction * (50 - progress * 95) + q * side * 18
            rect = pygame.Rect(center.x - 92, center.y - 92, 184, 184)
            angle = math.atan2(direction.y, direction.x) - .9 + side * .18
            pygame.draw.arc(layer, (*RIKA_SKIN, int(185 * fade)), rect, angle, angle + 1.4, 9)
            pygame.draw.arc(layer, (20, 21, 29, int(230 * fade)), rect.inflate(-18, -18), angle + .1, angle + 1.25, 4)
            for i in range(3):
                start = target - direction * (46 - progress * 34) + q * (side * 22 + (i - 1) * 9)
                end = target + direction * (34 + i * 8) + q * (side * 10 + (i - 1) * 18)
                pygame.draw.line(layer, (8, 9, 15, int(220 * fade)), start, end, 3)
                pygame.draw.line(layer, (255, 255, 255, int(80 * fade)), start - q * 2, end - q * 2, 1)
        dst.blit(layer, (0, 0))

    def draw_status_icons(self, dst, offset):
        if self.dummy.stunned <= 0:
            return
        center = self.dummy.pos + offset - Vec2(0, self.dummy.radius + 34)
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(5):
            angle = self.time * 5 + i / 5 * math.tau
            p = center + Vec2(math.cos(angle) * 34, math.sin(angle) * 13)
            pygame.draw.circle(layer, (255, 218, 92, 220), p, 5)
            pygame.draw.line(layer, (255, 246, 175, 210), p - Vec2(6, 0), p + Vec2(6, 0), 2)
        dst.blit(layer, (0, 0))


def make_fonts():
    return shared.make_fonts()


def main():
    parser = argparse.ArgumentParser(description="Yuta autonomous combat prototype")
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
    pygame.display.set_caption("Yuta // Autonomous Combat Prototype")
    clock, fonts = pygame.time.Clock(), make_fonts()
    battle, elapsed, running = Battle(args.mute or args.headless), 0, True
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
