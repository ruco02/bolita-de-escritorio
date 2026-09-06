"""
bolita v1- Bolita  sin gravedad, optimizada para fluidez
------------------------------------------------------------------------
Bolita negra que se estira y lanza con el mouse, rebota contra los bordes
de la pantalla SIN gravedad, se deforma al impactar y se ilumina con un
color aleatorio en cada rebote.

Como ejecutar:
    python bolita.py

Requisitos:
    - Python 3.8+ (tkinter viene incluido en la instalacion estandar de Windows)
    - Sin dependencias externas, no hace falta usar pip.

Controles:
    - Click izquierdo + arrastrar: estira la bolita como goma.
      Al soltar, sale disparada en direccion OPUESTA al estiramiento.
    - Click derecho sobre la bolita: la hace desaparecer y cierra el programa.

Notas de rendimiento:
    - El dibujo NO crea ni destruye figuras del canvas en cada frame.
      Se actualizan las coordenadas y el color de una unica figura via
      canvas.coords()/itemconfig(), que es mucho mas barato en tkinter
      que create_*/delete en cada frame.
    - La fisica usa delta time real (time.perf_counter), no asume una
      tasa de frames fija.
    - No hay gravedad: la bolita solo se mueve por la velocidad que
      recibe al ser lanzada, perdiendo energia por friccion y rebotes.

Autor: ronsito
"""

import math
import random
import sys
import time
import tkinter as tk

# ========================= CONFIGURACION =========================

BASE_RADIUS = 40.0
MAX_STRETCH = 180.0          # limite de estiramiento (mayor que en una version normal)
LAUNCH_POWER = 9.0           # multiplicador de fuerza al soltar
AIR_FRICTION = 0.9992        # perdida de energia leve por frame (independiente del rebote)
WALL_RESTITUTION = 0.84      # energia conservada en cada rebote (ajustado para ~4+ rebotes)
SLEEP_SPEED = 14.0           # por debajo de esta velocidad, se considera detenida
DEFORM_RECOVERY = 9.0        # velocidad de recuperacion de la forma tras un impacto
GLOW_DURATION = 0.45         # segundos que tarda el glow en apagarse tras un rebote
BG_TRANSPARENT_KEY = "#ff00fe"

BASE_COLOR = (10, 10, 10)    # negro (casi puro, evita artefactos con el color de fondo)
GLOW_COLORS = [
    (255, 80, 80), (255, 210, 80), (100, 220, 255),
    (140, 255, 140), (200, 120, 255), (255, 150, 220),
]

FRAME_MS = 8  # objetivo de reprogramacion del loop (~120hz de intento; el dt real manda)
MAX_DT = 0.05  # clamp para evitar saltos grandes si el sistema se traba


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def lerp(a, b, t):
    return a + (b - a) * t


def rgb_to_hex(rgb):
    r, g, b = rgb
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


# ========================= FISICA / ESTADO =========================

class BallPhysics:
    """Estado fisico puro de la bolita: posicion, velocidad, deformacion.

    No conoce nada de tkinter ni de dibujo -- eso vive en BallRenderer.
    """

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.radius = BASE_RADIUS

        self.scale_x = 1.0
        self.scale_y = 1.0

        self.dragging = False
        self.anchor_x = x
        self.anchor_y = y
        self.drag_x = x
        self.drag_y = y

        self.asleep = True  # arranca completamente quieta

        # Sistema de color / glow
        self.glow_timer = 0.0        # 0 = sin glow (negro), GLOW_DURATION = recien golpeada
        self.glow_color = GLOW_COLORS[0]

    # ----------------- Entrada del mouse (drag / lanzamiento) -----------------

    def hit_test(self, px, py):
        cx = self.drag_x if self.dragging else self.x
        cy = self.drag_y if self.dragging else self.y
        return math.hypot(px - cx, py - cy) <= self.radius * 1.3

    def start_drag(self, mx, my):
        self.dragging = True
        self.asleep = False
        self.anchor_x = self.x
        self.anchor_y = self.y
        self.drag_x = mx
        self.drag_y = my
        self.vx = 0.0
        self.vy = 0.0

    def update_drag(self, mx, my):
        dx, dy = mx - self.anchor_x, my - self.anchor_y
        dist = math.hypot(dx, dy)
        if dist > MAX_STRETCH:
            f = MAX_STRETCH / dist
            dx *= f
            dy *= f
        self.drag_x = self.anchor_x + dx
        self.drag_y = self.anchor_y + dy

    def release_drag(self):
        dx = self.drag_x - self.anchor_x
        dy = self.drag_y - self.anchor_y
        stretch = math.hypot(dx, dy)

        self.x = self.drag_x
        self.y = self.drag_y

        if stretch > 1.0:
            nx, ny = dx / stretch, dy / stretch
            power = (stretch / MAX_STRETCH) * LAUNCH_POWER * 220.0
            self.vx = -nx * power
            self.vy = -ny * power
            self._apply_directional_stretch(nx, ny, stretch / MAX_STRETCH)
        else:
            self.vx = 0.0
            self.vy = 0.0
            self.asleep = True

        self.dragging = False

    def _apply_directional_stretch(self, nx, ny, amount):
        s = clamp(amount, 0.0, 1.0) * 0.35
        if abs(nx) >= abs(ny):
            self.scale_x, self.scale_y = 1 + s, 1 - s * 0.6
        else:
            self.scale_y, self.scale_x = 1 + s, 1 - s * 0.6

    # ----------------------- Integracion fisica (sin gravedad) -----------------------

    def step(self, dt, width, height):
        if self.dragging or self.asleep:
            return

        # Sin gravedad: la velocidad solo decae por friccion.
        self.vx *= AIR_FRICTION
        self.vy *= AIR_FRICTION

        self.x += self.vx * dt
        self.y += self.vy * dt

        bounced_vertical = False
        bounced_horizontal = False
        impact_speed = 0.0

        if self.y - self.radius < 0:
            self.y = self.radius
            impact_speed = abs(self.vy)
            self.vy = -self.vy * WALL_RESTITUTION
            bounced_vertical = True
        elif self.y + self.radius > height:
            self.y = height - self.radius
            impact_speed = abs(self.vy)
            self.vy = -self.vy * WALL_RESTITUTION
            bounced_vertical = True

        if self.x - self.radius < 0:
            self.x = self.radius
            impact_speed = max(impact_speed, abs(self.vx))
            self.vx = -self.vx * WALL_RESTITUTION
            bounced_horizontal = True
        elif self.x + self.radius > width:
            self.x = width - self.radius
            impact_speed = max(impact_speed, abs(self.vx))
            self.vx = -self.vx * WALL_RESTITUTION
            bounced_horizontal = True

        if bounced_vertical or bounced_horizontal:
            self._on_bounce(vertical=bounced_vertical, speed=impact_speed)

        # Recuperacion gradual de la forma
        t = min(1.0, DEFORM_RECOVERY * dt)
        self.scale_x = lerp(self.scale_x, 1.0, t)
        self.scale_y = lerp(self.scale_y, 1.0, t)

        # Decaimiento del glow
        if self.glow_timer > 0.0:
            self.glow_timer = max(0.0, self.glow_timer - dt)

        speed = math.hypot(self.vx, self.vy)
        if speed < SLEEP_SPEED:
            self.vx = 0.0
            self.vy = 0.0
            self.asleep = True

    def _on_bounce(self, vertical, speed):
        amount = clamp(speed / 1100.0, 0.05, 0.45)
        if vertical:
            self.scale_y = 1 - amount
            self.scale_x = 1 + amount * 0.8
        else:
            self.scale_x = 1 - amount
            self.scale_y = 1 + amount * 0.8

        self.glow_color = random.choice(GLOW_COLORS)
        self.glow_timer = GLOW_DURATION

    def current_color_rgb(self):
        if self.glow_timer <= 0.0:
            return BASE_COLOR
        t = self.glow_timer / GLOW_DURATION  # 1.0 justo despues del choque -> 0.0 al apagarse
        return (
            lerp(BASE_COLOR[0], self.glow_color[0], t),
            lerp(BASE_COLOR[1], self.glow_color[1], t),
            lerp(BASE_COLOR[2], self.glow_color[2], t),
        )


# ========================= RENDERIZADO =========================

class BallRenderer:
    """Dibuja el estado de BallPhysics reutilizando una unica figura del canvas.

    Nunca llama a create_*/delete durante la animacion: solo coords()/itemconfig().
    """

    N_POINTS = 18  # cantidad de vertices del blob (fijo, se reutiliza el buffer)

    def __init__(self, canvas: tk.Canvas, ball: BallPhysics):
        self.canvas = canvas
        self.ball = ball
        # Precalculamos los angulos base del poligono una sola vez.
        self._angles = [2 * math.pi * i / self.N_POINTS for i in range(self.N_POINTS)]
        # Buffer reutilizable de coordenadas (se sobreescribe cada frame).
        self._coords = [0.0] * (self.N_POINTS * 2)

        initial_color = rgb_to_hex(ball.current_color_rgb())
        self.body_id = canvas.create_polygon(
            self._blob_points(ball.x, ball.y, ball.radius, ball.radius, 0.0),
            fill=initial_color, outline="", smooth=True
        )

    def _blob_points(self, cx, cy, rx, ry, angle):
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        coords = self._coords
        for i, t in enumerate(self._angles):
            ex = rx * math.cos(t)
            ey = ry * math.sin(t)
            px = cx + (ex * cos_a - ey * sin_a)
            py = cy + (ex * sin_a + ey * cos_a)
            coords[i * 2] = px
            coords[i * 2 + 1] = py
        return coords

    def draw(self):
        ball = self.ball
        if ball.dragging:
            ax, ay = ball.anchor_x, ball.anchor_y
            dx, dy = ball.drag_x - ax, ball.drag_y - ay
            dist = math.hypot(dx, dy)
            angle = math.atan2(dy, dx) if dist > 0 else 0.0
            cx, cy = (ax + ball.drag_x) / 2, (ay + ball.drag_y) / 2
            major = (dist / 2) + ball.radius * 0.9
            minor = max(ball.radius * 0.45, ball.radius - dist * 0.15)
            points = self._blob_points(cx, cy, major, minor, angle)
        else:
            rx = ball.radius * ball.scale_x
            ry = ball.radius * ball.scale_y
            points = self._blob_points(ball.x, ball.y, rx, ry, 0.0)

        self.canvas.coords(self.body_id, *points)
        self.canvas.itemconfig(self.body_id, fill=rgb_to_hex(ball.current_color_rgb()))


# ========================= APLICACION / VENTANA =========================

class JellyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        self.width = self.root.winfo_screenwidth()
        self.height = self.root.winfo_screenheight()
        self.root.geometry(f"{self.width}x{self.height}+0+0")

        try:
            self.root.attributes("-transparentcolor", BG_TRANSPARENT_KEY)
            bg = BG_TRANSPARENT_KEY
        except tk.TclError:
            bg = "#202020"

        self.canvas = tk.Canvas(
            self.root, width=self.width, height=self.height,
            bg=bg, highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        # La bolita arranca exactamente en el centro de la pantalla, quieta.
        self.ball = BallPhysics(self.width / 2, self.height / 2)
        self.renderer = BallRenderer(self.canvas, self.ball)

        self.canvas.bind("<ButtonPress-1>", self._on_left_down)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_up)
        self.canvas.bind("<ButtonPress-3>", self._on_right_click)

        self._last_time = time.perf_counter()
        self._loop()

    # ----------------------- Entrada -----------------------

    def _on_left_down(self, event):
        if self.ball.hit_test(event.x, event.y):
            self.ball.start_drag(event.x, event.y)

    def _on_left_drag(self, event):
        if self.ball.dragging:
            self.ball.update_drag(event.x, event.y)

    def _on_left_up(self, event):
        if self.ball.dragging:
            self.ball.release_drag()

    def _on_right_click(self, event):
        if self.ball.hit_test(event.x, event.y):
            self.root.destroy()
            sys.exit(0)

    # ----------------------- Loop principal -----------------------

    def _loop(self):
        now = time.perf_counter()
        dt = min(MAX_DT, now - self._last_time)
        self._last_time = now

        self.ball.step(dt, self.width, self.height)
        self.renderer.draw()

        self.root.after(FRAME_MS, self._loop)

    def run(self):
        self.root.mainloop()


def main():
    app = JellyApp()
    app.run()


if __name__ == "__main__":
    main()
