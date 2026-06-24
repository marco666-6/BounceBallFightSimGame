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

ORANGE = (255, 129, 31)
DEEP_ORANGE = (218, 73, 18)
GOLD = (255, 205, 84)
CHAKRA = (72, 210, 255)
CHAKRA_WHITE = (225, 250, 255)
CLONE_ORANGE = (224, 151, 88)
INK = (7, 10, 22)
STEEL = (176, 186, 204)
BLACK = (10, 12, 18)

NARUTO_SPEED = 350
PUNCH_RANGE = 120
PUNCH_INTERVAL = 0.20
PUNCH_DAMAGE = 30
SHURIKEN_RANGE = 500
SHURIKEN_INTERVAL = 0.40
SHURIKEN_DAMAGE = 20
CLONE_DAMAGE_SCALE = 0.60
LIFESTEAL = 0.45


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def mix(a, b, t):
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def safe_normal(vector, fallback=Vec2(1, 0)):
    return vector.normalize() if vector.length_squared() > 0.001 else Vec2(fallback)


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
    drag: float = 0.94

    def update(self, dt):
        self.life -= dt
        self.pos += self.vel * dt
        self.vel *= self.drag ** (dt * 60)
        if self.kind == "smoke":
            self.vel.y -= 20 * dt
        elif self.kind == "flame":
            self.vel.y -= 55 * dt
        elif self.kind == "debris":
            self.vel.y += 180 * dt

    def draw(self, dst, offset):
        t = clamp(self.life / self.max_life, 0, 1)
        p = self.pos + offset
        if isinstance(self.color, (tuple, list)) and len(self.color) >= 3:
            color = tuple(self.color[:3])
        else:
            color = (255, 255, 255)
        if self.kind == "ring":
            pygame.draw.circle(
                dst,
                (*color, int(190 * t)),
                p,
                int(self.size * (2 - t)),
                max(1, int(3 * t)),
            )
        elif self.kind == "smoke":
            pygame.draw.circle(
                dst, (*color, int(72 * t)), p, int(self.size * (1.7 - t))
            )
            if self.size > 12:
                pygame.draw.circle(
                    dst,
                    (255, 255, 255, int(22 * t)),
                    p - Vec2(self.size * 0.18, self.size * 0.2),
                    max(2, int(self.size * 0.38)),
                )
        elif self.kind == "flame":
            direction = safe_normal(self.vel)
            q = Vec2(-direction.y, direction.x)
            points = [
                p + direction * self.size * 2.3,
                p - direction * self.size * 1.2 + q * self.size,
                p - direction * self.size * 0.45,
                p - direction * self.size * 1.2 - q * self.size,
            ]
            pygame.draw.polygon(dst, (*color, int(185 * t)), points)
            pygame.draw.circle(
                dst,
                (255, 238, 165, int(120 * t)),
                p - direction * self.size * 0.2,
                max(1, int(self.size * 0.32)),
            )
        elif self.kind == "shard":
            direction = safe_normal(self.vel)
            q = Vec2(-direction.y, direction.x)
            points = [
                p + direction * self.size * 2.4,
                p - direction * self.size * 0.9 + q * self.size * 0.65,
                p - direction * self.size * 0.9 - q * self.size * 0.65,
            ]
            pygame.draw.polygon(dst, (*color, int(220 * t)), points)
        elif self.kind == "orb":
            glow_circle(dst, p, self.size * (0.5 + t * 0.7), color, t)
        else:
            tail = p - safe_normal(self.vel) * self.size * 4
            pygame.draw.line(
                dst, (*self.color, int(230 * t)), tail, p, max(1, int(self.size * t))
            )


@dataclass
class FloatText:
    text: str
    pos: Vec2
    color: tuple
    life: float = 0.85
    big: bool = False

    def update(self, dt):
        self.life -= dt
        self.pos.y -= 42 * dt


@dataclass
class FistAnim:
    target: Vec2
    direction: Vec2
    color: tuple
    life: float = 0.36
    max_life: float = 0.36


@dataclass
class Shuriken:
    pos: Vec2
    vel: Vec2
    owner: object
    life: float = 1.25
    angle: float = 0
    hit: bool = False


@dataclass
class RasenganImpact:
    pos: Vec2
    direction: Vec2
    life: float = 0.58
    max_life: float = 0.58


@dataclass
class WallCrack:
    pos: Vec2
    normal: Vec2
    life: float = 1.1
    max_life: float = 1.1


@dataclass
class ShieldPop:
    pos: Vec2
    life: float = 0.34
    max_life: float = 0.34


@dataclass
class Clone:
    pos: Vec2
    vel: Vec2
    radius: float = 46
    hp: float = 70
    max_hp: float = 70
    facing: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    punch_timer: float = field(default_factory=lambda: random.uniform(0.05, 0.18))
    shuriken_timer: float = field(default_factory=lambda: random.uniform(0.12, 0.35))
    hit_flash: float = 0
    squash: float = 0
    roll: float = 0
    stunned: float = 0
    wall_bounces: int = 0
    spawn_anim: float = 0.34
    death_anim: float = 0

    def alive(self):
        return self.hp > 0 and self.death_anim <= 0

    def timers(self, dt):
        self.punch_timer -= dt
        self.shuriken_timer -= dt
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 5)
        self.stunned = max(0, self.stunned - dt)
        self.spawn_anim = max(0, self.spawn_anim - dt)
        if self.death_anim > 0:
            self.death_anim -= dt
        self.roll += self.vel.length() * dt / max(1, self.radius)


@dataclass
class Naruto:
    pos: Vec2
    vel: Vec2 = field(default_factory=lambda: Vec2(313, 158))
    radius: float = 46
    hp: float = 5000
    max_hp: float = 5000
    chakra: float = 100
    max_chakra: float = 1000
    facing: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    punch_timer: float = 0.08
    shuriken_timer: float = 0.22
    clone_cd: float = 1.2
    rasengan_cd: float = 3.4
    keikaku_cd: float = 6
    keikaku_active: float = 0
    keikaku_tick: float = 0.5
    rasengan_charge: float = 0
    rasengan_ready: bool = False
    stunned: float = 0
    fail_pending_cd: bool = False
    knockback: Vec2 = field(default_factory=Vec2)
    hit_flash: float = 0
    squash: float = 0
    roll: float = 0

    def timers(self, dt):
        self.punch_timer -= dt
        self.shuriken_timer -= dt
        self.clone_cd -= dt
        self.rasengan_cd -= dt
        self.keikaku_cd -= dt
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 5)
        self.stunned = max(0, self.stunned - dt)
        self.roll += self.vel.length() * dt / max(1, self.radius)


class SoundBank:
    def __init__(self, muted=False):
        self.muted = muted
        self.sounds = {}
        if muted:
            return
        try:
            pygame.mixer.init()
            pygame.mixer.set_num_channels(max(20, pygame.mixer.get_num_channels()))
            folder = ROOT / "Naruto-SoundEffects"
            names = {
                "punch": "Naruto-NinjaPunch.mp3",
                "shuriken_hit": "Naruto-ShurikenHit.mp3",
                "clone": "Naruto-Kagebunshin.mp3",
                "clone_death": "Naruto-CloneDeath.mp3",
                "fail": "Naruto-ChakraFailControl.mp3",
                "rasengan_charge": "Naruto-Rasengan-Charge.mp3",
                "rasengan_impact": "Naruto-Rasengan-Impact.mp3",
                "rasengan_wall": "Naruto-Rasengan-WallHit.mp3",
                "keikaku_start": "Naruto-KeikakuStart.mp3",
                "keikaku_tick": "Naruto-KeikakuTick.mp3",
                "throw1": "Naruto-ShurikenThrowOne.mp3",
                "throw2": "Naruto-ShurikenThrowTwo.mp3",
                "throw3": "Naruto-ShurikenThrowThree.mp3",
                "dummy_punch": str(
                    ROOT / "DummyBot-SoundEffects" / "MoroZhar-Punch.mp3"
                ),
            }
            for key, name in names.items():
                sound = pygame.mixer.Sound(
                    name if key == "dummy_punch" else folder / name
                )
                sound.set_volume(0.34 if key.startswith("throw") else 0.42)
                if key in {"rasengan_impact", "rasengan_wall"}:
                    sound.set_volume(0.48)
                self.sounds[key] = sound
        except (pygame.error, FileNotFoundError):
            self.muted = True

    def play(self, key):
        if not self.muted and key in self.sounds:
            self.sounds[key].play()

    def play_throw(self):
        self.play(random.choice(("throw1", "throw2", "throw3")))


class Battle:
    def __init__(self, muted=False):
        self.naruto = Naruto(Vec2(290, 385))
        self.dummy = DummyBot(Vec2(985, 385))
        self.clones = []
        self.shuriken = []
        self.particles = []
        self.texts = []
        self.fists = []
        self.rasengan_impacts = []
        self.wall_cracks = []
        self.shield_pops = []
        self.sound = SoundBank(muted)
        self.time = 0
        self.shake = 0
        self.hit_stop = 0
        self.round_over = 0
        self.winner = ""
        self.banner_time = 2.8
        self.actions_locked = False
        self.dummy_knockback = Vec2()
        self.dummy_knockback_stun_armed = False
        self.tournament_forced_target_motion = False

    def burst(self, pos, color=CHAKRA, amount=16, speed=260, kind="spark", size=4):
        for _ in range(amount):
            direction = Vec2(1, 0).rotate(random.random() * 360)
            self.particles.append(
                Particle(
                    Vec2(pos),
                    direction * random.uniform(speed * 0.25, speed),
                    random.uniform(0.25, 0.85),
                    0.85,
                    random.uniform(size * 0.55, size * 1.45),
                    color,
                    kind,
                )
            )

    def smoke(self, pos, amount=24, color=(232, 232, 224), speed=130, size=(10, 28)):
        for _ in range(amount):
            direction = Vec2(1, 0).rotate(random.random() * 360)
            self.particles.append(
                Particle(
                    Vec2(pos) + direction * random.uniform(2, 38),
                    direction * random.uniform(35, speed),
                    random.uniform(0.45, 1.15),
                    1.15,
                    random.uniform(size[0], size[1]),
                    color,
                    "smoke",
                )
            )

    def text(self, value, pos, color=GOLD, big=False):
        self.texts.append(FloatText(value, Vec2(pos), color, 1 if big else 0.78, big))

    def impact(self, pos, color=CHAKRA, power=1):
        self.shake = max(self.shake, 4 + power * 4)
        self.hit_stop = max(self.hit_stop, 0.01 + power * 0.012)
        self.burst(pos, color, 12 + power * 7, 240 + power * 115, "spark", 3 + power)
        self.particles.append(
            Particle(Vec2(pos), Vec2(), 0.3, 0.3, 18 + power * 6, color, "ring")
        )

    def rasengan_blast_fx(self, pos, direction):
        pos = Vec2(pos)
        direction = safe_normal(direction)
        q = Vec2(-direction.y, direction.x)
        self.smoke(pos, 34, (235, 238, 230), 230, (18, 46))
        self.smoke(pos + direction * 22, 24, (118, 132, 145), 260, (16, 40))
        self.smoke(pos - direction * 18, 16, (255, 183, 82), 210, (10, 25))
        for _ in range(58):
            angle = random.random() * math.tau
            out = Vec2(math.cos(angle), math.sin(angle))
            bias = direction * random.uniform(0.25, 1.1) + q * random.uniform(
                -0.75, 0.75
            )
            vel = safe_normal(out + bias) * random.uniform(280, 820)
            color = random.choice(
                (CHAKRA, CHAKRA_WHITE, (255, 221, 106), (255, 133, 48))
            )
            kind = random.choice(("spark", "shard", "flame"))
            self.particles.append(
                Particle(
                    pos + out * random.uniform(6, 38),
                    vel,
                    random.uniform(0.28, 0.95),
                    0.95,
                    random.uniform(3, 9),
                    color,
                    kind,
                    0.91,
                )
            )
        for i in range(4):
            self.particles.append(
                Particle(
                    pos,
                    Vec2(),
                    0.32 + i * 0.08,
                    0.32 + i * 0.08,
                    32 + i * 18,
                    CHAKRA_WHITE if i % 2 else CHAKRA,
                    "ring",
                )
            )

    def add_chakra(self, amount):
        n = self.naruto
        before = n.chakra
        n.chakra = clamp(n.chakra + amount, 0, n.max_chakra)
        return n.chakra - before

    def heal_owner(self, owner, dealt):
        healed = min(dealt * LIFESTEAL, owner.max_hp - owner.hp)
        owner.hp += healed
        if healed > 0:
            self.text(f"+{int(healed)} HP", owner.pos + Vec2(0, -72), CHAKRA_WHITE)

    def damage_dummy(self, amount, label="", color=ORANGE, power=1):
        dealt = self.dummy.take_damage(amount)
        self.text(
            f"-{int(dealt)}" + (f"  {label}" if label else ""),
            self.dummy.pos + Vec2(0, -64),
            color,
            power > 1,
        )
        self.impact(self.dummy.pos, color, power)
        return dealt

    def damage_naruto(self, amount):
        n = self.naruto
        if n.keikaku_active > 0:
            self.shield_pops.append(ShieldPop(Vec2(n.pos)))
            self.text("CHAKRA SHIELD", n.pos + Vec2(0, -92), CHAKRA_WHITE)
            self.burst(n.pos, CHAKRA, 15, 240, "spark", 3)
            return
        n.hp = max(0, n.hp - amount)
        n.hit_flash = 0.13
        n.squash = 0.45
        self.text(f"-{int(amount)}", n.pos + Vec2(0, -62), STEEL)
        self.impact(n.pos, STEEL, 1)

    def damage_clone(self, clone, amount):
        clone.hp = max(0, clone.hp - amount)
        clone.hit_flash = 0.12
        clone.squash = 0.45
        self.text(f"-{int(amount)}", clone.pos + Vec2(0, -56), (238, 218, 190))
        if clone.hp <= 0 and clone.death_anim <= 0:
            clone.death_anim = 0.55
            self.sound.play("clone_death")
            self.smoke(clone.pos, 20)
            self.text("POOF", clone.pos + Vec2(0, -76), CHAKRA_WHITE)

    def active_clones(self):
        return [
            clone for clone in self.clones if clone.hp > 0 and clone.death_anim <= 0
        ]

    def body_controlled(self, body):
        if body is self.naruto:
            return body.stunned > 0 or body.keikaku_active > 0
        return body.stunned > 0

    def kagebunshin(self):
        n = self.naruto
        count = len(self.active_clones())
        if count >= 5:
            n.stunned = 1.5
            n.fail_pending_cd = True
            for clone in self.active_clones():
                clone.stunned = 1.5
                self.damage_clone(clone, 100)
            self.sound.play("fail")
            self.text("CHAKRA FAIL CONTROL", n.pos + Vec2(0, -92), CHAKRA_WHITE, True)
            self.burst(n.pos, CHAKRA_WHITE, 48, 430, "spark", 5)
            n.clone_cd = 999
            return
        create_count = 2 if count == 4 else 3
        create_count = min(create_count, 6 - count)
        if create_count <= 0:
            return
        n.chakra -= 300
        n.clone_cd = 12
        self.sound.play("clone")
        self.text(
            f"KAGEBUNSHIN  x{create_count}", n.pos + Vec2(0, -92), CHAKRA_WHITE, True
        )
        self.smoke(n.pos, 34)
        for i in range(create_count):
            angle = (i / max(1, create_count)) * math.tau + random.uniform(-0.35, 0.35)
            offset = Vec2(math.cos(angle), math.sin(angle)) * random.uniform(74, 112)
            pos = Vec2(
                clamp(
                    n.pos.x + offset.x, ARENA.left + n.radius, ARENA.right - n.radius
                ),
                clamp(
                    n.pos.y + offset.y, ARENA.top + n.radius, ARENA.bottom - n.radius
                ),
            )
            direction = safe_normal(offset, Vec2(1, 0)).rotate(random.uniform(-45, 45))
            self.clones.append(Clone(pos, direction * NARUTO_SPEED))
            self.particles.append(
                Particle(Vec2(pos), Vec2(), 0.35, 0.35, 32, CHAKRA_WHITE, "ring")
            )

    def start_rasengan(self):
        n = self.naruto
        n.chakra -= 500
        n.rasengan_cd = 7.5
        n.rasengan_charge = 0.6
        n.rasengan_ready = False
        self.sound.play("rasengan_charge")
        self.text("RASENGAN", n.pos + Vec2(0, -88), CHAKRA, True)

    def rasengan_hit(self):
        n = self.naruto
        n.rasengan_ready = False
        direction = safe_normal(self.dummy.pos - n.pos)
        self.sound.play("rasengan_impact")
        self.damage_dummy(120, "RASENGAN", CHAKRA, 5)
        self.rasengan_blast_fx(self.dummy.pos, direction)
        self.rasengan_impacts.append(RasenganImpact(Vec2(self.dummy.pos), direction))
        self.dummy_knockback = direction * 1400
        self.dummy_knockback_stun_armed = True
        self.text(
            "MASSIVE KNOCKBACK", self.dummy.pos + Vec2(0, -98), CHAKRA_WHITE, True
        )
        self.shake = max(self.shake, 18)
        self.hit_stop = max(self.hit_stop, 0.07)

    def start_keikaku(self):
        n = self.naruto
        n.keikaku_active = 3
        n.keikaku_tick = 0.001
        n.keikaku_cd = 999
        self.sound.play("keikaku_start")
        self.text("CHAKRA FILL", n.pos + Vec2(0, -92), CHAKRA_WHITE, True)
        self.burst(n.pos, CHAKRA, 32, 260, "orb", 5)

    def keikaku_tick(self):
        gained = self.add_chakra(45)
        self.sound.play("keikaku_tick")
        self.text(
            f"+{int(gained)} CHAKRA",
            self.naruto.pos + Vec2(0, -116),
            CHAKRA_WHITE,
            True,
        )
        self.burst(self.naruto.pos, CHAKRA_WHITE, 18, 245, "spark", 4)
        self.particles.append(
            Particle(Vec2(self.naruto.pos), Vec2(), 0.4, 0.4, 46, CHAKRA, "ring")
        )

    def throw_shuriken(self, owner, target):
        direction = safe_normal(target.pos - owner.pos)
        spawn = owner.pos + direction * (owner.radius + 14)
        self.shuriken.append(Shuriken(Vec2(spawn), direction * 740, owner))
        owner.shuriken_timer = SHURIKEN_INTERVAL
        self.sound.play_throw()
        self.burst(spawn, (200, 214, 230), 4, 110, "spark", 2)

    def punch(self, owner, target):
        direction_to_target = safe_normal(target.pos - owner.pos)
        incoming = direction_to_target.rotate(
            random.choice((-145, -115, -75, 75, 115, 145))
        )
        color = CHAKRA if owner is self.naruto else CLONE_ORANGE
        damage = (
            PUNCH_DAMAGE
            if owner is self.naruto
            else int(PUNCH_DAMAGE * CLONE_DAMAGE_SCALE)
        )
        self.fists.append(FistAnim(Vec2(target.pos), incoming, color))
        owner.punch_timer = PUNCH_INTERVAL
        self.sound.play("punch")
        dealt = self.damage_dummy(damage, "NINJA PUNCH", color, 1)
        self.heal_owner(owner, dealt)
        if owner is self.naruto:
            self.add_chakra(15)

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
            fighter.squash = 0.4
            self.burst(fighter.pos, (130, 160, 210), 6, 130, "spark", 2)
            if isinstance(fighter, Clone):
                fighter.wall_bounces += 1
                if fighter.wall_bounces % 2 == 0:
                    fighter.vel = (
                        safe_normal(self.dummy.pos - fighter.pos) * NARUTO_SPEED
                    )
                    self.text(
                        "CLONE REDIRECT", fighter.pos + Vec2(0, -58), CLONE_ORANGE
                    )
            elif target and hasattr(fighter, "redirects") and fighter.redirects > 0:
                direction = safe_normal(
                    fighter.pos - target.pos if away else target.pos - fighter.pos
                )
                fighter.vel = direction * fighter.vel.length()
                fighter.redirects -= 1
        return bounced

    def resolve_collision(self, a, b, a_speed=None, b_speed=None):
        delta = b.pos - a.pos
        distance = delta.length()
        if distance >= a.radius + b.radius:
            return False
        n = safe_normal(delta)
        overlap = a.radius + b.radius - distance
        a.pos -= n * overlap * 0.5
        b.pos += n * overlap * 0.5
        if a_speed is None:
            a_speed = a.vel.length()
        if b_speed is None:
            b_speed = b.vel.length()
        a.vel = safe_normal(a.vel.reflect(n)) * a_speed
        b.vel = safe_normal(b.vel.reflect(n)) * b_speed
        a.squash = b.squash = 0.35
        return True

    def update_naruto_actions(self, dt):
        n, d = self.naruto, self.dummy
        if n.fail_pending_cd and n.stunned <= 0:
            n.fail_pending_cd = False
            n.clone_cd = 12
        if n.keikaku_active > 0:
            n.keikaku_active -= dt
            n.keikaku_tick -= dt
            for _ in range(2):
                angle = random.random() * math.tau
                outward = Vec2(math.cos(angle), math.sin(angle))
                start = n.pos + outward * random.uniform(n.radius + 30, n.radius + 68)
                inward = safe_normal(n.pos - start).rotate(random.uniform(-8, 8))
                color = random.choice((CHAKRA, CHAKRA_WHITE, (120, 228, 255)))
                self.particles.append(
                    Particle(
                        start,
                        inward * random.uniform(90, 175),
                        random.uniform(0.35, 0.72),
                        0.72,
                        random.uniform(2, 4.5),
                        color,
                        "orb",
                        0.96,
                    )
                )
            if n.keikaku_tick <= 0 and n.keikaku_active > 0:
                n.keikaku_tick += 0.5
                self.keikaku_tick()
            if n.keikaku_active <= 0:
                n.keikaku_cd = 6
                n.vel = safe_normal(n.vel, Vec2(1, 0)) * NARUTO_SPEED
                self.text("BURST STEP", n.pos + Vec2(0, -82), CHAKRA)
            return
        if n.stunned > 0 or self.actions_locked:
            return
        if n.clone_cd <= 0 and n.chakra >= 300:
            self.kagebunshin()
            return
        if (
            n.rasengan_cd <= 0
            and n.chakra >= 500
            and not n.rasengan_ready
            and n.rasengan_charge <= 0
        ):
            self.start_rasengan()
            return
        if n.keikaku_cd <= 0:
            if n.chakra < n.max_chakra:
                self.start_keikaku()
            else:
                n.keikaku_cd = 6
            return
        if n.rasengan_charge > 0:
            n.rasengan_charge -= dt
            if n.rasengan_charge <= 0:
                n.rasengan_ready = True
                self.burst(n.pos + n.facing * 52, CHAKRA_WHITE, 18, 160, "orb", 4)
        distance = n.pos.distance_to(d.pos) - n.radius - d.radius
        if n.punch_timer <= 0 and distance <= PUNCH_RANGE:
            self.punch(n, d)
        if n.shuriken_timer <= 0 and PUNCH_RANGE < distance <= SHURIKEN_RANGE:
            self.throw_shuriken(n, d)

    def update_clone_actions(self):
        for clone in self.active_clones():
            if clone.stunned > 0:
                continue
            distance = (
                clone.pos.distance_to(self.dummy.pos) - clone.radius - self.dummy.radius
            )
            if clone.punch_timer <= 0 and distance <= PUNCH_RANGE:
                self.punch(clone, self.dummy)
            if clone.shuriken_timer <= 0 and PUNCH_RANGE < distance <= SHURIKEN_RANGE:
                self.throw_shuriken(clone, self.dummy)

    def update_shuriken(self, dt):
        for shuriken in self.shuriken:
            shuriken.life -= dt
            shuriken.pos += shuriken.vel * dt
            shuriken.angle += dt * 22
            if not ARENA.collidepoint(shuriken.pos):
                shuriken.hit = True
                self.burst(shuriken.pos, (188, 202, 218), 5, 120, "spark", 2)
                continue
            if shuriken.pos.distance_to(self.dummy.pos) <= self.dummy.radius + 12:
                shuriken.hit = True
                self.sound.play("shuriken_hit")
                damage = (
                    SHURIKEN_DAMAGE
                    if shuriken.owner is self.naruto
                    else int(SHURIKEN_DAMAGE * CLONE_DAMAGE_SCALE)
                )
                dealt = self.damage_dummy(damage, "SHURIKEN", (205, 220, 235), 1)
                self.heal_owner(shuriken.owner, dealt)
                if shuriken.owner is self.naruto:
                    self.add_chakra(10)
        self.shuriken = [s for s in self.shuriken if s.life > 0 and not s.hit]

    def update_dummy_knockback(self, dt):
        self.tournament_forced_target_motion = False
        if self.dummy_knockback.length_squared() <= 0.001:
            return False
        self.tournament_forced_target_motion = True
        self.dummy.pos += self.dummy_knockback * dt
        self.dummy_knockback *= 0.08**dt
        hit_wall = self.wall_bounce(self.dummy, self.naruto, True)
        if hit_wall and self.dummy_knockback_stun_armed:
            self.dummy.stunned = 2
            self.dummy_knockback = Vec2()
            self.dummy_knockback_stun_armed = False
            self.sound.play("rasengan_wall")
            normal = safe_normal(self.dummy.pos - Vec2(ARENA.center))
            self.wall_cracks.append(WallCrack(Vec2(self.dummy.pos), normal))
            self.text(
                "WALL STUN  2.0s", self.dummy.pos + Vec2(0, -96), CHAKRA_WHITE, True
            )
            self.shake = max(self.shake, 15)
            self.burst(self.dummy.pos, CHAKRA_WHITE, 34, 440, "debris", 5)
            self.smoke(self.dummy.pos, 22, (130, 136, 142), 240, (14, 34))
        if self.dummy_knockback.length() < 35:
            self.dummy_knockback = Vec2()
            self.dummy_knockback_stun_armed = False
        return True

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

        n, d = self.naruto, self.dummy
        n.timers(dt)
        d.update_timers(dt)
        for clone in self.clones:
            clone.timers(dt)
        for group in (
            self.particles,
            self.texts,
            self.fists,
            self.rasengan_impacts,
            self.wall_cracks,
            self.shield_pops,
        ):
            for item in group:
                item.life -= dt
        for particle in self.particles:
            particle.update(dt)
        for text in self.texts:
            text.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        self.texts = [t for t in self.texts if t.life > 0]
        self.fists = [f for f in self.fists if f.life > 0]
        self.rasengan_impacts = [r for r in self.rasengan_impacts if r.life > 0]
        self.wall_cracks = [c for c in self.wall_cracks if c.life > 0]
        self.shield_pops = [s for s in self.shield_pops if s.life > 0]
        self.clones = [c for c in self.clones if c.hp > 0 or c.death_anim > 0]

        if n.vel.length_squared() > 0.001:
            n.facing += (safe_normal(n.vel, n.facing) - n.facing) * min(1, dt * 9)
            n.facing = safe_normal(n.facing)
        d.facing += (safe_normal(d.vel, d.facing) - d.facing) * min(1, dt * 9)
        d.facing = safe_normal(d.facing)
        for clone in self.active_clones():
            clone.facing += (safe_normal(clone.vel, clone.facing) - clone.facing) * min(
                1, dt * 9
            )
            clone.facing = safe_normal(clone.facing)

        if n.keikaku_active <= 0 and n.stunned <= 0:
            n.pos += safe_normal(n.vel) * NARUTO_SPEED * dt
            n.vel = safe_normal(n.vel) * NARUTO_SPEED
            self.wall_bounce(n)
        for clone in self.active_clones():
            if clone.stunned <= 0:
                clone.pos += safe_normal(clone.vel) * NARUTO_SPEED * dt
                clone.vel = safe_normal(clone.vel) * NARUTO_SPEED
                self.wall_bounce(clone)

        dummy_moved_by_knockback = self.update_dummy_knockback(dt)
        if not dummy_moved_by_knockback and d.stunned <= 0:
            d.pos += d.vel * d.speed_scale * dt
            self.wall_bounce(d, n, True)

        naruto_body_speed = (
            NARUTO_SPEED if n.keikaku_active <= 0 and n.stunned <= 0 else 0
        )
        if self.resolve_collision(n, d, naruto_body_speed, d.vel.length()):
            if n.rasengan_ready and n.keikaku_active <= 0:
                self.rasengan_hit()
            if d.punch_timer <= 0 and d.stunned <= 0:
                d.punch_timer = 1
                d.punch_anim = 0.42
                d.punch_target = Vec2(n.pos)
                base = math.degrees(math.atan2(n.pos.y - d.pos.y, n.pos.x - d.pos.x))
                d.punch_dir = Vec2(1, 0).rotate(
                    base + random.choice((-125, -75, 75, 125))
                )
                self.sound.play("dummy_punch")
                self.damage_naruto(255)

        for clone in self.active_clones():
            if self.resolve_collision(clone, d, NARUTO_SPEED, d.vel.length()):
                if d.punch_timer <= 0 and d.stunned <= 0:
                    d.punch_timer = 1
                    d.punch_anim = 0.42
                    d.punch_target = Vec2(clone.pos)
                    base = math.degrees(
                        math.atan2(clone.pos.y - d.pos.y, clone.pos.x - d.pos.x)
                    )
                    d.punch_dir = Vec2(1, 0).rotate(
                        base + random.choice((-125, -75, 75, 125))
                    )
                    self.sound.play("dummy_punch")
                    self.damage_clone(clone, 255)

        for clone in self.active_clones():
            if n.pos.distance_to(clone.pos) < n.radius + clone.radius:
                naruto_speed = (
                    NARUTO_SPEED if n.keikaku_active <= 0 and n.stunned <= 0 else 0
                )
                clone_speed = NARUTO_SPEED if clone.stunned <= 0 else 0
                self.resolve_collision(n, clone, naruto_speed, clone_speed)

        for i, a in enumerate(self.active_clones()):
            for b in self.active_clones()[i + 1 :]:
                if a.pos.distance_to(b.pos) < a.radius + b.radius:
                    self.resolve_collision(a, b, NARUTO_SPEED, NARUTO_SPEED)

        self.update_naruto_actions(dt)
        self.update_clone_actions()
        self.update_shuriken(dt)

        if n.hp <= 0:
            self.round_over = 3
            self.winner = "DUMMYBOT WINS"
        elif d.hp <= 0:
            self.round_over = 3
            self.winner = "NARUTO WINS"

    def draw_naruto_decor(self, ball, center, radius, facing, roll):
        q = Vec2(-facing.y, facing.x)
        forehead = center + facing * radius * 0.12 - q * radius * 0.03
        band = pygame.Rect(
            center.x - radius * 0.58,
            center.y - radius * 0.61,
            radius * 1.16,
            radius * 0.42,
        )
        pygame.draw.arc(ball, (36, 42, 58), band, roll + 0.2, roll + math.pi * 1.08, 7)
        pygame.draw.arc(
            ball,
            CHAKRA_WHITE,
            band.inflate(-4, -4),
            roll + 0.28,
            roll + math.pi * 0.96,
            2,
        )
        pygame.draw.circle(ball, (60, 68, 82), forehead, int(radius * 0.13))
        pygame.draw.circle(ball, (186, 198, 210), forehead, int(radius * 0.1), 2)
        for side in (-1, 1):
            cheek = center + facing * radius * 0.48 + q * side * radius * 0.31
            for k in (-1, 0, 1):
                start = cheek - facing * radius * 0.03 + Vec2(0, k * radius * 0.08)
                end = cheek + q * side * radius * 0.22 + Vec2(0, k * radius * 0.055)
                pygame.draw.line(
                    ball, (72, 35, 20), start, end, max(1, int(radius * 0.035))
                )

    def draw_clone_bar(self, dst, clone, offset):
        pos = clone.pos + offset - Vec2(34, clone.radius + 20)
        rect = pygame.Rect(pos.x, pos.y, 68, 6)
        pygame.draw.rect(dst, (22, 17, 16), rect, border_radius=3)
        fill = rect.copy()
        fill.width = int(fill.width * clamp(clone.hp / clone.max_hp, 0, 1))
        pygame.draw.rect(dst, CLONE_ORANGE, fill, border_radius=3)

    def draw_chakra_aura(self, dst, offset):
        n = self.naruto
        intensity = clamp(n.chakra / n.max_chakra, 0, 1)
        if intensity < 0.15 and n.keikaku_active <= 0 and not n.rasengan_ready:
            return
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        center = n.pos + offset
        if n.keikaku_active > 0:
            pulse = (math.sin(self.time * 7) + 1) * 0.5
            aura_radius = n.radius + 18 + pulse * 5
            glow_circle(layer, center, 26 + pulse * 5, CHAKRA, 0.22)
            pygame.draw.circle(layer, (*CHAKRA, 88), center, int(aura_radius), 2)
            pygame.draw.circle(
                layer, (*CHAKRA_WHITE, 56), center, int(aura_radius * 0.72), 1
            )
            for i in range(8):
                angle = self.time * 1.6 + i * math.tau / 8
                p = center + Vec2(math.cos(angle), math.sin(angle)) * (
                    n.radius + 16 + math.sin(self.time * 5 + i) * 4
                )
                pygame.draw.circle(layer, (*CHAKRA_WHITE, 80), p, 2)
            dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)
            return
        streaks = 8 + int(intensity * 10)
        for i in range(streaks):
            angle = self.time * (1.8 + i % 3 * 0.25) + i * math.tau / streaks
            radius = n.radius + 12 + (i % 4) * 9 + math.sin(self.time * 8 + i) * 5
            direction = Vec2(math.cos(angle), math.sin(angle))
            tangent = Vec2(-direction.y, direction.x)
            start = center + direction * radius - tangent * (10 + intensity * 10)
            end = (
                center
                + direction * (radius + 22 + intensity * 24)
                + tangent * (14 + intensity * 18)
            )
            pygame.draw.line(
                layer,
                (*CHAKRA, int(38 + intensity * 86)),
                start,
                end,
                2 + int(intensity * 2),
            )
            pygame.draw.circle(
                layer, (*CHAKRA_WHITE, int(70 * intensity)), end, 2 + i % 2
            )
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_rasengan_charge(self, dst, offset):
        n = self.naruto
        if n.rasengan_charge <= 0 and not n.rasengan_ready:
            return
        progress = 1 if n.rasengan_ready else 1 - clamp(n.rasengan_charge / 0.6, 0, 1)
        center = n.pos + offset + safe_normal(n.facing) * (n.radius + 20)
        radius = 14 + progress * 16 + math.sin(self.time * 24) * 2
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(4):
            rect = pygame.Rect(
                center.x - radius - i * 7,
                center.y - radius - i * 7,
                (radius + i * 7) * 2,
                (radius + i * 7) * 2,
            )
            pygame.draw.arc(
                layer,
                (*CHAKRA, 185 - i * 30),
                rect,
                self.time * (8 + i) + i,
                self.time * (8 + i) + i + math.pi * 1.3,
                3,
            )
        pygame.draw.circle(layer, (232, 252, 255, 210), center, int(radius * 0.58))
        pygame.draw.circle(layer, (*CHAKRA, 235), center, int(radius), 4)
        for i in range(14):
            angle = self.time * (9 + i % 3) + i / 14 * math.tau
            a = center + Vec2(math.cos(angle), math.sin(angle)) * radius * 0.38
            b = center + Vec2(math.cos(angle + 0.35), math.sin(angle + 0.35)) * (
                radius + 18 + i % 4 * 4
            )
            pygame.draw.line(layer, (*CHAKRA_WHITE, 92), b, a, 2)
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_fists(self, dst, offset):
        for fist in self.fists:
            progress = 1 - fist.life / fist.max_life
            fade = clamp(min(progress / 0.1, (1 - progress) / 0.22), 0, 1)
            direction = safe_normal(fist.direction)
            q = Vec2(-direction.y, direction.x)
            target = fist.target + offset
            palm = target + direction * lerp(
                -128, 118, progress * progress * (3 - 2 * progress)
            )
            wrist = palm - direction * 40
            base = wrist - direction * 47
            alpha = int(235 * fade)
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(5, 0, -1):
                echo = palm - direction * i * 16
                pygame.draw.ellipse(
                    layer,
                    (*fist.color, int(alpha * 0.045 * (6 - i))),
                    pygame.Rect(echo.x - 28, echo.y - 22, 56, 44),
                )
            forearm = [
                base - q * 15,
                wrist - q * 20,
                palm - direction * 19 - q * 24,
                palm - direction * 19 + q * 24,
                wrist + q * 20,
                base + q * 15,
            ]
            pygame.draw.polygon(layer, (35, 45, 64, int(alpha * 0.75)), forearm)
            pygame.draw.line(
                layer,
                (*fist.color, int(alpha * 0.72)),
                base - q * 7,
                palm - direction * 20 - q * 14,
                4,
            )
            glove = [
                palm - direction * 25 - q * 25,
                palm + direction * 12 - q * 31,
                palm + direction * 31 - q * 18,
                palm + direction * 31 + q * 19,
                palm + direction * 10 + q * 31,
                palm - direction * 27 + q * 23,
            ]
            pygame.draw.polygon(layer, (*ORANGE, alpha), glove)
            pygame.draw.lines(layer, (255, 234, 184, int(alpha * 0.85)), True, glove, 3)
            for side in (-21, -7, 7, 21):
                knuckle = palm + direction * 30 + q * side
                pygame.draw.circle(layer, (255, 235, 170, alpha), knuckle, 10)
                pygame.draw.circle(
                    layer, (*DEEP_ORANGE, int(alpha * 0.9)), knuckle + direction * 2, 6
                )
            for i in range(7):
                spark = (
                    wrist - direction * (i * 13) + q * math.sin(self.time * 12 + i) * 14
                )
                pygame.draw.circle(
                    layer, (*CHAKRA, int(alpha * 0.32)), spark, 2 + i % 2
                )
            dst.blit(layer, (0, 0))

    def draw_shuriken(self, dst, offset):
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for s in self.shuriken:
            center = s.pos + offset
            for i in range(1, 5):
                trail = center - safe_normal(s.vel) * i * 12
                pygame.draw.circle(
                    layer, (185, 205, 225, max(10, 58 - i * 10)), trail, max(2, 7 - i)
                )
            for blade in range(4):
                angle = s.angle + blade * math.pi / 2
                direction = Vec2(math.cos(angle), math.sin(angle))
                q = Vec2(-direction.y, direction.x)
                points = [
                    center + direction * 18,
                    center - direction * 4 + q * 7,
                    center - direction * 4 - q * 7,
                ]
                pygame.draw.polygon(layer, (33, 39, 50, 240), points)
                pygame.draw.line(
                    layer, (235, 242, 248, 190), center, center + direction * 15, 2
                )
            pygame.draw.circle(layer, (210, 222, 235, 230), center, 5, 2)
        dst.blit(layer, (0, 0))

    def draw_rasengan_impacts(self, dst, offset):
        for impact in self.rasengan_impacts:
            progress = 1 - impact.life / impact.max_life
            fade = clamp(impact.life / impact.max_life, 0, 1)
            center = impact.pos + offset
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(7):
                radius = 24 + progress * (56 + i * 13)
                pygame.draw.circle(
                    layer, (*CHAKRA, int((120 - i * 12) * fade)), center, int(radius), 4
                )
                start = self.time * (8 + i) + i
                pygame.draw.arc(
                    layer,
                    (*CHAKRA_WHITE, int((210 - i * 22) * fade)),
                    pygame.Rect(
                        center.x - radius, center.y - radius, radius * 2, radius * 2
                    ),
                    start,
                    start + math.pi * (1.0 + i * 0.2),
                    3,
                )
            for i in range(18):
                angle = self.time * 7 + i / 18 * math.tau
                direction = Vec2(math.cos(angle), math.sin(angle))
                start = center + direction * (18 + progress * 35)
                end = center + direction.rotate(15) * (82 + progress * 70)
                pygame.draw.line(layer, (*CHAKRA_WHITE, int(130 * fade)), start, end, 3)
            dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_wall_cracks(self, dst, offset):
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for crack in self.wall_cracks:
            t = clamp(crack.life / crack.max_life, 0, 1)
            p = crack.pos + offset
            normal = safe_normal(crack.normal)
            q = Vec2(-normal.y, normal.x)
            for i in range(9):
                direction = safe_normal(
                    normal * random.Random(i).uniform(0.2, 1.0)
                    + q * random.Random(i + 99).uniform(-1, 1)
                )
                length = (28 + i * 9) * t
                pygame.draw.line(
                    layer, (235, 245, 255, int(210 * t)), p, p + direction * length, 3
                )
                pygame.draw.line(
                    layer,
                    (*CHAKRA, int(135 * t)),
                    p + direction * 8,
                    p + direction * length,
                    1,
                )
            pygame.draw.circle(
                layer, (*CHAKRA_WHITE, int(85 * t)), p, int(50 * (1.2 - t)), 3
            )
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_shields(self, dst, offset):
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for shield in self.shield_pops:
            t = clamp(shield.life / shield.max_life, 0, 1)
            p = shield.pos + offset
            radius = 34 + (1 - t) * 48
            pygame.draw.circle(layer, (*CHAKRA, int(140 * t)), p, int(radius), 4)
            pygame.draw.circle(
                layer, (*CHAKRA_WHITE, int(125 * t)), p, int(radius * 0.68), 2
            )
        dst.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def draw_status_icons(self, dst, offset):
        entries = []
        if self.naruto.stunned > 0:
            entries.append(
                (self.naruto.pos, self.naruto.radius, self.naruto.stunned, CHAKRA_WHITE)
            )
        if self.dummy.stunned > 0:
            entries.append(
                (self.dummy.pos, self.dummy.radius, self.dummy.stunned, GOLD)
            )
        for clone in self.active_clones():
            if clone.stunned > 0:
                entries.append((clone.pos, clone.radius, clone.stunned, CLONE_ORANGE))
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for pos, radius, duration, color in entries:
            center = pos + offset - Vec2(0, radius + 34)
            for i in range(5):
                angle = self.time * 5 + i / 5 * math.tau
                p = center + Vec2(math.cos(angle) * 32, math.sin(angle) * 13)
                pygame.draw.circle(layer, (*color, 220), p, 5)
                pygame.draw.line(
                    layer, (255, 255, 235, 210), p - Vec2(6, 0), p + Vec2(6, 0), 2
                )
        dst.blit(layer, (0, 0))

    def draw_hud(self, dst, fonts):
        def bar(rect, value, maximum, color, flip=False):
            pygame.draw.rect(dst, (12, 14, 25), rect, border_radius=8)
            pygame.draw.rect(dst, (60, 68, 88), rect, 2, border_radius=8)
            fill = rect.inflate(-6, -6)
            fill.width = int(fill.width * clamp(value / maximum, 0, 1))
            if flip:
                fill.right = rect.right - 3
            pygame.draw.rect(dst, color, fill, border_radius=5)

        n, d = self.naruto, self.dummy
        bar(pygame.Rect(75, 42, 430, 23), n.hp, n.max_hp, ORANGE)
        bar(pygame.Rect(W - 505, 42, 430, 23), d.hp, d.max_hp, STEEL, True)
        dst.blit(fonts["name"].render("NARUTO", True, GOLD), (75, 13))
        name = fonts["name"].render("DUMMYBOT", True, (225, 228, 235))
        dst.blit(name, (W - 75 - name.get_width(), 13))
        dst.blit(
            fonts["small"].render(f"{int(n.hp)} / 5000", True, (255, 232, 190)),
            (80, 70),
        )
        hp = fonts["small"].render(f"{int(d.hp)} / {int(d.max_hp)}", True, STEEL)
        dst.blit(hp, (W - 80 - hp.get_width(), 70))
        chakra = pygame.Rect(75, 86, 430, 12)
        pygame.draw.rect(dst, (9, 24, 38), chakra, border_radius=6)
        pygame.draw.rect(
            dst,
            CHAKRA,
            (
                chakra.x,
                chakra.y,
                int(chakra.width * n.chakra / n.max_chakra),
                chakra.height,
            ),
            border_radius=6,
        )
        pygame.draw.rect(dst, CHAKRA_WHITE, chakra, 1, border_radius=6)
        dst.blit(
            fonts["tiny"].render(
                f"CHAKRA {int(n.chakra)} / 1000    CLONES {len(self.active_clones())}/6",
                True,
                CHAKRA_WHITE,
            ),
            (80, 102),
        )
        title = fonts["tiny"].render(
            "NINJA PUNCH  //  SHURIKEN  //  KAGEBUNSHIN  //  RASENGAN  //  KEIKAKU",
            True,
            (198, 221, 235),
        )
        dst.blit(title, (W / 2 - title.get_width() / 2, 18))
        status = []
        if n.keikaku_active > 0:
            status.append(f"CHAKRA FILL {n.keikaku_active:.1f}s")
        if n.rasengan_ready:
            status.append("RASENGAN READY")
        elif n.rasengan_charge > 0:
            status.append("RASENGAN CHARGING")
        if n.stunned > 0:
            status.append(f"NARUTO STUNNED {n.stunned:.1f}s")
        if d.stunned > 0:
            status.append(f"DUMMY STUNNED {d.stunned:.1f}s")
        st = fonts["tiny"].render("   ".join(status), True, GOLD)
        dst.blit(st, (W / 2 - st.get_width() / 2, 76))
        skills = [
            ("KAGEBUNSHIN", n.clone_cd, 12, ORANGE),
            ("RASENGAN", n.rasengan_cd, 7.5, CHAKRA),
            ("KEIKAKU", n.keikaku_cd if n.keikaku_active <= 0 else 0, 6, CHAKRA_WHITE),
        ]
        for i, (label, cd, total, color) in enumerate(skills):
            x, y = 82 + i * 208, H - 52
            dst.blit(fonts["tiny"].render(label, True, color), (x, y - 18))
            pygame.draw.rect(dst, (22, 24, 34), (x, y, 170, 7), border_radius=4)
            ready = 1 - clamp(cd / total, 0, 1)
            pygame.draw.rect(dst, color, (x, y, int(170 * ready), 7), border_radius=4)
        info = fonts["tiny"].render(
            "R  RESTART     M  MUTE     ESC  EXIT", True, (110, 122, 150)
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
        shared.draw_arena(dst, ARENA, W, H, self.time, offset)
        shared.draw_movement_trail(dst, self.naruto, ORANGE, offset, 5)
        for clone in self.active_clones():
            shared.draw_movement_trail(dst, clone, CLONE_ORANGE, offset, 3)
        shared.draw_movement_trail(dst, self.dummy, (155, 165, 185), offset, 4)
        self.draw_wall_cracks(dst, offset)
        for particle in self.particles:
            particle.draw(dst, offset)
        self.draw_chakra_aura(dst, offset)
        self.draw_rasengan_impacts(dst, offset)
        self.draw_shuriken(dst, offset)
        for clone in self.clones:
            if clone.hp <= 0 and clone.death_anim <= 0:
                continue
            scale = 1
            if clone.spawn_anim > 0:
                scale = lerp(0.45, 1, 1 - clone.spawn_anim / 0.34)
            if clone.death_anim > 0:
                scale = clamp(clone.death_anim / 0.55, 0, 1)
            radius = clone.radius * scale
            shared.draw_ball(
                dst,
                clone.pos + offset,
                radius,
                (194, 108, 63),
                CLONE_ORANGE,
                clone.facing,
                clone.roll,
                clone.squash,
                clone.hit_flash,
                0,
                0,
                (255, 230, 175),
                self.draw_naruto_decor,
            )
            if clone.hp > 0:
                self.draw_clone_bar(dst, clone, offset)
        shared.draw_ball(
            dst,
            self.naruto.pos + offset,
            self.naruto.radius,
            DEEP_ORANGE,
            GOLD,
            self.naruto.facing,
            self.naruto.roll,
            self.naruto.squash,
            self.naruto.hit_flash,
            0,
            0,
            CHAKRA_WHITE,
            self.draw_naruto_decor,
        )
        self.draw_rasengan_charge(dst, offset)
        shared.draw_ball(
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
        self.draw_fists(dst, offset)
        shared.draw_dummy_punch(dst, self.dummy, self.time, offset, W, H)
        self.draw_shields(dst, offset)
        self.draw_status_icons(dst, offset)
        for text in self.texts:
            font = fonts["impact"] if text.big else fonts["small"]
            image = font.render(text.text, True, text.color)
            shadow = font.render(text.text, True, (5, 6, 12))
            p = text.pos + offset
            dst.blit(shadow, (p.x - image.get_width() / 2 + 2, p.y + 2))
            dst.blit(image, (p.x - image.get_width() / 2, p.y))
        self.draw_hud(dst, fonts)
        if self.banner_time > 0:
            image = fonts["banner"].render(
                "NARUTO // AUTONOMOUS COMBAT PROTOTYPE", True, CHAKRA_WHITE
            )
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - 100))
        if self.round_over:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((5, 8, 14, 150))
            dst.blit(veil, (0, 0))
            image = fonts["winner"].render(self.winner, True, GOLD)
            dst.blit(
                image, (W / 2 - image.get_width() / 2, H / 2 - image.get_height() / 2)
            )


def make_fonts():
    return shared.make_fonts()


def main():
    parser = argparse.ArgumentParser(description="Naruto autonomous combat prototype")
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
    pygame.display.set_caption("Naruto // Autonomous Combat Prototype")
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
