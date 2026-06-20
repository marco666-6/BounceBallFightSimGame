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
INK = (8, 5, 10)
RED = (242, 43, 31)
HOT_RED = (255, 82, 45)
DARK_RED = (105, 12, 18)
VIRA = (15, 8, 14)
GREY = (185, 190, 205)
GOLD = (255, 205, 92)


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def safe_normal(vector, fallback=Vec2(1, 0)):
    return vector.normalize() if vector.length_squared() > .001 else Vec2(fallback)


def point_segment_distance(point, start, end):
    segment = end - start
    if segment.length_squared() <= .001:
        return point.distance_to(start)
    t = clamp((point - start).dot(segment) / segment.length_squared(), 0, 1)
    return point.distance_to(start + segment * t)


def mix(a, b, t):
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def glow_circle(dst, pos, radius, color, strength=1):
    radius = max(2, int(radius))
    surf = pygame.Surface((radius * 5, radius * 5), pygame.SRCALPHA)
    c = Vec2(surf.get_width() / 2, surf.get_height() / 2)
    for i in range(5, 0, -1):
        pygame.draw.circle(surf, (*color, int(8 * strength * (6 - i))), c, int(radius * (.5 + i * .42)))
    pygame.draw.circle(surf, (*color, int(80 * strength)), c, max(1, radius // 2))
    dst.blit(surf, c * -1 + pos, special_flags=pygame.BLEND_ADD)


def wall_point(side, along):
    if side == 0:
        return Vec2(ARENA.left, lerp(ARENA.top + 30, ARENA.bottom - 30, along))
    if side == 1:
        return Vec2(ARENA.right, lerp(ARENA.top + 30, ARENA.bottom - 30, along))
    if side == 2:
        return Vec2(lerp(ARENA.left + 30, ARENA.right - 30, along), ARENA.top)
    return Vec2(lerp(ARENA.left + 30, ARENA.right - 30, along), ARENA.bottom)


@dataclass
class Particle:
    pos: Vec2
    vel: Vec2
    life: float
    max_life: float
    size: float
    color: tuple
    kind: str = "orb"

    def update(self, dt):
        self.life -= dt
        self.pos += self.vel * dt
        self.vel *= .94 ** (dt * 60)

    def draw(self, dst, offset):
        t = clamp(self.life / self.max_life, 0, 1)
        p = self.pos + offset
        if self.kind == "spark":
            pygame.draw.line(dst, (*self.color, int(230 * t)), p, p - safe_normal(self.vel) * self.size * 4,
                             max(1, int(self.size * t)))
        elif self.kind == "smoke":
            pygame.draw.circle(dst, (*self.color, int(75 * t)), p, int(self.size * (1.7 - t)))
        else:
            glow_circle(dst, p, self.size * t, self.color, t)


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
class Pool:
    pos: Vec2
    points: list
    phase: float
    hardened: float = 0
    tick: float = 0
    melt: float = 0
    spent: bool = False


@dataclass
class FireBall:
    pos: Vec2
    vel: Vec2
    life: float = 3
    radius: float = 24
    age: float = 0


@dataclass
class Spider:
    pos: Vec2
    end: Vec2
    vel: Vec2
    hit: bool = False
    phase: float = 0
    age: float = 0


@dataclass
class Portal:
    pos: Vec2
    normal: Vec2
    life: float
    max_life: float
    outgoing: bool = False


@dataclass
class DarkLord:
    pos: Vec2
    vel: Vec2 = field(default_factory=lambda: Vec2(315, 154))
    radius: float = 48
    hp: float = 5000
    max_hp: float = 5000
    facing: Vec2 = field(default_factory=lambda: Vec2(1, 0))
    attack_timer: float = .2
    hit_count: int = 0
    stacks: int = 0
    portal_timer: float = 3
    fire_timer: float = 4.5
    spider_timer: float = 7
    mode: str = "normal"
    mode_timer: float = 0
    hidden: bool = False
    immobilized: float = 0
    stab_anim: float = 0
    slash_anim: float = 0
    slash_side: int = 1
    hit_flash: float = 0
    squash: float = 0
    roll: float = 0

    def timers(self, dt):
        self.attack_timer -= dt
        self.portal_timer -= dt
        self.fire_timer -= dt
        self.spider_timer -= dt
        self.mode_timer -= dt
        self.immobilized = max(0, self.immobilized - dt)
        self.stab_anim = max(0, self.stab_anim - dt)
        self.slash_anim = max(0, self.slash_anim - dt)
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 5)
        self.roll += self.vel.length() * dt / self.radius


class SoundBank:
    def __init__(self, muted=False):
        self.muted, self.sounds = muted, {}
        if muted:
            return
        try:
            pygame.mixer.init()
            folder = ROOT / "DarkLord-SoundEffects"
            names = {
                "fire": "DarkLord-DarkEnergyFireBall.mp3",
                "let_go": "DarkLord-DoubleStab-LetGo.mp3",
                "stab": "DarkLord-DoubleStab-Stab.mp3",
                "portal_in": "DarkLord-Portal-In.mp3",
                "portal_out": "DarkLord-Portal-Out.mp3",
                "slash": "DarkLord-ViraBladeSlash.mp3",
                "eruption": "DarkLord-ViraEruption.mp3",
                "liquid1": "DarkLord-ViraLiquid-1.mp3",
                "liquid2": "DarkLord-ViraLiquid-2.mp3",
                "spider": "DarkLord-ViraSpider.mp3",
                "crash": "DarkLord-WallCrash.mp3",
                "dummy_punch": str(ROOT / "DummyBot-SoundEffects" / "MoroZhar-Punch.mp3"),
            }
            for key, name in names.items():
                sound = pygame.mixer.Sound(name if key == "dummy_punch" else folder / name)
                sound.set_volume(.32 if key in ("slash", "liquid1", "liquid2") else .42)
                self.sounds[key] = sound
        except (pygame.error, FileNotFoundError):
            self.muted = True

    def play(self, key):
        if not self.muted and key in self.sounds:
            self.sounds[key].play()


class Battle:
    def __init__(self, muted=False):
        self.dark = DarkLord(Vec2(290, 385))
        self.dummy = DummyBot(Vec2(985, 385))
        self.dummy.stunned = 0
        self.pools, self.fireballs, self.spiders, self.portals = [], [], [], []
        self.particles, self.texts = [], []
        self.sound = SoundBank(muted)
        self.time = self.shake = self.hit_stop = 0
        self.round_over = 0
        self.winner = ""
        self.banner_time = 2.8
        self.dash_target = Vec2()
        self.lock_offset = Vec2()
        self.spawn_queue = []
        self.fire_cast = 0
        self.actions_locked = False

    def burst(self, pos, color=RED, amount=16, speed=280, kind="spark", size=4):
        for _ in range(amount):
            direction = Vec2(1, 0).rotate(random.random() * 360)
            self.particles.append(Particle(Vec2(pos), direction * random.uniform(speed * .25, speed),
                                           random.uniform(.25, .75), .75, random.uniform(size * .5, size * 1.5),
                                           color, kind))

    def text(self, value, pos, color=GOLD, big=False):
        self.texts.append(FloatText(value, Vec2(pos), color, 1 if big else .8, big))

    def impact(self, pos, power=1, color=RED):
        self.shake = max(self.shake, 4 + power * 4)
        self.hit_stop = max(self.hit_stop, .012 + power * .012)
        self.burst(pos, color, 10 + power * 6, 220 + power * 90, "spark", 3 + power)

    def damage_dummy(self, amount, label="", power=1):
        if label == "ERUPTION" and getattr(self, "target_is_summon", False):
            amount = 45
            label = "ERUPTION / SUMMON"
        dealt = self.dummy.take_damage(amount)
        self.text(f"-{int(dealt)}" + (f"  {label}" if label else ""), self.dummy.pos + Vec2(0, -64),
                  HOT_RED, power > 1)
        self.impact(self.dummy.pos, power)
        return dealt

    def damage_dark(self, amount):
        self.dark.hp = max(0, self.dark.hp - amount)
        self.dark.hit_flash = .12
        self.text(f"-{int(amount)}", self.dark.pos + Vec2(0, -62), GREY)
        self.impact(self.dark.pos, 1, GREY)

    def add_pool(self):
        points = []
        count = random.randint(10, 14)
        for i in range(count):
            angle = i / count * math.tau
            points.append(Vec2(math.cos(angle), math.sin(angle)) * random.uniform(29, 52))
        self.pools.append(Pool(Vec2(self.dummy.pos), points, random.random() * math.tau))
        self.dark.stacks += 1
        self.sound.play(random.choice(("liquid1", "liquid2")))
        self.text(f"VIRA STACK  {self.dark.stacks}/10", self.dummy.pos + Vec2(0, -88), RED, True)
        self.burst(self.dummy.pos, DARK_RED, 18, 190, "orb", 6)
        if self.dark.stacks >= 10:
            self.erupt()

    def erupt(self):
        self.sound.play("eruption")
        self.text("VIRA ERUPTION", self.dark.pos + Vec2(0, -88), HOT_RED, True)
        self.dark.stacks = self.dark.hit_count = 0
        self.shake = 17
        for pool in self.pools:
            if pool.hardened <= 0 and not pool.spent:
                pool.hardened, pool.tick = 7.25, .5
                self.burst(pool.pos, RED, 25, 420, "spark", 5)
                if pool.pos.distance_to(self.dummy.pos) < 80:
                    self.damage_dummy(145, "ERUPTION", 3)

    def slash(self):
        self.dark.attack_timer = .35
        self.dark.slash_anim = .28
        self.dark.slash_side *= -1
        self.sound.play("slash")
        self.damage_dummy(32, "VIRA-BLADE", 1)
        self.dark.hit_count += 1
        if self.dark.hit_count >= 2:
            self.dark.hit_count = 0
            self.add_pool()

    def start_portal(self, normal):
        d = self.dark
        d.mode, d.mode_timer, d.hidden = "portal", .45, False
        d.portal_timer = 9
        entry = Vec2(d.pos)
        self.portals.append(Portal(entry, normal, .8, .8))
        if abs(normal.x):
            exit_pos, exit_normal = Vec2(ARENA.right if normal.x < 0 else ARENA.left, entry.y), normal
        else:
            exit_pos, exit_normal = Vec2(entry.x, ARENA.bottom if normal.y < 0 else ARENA.top), normal
        self.dash_target = Vec2(exit_pos)
        self.lock_offset = Vec2(exit_normal)
        self.sound.play("portal_in")
        self.text("VIRA-PORTAL", entry + Vec2(0, -55), RED, True)

    def emerge(self):
        d = self.dark
        d.pos = self.dash_target + self.lock_offset * (d.radius + 8)
        self.portals.append(Portal(Vec2(self.dash_target), Vec2(self.lock_offset), .9, .9, True))
        d.hidden, d.mode, d.mode_timer = False, "dash", 3
        d.vel = safe_normal(self.dummy.pos - d.pos) * 875
        self.sound.play("portal_out")
        self.burst(d.pos, RED, 30, 350, "spark", 5)

    def stab(self):
        d = self.dark
        d.mode, d.mode_timer, d.stab_anim = "stab", 1, 1
        d.vel = Vec2()
        self.dummy.stunned = 2
        self.lock_offset = self.dummy.pos - d.pos
        self.sound.play("stab")
        self.damage_dummy(217, "DOUBLE STAB", 4)
        healed = min(100, d.max_hp - d.hp)
        d.hp += healed
        if healed > 0:
            self.text(f"+{int(healed)} HP", d.pos + Vec2(0, -72), HOT_RED, True)
        d.stacks = min(10, d.stacks + 2)
        self.text(f"VIRA STACK  {d.stacks}/10", d.pos + Vec2(0, -104), RED, True)
        if d.stacks >= 10:
            self.erupt()
        self.text("STUNNED  2.0s", self.dummy.pos + Vec2(0, -92), HOT_RED, True)

    def cast_fire(self):
        d = self.dark
        count = d.stacks
        d.fire_timer = 8
        self.fire_cast = .42
        self.sound.play("fire")
        self.text(f"DARK ENERGY  x{count}", d.pos + Vec2(0, -88), HOT_RED, True)
        base = math.degrees(math.atan2(self.dummy.pos.y - d.pos.y, self.dummy.pos.x - d.pos.x))
        spread = 9
        for i in range(count):
            angle = base + (i - (count - 1) / 2) * spread
            direction = Vec2(1, 0).rotate(angle)
            self.spawn_queue.append([i * .07, direction])

    def spawn_spiders(self):
        self.dark.spider_timer = 20
        self.sound.play("spider")
        self.text("VIRA-SPIDER MIGRATION", self.dark.pos + Vec2(0, -88), RED, True)
        for i in range(6):
            side = i % 4
            other = (side + random.choice((1, 2, 3))) % 4
            start, end = wall_point(side, random.uniform(.08, .92)), wall_point(other, random.uniform(.08, .92))
            direction = safe_normal(end - start)
            self.spiders.append(Spider(start + direction * 12, end, direction * 300, False, random.random() * math.tau))
            self.portals.append(Portal(start, -direction, 1, 1))

    def wall_bounce(self, fighter, target, away=False):
        bounced, normal = False, Vec2()
        if fighter.pos.x - fighter.radius < ARENA.left:
            fighter.pos.x, fighter.vel.x, normal, bounced = ARENA.left + fighter.radius, abs(fighter.vel.x), Vec2(-1, 0), True
        elif fighter.pos.x + fighter.radius > ARENA.right:
            fighter.pos.x, fighter.vel.x, normal, bounced = ARENA.right - fighter.radius, -abs(fighter.vel.x), Vec2(1, 0), True
        if fighter.pos.y - fighter.radius < ARENA.top:
            fighter.pos.y, fighter.vel.y, normal, bounced = ARENA.top + fighter.radius, abs(fighter.vel.y), Vec2(0, -1), True
        elif fighter.pos.y + fighter.radius > ARENA.bottom:
            fighter.pos.y, fighter.vel.y, normal, bounced = ARENA.bottom - fighter.radius, -abs(fighter.vel.y), Vec2(0, 1), True
        if bounced:
            fighter.squash = .4
            if (fighter is self.dark and fighter.mode == "normal" and fighter.portal_timer <= 0
                    and not self.actions_locked):
                self.start_portal(normal)
                return
            if fighter is self.dummy and fighter.redirects > 0:
                fighter.vel = safe_normal(fighter.pos - target.pos if away else target.pos - fighter.pos) * fighter.vel.length()
                fighter.redirects -= 1

    def update(self, dt):
        self.time += dt
        self.fire_cast = max(0, self.fire_cast - dt)
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
        d, bot = self.dark, self.dummy
        d.timers(dt)
        bot.update_timers(dt)
        d.facing += (safe_normal(d.vel, d.facing) - d.facing) * min(1, dt * 9)
        bot.facing += (safe_normal(bot.vel, bot.facing) - bot.facing) * min(1, dt * 9)

        if d.mode == "portal":
            if d.mode_timer < .18:
                d.hidden = True
            if d.mode_timer <= 0:
                self.emerge()
        elif d.mode == "stab":
            bot.pos = d.pos + self.lock_offset
            if d.mode_timer <= 0:
                d.mode = "normal"
                d.vel = safe_normal(self.lock_offset, Vec2(1, 0)).rotate(130) * 350
                self.sound.play("let_go")
        elif d.mode == "dash":
            d.pos += d.vel * dt
            if d.pos.distance_to(bot.pos) <= d.radius + bot.radius + 34:
                self.stab()
            elif not ARENA.inflate(-d.radius * 2, -d.radius * 2).collidepoint(d.pos):
                d.pos.x = clamp(d.pos.x, ARENA.left + d.radius, ARENA.right - d.radius)
                d.pos.y = clamp(d.pos.y, ARENA.top + d.radius, ARENA.bottom - d.radius)
                d.mode, d.immobilized, d.vel = "normal", 2, safe_normal(d.vel).reflect(
                    Vec2(1, 0) if d.pos.x in (ARENA.left + d.radius, ARENA.right - d.radius) else Vec2(0, 1)) * 350
                self.sound.play("crash")
                self.text("IMMOBILIZED  2.0s", d.pos + Vec2(0, -82), HOT_RED, True)
                self.impact(d.pos, 3)
        elif not d.hidden and d.immobilized <= 0:
            d.pos += safe_normal(d.vel) * 350 * dt
            d.vel = safe_normal(d.vel) * 350
            self.wall_bounce(d, bot)

        if bot.stunned <= 0:
            bot.pos += bot.vel * bot.speed_scale * dt
            self.wall_bounce(bot, d, True)

        distance = d.pos.distance_to(bot.pos)
        if d.mode == "normal" and not d.hidden and distance < d.radius + bot.radius:
            n = safe_normal(bot.pos - d.pos)
            overlap = d.radius + bot.radius - distance
            d.pos -= n * overlap * .5
            bot.pos += n * overlap * .5
            d.vel = safe_normal(d.vel.reflect(n)) * 350
            bot.vel = safe_normal(bot.vel.reflect(n)) * bot.vel.length()
            if bot.punch_timer <= 0 and bot.stunned <= 0:
                bot.punch_timer = 1
                bot.punch_anim = .42
                bot.punch_target = Vec2(d.pos)
                base_angle = math.degrees(math.atan2(d.pos.y - bot.pos.y, d.pos.x - bot.pos.x))
                bot.punch_dir = Vec2(1, 0).rotate(base_angle + random.choice((-125, -75, 75, 125)))
                self.sound.play("dummy_punch")
                self.damage_dark(255)
        if (d.mode == "normal" and not d.hidden and distance <= d.radius + bot.radius + 125
                and d.attack_timer <= 0 and not self.actions_locked):
            self.slash()
        if d.mode == "normal" and d.stacks and d.fire_timer <= 0 and not self.actions_locked:
            self.cast_fire()
        if d.spider_timer <= 0 and not self.actions_locked:
            self.spawn_spiders()

        for queued in self.spawn_queue:
            queued[0] -= dt
            if queued[0] <= 0:
                direction = queued[1]
                self.fireballs.append(FireBall(d.pos + direction * 58, direction * 520))
        self.spawn_queue = [queued for queued in self.spawn_queue if queued[0] > 0]

        for pool in self.pools:
            if pool.hardened > 0:
                pool.hardened -= dt
                pool.tick -= dt
                spike_hit = pool.pos.distance_to(bot.pos) < 62 + bot.radius
                for i, edge in enumerate(pool.points):
                    direction = safe_normal(edge)
                    length = 34 + (i % 4) * 12 + math.sin(pool.phase + i) * 6
                    start = pool.pos + edge
                    tip = start + direction * length
                    if point_segment_distance(bot.pos, start, tip) <= bot.radius + 9:
                        spike_hit = True
                        break
                if pool.tick <= 0 and spike_hit:
                    pool.tick = .5
                    spike_damage = 12 if getattr(self, "target_is_summon", False) else 37
                    self.damage_dummy(spike_damage, "VIRA SPIKES")
                    healed = min(spike_damage * .5, d.max_hp - d.hp)
                    d.hp += healed
                    if healed > 0:
                        self.text(f"+{healed:g} HP", d.pos + Vec2(0, -72), HOT_RED)
        expired = [p for p in self.pools if p.hardened <= 0 and p.hardened != 0 and p.melt <= 0]
        for pool in expired:
            pool.hardened = 0
            pool.melt = 1.15
            pool.spent = True
            self.burst(pool.pos, DARK_RED, 15, 90, "smoke", 11)
            self.sound.play(random.choice(("liquid1", "liquid2")))
        for pool in self.pools:
            if pool.melt > 0:
                pool.melt -= dt
        self.pools = [p for p in self.pools if not p.spent or p.melt > 0]

        for fire in self.fireballs:
            fire.life -= dt
            fire.age += dt
            fire.pos += fire.vel * dt
            if fire.pos.distance_to(bot.pos) < fire.radius + bot.radius:
                fire.life = 0
                self.damage_dummy(47, "DARK ENERGY")
                self.burst(fire.pos, HOT_RED, 14, 250, "spark", 4)
            elif not ARENA.collidepoint(fire.pos):
                fire.life = 0
                self.burst(fire.pos, DARK_RED, 8, 120, "smoke", 5)
        self.fireballs = [f for f in self.fireballs if f.life > 0]

        for spider in self.spiders:
            spider.age += dt
            spider.pos += spider.vel * dt
            if not spider.hit and spider.pos.distance_to(bot.pos) < bot.radius + 25:
                spider.hit = True
                self.damage_dummy(65, "VIRA-SPIDER", 2)
            if spider.pos.distance_to(spider.end) < 18:
                spider.vel = Vec2()
        self.spiders = [s for s in self.spiders if s.vel.length_squared()]
        for portal in self.portals:
            portal.life -= dt
        self.portals = [p for p in self.portals if p.life > 0]
        for particle in self.particles:
            particle.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        for text in self.texts:
            text.update(dt)
        self.texts = [t for t in self.texts if t.life > 0]
        if bot.hp <= 0 or d.hp <= 0:
            self.winner = "DARKLORD WINS" if bot.hp <= 0 else "DUMMYBOT WINS"
            self.round_over = 5
            self.shake = 18

    def draw_background(self, dst, offset):
        shared.draw_arena(dst, ARENA, W, H, self.time, offset)

    def draw_electric_arc(self, layer, start, end, phase=0, alpha=220, width=2):
        direction = end - start
        q = Vec2(-direction.y, direction.x)
        q = safe_normal(q)
        points = [start]
        for i in range(1, 7):
            t = i / 7
            jitter = math.sin(self.time * 42 + phase + i * 3.7) * (8 - abs(.5 - t) * 8)
            points.append(start + direction * t + q * jitter)
        points.append(end)
        pygame.draw.lines(layer, (*DARK_RED, int(alpha * .55)), False, points, width + 4)
        pygame.draw.lines(layer, (*HOT_RED, alpha), False, points, width)
        pygame.draw.lines(layer, (255, 210, 165, int(alpha * .55)), False, points, 1)

    def draw_vira_blade(self, layer, origin, direction, scale=1, mirror=1, alpha=255):
        direction = safe_normal(direction)
        q = Vec2(-direction.y, direction.x) * mirror
        source = [
            (0, 0), (50, -10), (94, -47), (116, -54), (128, -49), (119, -35),
            (104, -31), (82, -11), (108, -8), (135, -20), (151, -14), (141, -3),
            (119, 4), (88, 9), (111, 24), (132, 28), (139, 39), (124, 42),
            (102, 27), (52, 13),
        ]
        # The forked branches form at the grip; the long single point faces outward.
        local = [(166 - x, y * 1.08) for x, y in source]
        points = [origin + direction * x * scale + q * y * scale for x, y in local]
        pygame.draw.polygon(layer, (3, 3, 8, alpha), points)
        pygame.draw.lines(layer, (*DARK_RED, alpha), True, points, max(4, int(9 * scale)))
        pygame.draw.lines(layer, (*HOT_RED, int(alpha * .88)), True, points, max(2, int(3 * scale)))
        inner = [
            origin + direction * 24 * scale + q * -25 * scale,
            origin + direction * 72 * scale + q * -12 * scale,
            origin + direction * 139 * scale,
            origin + direction * 70 * scale + q * 12 * scale,
            origin + direction * 27 * scale + q * 28 * scale,
        ]
        pygame.draw.polygon(layer, (32, 3, 12, int(alpha * .75)), inner)
        pygame.draw.lines(layer, (135, 13, 24, int(alpha * .92)), True, inner, max(2, int(3 * scale)))
        point = origin + direction * 166 * scale
        fork_a = origin + direction * 38 * scale + q * -48 * scale
        fork_b = origin + direction * 28 * scale + q * 42 * scale
        self.draw_electric_arc(layer, fork_a, point, 1.7, int(alpha * .86), max(1, int(2 * scale)))
        self.draw_electric_arc(layer, fork_b, point, 4.1, int(alpha * .8), max(1, int(2 * scale)))
        for i in range(5):
            spark = point - direction * (8 + i * 7) + q * math.sin(self.time * 35 + i) * 7
            pygame.draw.circle(layer, (*HOT_RED, int(alpha * .7)), spark, max(1, int((3 - i * .35) * scale)))

    def draw_pool(self, dst, pool, offset):
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        melt_progress = clamp(pool.melt / 1.15, 0, 1)
        pulse = 1 + math.sin(self.time * 3 + pool.phase) * .07
        flatten = 1 - (1 - melt_progress) * .28 if pool.spent else 1
        points = [pool.pos + Vec2(p.x * pulse * (1.15 if pool.spent else 1), p.y * pulse * flatten) + offset
                  for p in pool.points]
        pygame.draw.polygon(layer, (3, 3, 10, 225), points)
        inner = [pool.pos + offset + (point - pool.pos - offset) * .68 for point in points]
        pygame.draw.polygon(layer, (42, 3, 14, 75), inner)
        pygame.draw.lines(layer, (*DARK_RED, 245), True, points, 7)
        pygame.draw.lines(layer, (*HOT_RED, 230), True, points, 2)
        for i in range(0, len(points), 3):
            a, b = points[i], points[(i + 2) % len(points)]
            pygame.draw.line(layer, (255, 70, 45, 100), a, b, 1)
        if pool.hardened > 0 or pool.melt > 0:
            for i, point in enumerate(points):
                direction = safe_normal(point - (pool.pos + offset))
                side = Vec2(-direction.y, direction.x)
                if pool.hardened > 0:
                    growth = clamp((7.25 - pool.hardened) / .25, 0, 1)
                    collapse = 1
                else:
                    growth = 1
                    collapse = melt_progress * melt_progress
                length = (34 + (i % 4) * 12 + math.sin(pool.phase + i) * 6) * growth * collapse
                sag = Vec2(0, (1 - collapse) * (35 + i % 3 * 10))
                tip = point + direction * length + sag
                base = 11 * max(.25, collapse)
                pygame.draw.polygon(layer, (5, 4, 11, int(255 * max(.25, collapse))),
                                    [point - side * base, point + side * base, tip])
                pygame.draw.line(layer, (*DARK_RED, int(255 * collapse)), point - side * base * .65, tip, 5)
                pygame.draw.line(layer, (*HOT_RED, int(245 * collapse)), point - side * base * .3, tip, 2)
                if pool.melt > 0:
                    drip = tip + Vec2(math.sin(i + self.time * 5) * 3, (1 - melt_progress) * 30)
                    pygame.draw.line(layer, (*DARK_RED, int(210 * melt_progress)), tip, drip, 3)
                    pygame.draw.circle(layer, (*HOT_RED, int(190 * melt_progress)), drip, 3)
        dst.blit(layer, (0, 0))

    def draw_portal(self, dst, portal, offset):
        t = clamp(portal.life / portal.max_life, 0, 1)
        p, n = portal.pos + offset, portal.normal
        q = Vec2(-n.y, n.x)
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        open_amount = math.sin(math.pi * t) ** .55
        points = []
        for i in range(36):
            angle = i / 36 * math.tau
            wobble = 1 + math.sin(angle * 6 + self.time * 18) * .16
            points.append(p + q * math.cos(angle) * 88 * open_amount * wobble + n * math.sin(angle) * 22)
        pygame.draw.polygon(layer, (2, 2, 8, int(245 * t)), points)
        pygame.draw.lines(layer, (*DARK_RED, int(255 * t)), True, points, 13)
        pygame.draw.lines(layer, (*HOT_RED, int(245 * t)), True, points, 3)
        for i in range(16):
            side = -1 if i % 2 else 1
            root = p + q * side * (32 + (i % 8) * 8) * open_amount
            mid = root + n * (23 + i % 4 * 9) + q * side * math.sin(self.time * 14 + i) * 11
            tip = mid + n * (13 + i % 3 * 7) - q * side * 5
            pygame.draw.lines(layer, (*DARK_RED, int(200 * t)), False, [root, mid, tip], 7)
            pygame.draw.lines(layer, (*HOT_RED, int(185 * t)), False, [root, mid, tip], 2)
            pygame.draw.circle(layer, (*HOT_RED, int(190 * t)), tip, 3)
        for radius in (24, 42, 61):
            rect = pygame.Rect(p.x - radius, p.y - radius * .32, radius * 2, radius * .64)
            pygame.draw.arc(layer, (*HOT_RED, int((150 - radius) * t)), rect, self.time * 5, self.time * 5 + math.pi * 1.3, 2)
        for i in range(5):
            a = p + q * (-64 + i * 32) * open_amount + n * 5
            b = p + q * (-48 + i * 30) * open_amount - n * (28 + i % 2 * 12)
            self.draw_electric_arc(layer, a, b, i * 1.9, int(180 * t), 2)
        dst.blit(layer, (0, 0))

    def draw_spider(self, dst, spider, offset):
        p = spider.pos + offset
        direction, q = safe_normal(spider.vel), Vec2(-safe_normal(spider.vel).y, safe_normal(spider.vel).x)
        phase = self.time * 22 + spider.phase
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        for i in range(1, 5):
            echo = p - direction * i * 14
            pygame.draw.ellipse(layer, (*DARK_RED, 24), pygame.Rect(echo.x - 10, echo.y - 17, 20, 34))
        for side in (-1, 1):
            for j in (-1, 1):
                root = p + q * side * 11 + direction * j * 7
                knee = root + q * side * (42 + j * 8) + direction * math.sin(phase + side * 2 + j) * 18
                ankle = knee + q * side * 29 - direction * (18 + j * 10)
                tip = ankle + direction * 13 + q * side * 8
                pygame.draw.lines(layer, (20, 3, 10, 230), False, [root, knee, ankle, tip], 11)
                pygame.draw.lines(layer, (*HOT_RED, 245), False, [root, knee, ankle, tip], 3)
                pygame.draw.circle(layer, (255, 150, 95, 220), knee, 3)
        pygame.draw.ellipse(layer, (22, 4, 12, 255), pygame.Rect(p.x - 15, p.y - 25, 30, 50))
        pygame.draw.ellipse(layer, HOT_RED, pygame.Rect(p.x - 15, p.y - 25, 30, 50), 3)
        pygame.draw.ellipse(layer, (245, 45, 30, 150), pygame.Rect(p.x - 7, p.y - 15, 14, 23))
        pygame.draw.line(layer, (255, 185, 120, 210), p - direction * 13, p + direction * 13, 2)
        for side in (-1, 1):
            eye = p + direction * 15 + q * side * 5
            pygame.draw.circle(layer, (255, 220, 165, 240), eye, 2)
        for side in (-1, 1):
            claw = p + direction * 20 + q * side * 7
            pygame.draw.arc(layer, HOT_RED, pygame.Rect(claw.x - 10, claw.y - 10, 20, 25),
                            -math.pi * .2 if side < 0 else math.pi * .7,
                            math.pi * .8 if side < 0 else math.pi * 1.7, 3)
        if int(spider.age * 16) % 3 == 0:
            self.draw_electric_arc(layer, p - direction * 12, p - direction * 38 + q * math.sin(phase) * 8,
                                   spider.phase, 130, 1)
        dst.blit(layer, (0, 0))

    def draw_ball(self, dst, fighter, offset, darklord=False):
        def decorate(ball, center, radius, facing, roll):
            if not darklord:
                return
            band_rect = pygame.Rect(center.x - radius * .72, center.y - radius * .72, radius * 1.44, radius * 1.44)
            pygame.draw.arc(ball, (18, 5, 12), band_rect, roll + .35, roll + 1.42, 7)
            pygame.draw.arc(ball, HOT_RED, band_rect, roll + .42, roll + 1.34, 2)
            pygame.draw.arc(ball, (18, 5, 12), band_rect, roll + math.pi + .35, roll + math.pi + 1.42, 7)
            pygame.draw.arc(ball, HOT_RED, band_rect, roll + math.pi + .42, roll + math.pi + 1.34, 2)
            eye_center = center + facing * radius * .39
            q = Vec2(-facing.y, facing.x)
            for side in (-1, 1):
                eye = eye_center + q * side * radius * .18
                pygame.draw.line(ball, VIRA, eye - facing * 7 - q * side * 5, eye + facing * 7, 6)
                pygame.draw.line(ball, (255, 225, 180), eye + facing * 1, eye + facing * 6, 2)

        shared.draw_ball(
            dst, fighter.pos + offset, fighter.radius,
            (168, 23, 28) if darklord else (84, 91, 108),
            HOT_RED if darklord else (180, 190, 205),
            fighter.facing, fighter.roll if darklord else self.time * 2,
            fighter.squash, fighter.hit_flash,
            fighter.frozen if not darklord else 0,
            fighter.burned if not darklord else 0,
            (255, 220, 180) if darklord else (210, 225, 245),
            decorate,
        )

    def draw_blades(self, dst, offset):
        d = self.dark
        if d.slash_anim <= 0 and d.stab_anim <= 0:
            return
        direction = safe_normal(self.dummy.pos - d.pos)
        q = Vec2(-direction.y, direction.x)
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        if d.stab_anim > 0:
            for side in (-1, 1):
                root = d.pos + offset + q * side * 25 - direction * 8
                self.draw_vira_blade(layer, root, direction, .92, side)
                for i in range(5):
                    a = root - direction * (10 + i * 12) + q * side * math.sin(self.time * 24 + i) * 6
                    b = a - direction * (12 + i * 3) + q * side * 4
                    self.draw_electric_arc(layer, a, b, i + side, 130 - i * 15, 1)
            dark_center = d.pos + offset
            dummy_center = self.dummy.pos + offset
            for i in range(11):
                angle = self.time * 9 + i / 11 * math.tau
                start = dark_center + Vec2(1, 0).rotate_rad(angle) * (d.radius + 4 + i % 3 * 5)
                end = dummy_center + Vec2(1, 0).rotate_rad(-angle * 1.3) * (self.dummy.radius + 5 + i % 4 * 4)
                self.draw_electric_arc(layer, start, end, i * 2.17, 205 - i % 3 * 25, 2 if i % 3 == 0 else 1)
            for center, radius, reverse in ((dark_center, d.radius + 13, 1), (dummy_center, self.dummy.radius + 14, -1)):
                ring = []
                for i in range(18):
                    angle = reverse * (self.time * 7 + i / 18 * math.tau)
                    ring.append(center + Vec2(1, 0).rotate_rad(angle) * (radius + math.sin(self.time * 31 + i) * 7))
                pygame.draw.lines(layer, (*DARK_RED, 120), True, ring, 7)
                pygame.draw.lines(layer, (*HOT_RED, 205), True, ring, 2)
        else:
            progress = 1 - d.slash_anim / .28
            center = d.pos + offset + direction * 22
            start_angle = math.degrees(math.atan2(direction.y, direction.x)) + d.slash_side * lerp(-112, 38, progress)
            blade_dir = Vec2(1, 0).rotate(start_angle)
            for i in range(5, 0, -1):
                echo_dir = Vec2(1, 0).rotate(start_angle - d.slash_side * i * 11)
                echo_tip = center + echo_dir * (125 + i * 4)
                pygame.draw.line(layer, (*DARK_RED, 15 + (6 - i) * 10), center, echo_tip, 8 - i)
            self.draw_vira_blade(layer, center, blade_dir, 1.08, d.slash_side)
            arc_center = d.pos + offset + direction * 72
            arc_rect = pygame.Rect(arc_center.x - 135, arc_center.y - 135, 270, 270)
            arc_start = math.radians(start_angle - d.slash_side * 52)
            pygame.draw.arc(layer, (*DARK_RED, 155), arc_rect, arc_start, arc_start + math.pi * .72, 18)
            pygame.draw.arc(layer, (*HOT_RED, 225), arc_rect, arc_start, arc_start + math.pi * .72, 3)
            for i in range(5):
                spark = self.dummy.pos + offset + Vec2(1, 0).rotate(self.time * 280 + i * 72) * (35 + i * 4)
                pygame.draw.circle(layer, (*HOT_RED, 190), spark, 2 + i % 2)
        dst.blit(layer, (0, 0))

    def draw_fire_cast(self, dst, offset):
        if self.fire_cast <= 0:
            return
        t = clamp(self.fire_cast / .42, 0, 1)
        center = self.dark.pos + offset - Vec2(0, 72)
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        radius = 28 + (1 - t) * 28
        for i in range(3):
            r = radius + i * 10
            rect = pygame.Rect(center.x - r, center.y - r * .38, r * 2, r * .76)
            pygame.draw.arc(layer, (*HOT_RED, int(220 * t)), rect,
                            self.time * (5 + i), self.time * (5 + i) + math.pi * (1.15 + i * .15), 3)
        for i in range(8):
            angle = self.time * 5 + i / 8 * math.tau
            a = center + Vec2(radius, 0).rotate_rad(angle)
            b = center + Vec2(radius + 17, 0).rotate_rad(angle + .22)
            pygame.draw.line(layer, (*RED, int(170 * t)), a, b, 3)
        pygame.draw.circle(layer, (4, 3, 10, int(230 * t)), center, int(radius * .62))
        pygame.draw.circle(layer, (*HOT_RED, int(240 * t)), center, int(radius * .62), 3)
        dst.blit(layer, (0, 0))

    def draw_hud(self, dst, fonts):
        def bar(rect, value, maximum, color, flip=False):
            pygame.draw.rect(dst, (15, 10, 18), rect, border_radius=8)
            pygame.draw.rect(dst, (70, 45, 55), rect, 2, border_radius=8)
            fill = rect.inflate(-6, -6)
            fill.width = int(fill.width * clamp(value / maximum, 0, 1))
            if flip:
                fill.right = rect.right - 3
            pygame.draw.rect(dst, color, fill, border_radius=5)
        bar(pygame.Rect(75, 42, 430, 23), self.dark.hp, 5000, RED)
        bar(pygame.Rect(W - 505, 42, 430, 23), self.dummy.hp, self.dummy.max_hp, GREY, True)
        dst.blit(fonts["name"].render("DARKLORD", True, HOT_RED), (75, 13))
        name = fonts["name"].render("DUMMYBOT", True, (225, 228, 235))
        dst.blit(name, (W - 75 - name.get_width(), 13))
        dst.blit(fonts["small"].render(f"{int(self.dark.hp)} / 5000", True, (255, 190, 175)), (80, 70))
        hp = fonts["small"].render(
            f"{int(self.dummy.hp)} / {int(self.dummy.max_hp)}", True, GREY
        )
        dst.blit(hp, (W - 80 - hp.get_width(), 70))
        title = fonts["tiny"].render("VIRA-LIQUID ARENA CONTROL", True, (190, 90, 95))
        dst.blit(title, (W / 2 - title.get_width() / 2, 18))
        for i in range(10):
            pygame.draw.circle(dst, RED if i < self.dark.stacks else (55, 22, 30), (W // 2 - 81 + i * 18, 55), 6)
        status = []
        if self.dummy.stunned > 0:
            status.append(f"DUMMY STUNNED {self.dummy.stunned:.1f}s")
        if self.dark.immobilized > 0:
            status.append(f"DARKLORD IMMOBILIZED {self.dark.immobilized:.1f}s")
        text = fonts["tiny"].render("   ".join(status), True, HOT_RED)
        dst.blit(text, (W / 2 - text.get_width() / 2, 76))
        skills = [("VIRA-PORTAL", self.dark.portal_timer, 9), ("DARK ENERGY", self.dark.fire_timer, 8),
                  ("VIRA-SPIDERS", self.dark.spider_timer, 20)]
        for i, (name, cooldown, total) in enumerate(skills):
            x, y = 82 + i * 208, H - 52
            dst.blit(fonts["tiny"].render(name, True, RED), (x, y - 18))
            pygame.draw.rect(dst, (30, 14, 22), (x, y, 170, 7), border_radius=4)
            pygame.draw.rect(dst, RED, (x, y, int(170 * (1 - clamp(cooldown / total, 0, 1))), 7), border_radius=4)
        info = fonts["tiny"].render("R  RESTART     M  MUTE     ESC  EXIT", True, (130, 95, 110))
        dst.blit(info, (W - 82 - info.get_width(), H - 40))

    def draw_world_effects(self, dst, offset):
        for pool in self.pools:
            self.draw_pool(dst, pool, offset)
        for fire in self.fireballs:
            tail = safe_normal(fire.vel)
            q = Vec2(-tail.y, tail.x)
            fire_layer = pygame.Surface((W, H), pygame.SRCALPHA)
            center = fire.pos + offset
            flame_points = []
            for i in range(28):
                angle = i / 28 * math.tau
                outward = Vec2(1, 0).rotate_rad(angle)
                rear = max(0, -outward.dot(tail))
                wobble = math.sin(fire.age * 38 + i * 2.7) * 4
                radius = fire.radius + wobble + rear * (13 + (i % 3) * 5)
                flame_points.append(center + outward * radius - tail * rear * 8)
            pygame.draw.polygon(fire_layer, (70, 5, 18, 145), flame_points)
            pygame.draw.lines(fire_layer, (*DARK_RED, 225), True, flame_points, 7)
            pygame.draw.lines(fire_layer, (*HOT_RED, 190), True, flame_points, 2)
            for i in range(11, 0, -1):
                trail = center - tail * i * 12 + q * math.sin(fire.age * 31 + i * 1.7) * (4 + i * 1.2)
                radius = max(2, int(fire.radius * (1 - i / 14)))
                pygame.draw.circle(fire_layer, (*DARK_RED, 22 + (12 - i) * 11), trail, radius)
                pygame.draw.circle(fire_layer, (*HOT_RED, 32 + (12 - i) * 7), trail, max(2, radius // 3))
            pygame.draw.circle(fire_layer, (3, 3, 9, 255), center, int(fire.radius * .88))
            pygame.draw.circle(fire_layer, (86, 7, 22, 235), center, int(fire.radius * .67), 5)
            pygame.draw.circle(fire_layer, HOT_RED, center, int(fire.radius * .88), 3)
            pygame.draw.circle(fire_layer, (255, 165, 100, 220), center - tail * 6 - q * 6, 5)
            for i in range(3):
                orbit_angle = fire.age * (7 + i * 1.7) + i * math.tau / 3
                satellite = center + Vec2(1, 0).rotate_rad(orbit_angle) * (fire.radius + 10 + i * 4)
                pygame.draw.circle(fire_layer, (*HOT_RED, 210), satellite, 3 + i)
            for i in range(5):
                a = center - tail * (fire.radius * .4 + i * 5) + q * (-18 + i * 9)
                b = center - tail * (fire.radius + 35 + i * 8) + q * math.sin(fire.age * 42 + i) * 21
                self.draw_electric_arc(fire_layer, a, b, i * 2.3, 195 - i * 18, 1 + (i % 2))
            dst.blit(fire_layer, (0, 0))
        for spider in self.spiders:
            self.draw_spider(dst, spider, offset)
        for particle in self.particles:
            particle.draw(dst, offset)
        if self.dark.mode == "dash":
            direction = safe_normal(self.dark.vel)
            q = Vec2(-direction.y, direction.x)
            dash_layer = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(1, 12):
                p = self.dark.pos + offset - direction * i * 17 + q * math.sin(self.time * 33 + i * 1.8) * (8 + i)
                pygame.draw.circle(dash_layer, (*DARK_RED, max(8, 78 - i * 6)), p, max(2, 16 - i))
                if i % 2:
                    pygame.draw.circle(dash_layer, (*HOT_RED, max(10, 125 - i * 9)), p + q * (8 + i), max(2, 6 - i // 3))
            for i in range(4):
                a = self.dark.pos + offset - direction * (28 + i * 22) + q * (-26 + i * 17)
                b = a - direction * (38 + i * 9) + q * math.sin(self.time * 48 + i * 2) * 28
                self.draw_electric_arc(dash_layer, a, b, i * 3.1, 190 - i * 25, 2)
            dst.blit(dash_layer, (0, 0))

    def draw(self, dst, fonts):
        offset = Vec2(random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake)) if self.shake else Vec2()
        self.draw_background(dst, offset)
        shared.draw_movement_trail(dst, self.dark, RED, offset, 5)
        shared.draw_movement_trail(dst, self.dummy, (155, 165, 185), offset, 4)
        self.draw_world_effects(dst, offset)
        if not self.dark.hidden:
            self.draw_ball(dst, self.dark, offset, True)
        self.draw_ball(dst, self.dummy, offset)
        for portal in self.portals:
            self.draw_portal(dst, portal, offset)
        self.draw_fire_cast(dst, offset)
        self.draw_blades(dst, offset)
        shared.draw_dummy_punch(dst, self.dummy, self.time, offset, W, H)
        for text in self.texts:
            font = fonts["impact"] if text.big else fonts["small"]
            image = font.render(text.text, True, text.color)
            shadow = font.render(text.text, True, (5, 3, 7))
            p = text.pos + offset
            dst.blit(shadow, (p.x - image.get_width() / 2 + 2, p.y + 2))
            dst.blit(image, (p.x - image.get_width() / 2, p.y))
        self.draw_hud(dst, fonts)
        if self.banner_time > 0:
            image = fonts["banner"].render("DARKLORD // AUTONOMOUS COMBAT PROTOTYPE", True, (255, 190, 175))
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - 100))
        if self.round_over:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((6, 2, 6, 160))
            dst.blit(veil, (0, 0))
            image = fonts["winner"].render(self.winner, True, HOT_RED)
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - image.get_height() / 2))


def make_fonts():
    return shared.make_fonts()


def main():
    parser = argparse.ArgumentParser(description="DarkLord autonomous combat prototype")
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
    pygame.display.set_caption("DarkLord // Autonomous Combat Prototype")
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
