from __future__ import annotations

import math

import pygame


Vec2 = pygame.Vector2
INK = (7, 10, 22)
ICE = (90, 220, 255)
ICE_WHITE = (220, 250, 255)


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def safe_normal(vector, fallback=Vec2(1, 0)):
    return vector.normalize() if vector.length_squared() > .001 else Vec2(fallback)


def mix(a, b, t):
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def glow_circle(dst, pos, radius, color, strength=1.0):
    radius = max(2, int(radius))
    size = radius * 4
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    center = size // 2
    for i in range(5, 0, -1):
        r = int(radius * (0.45 + i * 0.32))
        alpha = int(10 * strength * (6 - i))
        pygame.draw.circle(surf, (*color, alpha), (center, center), r)
    pygame.draw.circle(surf, (*color, int(110 * strength)), (center, center), max(1, radius // 2))
    dst.blit(surf, (pos[0] - center, pos[1] - center), special_flags=pygame.BLEND_ADD)


def draw_arena(dst, arena, width, height, time, offset):
    dst.fill(INK)
    for i in range(12):
        rect = arena.inflate(-i * 16, -i * 10).move(offset)
        pygame.draw.rect(dst, (10 + i, 16 + i, 35 + i * 2), rect, border_radius=30)
    grid = pygame.Surface((width, height), pygame.SRCALPHA)
    ox = int((time * 18) % 48)
    for x in range(arena.left - 48 + ox, arena.right, 48):
        pygame.draw.line(grid, (75, 120, 190, 18), (x, arena.top), (x, arena.bottom))
    for y in range(arena.top, arena.bottom, 48):
        pygame.draw.line(grid, (75, 120, 190, 16), (arena.left, y), (arena.right, y))
    dst.blit(grid, offset)
    border = arena.move(offset)
    pygame.draw.rect(dst, (66, 110, 175), border, 3, border_radius=30)
    pygame.draw.rect(dst, (135, 205, 255), border.inflate(-10, -10), 1, border_radius=25)
    for corner in (border.topleft, border.topright, border.bottomleft, border.bottomright):
        glow_circle(dst, corner, 12, ICE, .6)


def draw_ball(dst, pos, radius, base, accent, facing, roll, squash, flash,
              frozen=0, burned=0, eye_color=(210, 225, 245), decorate=None):
    pos = Vec2(pos)
    shadow = pygame.Surface((int(radius * 3), int(radius)), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow, (0, 0, 0, 100), shadow.get_rect())
    dst.blit(shadow, (pos.x - radius * 1.5, pos.y + radius * .72))
    sx, sy = 1 + squash * .18, 1 - squash * .14
    r = int(radius * 1.35)
    ball = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    c = Vec2(r, r)
    for rr in range(int(radius), 0, -2):
        t = rr / radius
        col = mix(base, (255, 255, 255), clamp(1 - t, 0, 1) * .45)
        pygame.draw.circle(ball, col, c + Vec2(-radius * .16, -radius * .18) * (1 - t), rr)
    pygame.draw.circle(ball, (255, 255, 255, 95), c + Vec2(-radius * .31, -radius * .33), int(radius * .2))
    pygame.draw.arc(ball, (*accent, 180), pygame.Rect(r - radius, r - radius, radius * 2, radius * 2),
                    roll, roll + math.pi * 1.25, max(2, int(radius * .11)))
    eye_center = c + facing * radius * .38
    q = Vec2(-facing.y, facing.x)
    for side in (-1, 1):
        eye = eye_center + q * side * radius * .18
        pygame.draw.circle(ball, (10, 13, 22), eye, int(radius * .13))
        pygame.draw.circle(ball, eye_color, eye, int(radius * .075))
    if decorate:
        decorate(ball, c, radius, facing, roll)
    if flash > 0:
        pygame.draw.circle(ball, (255, 255, 255, 190), c, int(radius))
    if frozen > 0:
        pygame.draw.circle(ball, (*ICE, 80), c, int(radius + 6), 5)
        for angle in range(0, 360, 45):
            pygame.draw.line(ball, ICE_WHITE, c + Vec2(radius - 3, 0).rotate(angle),
                             c + Vec2(radius + 13, 0).rotate(angle), 3)
    if burned > 0:
        pygame.draw.circle(ball, (255, 75, 34, 70), c, int(radius + 6), 4)
    scaled = pygame.transform.smoothscale(ball, (int(ball.get_width() * sx), int(ball.get_height() * sy)))
    dst.blit(scaled, (pos.x - scaled.get_width() / 2, pos.y - scaled.get_height() / 2))


def draw_movement_trail(dst, fighter, color, offset, length=4):
    if fighter.vel.length_squared() <= .001:
        return
    for i in range(1, length + 1):
        p = fighter.pos - safe_normal(fighter.vel) * i * 13 + offset
        pygame.draw.circle(dst, (*color, 18), p, max(2, int(fighter.radius - i * 8)))


def draw_dummy_punch(dst, dummy, time, offset, width, height):
    remaining = dummy.punch_anim
    if remaining <= 0:
        return
    progress = clamp(1 - remaining / .42, 0, 1)
    fade = clamp(min(progress / .1, (1 - progress) / .25), 0, 1)
    travel = progress * progress * (3 - 2 * progress)
    direction = safe_normal(dummy.punch_dir)
    q = Vec2(-direction.y, direction.x)
    target = dummy.punch_target + offset
    palm = target + direction * lerp(-115, 115, travel)
    wrist, base = palm - direction * 34, palm - direction * 69
    alpha = int(220 * fade)
    layer = pygame.Surface((width, height), pygame.SRCALPHA)
    for i in range(4, 0, -1):
        trail = palm - direction * i * 17
        pygame.draw.line(layer, (155, 165, 180, int(alpha * .12 * (5 - i))),
                         trail - direction * 24 - q * 8, trail + q * 8, 2)
    arm = [base - q * 11, wrist - q * 15, palm - direction * 18 - q * 18,
           palm - direction * 18 + q * 18, wrist + q * 15, base + q * 11]
    pygame.draw.polygon(layer, (76, 82, 95, alpha), arm)
    pygame.draw.line(layer, (175, 184, 198, int(alpha * .55)), base - q * 6, wrist - q * 9, 3)
    glove = [palm - direction * 20 - q * 19, palm + direction * 16 - q * 23,
             palm + direction * 25 + q * 18, palm - direction * 17 + q * 23]
    pygame.draw.polygon(layer, (115, 122, 137, alpha), glove)
    pygame.draw.lines(layer, (205, 211, 220, int(alpha * .72)), True, glove, 2)
    for side in (-15, -5, 5, 15):
        knuckle = palm + direction * 24 + q * side
        pygame.draw.rect(layer, (82, 88, 101, alpha),
                         pygame.Rect(knuckle.x - 7, knuckle.y - 7, 14, 14), border_radius=3)
        pygame.draw.line(layer, (190, 197, 208, int(alpha * .65)),
                         knuckle - direction * 4 - q * 3, knuckle - direction * 4 + q * 3, 2)
    thumb = palm - direction + q * 23
    pygame.draw.rect(layer, (92, 99, 113, alpha), pygame.Rect(thumb.x - 8, thumb.y - 8, 16, 16), border_radius=4)
    for i in range(5):
        dust = wrist - direction * (12 + i * 13) + q * math.sin(time * 8 + i) * 10
        pygame.draw.circle(layer, (175, 180, 190, int(alpha * .22)), dust, 2 + i % 2)
    dst.blit(layer, (0, 0))


def make_fonts():
    return {
        "tiny": pygame.font.SysFont("consolas", 13, bold=True),
        "small": pygame.font.SysFont("consolas", 17, bold=True),
        "name": pygame.font.SysFont("consolas", 25, bold=True),
        "impact": pygame.font.SysFont("consolas", 23, bold=True),
        "banner": pygame.font.SysFont("consolas", 26, bold=True),
        "winner": pygame.font.SysFont("consolas", 58, bold=True),
    }
