from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pygame


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "Prototype-Shared"))
sys.path.insert(0, str(ROOT / "DummyBot-Prototype"))
import visuals as shared  # noqa: E402
from DummyBot import DummyBot  # noqa: E402

W, H, FPS = 1280, 720, 120
ARENA = pygame.Rect(72, 112, W - 144, H - 184)
Vec2 = pygame.Vector2
ICE = (90, 220, 255)
ICE_WHITE = (220, 250, 255)
HEAT = (255, 75, 34)
RED = (242, 43, 31)
HOT_RED = (255, 82, 45)
PINK = (255, 92, 185)
PINK_HOT = (255, 39, 156)
GOLD = (255, 205, 92)
GREY = (185, 190, 205)
SETTINGS = json.loads((ROOT / "tournament-settings.json").read_text(encoding="utf-8"))


def clamp(value, low, high):
    return max(low, min(high, value))


def safe_normal(vector, fallback=Vec2(1, 0)):
    return vector.normalize() if vector.length_squared() > .001 else Vec2(fallback)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MORO = load_module("tournament_morozhar", ROOT / "MoroZhar-Prototype" / "MoroZhar.py")
DARK = load_module("tournament_darklord", ROOT / "DarkLord-Prototype" / "DarkLord.py")
YUTA = load_module("tournament_yuta", ROOT / "Yuta-Prototype" / "Yuta.py")


def discover_eligible():
    eligible = []
    for folder in sorted(ROOT.glob("*-Prototype")):
        if character_name(folder.name) in SETTINGS["excluded_characters"]:
            continue
        data_files = list(folder.glob("*-Datas.txt"))
        if not data_files:
            continue
        text = data_files[0].read_text(encoding="utf-8", errors="ignore")
        status = ""
        for line in text.splitlines():
            if line.startswith("PROTOTYPE STATUS:"):
                status = line.split(":", 1)[1].strip()
                break
        character = folder.name.removesuffix("-Prototype")
        if status in SETTINGS["eligible_statuses"] and (folder / f"{character}.py").exists():
            eligible.append((character.upper(), status))
    return eligible


def character_name(folder_name):
    return folder_name.removesuffix("-Prototype").upper()


@dataclass
class StatusState:
    frozen: float = 0
    slowed: float = 0
    burned: float = 0
    stunned: float = 0
    burn_tick: float = 0
    ice_stacks: int = 0
    heat_stacks: int = 0
    heat_decay_timer: float = 0
    thermal_shock_locked: bool = False
    ice_break_warned: bool = False


class TournamentTarget(DummyBot):
    """DummyBot's status API used as a synchronized combat target facade."""

    def __init__(self, pos):
        super().__init__(Vec2(pos))
        self.punch_timer = 999999
        self.redirects = 0
        self.redirect_timer = 999999

    def update_timers(self, dt):
        self.punch_anim = max(0, self.punch_anim - dt)
        self.hit_flash = max(0, self.hit_flash - dt)
        self.squash = max(0, self.squash - dt * 4.5)
        self.redirects = 0

    @property
    def speed_scale(self):
        # The real opponent is moved by its own controller. This facade stays
        # at the synchronized position for the attacker's combat calculation.
        return 0


@dataclass
class FighterSlot:
    key: str
    name: str
    controller: object
    body: object
    target: TournamentTarget
    accent: tuple
    status: StatusState = field(default_factory=StatusState)
    target_entity: object = None
    tournament_wins: int = 0

    @property
    def hp(self):
        return self.body.hp

    @hp.setter
    def hp(self, value):
        self.body.hp = max(0, value)

    @property
    def max_hp(self):
        return self.body.max_hp


def randomize_opening_direction(body, side):
    enemy_wall_x = ARENA.right if side == 0 else ARENA.left
    target = Vec2(enemy_wall_x, random.uniform(ARENA.top + body.radius, ARENA.bottom - body.radius))
    body.vel = safe_normal(target - body.pos) * body.vel.length()
    body.facing = safe_normal(body.vel)


def make_slot(key, side, muted):
    pos = Vec2(290 if side == 0 else 985, 385)
    enemy_pos = Vec2(985 if side == 0 else 290, 385)
    if key == "MOROZHAR":
        controller = MORO.Battle(muted)
        controller.moro.pos = pos
        randomize_opening_direction(controller.moro, side)
        target = TournamentTarget(enemy_pos)
        controller.dummy = target
        controller.round_over = 0
        return FighterSlot(key, "MOROZHAR", controller, controller.moro, target, ICE)
    if key == "DARKLORD":
        controller = DARK.Battle(muted)
        controller.dark.pos = pos
        randomize_opening_direction(controller.dark, side)
        target = TournamentTarget(enemy_pos)
        controller.dummy = target
        controller.round_over = 0
        return FighterSlot(key, "DARKLORD", controller, controller.dark, target, RED)
    if key == "YUTA":
        controller = YUTA.Battle(muted)
        controller.yuta.pos = pos
        randomize_opening_direction(controller.yuta, side)
        target = TournamentTarget(enemy_pos)
        controller.dummy = target
        controller.round_over = 0
        return FighterSlot(key, "YUTA", controller, controller.yuta, target, PINK)
    raise ValueError(f"No tournament adapter exists for {key}")


def is_alive_entity(entity):
    state = getattr(entity, "alive", True)
    return state() if callable(state) else bool(state)


def enemy_target_candidates(enemy):
    candidates = [enemy.body]
    if enemy.key == "YUTA" and enemy.controller.rika.alive:
        candidates.append(enemy.controller.rika)
    return [entity for entity in candidates if getattr(entity, "hp", 1) > 0 and is_alive_entity(entity)]


def select_target_entity(slot, enemy):
    candidates = enemy_target_candidates(enemy)
    return min(candidates or [enemy.body], key=lambda entity: slot.body.pos.distance_squared_to(entity.pos))


def copy_status_to_target(slot, enemy, entity=None):
    entity = entity or enemy.body
    target, status = slot.target, enemy.status
    target.pos = Vec2(entity.pos)
    target.vel = Vec2(getattr(entity, "vel", Vec2()))
    target.radius = entity.radius
    target.hp = entity.hp
    target.max_hp = entity.max_hp
    target.facing = Vec2(getattr(entity, "facing", safe_normal(target.vel, Vec2(1, 0))))
    target.hit_flash = getattr(entity, "hit_flash", 0)
    target.squash = getattr(entity, "squash", 0)
    if entity is enemy.body:
        for name in vars(status):
            setattr(target, name, getattr(status, name))
    else:
        for name in vars(status):
            setattr(target, name, 0 if isinstance(getattr(status, name), (int, float)) else False)
    target.punch_timer = 999999
    target.redirect_timer = 999999
    target.redirects = 0


def copy_target_to_enemy(slot, enemy):
    entity = slot.target_entity or enemy.body
    target, status = slot.target, enemy.status
    yuta_forced_position = (
        slot.key == "YUTA" and
        (slot.controller.beam.phase == "blast" or slot.controller.chain.life > 0)
    )
    if entity is enemy.body:
        enemy.body.hp = target.hp
        if yuta_forced_position:
            enemy.body.pos = Vec2(target.pos)
            enemy.body.vel = Vec2(target.vel)
        for name in vars(status):
            setattr(status, name, getattr(target, name))
        enemy.body.hit_flash = max(getattr(enemy.body, "hit_flash", 0), target.hit_flash)
        enemy.body.squash = max(getattr(enemy.body, "squash", 0), target.squash)
        if slot.key == "DARKLORD" and slot.body.mode == "stab":
            enemy.body.pos = Vec2(target.pos)
    elif enemy.key == "YUTA" and entity is enemy.controller.rika:
        rika = enemy.controller.rika
        if enemy.controller.beam.phase in {"charge", "blast"}:
            if target.hp < rika.hp:
                enemy.controller.shield_pops.append(YUTA.ShieldPop(Vec2(rika.pos)))
                enemy.controller.text("SHIELDED", rika.pos + Vec2(0, -122), PINK)
            target.hp = rika.hp
        else:
            rika.hp = max(0, target.hp)
            if yuta_forced_position:
                rika.pos = Vec2(target.pos)
                rika.vel = Vec2(target.vel)
            rika.hit_flash = max(rika.hit_flash, target.hit_flash)
            rika.squash = max(rika.squash, target.squash)
            if slot.key == "DARKLORD" and slot.body.mode == "stab":
                rika.pos = Vec2(target.pos)
            if rika.hp <= 0 and rika.alive:
                rika.alive = False
                rika.died_after_spawn = True
                rika.despawning = 1.25
                rika.saved_pure_love_cd = max(0, enemy.controller.yuta.pure_cd)
                enemy.controller.sound.play("rika_death")
                enemy.controller.text("RIKA DISPERSED", rika.pos + Vec2(0, -120), YUTA.RIKA_SKIN, True)
                enemy.controller.rika_disappear_fx(rika.pos)


def status_locked(slot):
    return slot.status.frozen > 0 or slot.status.stunned > 0


def deployed_motion_active(slot):
    if slot.key == "DARKLORD" and slot.body.mode in {"portal", "dash", "stab"}:
        return True
    return slot.key == "YUTA" and bool(slot.controller.beam.phase)


def position_locked(slot):
    status_position_lock = status_locked(slot) and not deployed_motion_active(slot)
    return status_position_lock or (getattr(slot.body, "immobilized", 0) > 0 and not deployed_motion_active(slot))


class Tournament:
    def __init__(self, muted=False, round_time=None):
        self.muted = muted
        self.round_time_limit = round_time or SETTINGS["round_time_seconds"]
        self.post_match_time = SETTINGS["post_match_seconds"]
        self.best_of = SETTINGS.get("series_best_of", 3)
        self.first_to = self.best_of // 2 + 1
        self.eligible = [name for name, _ in discover_eligible() if name in {"MOROZHAR", "DARKLORD", "YUTA"}]
        if len(self.eligible) < 2:
            raise RuntimeError("At least two completed tournament adapters are required.")
        self.match_number = 0
        self.bracket_number = 0
        self.series_number = 0
        self.series_stage = ""
        self.waiting = []
        self.series_wins = {}
        self.champion_name = ""
        self.next_series = None
        self.start_new_bracket()

    def start_new_bracket(self):
        self.bracket_number += 1
        order = self.eligible[:]
        random.shuffle(order)
        self.waiting = order[2:]
        self.champion_name = ""
        stage = "OPENING" if self.waiting else "FINAL"
        self.start_series(order[0], order[1], stage)

    def start_series(self, left_key, right_key, stage):
        self.series_number += 1
        self.series_stage = stage
        self.left_key = left_key
        self.right_key = right_key
        self.series_wins = {left_key: 0, right_key: 0}
        self.reset_round()

    def reset_round(self):
        self.match_number += 1
        self.left = make_slot(self.left_key, 0, self.muted)
        self.right = make_slot(self.right_key, 1, self.muted)
        self.time = 0
        self.round_time = self.round_time_limit
        self.round_over = 0
        self.winner = ""
        self.banner_time = 3
        self.intro_time = 5
        self.shake = 0

    def reset_match(self):
        self.start_new_bracket()

    def finish_round(self, winner):
        self.series_wins[winner.key] += 1
        score = f"{self.series_wins[self.left_key]}-{self.series_wins[self.right_key]}"
        if self.series_wins[winner.key] >= self.first_to:
            if self.waiting:
                next_key = self.waiting.pop(0)
                self.winner = f"{winner.name} TAKES SERIES {score}  //  NEXT: {next_key}"
                self.round_over = self.post_match_time
                self.next_series = (winner.key, next_key, "FINAL" if not self.waiting else "NEXT")
            else:
                self.champion_name = winner.key
                self.winner = f"{winner.name} IS TOURNAMENT CHAMPION"
                self.round_over = self.post_match_time
                self.next_series = None
        else:
            self.winner = f"{winner.name} WINS ROUND  //  SERIES {score}"
            self.round_over = self.post_match_time
            self.next_series = "same"
        self.shake = 18

    def update_slot(self, slot, enemy, dt):
        slot.target_entity = select_target_entity(slot, enemy)
        slot.controller.target_is_summon = slot.target_entity is not enemy.body
        copy_status_to_target(slot, enemy, slot.target_entity)
        if slot.key == "YUTA":
            enemy_summons = []
            if enemy.key == "YUTA" and enemy.controller.rika.alive:
                enemy_summons.append(enemy.controller.rika)
            slot.controller.enemy_summons = enemy_summons
        existing_burn = slot.target.burned
        existing_burn_tick = slot.target.burn_tick
        # Burn damage is authoritative in the tournament engine, preventing
        # duplicated ticks when multiple character controllers inspect it.
        slot.target.burned = 0
        slot.target.burn_tick = 0
        locked = status_locked(slot)
        slot.controller.actions_locked = locked
        old_pos = Vec2(slot.body.pos)
        # Controllers always update so already-deployed actions and effects
        # finish. actions_locked blocks only new activations.
        slot.controller.update(dt)
        if slot.target.burned <= 0:
            slot.target.burned = existing_burn
            slot.target.burn_tick = existing_burn_tick
        if position_locked(slot):
            slot.body.pos = old_pos
        elif slot.status.slowed > 0:
            slot.body.pos = old_pos + (slot.body.pos - old_pos) * .25
        copy_target_to_enemy(slot, enemy)
        slot.target_entity = None
        slot.controller.round_over = 0

    def update_statuses(self, dt):
        for slot in (self.left, self.right):
            status = slot.status
            frozen_before = status.frozen
            status.frozen = max(0, status.frozen - dt)
            status.slowed = max(0, status.slowed - dt)
            status.stunned = max(0, status.stunned - dt)
            if status.burned > 0:
                status.burned = max(0, status.burned - dt)
                status.burn_tick -= dt
                if status.burn_tick <= 0:
                    status.burn_tick = .5
                    slot.hp -= 32
                    slot.body.hit_flash = .12
                    source = next((fighter for fighter in (self.left, self.right)
                                   if fighter is not slot and fighter.key == "MOROZHAR"), None)
                    if source:
                        source.controller.text("-32  BURN", slot.body.pos + Vec2(0, -62), HEAT)
                        source.controller.impact(slot.body.pos, HEAT, 1)
                        healed = min(7, source.body.max_hp - source.body.hp)
                        source.body.hp += healed
                        if healed > 0:
                            source.controller.text(f"+{healed:g} HP", source.body.pos + Vec2(0, -72), HEAT)
            if status.heat_stacks:
                status.heat_decay_timer -= dt
                if status.heat_decay_timer <= 0:
                    status.heat_stacks -= 1
                    status.heat_decay_timer = 4.5 if status.heat_stacks else 0
                    if not status.heat_stacks:
                        status.thermal_shock_locked = False
            if frozen_before > 2 >= status.frozen and not status.ice_break_warned:
                source = next((fighter for fighter in (self.left, self.right)
                               if fighter is not slot and fighter.key == "MOROZHAR"), None)
                if source:
                    copy_status_to_target(source, slot, slot.body)
                    source.controller.warn_ice_break()
                status.ice_break_warned = True
            if frozen_before > 0 and status.frozen <= 0:
                source = next((fighter for fighter in (self.left, self.right)
                               if fighter is not slot and fighter.key == "MOROZHAR"), None)
                if source:
                    source.controller.shatter_ice()

    def separate_fighters(self):
        a, b = self.left.body, self.right.body
        delta = b.pos - a.pos
        distance = delta.length()
        minimum = a.radius + b.radius
        if 0 < distance < minimum:
            normal = delta / distance
            overlap = minimum - distance
            left_locked, right_locked = position_locked(self.left), position_locked(self.right)
            if not left_locked and not right_locked:
                a.pos -= normal * overlap * .5
                b.pos += normal * overlap * .5
            elif not left_locked:
                a.pos -= normal * overlap
            elif not right_locked:
                b.pos += normal * overlap

    def update(self, dt):
        if self.round_over:
            self.round_over -= dt
            if self.round_over <= 0:
                if self.champion_name:
                    self.start_new_bracket()
                elif self.next_series == "same":
                    self.reset_round()
                elif self.next_series:
                    left_key, right_key, stage = self.next_series
                    self.start_series(left_key, right_key, stage)
                else:
                    self.start_new_bracket()
            return
        self.time += dt
        self.banner_time -= dt
        if self.intro_time > 0:
            self.intro_time -= dt
            return
        self.round_time -= dt
        self.update_statuses(dt)
        self.update_slot(self.left, self.right, dt)
        self.update_slot(self.right, self.left, dt)
        self.separate_fighters()
        if self.left.hp <= 0 or self.right.hp <= 0 or self.round_time <= 0:
            if self.left.hp == self.right.hp:
                winner = random.choice((self.left, self.right))
            else:
                winner = self.left if self.left.hp > self.right.hp else self.right
            self.finish_round(winner)

    def draw_dark_effects(self, slot, dst, offset):
        slot.controller.draw_world_effects(dst, offset)

    def draw_moro_effects(self, slot, dst, offset):
        slot.controller.draw_world_effects(dst, offset)

    def draw_yuta_effects(self, slot, dst, offset):
        c = slot.controller
        c.draw_chain(dst, offset)
        c.draw_beam(dst, offset)
        for particle in c.particles:
            particle.draw(dst, offset)
        c.draw_rika(dst, offset)
        c.draw_shield_pops(dst, offset)

    def draw_fighter(self, slot, dst, offset):
        if slot.key == "DARKLORD":
            if not slot.body.hidden:
                slot.controller.draw_ball(dst, slot.body, offset, True)
        elif slot.key == "YUTA":
            c = slot.controller
            c.draw_surge_aura(dst, offset)
            shared.draw_ball(
                dst, slot.body.pos + offset, slot.body.radius,
                (26, 30, 42), PINK,
                slot.body.facing, slot.body.roll, slot.body.squash, slot.body.hit_flash,
                0, 0, YUTA.WHITE, c.draw_yuta_decor,
            )
        else:
            slot.controller.draw_character_aura(dst, offset)
            slot.controller.draw_ball(dst, slot.body.pos + offset, slot.body.radius, (28, 85, 130), (185, 235, 255),
                                      slot.body.facing, slot.body.roll, slot.body.squash, slot.body.hit_flash, moro=True)

    def draw_foreground(self, slot, dst, offset):
        c = slot.controller
        if slot.key == "DARKLORD":
            for portal in c.portals:
                c.draw_portal(dst, portal, offset)
            c.draw_fire_cast(dst, offset)
            c.draw_blades(dst, offset)
        elif slot.key == "YUTA":
            c.draw_slashes(dst, offset)
            c.draw_iron_arm(dst, offset)
            if c.rika.alive and c.rika.claw_anim > 0:
                c.draw_rika_claw(dst, offset)
        else:
            c.draw_punch_hand(dst, offset)
            color = {"PUNCH": GREY, "ICE PUNCH": ICE, "HEAT PUNCH": HEAT}[c.moro.next_punch]
            image = self.fonts["tiny"].render(c.moro.next_punch, True, color)
            p = c.moro.pos + offset
            dst.blit(image, (p.x - image.get_width() / 2, p.y - c.moro.radius - 34))
        for text in c.texts:
            font = self.fonts["impact"] if text.big else self.fonts["small"]
            image = font.render(text.text, True, text.color)
            p = text.pos + offset
            dst.blit(image, (p.x - image.get_width() / 2, p.y))

    def draw_status_overlay(self, slot, dst, offset):
        center = slot.body.pos + offset
        status = slot.status
        layer = pygame.Surface((W, H), pygame.SRCALPHA)
        if status.burned > 0:
            pygame.draw.circle(layer, (*HEAT, 100), center, int(slot.body.radius + 9), 4)
            for i in range(9):
                angle = self.time * 4 + i / 9 * math.tau
                p = center + Vec2(1, 0).rotate_rad(angle) * (slot.body.radius + 9 + math.sin(self.time * 12 + i) * 5)
                pygame.draw.circle(layer, (255, 155, 70, 175), p, 3 + i % 3)
        if status.slowed > 0:
            pygame.draw.arc(layer, (*ICE, 190), pygame.Rect(center.x - 61, center.y - 61, 122, 122),
                            self.time * 2, self.time * 2 + math.pi * 1.5, 4)
        if status.stunned > 0:
            for i in range(4):
                angle = self.time * 8 + i * math.pi * .5
                a = center + Vec2(1, 0).rotate_rad(angle) * (slot.body.radius + 10)
                b = center + Vec2(1, 0).rotate_rad(angle + .55) * (slot.body.radius + 22)
                pygame.draw.line(layer, (255, 215, 110, 220), a, b, 3)
        dst.blit(layer, (0, 0))
        if status.frozen > 0:
            moro_slot = next((fighter for fighter in (self.left, self.right) if fighter.key == "MOROZHAR"), None)
            if moro_slot:
                moro_slot.controller.draw_ice_cube(dst, center, status.frozen)
            else:
                pygame.draw.circle(dst, (*ICE, 120), center, int(slot.body.radius + 12), 6)
        labels = []
        if status.frozen > 0:
            labels.append(f"FROZEN {status.frozen:.1f}s")
        if status.stunned > 0:
            labels.append(f"STUNNED {status.stunned:.1f}s")
        if status.slowed > 0:
            labels.append(f"SLOWED {status.slowed:.1f}s")
        if status.burned > 0:
            labels.append(f"BURN {status.burned:.1f}s")
        if labels:
            image = self.fonts["tiny"].render("  ".join(labels), True, ICE_WHITE)
            dst.blit(image, (center.x - image.get_width() / 2, center.y - slot.body.radius - 48))

    def draw_hud(self, dst):
        def bar(rect, value, maximum, color, flip=False):
            pygame.draw.rect(dst, (12, 17, 31), rect, border_radius=8)
            pygame.draw.rect(dst, (55, 66, 90), rect, 2, border_radius=8)
            fill = rect.inflate(-6, -6)
            fill.width = int(fill.width * clamp(value / maximum, 0, 1))
            if flip:
                fill.right = rect.right - 3
            pygame.draw.rect(dst, color, fill, border_radius=5)
        bar(pygame.Rect(75, 42, 430, 23), self.left.hp, self.left.max_hp, self.left.accent)
        bar(pygame.Rect(W - 505, 42, 430, 23), self.right.hp, self.right.max_hp, self.right.accent, True)
        dst.blit(self.fonts["name"].render(self.left.name, True, self.left.accent), (75, 13))
        right_name = self.fonts["name"].render(self.right.name, True, self.right.accent)
        dst.blit(right_name, (W - 75 - right_name.get_width(), 13))
        dst.blit(self.fonts["small"].render(f"{int(self.left.hp)} / {int(self.left.max_hp)}", True, ICE_WHITE), (80, 70))
        hp = self.fonts["small"].render(f"{int(self.right.hp)} / {int(self.right.max_hp)}", True, ICE_WHITE)
        dst.blit(hp, (W - 80 - hp.get_width(), 70))
        center = self.fonts["small"].render(
            f"BRACKET {self.bracket_number}  {self.series_stage} SERIES  //  ROUND {self.match_number}  //  {max(0, self.round_time):05.1f}s",
                                            True, GOLD)
        dst.blit(center, (W / 2 - center.get_width() / 2, 18))
        score = (
            f"BEST OF {self.best_of}   {self.left_key}: {self.series_wins.get(self.left_key, 0)}"
            f"   {self.right_key}: {self.series_wins.get(self.right_key, 0)}"
        )
        if self.waiting:
            score += f"   WAITING: {', '.join(self.waiting)}"
        score_img = self.fonts["tiny"].render(score, True, (150, 170, 205))
        dst.blit(score_img, (W / 2 - score_img.get_width() / 2, 76))
        details = []
        for slot, enemy in ((self.left, self.right), (self.right, self.left)):
            if slot.key == "DARKLORD":
                details.append(f"{slot.name} VIRA {slot.body.stacks}/10")
            elif slot.key == "YUTA":
                rika = "RIKA UP" if slot.controller.rika.alive else "RIKA DOWN"
                details.append(f"{slot.name} CE {int(slot.body.ce)}/750 {rika}")
            else:
                details.append(f"{slot.name} TARGET ICE {enemy.status.ice_stacks}/3 HEAT {enemy.status.heat_stacks}/3")
        detail_img = self.fonts["tiny"].render("    ".join(details), True, (175, 190, 220))
        dst.blit(detail_img, (W / 2 - detail_img.get_width() / 2, 94))
        info = self.fonts["tiny"].render("R  NEW MATCH     M  MUTE     ESC  EXIT", True, (105, 125, 160))
        dst.blit(info, (W - 82 - info.get_width(), H - 40))

    def draw_intro_card(self, dst):
        if self.intro_time <= 0:
            return
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((2, 4, 12, 205))
        dst.blit(veil, (0, 0))

        t = self.time
        card = pygame.Rect(W // 2 - 390, H // 2 - 155, 780, 310)
        panel = pygame.Surface((card.width, card.height), pygame.SRCALPHA)
        pygame.draw.rect(panel, (8, 11, 24, 238), panel.get_rect(), border_radius=18)
        pygame.draw.rect(panel, (80, 95, 135, 180), panel.get_rect(), 2, border_radius=18)
        for i in range(7):
            alpha = 35 - i * 4
            pygame.draw.rect(panel, (*self.left.accent, alpha),
                             pygame.Rect(18 + i * 5, 18 + i * 5, 210, card.height - 36 - i * 10),
                             2, border_radius=16)
            pygame.draw.rect(panel, (*self.right.accent, alpha),
                             pygame.Rect(card.width - 228 - i * 5, 18 + i * 5, 210, card.height - 36 - i * 10),
                             2, border_radius=16)
        dst.blit(panel, card.topleft)

        left_center = Vec2(card.left + 165, card.centery + math.sin(t * 2.2) * 7)
        right_center = Vec2(card.right - 165, card.centery + math.sin(t * 2.2 + math.pi) * 7)
        for slot, center, flip in ((self.left, left_center, 1), (self.right, right_center, -1)):
            glow = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(5, 0, -1):
                pygame.draw.circle(glow, (*slot.accent, 8 + i * 7), center, 38 + i * 15)
            dst.blit(glow, (0, 0), special_flags=pygame.BLEND_ADD)
            fake = slot.body
            facing = Vec2(flip, 0)
            shared.draw_ball(
                dst, center, 54,
                (35, 45, 65) if slot.key != "DARKLORD" else (168, 23, 28),
                slot.accent, facing, t * 2 * flip, .08 + math.sin(t * 6) * .025, 0,
                0, 0, (255, 235, 245) if slot.key == "YUTA" else ICE_WHITE,
            )
            for i in range(3):
                radius = 72 + i * 13 + math.sin(t * 4 + i) * 3
                rect = pygame.Rect(center.x - radius, center.y - radius, radius * 2, radius * 2)
                pygame.draw.arc(dst, (*slot.accent, 190 - i * 45), rect,
                                t * (2.4 + i * .4) * flip, t * (2.4 + i * .4) * flip + math.pi * .9, 3)

        vs = self.fonts["winner"].render("VS", True, GOLD)
        dst.blit(vs, (W / 2 - vs.get_width() / 2, H / 2 - vs.get_height() / 2 - 8))
        title = self.fonts["banner"].render(f"{self.series_stage}  //  BEST OF {self.best_of}", True, ICE_WHITE)
        dst.blit(title, (W / 2 - title.get_width() / 2, card.top + 28))
        left_name = self.fonts["name"].render(self.left.name, True, self.left.accent)
        right_name = self.fonts["name"].render(self.right.name, True, self.right.accent)
        dst.blit(left_name, (left_center.x - left_name.get_width() / 2, card.bottom - 68))
        dst.blit(right_name, (right_center.x - right_name.get_width() / 2, card.bottom - 68))
        count = self.fonts["impact"].render(f"FIGHT STARTS IN {max(0, self.intro_time):.1f}", True, (220, 230, 250))
        dst.blit(count, (W / 2 - count.get_width() / 2, card.bottom - 37))

    def draw(self, dst, fonts):
        self.fonts = fonts
        character_shake = max(getattr(self.left.controller, "shake", 0), getattr(self.right.controller, "shake", 0))
        shake = max(self.shake, character_shake)
        offset = Vec2(random.uniform(-shake, shake), random.uniform(-shake, shake)) if shake else Vec2()
        shared.draw_arena(dst, ARENA, W, H, self.time, offset)
        for slot in (self.left, self.right):
            shared.draw_movement_trail(dst, slot.body, slot.accent, offset, 5)
            if slot.key == "DARKLORD":
                self.draw_dark_effects(slot, dst, offset)
            elif slot.key == "YUTA":
                self.draw_yuta_effects(slot, dst, offset)
            else:
                self.draw_moro_effects(slot, dst, offset)
        self.draw_fighter(self.left, dst, offset)
        self.draw_fighter(self.right, dst, offset)
        self.draw_status_overlay(self.left, dst, offset)
        self.draw_status_overlay(self.right, dst, offset)
        self.draw_foreground(self.left, dst, offset)
        self.draw_foreground(self.right, dst, offset)
        self.draw_hud(dst)
        self.draw_intro_card(dst)
        if self.banner_time > 0 and self.intro_time <= 0:
            image = fonts["banner"].render(f"{self.left.name}  VS  {self.right.name}", True, ICE_WHITE)
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - 100))
        if self.round_over:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((3, 5, 12, 150))
            dst.blit(veil, (0, 0))
            image = fonts["winner"].render(self.winner, True, GOLD)
            dst.blit(image, (W / 2 - image.get_width() / 2, H / 2 - image.get_height() / 2))


def main():
    parser = argparse.ArgumentParser(description="Bounce Ball Fight Simulator tournament")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--seconds", type=float, default=0)
    parser.add_argument("--screenshot", type=str, default="")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--round-time", type=float, default=0,
                        help="Override tournament-settings.json round time")
    args = parser.parse_args()
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Bounce Ball Fight Simulator // Tournament")
    clock, fonts = pygame.time.Clock(), shared.make_fonts()
    tournament = Tournament(args.mute or args.headless, args.round_time or None)
    elapsed, running = 0, True
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
                    tournament.reset_match()
                elif event.key == pygame.K_m:
                    tournament.muted = not tournament.muted
                    for slot in (tournament.left, tournament.right):
                        slot.controller.sound.muted = tournament.muted
        tournament.update(dt)
        tournament.draw(screen, fonts)
        pygame.display.flip()
        if args.seconds and elapsed >= args.seconds:
            if args.screenshot:
                pygame.image.save(screen, args.screenshot)
            running = False
    pygame.quit()


if __name__ == "__main__":
    main()
