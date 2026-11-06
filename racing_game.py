from __future__ import annotations

import asyncio
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import pygame


pygame.init()

WIDTH, HEIGHT = 1240, 800
MIN_WIDTH, MIN_HEIGHT = 940, 650
FPS = 60
FINISH_DISTANCE = 3.0
STAGES = (
    ("Downtown Dash", 1.0, 1.15, 0.25),
    ("Warehouse District", 1.28, 1.0, 0.28),
    ("Uptown Express", 0.82, 0.88, 0.32),
    ("Neon Boulevard", 1.48, 0.76, 0.36),
)
LANE_COUNT = 3
LANE_SPACING = 1 / LANE_COUNT
MAX_SPEED = 220.0
ACCELERATION = 30.0
BRAKING = 96.0
PLAYER_DEPTH = 0.92
ROAD_COLOR = (57, 61, 58)
PAPER = (241, 238, 229)
MUTED = (156, 155, 141)
LIME = (211, 243, 107)
ORANGE = (240, 117, 74)
BACKGROUND = (23, 26, 22)
PANEL = (32, 35, 30)
LINE = (57, 60, 51)
FONT_DISPLAY = "Bahnschrift"
FONT_BODY = "Segoe UI"
FONT_MONO = "Consolas"
RECORD_PATH = Path.home() / ".apex_circuit_record.json"


@dataclass
class TrafficCar:
    lane: int
    depth: float
    color: tuple[int, int, int]
    passed: bool = False


class ApexCircuit:
    def __init__(self) -> None:
        pygame.display.set_caption("Apex Circuit | Arcade Racing")
        self.screen = pygame.display.set_mode(
            (WIDTH, HEIGHT), pygame.RESIZABLE | pygame.DOUBLEBUF
        )
        self.clock = pygame.time.Clock()
        self.skyline = self.build_skyline()
        self.city_blocks = self.build_city_blocks()
        self.fonts = {
            "display": pygame.font.SysFont(FONT_DISPLAY, 28, bold=True),
            "title": pygame.font.SysFont(FONT_DISPLAY, 56, bold=True),
            "speed": pygame.font.SysFont(FONT_DISPLAY, 55, bold=True),
            "body": pygame.font.SysFont(FONT_BODY, 14),
            "small": pygame.font.SysFont(FONT_BODY, 12),
            "mono": pygame.font.SysFont(FONT_MONO, 11),
            "tiny": pygame.font.SysFont(FONT_MONO, 9),
        }
        self.running = True
        self.keys = pygame.key.get_pressed()
        self.pointer_controls: dict[tuple[str, int], str] = {}
        self.best_distance = self.load_record()
        self.reset_race()
        self.state = "ready"
        self.message = "Find your racing line."
        self.message_detail = f"Race {len(STAGES)} stages. Dodge traffic and reach each 3 km finish."

    @staticmethod
    def load_record() -> float:
        try:
            record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
            return max(0.0, float(record.get("best_km", 0)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0.0

    def save_record(self, force: bool = False) -> None:
        run_distance = self.total_distance + self.distance
        if run_distance <= self.best_distance:
            return
        if not force and run_distance - self.best_distance < 0.01:
            return
        self.best_distance = run_distance
        try:
            RECORD_PATH.write_text(
                json.dumps({"best_km": round(self.best_distance, 3)}),
                encoding="utf-8",
            )
        except OSError:
            pass

    def reset_race(self) -> None:
        self.stage_index = 0
        self.total_distance = 0.0
        self.distance = 0.0
        self.speed = 0.0
        self.score = 0
        self.passes = 0
        self.crashes = 0
        self.steer_offset = 0.0
        self.steering_velocity = 0.0
        self.road_scroll = 0.0
        self.traffic_timer = 0.8
        self.crash_flash = 0.0
        self.traffic: list[TrafficCar] = []

    def start_race(self) -> None:
        self.reset_race()
        self.pointer_controls.clear()
        self.speed = 92.0
        self.state = "racing"
        self.message = ""
        self.message_detail = ""

    @staticmethod
    def build_skyline() -> list[tuple[float, float, float, tuple[int, int, int]]]:
        generator = random.Random(31)
        skyline = []
        position = -0.04
        while position < 1.04:
            width = generator.uniform(0.035, 0.085)
            height = generator.uniform(0.045, 0.17)
            shade = generator.randint(47, 68)
            skyline.append((position, width, height, (shade, shade + 5, shade + 8)))
            position += width * generator.uniform(0.72, 0.96)
        return skyline

    @staticmethod
    def build_city_blocks() -> list[tuple[float, int, float, float, tuple[int, int, int], tuple[tuple[bool, ...], ...]]]:
        generator = random.Random(82)
        blocks = []
        for side in (-1, 1):
            for index in range(9):
                depth = 0.12 + index * 0.105
                width = generator.uniform(0.045, 0.105)
                height = generator.uniform(0.1, 0.34)
                shade = generator.randint(58, 83)
                color = (shade, shade + 3, shade + 5)
                windows = tuple(
                    tuple(generator.random() > 0.32 for _ in range(generator.randint(3, 5)))
                    for _ in range(7)
                )
                blocks.append((depth, side, width, height, color, windows))
        return blocks

    def layout(self) -> tuple[pygame.Rect, pygame.Rect]:
        width, height = self.screen.get_size()
        margin = max(24, int(width * 0.045))
        top = max(160, int(height * 0.24))
        bottom = max(52, int(height * 0.095))
        gap = 30
        side_width = max(205, min(260, int(width * 0.22)))
        scene_width = width - margin * 2 - gap - side_width
        scene = pygame.Rect(margin, top, scene_width, height - top - bottom)
        sidebar = pygame.Rect(scene.right + gap, top, side_width, scene.height)
        return scene, sidebar

    @staticmethod
    def horizon_y(scene: pygame.Rect) -> float:
        return scene.top + scene.height * 0.12

    @classmethod
    def project_depth(cls, scene: pygame.Rect, depth: float) -> float:
        horizon = cls.horizon_y(scene)
        depth = max(0.0, min(depth, 1.15))
        return horizon + depth**1.8 * (scene.bottom - horizon)

    @classmethod
    def road_width_at(cls, scene: pygame.Rect, y: float) -> float:
        horizon = cls.horizon_y(scene)
        depth = max(0.0, min(1.0, (y - horizon) / max(scene.bottom - horizon, 1))) ** (1 / 1.8)
        return scene.width * 0.84 * (0.12 + depth * 0.88)

    def road_center(self, scene: pygame.Rect, y: float, distance: float) -> float:
        horizon = self.horizon_y(scene)
        depth = max(0.0, min(1.0, (y - horizon) / max(scene.bottom - horizon, 1))) ** (1 / 1.8)
        progress = distance / FINISH_DISTANCE
        lookahead = progress + (1 - depth) * 0.2
        return scene.centerx + (
            self.route_offset(lookahead, self.stage_index)
            - self.route_offset(progress, self.stage_index)
        ) * scene.width * 0.75

    @staticmethod
    def route_offset(progress: float, stage_index: int = 0) -> float:
        _, curve_strength, curve_frequency, _ = STAGES[stage_index]
        phase = progress * math.tau * curve_frequency
        return (
            math.sin(phase) * 0.16
            + math.sin(phase * 2.1 + 0.7) * 0.055
        ) * curve_strength

    def scene_metrics(self, scene: pygame.Rect) -> tuple[float, float, float]:
        road_width = scene.width * 0.84
        lane_width = road_width / LANE_COUNT
        car_width = max(44.0, min(82.0, lane_width * 0.38))
        return road_width, lane_width, car_width

    def car_width_at(self, scene: pygame.Rect, depth: float) -> int:
        _, lane_width, _ = self.scene_metrics(scene)
        scale = 0.18 + max(0.0, min(depth, 1.0)) * 0.82
        return max(12, int(lane_width * 0.38 * scale))

    def touch_button_rects(self, scene: pygame.Rect) -> dict[str, pygame.Rect]:
        size = max(42, min(58, int(scene.width * 0.075)))
        y = scene.bottom - size - 12
        return {
            "left": pygame.Rect(scene.left + 14, y, size, size),
            "right": pygame.Rect(scene.left + 14 + size + 8, y, size, size),
            "brake": pygame.Rect(scene.right - size - 14, y, size, size),
        }

    def sidebar_action_rect(self) -> pygame.Rect:
        _, sidebar = self.layout()
        return pygame.Rect(sidebar.left, sidebar.bottom - 47, sidebar.width, 38)

    def overlay_action_rect(self, scene: pygame.Rect) -> pygame.Rect:
        button = pygame.Rect(0, 0, 160, 40)
        button.center = (scene.centerx, scene.centery + 48)
        return button

    def control_at_position(self, position: tuple[int, int]) -> str | None:
        scene, _ = self.layout()
        if self.state != "racing" and self.state in (
            "ready", "paused", "stage_clear", "finished", "wrecked"
        ):
            if self.overlay_action_rect(scene).collidepoint(position):
                return "action"
        if self.sidebar_action_rect().collidepoint(position):
            return "action"
        if self.state == "racing":
            for name, rect in self.touch_button_rects(scene).items():
                if rect.collidepoint(position):
                    return name
        return None

    def set_pointer_control(
        self,
        pointer: tuple[str, int],
        position: tuple[int, int] | None,
    ) -> None:
        previous = self.pointer_controls.pop(pointer, None)
        if position is None:
            return
        control = self.control_at_position(position)
        if control in ("left", "right", "brake"):
            self.pointer_controls[pointer] = control
        elif previous == "action" and control == "action":
            return

    def activate_action(self) -> None:
        if self.state in ("racing", "paused"):
            self.handle_keydown(pygame.K_SPACE)
        elif self.state == "stage_clear":
            self.handle_keydown(pygame.K_SPACE)
        else:
            self.start_race()

    def handle_pointer_down(self, pointer: tuple[str, int], position: tuple[int, int]) -> None:
        control = self.control_at_position(position)
        if control == "action":
            self.activate_action()
            return
        if control in ("left", "right", "brake"):
            self.pointer_controls[pointer] = control

    def handle_pointer_motion(self, pointer: tuple[str, int], position: tuple[int, int]) -> None:
        if pointer in self.pointer_controls:
            self.set_pointer_control(pointer, position)

    def handle_pointer_up(self, pointer: tuple[str, int]) -> None:
        self.pointer_controls.pop(pointer, None)

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.VIDEORESIZE:
                width = max(MIN_WIDTH, event.w)
                height = max(MIN_HEIGHT, event.h)
                self.screen = pygame.display.set_mode(
                    (width, height), pygame.RESIZABLE | pygame.DOUBLEBUF
                )
            elif event.type == pygame.KEYDOWN:
                self.handle_keydown(event.key)
            elif event.type == pygame.FINGERDOWN:
                width, height = self.screen.get_size()
                position = (int(event.x * width), int(event.y * height))
                self.handle_pointer_down(("finger", event.finger_id), position)
            elif event.type == pygame.FINGERMOTION:
                width, height = self.screen.get_size()
                position = (int(event.x * width), int(event.y * height))
                self.handle_pointer_motion(("finger", event.finger_id), position)
            elif event.type == pygame.FINGERUP:
                self.handle_pointer_up(("finger", event.finger_id))
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if not getattr(event, "touch", False):
                    self.handle_pointer_down(("mouse", 0), event.pos)
            elif event.type == pygame.MOUSEMOTION:
                if event.buttons and event.buttons[0] and not getattr(event, "touch", False):
                    self.handle_pointer_motion(("mouse", 0), event.pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if not getattr(event, "touch", False):
                    self.handle_pointer_up(("mouse", 0))

    def handle_keydown(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            if self.state == "racing":
                self.state = "paused"
                self.message = "Take a breather."
                self.message_detail = "Race paused. Press SPACE to get back on the road."
            else:
                self.running = False
        elif key in (pygame.K_SPACE, pygame.K_p):
            if self.state == "racing":
                self.state = "paused"
                self.message = "Take a breather."
                self.message_detail = "Race paused. Press SPACE to get back on the road."
            elif self.state == "paused":
                self.state = "racing"
                self.message = ""
            elif self.state == "stage_clear":
                self.state = "racing"
                self.speed = max(92.0, self.speed)
                self.message = ""
            else:
                self.start_race()
        elif key == pygame.K_r:
            self.start_race()

    def update(self, dt: float) -> None:
        if self.state != "racing":
            return

        keys = pygame.key.get_pressed()
        if keys[pygame.K_DOWN] or keys[pygame.K_s] or "brake" in self.pointer_controls.values():
            self.speed = max(45.0, self.speed - BRAKING * dt)
        else:
            self.speed = min(MAX_SPEED, self.speed + ACCELERATION * dt)

        steer_right = keys[pygame.K_RIGHT] or keys[pygame.K_d] or "right" in self.pointer_controls.values()
        steer_left = keys[pygame.K_LEFT] or keys[pygame.K_a] or "left" in self.pointer_controls.values()
        steer = float(steer_right) - float(steer_left)
        self.steering_velocity += steer * 1050 * dt
        if not steer:
            self.steering_velocity *= max(0.0, 1 - 5.2 * dt)
        self.steering_velocity = max(-440.0, min(440.0, self.steering_velocity))
        self.steer_offset = max(
            -0.42,
            min(0.42, self.steer_offset + self.steering_velocity * dt / 420),
        )

        self.distance += self.speed * dt / 3600
        self.score = int((self.total_distance + self.distance) * 1000) + self.passes * 250
        self.road_scroll += self.speed * 2.15 * dt
        self.crash_flash = max(0.0, self.crash_flash - dt)
        self.traffic_timer -= dt
        if self.traffic_timer <= 0:
            colors = [
                (231, 212, 154),
                (91, 192, 163),
                (117, 132, 193),
                (220, 104, 72),
                (210, 215, 207),
            ]
            self.traffic.append(
                TrafficCar(random.randrange(LANE_COUNT), -0.08, random.choice(colors))
            )
            _, _, traffic_interval, _ = STAGES[self.stage_index]
            self.traffic_timer = max(0.55, traffic_interval - self.speed / 700) + random.random() * 0.35

        scene, _ = self.layout()
        player_y = self.project_depth(scene, PLAYER_DEPTH)
        player_center = self.road_center(scene, player_y, self.distance)
        player_width = self.car_width_at(scene, PLAYER_DEPTH)
        player_x = player_center + self.steer_offset * self.scene_metrics(scene)[0]
        for car in self.traffic:
            _, _, _, traffic_flow = STAGES[self.stage_index]
            car.depth += (traffic_flow + self.speed / 500) * dt
            car_y = self.project_depth(scene, car.depth)
            lane_width = self.road_width_at(scene, car_y) / LANE_COUNT
            car_x = self.road_center(scene, car_y, self.distance) + (car.lane - 1) * lane_width
            horizontal_overlap = abs(car_x - player_x) < (player_width + self.car_width_at(scene, car.depth)) * 0.42
            if self.crash_flash <= 0 and abs(car.depth - PLAYER_DEPTH) < 0.055 and horizontal_overlap:
                self.handle_crash()
                break
            if car.depth > PLAYER_DEPTH and not car.passed:
                car.passed = True
                self.passes += 1
                self.score += 250

        self.traffic = [car for car in self.traffic if car.depth < 1.13]
        self.save_record()
        if self.distance >= FINISH_DISTANCE:
            self.complete_stage()

    def complete_stage(self) -> None:
        self.total_distance += self.distance
        self.distance = 0.0
        self.traffic.clear()
        self.traffic_timer = 0.8

        if self.stage_index == len(STAGES) - 1:
            self.state = "finished"
            self.message = "Championship complete."
            self.message_detail = f"{self.total_distance:.2f} km covered. {self.passes} clean passes."
            self.save_record(force=True)
            return

        completed_stage = STAGES[self.stage_index][0]
        self.save_record(force=True)
        self.stage_index += 1
        next_stage = STAGES[self.stage_index][0]
        self.state = "stage_clear"
        self.message = f"Stage {self.stage_index} complete."
        self.message_detail = f"{completed_stage} cleared. Next up: {next_stage}. Tap NEXT STAGE or press SPACE."

    def handle_crash(self) -> None:
        self.crashes += 1
        self.crash_flash = 1.5
        self.speed = max(66.0, self.speed * 0.48)
        scene, _ = self.layout()
        self.traffic = [car for car in self.traffic if abs(car.depth - PLAYER_DEPTH) > 0.1]
        if self.crashes >= 3:
            self.state = "wrecked"
            self.message = "One more for the road?"
            self.message_detail = f"{self.distance:.2f} km covered. {self.passes} clean passes. Press R to race again."

    def draw_text(
        self,
        text: str,
        x: int,
        y: int,
        color: tuple[int, int, int],
        font: pygame.font.Font | None = None,
        anchor: str = "topleft",
    ) -> pygame.Rect:
        chosen_font = font or self.fonts["body"]
        surface = chosen_font.render(text, True, color)
        rect = surface.get_rect(**{anchor: (x, y)})
        self.screen.blit(surface, rect)
        return rect

    def draw_background(self, scene: pygame.Rect) -> None:
        horizon = int(self.horizon_y(scene))
        if self.stage_index == len(STAGES) - 1:
            sky_top = (19, 28, 48)
            sky_bottom = (87, 77, 76)
        else:
            sky_top = (46, 65, 81)
            sky_bottom = (166, 132, 103)
        gradient_steps = max(1, horizon - scene.top)
        for offset in range(gradient_steps):
            blend = offset / gradient_steps
            color = tuple(int(start + (end - start) * blend) for start, end in zip(sky_top, sky_bottom))
            pygame.draw.line(self.screen, color, (scene.left, scene.top + offset), (scene.right, scene.top + offset))

        ground_color = (49, 56, 61) if self.stage_index == len(STAGES) - 1 else (85, 91, 87)
        pygame.draw.rect(self.screen, ground_color, (scene.left, horizon, scene.width, scene.bottom - horizon))

        skyline_base = horizon + 20
        for position, width, height, color in self.skyline:
            building = pygame.Rect(
                int(scene.left + position * scene.width),
                int(skyline_base - height * scene.height),
                max(4, int(width * scene.width)),
                int(height * scene.height),
            )
            pygame.draw.rect(self.screen, color, building)
            roof = pygame.Rect(building.centerx - max(1, building.width // 12), building.top - 4, max(2, building.width // 6), 4)
            pygame.draw.rect(self.screen, color, roof)
            window_color = (202, 175, 117) if self.stage_index == len(STAGES) - 1 else (166, 167, 146)
            for window_x in range(building.left + 4, building.right - 2, 8):
                for window_y in range(building.top + 6, building.bottom - 3, 9):
                    if (window_x + window_y) % 3:
                        pygame.draw.rect(self.screen, window_color, (window_x, window_y, 2, 3))

        self.draw_city_blocks(scene)

    def draw_city_blocks(self, scene: pygame.Rect) -> None:
        for depth, side, width_factor, height_factor, color, windows in self.city_blocks:
            y = self.project_depth(scene, depth)
            center = self.road_center(scene, y, self.distance)
            road_half = self.road_width_at(scene, y) / 2
            scale = 0.2 + depth * 0.8
            building_width = max(7, int(scene.width * width_factor * scale))
            building_height = max(12, int(scene.height * height_factor * scale))
            gap = scene.width * (0.08 + depth * 0.08)
            if side < 0:
                building_x = int(center - road_half - gap - building_width)
            else:
                building_x = int(center + road_half + gap)
            building_bottom = int(y + depth * 8)
            building = pygame.Rect(
                building_x,
                building_bottom - building_height,
                building_width,
                building_height,
            )
            face_color = tuple(min(255, channel + 8) for channel in color)
            side_color = tuple(max(0, channel - 16) for channel in color)
            pygame.draw.rect(self.screen, face_color, building)
            side_width = max(2, building_width // 8)
            face_edge = building.right - side_width if side < 0 else building.left
            pygame.draw.rect(self.screen, side_color, (face_edge, building.top, side_width, building.height))
            pygame.draw.line(self.screen, (112, 117, 115), building.topleft, (building.right, building.top), 1)

            inset_x = max(3, building_width // 7)
            inset_y = max(5, building_height // 12)
            window_gap_x = max(3, building_width // (len(windows[0]) + 3))
            window_gap_y = max(4, building_height // (len(windows) + 2))
            window_w = max(2, min(5, building_width // 13))
            window_h = max(2, min(7, building_height // 22))
            for row, row_windows in enumerate(windows):
                for column, lit in enumerate(row_windows):
                    if not lit:
                        continue
                    window_x = building.left + inset_x + column * window_gap_x
                    window_y = building.top + inset_y + row * window_gap_y
                    if window_x + window_w < building.right - 2 and window_y + window_h < building.bottom - 2:
                        light = (219, 180, 112) if (row + column) % 3 else (150, 177, 182)
                        pygame.draw.rect(self.screen, light, (window_x, window_y, window_w, window_h))

        for depth in (0.22, 0.43, 0.66, 0.89):
            y = self.project_depth(scene, depth)
            center = self.road_center(scene, y, self.distance)
            road_half = self.road_width_at(scene, y) / 2
            pole_height = max(7, int(scene.height * (0.025 + depth * 0.045)))
            pole_width = max(1, int(depth * 2))
            offset = road_half + scene.width * (0.06 + depth * 0.025)
            for side in (-1, 1):
                pole_x = int(center + side * offset)
                pygame.draw.line(self.screen, (53, 58, 58), (pole_x, int(y)), (pole_x, int(y - pole_height)), pole_width)
                arm_length = max(4, int(depth * 12))
                arm_end = pole_x - arm_length if side < 0 else pole_x + arm_length
                pygame.draw.line(self.screen, (53, 58, 58), (pole_x, int(y - pole_height)), (arm_end, int(y - pole_height)), pole_width)
                lamp = pygame.Rect(arm_end - 2, int(y - pole_height) - 2, max(4, int(depth * 7)), max(2, int(depth * 3)))
                pygame.draw.rect(self.screen, (235, 207, 142), lamp, border_radius=2)

    def draw_road(self, scene: pygame.Rect) -> None:
        horizon = self.horizon_y(scene)
        points_left = []
        points_right = []
        shoulder_left = []
        shoulder_right = []
        for y in range(int(horizon), scene.bottom + 5, 5):
            center = self.road_center(scene, y, self.distance)
            road_width = self.road_width_at(scene, y)
            half_width = road_width / 2
            shoulder_width = road_width * 0.15
            points_left.append((center - half_width, y))
            points_right.append((center + half_width, y))
            shoulder_left.append((center - half_width - shoulder_width, y))
            shoulder_right.append((center + half_width + shoulder_width, y))

        pygame.draw.polygon(
            self.screen,
            (100, 105, 105),
            shoulder_left + points_left[::-1],
        )
        pygame.draw.polygon(
            self.screen,
            (100, 105, 105),
            points_right + shoulder_right[::-1],
        )

        rail_depths = [index / 32 for index in range(1, 33)]
        for side in (-1, 1):
            rail_points = []
            post_points = []
            for depth in rail_depths:
                rail_y = self.project_depth(scene, depth)
                center = self.road_center(scene, rail_y, self.distance)
                rail_offset = self.road_width_at(scene, rail_y) * 0.66
                rail_x = center + side * rail_offset
                rail_points.append((rail_x, rail_y - max(1, depth * 3)))
                if int(depth * 32) % 3 == 0:
                    post_points.append((rail_x, rail_y))
            for rail_y_offset, rail_color, rail_width in ((0, (51, 56, 55), 5), (-3, (175, 177, 166), 2)):
                shifted_points = [(x, y + rail_y_offset) for x, y in rail_points]
                pygame.draw.lines(self.screen, rail_color, False, shifted_points, rail_width)
            for x, y in post_points:
                post_height = max(2, int((y - horizon) / max(scene.height - horizon, 1) * 13))
                pygame.draw.line(self.screen, (79, 84, 79), (x, y), (x, y - post_height), max(1, post_height // 4))

        pygame.draw.polygon(self.screen, ROAD_COLOR, points_left + points_right[::-1])

        for index in range(115):
            depth = ((index * 0.618033 + self.road_scroll * 0.002) % 0.97) + 0.02
            grain_y = self.project_depth(scene, depth)
            half_width = self.road_width_at(scene, grain_y) / 2
            lateral = math.sin(index * 17.73) * 0.82
            grain_x = self.road_center(scene, grain_y, self.distance) + lateral * half_width
            grain_color = (67, 70, 67) if index % 2 else (48, 51, 49)
            pygame.draw.circle(
                self.screen,
                grain_color,
                (int(grain_x), int(grain_y)),
                max(1, int(depth * 1.3)),
            )

        stripe_phase = (self.road_scroll * 0.0018) % 0.17
        depth = stripe_phase
        stripe_index = 0
        while depth < 1.0:
            end_depth = min(depth + 0.08, 1.0)
            top_y = self.project_depth(scene, depth)
            bottom_y = self.project_depth(scene, end_depth)
            color = (62, 66, 63) if stripe_index % 2 else (54, 58, 55)
            strip_points = []
            for y in (top_y, bottom_y):
                center = self.road_center(scene, y, self.distance)
                half_width = self.road_width_at(scene, y) / 2
                strip_points.extend(((center - half_width, y), (center + half_width, y)))
            pygame.draw.polygon(self.screen, color, [strip_points[0], strip_points[1], strip_points[3], strip_points[2]])
            curb_color = PAPER if stripe_index % 2 else ORANGE
            for side in (-1, 1):
                for y in (top_y, bottom_y):
                    center = self.road_center(scene, y, self.distance)
                    half_width = self.road_width_at(scene, y) / 2
                    edge_x = center + side * half_width
                    curb_width = max(2, int(self.road_width_at(scene, y) * 0.012))
                    curb_points = [
                        (edge_x, y),
                        (edge_x + side * curb_width, y),
                    ]
                    if y == top_y:
                        top_curb = curb_points
                    else:
                        bottom_curb = curb_points
                pygame.draw.polygon(self.screen, curb_color, [top_curb[0], top_curb[1], bottom_curb[1], bottom_curb[0]])
            depth += 0.08
            stripe_index += 1

        dash_phase = (self.road_scroll * 0.0024) % 0.15
        depth = dash_phase
        while depth < 1.0:
            end_depth = min(depth + 0.055, 1.0)
            top_y = self.project_depth(scene, depth)
            bottom_y = self.project_depth(scene, end_depth)
            dash_color = (198, 194, 174)
            for lane in (1, 2):
                top_center = self.road_center(scene, top_y, self.distance)
                bottom_center = self.road_center(scene, bottom_y, self.distance)
                top_x = top_center - self.road_width_at(scene, top_y) / 2 + self.road_width_at(scene, top_y) * lane / LANE_COUNT
                bottom_x = bottom_center - self.road_width_at(scene, bottom_y) / 2 + self.road_width_at(scene, bottom_y) * lane / LANE_COUNT
                mark_width = max(1, int(1 + depth * 3))
                pygame.draw.polygon(
                    self.screen,
                    dash_color,
                    [
                        (top_x - mark_width, top_y),
                        (top_x + mark_width, top_y),
                        (bottom_x + mark_width * 2, bottom_y),
                        (bottom_x - mark_width * 2, bottom_y),
                    ],
                )
            depth += 0.15

    def draw_car(
        self,
        x: float,
        y: float,
        color: tuple[int, int, int],
        width: int,
        is_player: bool = False,
    ) -> None:
        width = int(width)
        height = max(13, int(width * 0.78))
        rect = pygame.Rect(0, 0, width, height)
        rect.center = (round(x), round(y))
        shadow = pygame.Rect(rect.left + width // 12, rect.bottom - height // 5, width * 5 // 6, height // 3)
        pygame.draw.ellipse(self.screen, (20, 23, 20), shadow.move(3, 5))

        tire_width = max(3, width // 10)
        tire_height = max(7, height // 3)
        for side in (-1, 1):
            tire_x = rect.left if side < 0 else rect.right - tire_width
            pygame.draw.rect(
                self.screen,
                (25, 27, 25),
                (tire_x, rect.top + height // 3, tire_width, tire_height),
                border_radius=max(2, tire_width // 2),
            )

        body = [
            (rect.left + width // 3, rect.top),
            (rect.left + width * 2 // 3, rect.top),
            (rect.left + width * 5 // 6, rect.top + height // 4),
            (rect.right, rect.top + height * 3 // 4),
            (rect.right - width // 10, rect.bottom),
            (rect.left + width // 10, rect.bottom),
            (rect.left, rect.top + height * 3 // 4),
            (rect.left + width // 6, rect.top + height // 4),
        ]
        pygame.draw.polygon(self.screen, color, body)
        highlight = tuple(min(255, channel + 28) for channel in color)
        pygame.draw.polygon(
            self.screen,
            highlight,
            [
                (rect.left + width // 3, rect.top + 2),
                (rect.left + width * 2 // 3, rect.top + 2),
                (rect.left + width * 4 // 5, rect.top + height // 4),
                (rect.left + width // 5, rect.top + height // 4),
            ],
        )
        pygame.draw.polygon(
            self.screen,
            (31, 47, 42) if is_player else (36, 46, 48),
            [
                (rect.left + width // 4, rect.top + height // 4),
                (rect.left + width * 3 // 4, rect.top + height // 4),
                (rect.left + width * 5 // 6, rect.top + height // 2),
                (rect.left + width // 6, rect.top + height // 2),
            ],
        )
        pygame.draw.rect(
            self.screen,
            tuple(max(0, channel - 33) for channel in color),
            (rect.left + width // 5, rect.top + height * 3 // 5, width * 3 // 5, max(3, height // 9)),
            border_radius=max(2, width // 14),
        )
        lamp_width = max(3, width // 5)
        lamp_y = rect.bottom - max(4, height // 5)
        for side in (-1, 1):
            lamp_x = rect.left + width // 8 if side < 0 else rect.right - width // 8 - lamp_width
            pygame.draw.rect(self.screen, (247, 83, 62), (lamp_x, lamp_y, lamp_width, max(3, height // 9)), border_radius=2)
        pygame.draw.line(
            self.screen,
            (33, 36, 33),
            (rect.left + width // 3, lamp_y + height // 12),
            (rect.left + width * 2 // 3, lamp_y + height // 12),
            max(1, width // 18),
        )

    def draw_scene(self, scene: pygame.Rect) -> None:
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(scene)
        self.draw_background(scene)
        self.draw_road(scene)
        for car in sorted(self.traffic, key=lambda traffic_car: traffic_car.depth):
            if car.depth <= 0 or car.depth >= 1.05:
                continue
            y = self.project_depth(scene, car.depth)
            lane_width = self.road_width_at(scene, y) / LANE_COUNT
            x = self.road_center(scene, y, self.distance) + (car.lane - 1) * lane_width
            self.draw_car(x, y, car.color, self.car_width_at(scene, car.depth))

        player_y = self.project_depth(scene, PLAYER_DEPTH)
        _, _, player_width = self.scene_metrics(scene)
        player_x = self.road_center(scene, player_y, self.distance) + self.steer_offset * (
            self.scene_metrics(scene)[0]
        )
        if self.crash_flash <= 0 or int(self.crash_flash * 15) % 2 != 0:
            self.draw_car(player_x, player_y, ORANGE, player_width, is_player=True)
        self.screen.set_clip(previous_clip)

    def draw_header(self, width: int) -> None:
        margin = max(24, int(width * 0.045))
        pygame.draw.line(self.screen, LINE, (margin, 72), (width - margin, 72), 1)
        pygame.draw.polygon(
            self.screen,
            LIME,
            [(margin + 15, 23), (margin + 31, 54), (margin + 21, 54), (margin + 15, 42), (margin + 9, 54), (margin - 1, 54)],
        )
        self.draw_text("APEX", margin + 39, 21, PAPER, self.fonts["display"])
        self.draw_text("CIRCUIT", margin + 106, 28, MUTED, self.fonts["mono"])
        self.draw_text("ARCADE SERIES   /   EVENT 01", width // 2, 35, MUTED, self.fonts["tiny"], "midtop")
        self.draw_text("OPEN ROAD  |  01 / 01", width - margin, 35, MUTED, self.fonts["tiny"], "topright")

    def draw_title(self, scene: pygame.Rect) -> None:
        x = scene.left
        stage_name = STAGES[self.stage_index][0].upper()
        self.draw_text(
            f"STAGE {self.stage_index + 1:02d} / {len(STAGES):02d}   {stage_name}",
            x,
            scene.top - 98,
            LIME,
            self.fonts["tiny"],
        )
        self.draw_text("ONE ROAD.", x, scene.top - 77, PAPER, self.fonts["title"])
        self.draw_text("ALL YOURS.", x, scene.top - 27, LIME, self.fonts["title"])
        self.draw_text("RACE DISTANCE", scene.right, scene.top - 60, MUTED, self.fonts["tiny"], "topright")
        self.draw_text("3.00 KM", scene.right, scene.top - 39, PAPER, self.fonts["display"], "topright")

    def draw_sidebar(self, sidebar: pygame.Rect) -> None:
        x, y = sidebar.left, sidebar.top
        width = sidebar.width
        pygame.draw.line(self.screen, LINE, (x, y + 30), (x + width, y + 30), 1)
        self.draw_text("LIVE TELEMETRY", x, y + 8, MUTED, self.fonts["tiny"])
        status = "LIVE" if self.state == "racing" else self.state.upper()
        status_color = LIME if self.state == "racing" else MUTED
        pygame.draw.circle(self.screen, status_color, (x + width - 36, y + 13), 3)
        self.draw_text(status, x + width, y + 8, status_color, self.fonts["tiny"], "topright")

        section_y = y + 49
        self.draw_text("CURRENT SPEED", x, section_y, MUTED, self.fonts["tiny"])
        self.draw_text("KM/H", x + width, section_y, MUTED, self.fonts["tiny"], "topright")
        self.draw_text(f"{int(self.speed):03}", x, section_y + 19, PAPER, self.fonts["speed"])
        self.draw_text("km/h", x + 117, section_y + 63, MUTED, self.fonts["tiny"])
        meter_y = section_y + 82
        pygame.draw.rect(self.screen, LINE, (x, meter_y, width, 4))
        pygame.draw.rect(self.screen, LIME, (x, meter_y, int(width * self.speed / MAX_SPEED), 4))
        for mark in range(5):
            mark_x = x + int(width * mark / 4)
            self.draw_text(str(mark * 60), mark_x, meter_y + 9, MUTED, self.fonts["tiny"], "midtop")

        stats_y = meter_y + 28
        pygame.draw.line(self.screen, LINE, (x, stats_y), (x + width, stats_y), 1)
        stats = [
            ("DISTANCE", f"{self.total_distance + self.distance:.2f} KM", PAPER),
            ("RACE SCORE", f"{self.score:06}", PAPER),
            ("PERSONAL BEST", f"{self.best_distance:.2f} KM", LIME),
        ]
        for index, (label, value, color) in enumerate(stats):
            row_y = stats_y + 15 + index * 29
            self.draw_text(label, x, row_y, MUTED, self.fonts["tiny"])
            self.draw_text(value, x + width, row_y - 1, color, self.fonts["mono"], "topright")
            pygame.draw.line(self.screen, LINE, (x, row_y + 23), (x + width, row_y + 23), 1)

        condition_y = stats_y + 105
        remaining = max(0, 3 - self.crashes)
        self.draw_text("CAR CONDITION", x, condition_y, MUTED, self.fonts["tiny"])
        self.draw_text(f"{remaining:02} / 03", x + width, condition_y, PAPER, self.fonts["tiny"], "topright")
        light_gap = 5
        light_width = (width - light_gap * 2) // 3
        for index in range(3):
            color = ORANGE if index >= remaining else LIME
            pygame.draw.rect(
                self.screen,
                color,
                (x + index * (light_width + light_gap), condition_y + 19, light_width, 4),
            )

        map_top = condition_y + 35
        controls_y = sidebar.bottom - 47
        self.draw_route_map(sidebar, map_top, controls_y - 10)

        button_rect = pygame.Rect(x, controls_y, width, 38)
        pygame.draw.rect(self.screen, PANEL, button_rect, border_radius=3)
        pygame.draw.rect(self.screen, LINE, button_rect, width=1, border_radius=3)
        if self.state == "racing":
            button_text = "SPACE  /  PAUSE RACE"
        elif self.state == "paused":
            button_text = "SPACE  /  RESUME RACE"
        else:
            button_text = "R  /  RESTART RACE"
        self.draw_text(button_text, button_rect.centerx, button_rect.centery, PAPER, self.fonts["tiny"], "center")
        self.draw_text("A  /  D   STEER     ↓   BRAKE", x, controls_y - 21, MUTED, self.fonts["tiny"])

    def draw_route_map(self, sidebar: pygame.Rect, top: int, bottom: int) -> None:
        x = sidebar.left
        width = sidebar.width
        height = bottom - top
        if height < 42:
            return

        self.draw_text("ROUTE MAP", x, top, MUTED, self.fonts["tiny"])
        self.draw_text(
            f"STAGE {self.stage_index + 1:02d}/{len(STAGES):02d}",
            x + width,
            top,
            LIME,
            self.fonts["tiny"],
            "topright",
        )
        map_rect = pygame.Rect(x, top + 16, width, height - 16)
        pygame.draw.rect(self.screen, PANEL, map_rect, border_radius=3)
        pygame.draw.rect(self.screen, LINE, map_rect, width=1, border_radius=3)

        route_area = map_rect.inflate(-28, -12)
        if route_area.height < 12:
            return

        route_points = []
        for index in range(51):
            progress = index / 50
            route_x = route_area.centerx + self.route_offset(progress, self.stage_index) * route_area.width * 1.2
            route_y = route_area.bottom - progress * route_area.height
            route_points.append((int(route_x), int(route_y)))

        pygame.draw.lines(self.screen, (88, 94, 83), False, route_points, 7)
        current_progress = max(0.0, min(1.0, self.distance / FINISH_DISTANCE))
        current_index = int(current_progress * (len(route_points) - 1))
        if current_index > 0:
            pygame.draw.lines(self.screen, LIME, False, route_points[: current_index + 1], 3)
        pygame.draw.circle(self.screen, (187, 190, 170), route_points[-1], 3)

        marker_x, marker_y = route_points[current_index]
        next_point = route_points[min(current_index + 1, len(route_points) - 1)]
        direction_x = next_point[0] - marker_x
        direction_y = next_point[1] - marker_y
        direction_length = max(1, math.hypot(direction_x, direction_y))
        direction_x /= direction_length
        direction_y /= direction_length
        perpendicular_x, perpendicular_y = -direction_y, direction_x
        arrow = [
            (marker_x + direction_x * 8, marker_y + direction_y * 8),
            (marker_x - direction_x * 5 + perpendicular_x * 4, marker_y - direction_y * 5 + perpendicular_y * 4),
            (marker_x - direction_x * 5 - perpendicular_x * 4, marker_y - direction_y * 5 - perpendicular_y * 4),
        ]
        pygame.draw.polygon(self.screen, ORANGE, arrow)

    def draw_touch_controls(self, scene: pygame.Rect) -> None:
        for name, rect in self.touch_button_rects(scene).items():
            pressed = name in self.pointer_controls.values()
            fill = (57, 68, 43, 220) if pressed else (22, 27, 24, 178)
            border = (*LIME, 210) if pressed else (177, 183, 162, 190)
            control_surface = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(
                control_surface,
                fill,
                control_surface.get_rect(),
                border_radius=8,
            )
            pygame.draw.rect(
                control_surface,
                border,
                control_surface.get_rect(),
                width=2,
                border_radius=8,
            )
            self.screen.blit(control_surface, rect)

            if name == "brake":
                self.draw_text("BRAKE", rect.centerx, rect.centery, PAPER, self.fonts["tiny"], "center")
                continue

            direction = -1 if name == "left" else 1
            center_x, center_y = rect.center
            tip_x = center_x + direction * 8
            base_x = center_x - direction * 5
            pygame.draw.lines(
                self.screen,
                LIME if pressed else PAPER,
                False,
                [(base_x, center_y - 10), (tip_x, center_y), (base_x, center_y + 10)],
                3,
            )

    def draw_progress(self, scene: pygame.Rect) -> None:
        y = scene.bottom + 14
        self.draw_text(f"STAGE {self.stage_index + 1:02d}", scene.left, y, MUTED, self.fonts["tiny"])
        self.draw_text("3 KM", scene.right, y, MUTED, self.fonts["tiny"], "topright")
        track = pygame.Rect(scene.left + 43, y + 3, scene.width - 86, 3)
        pygame.draw.rect(self.screen, LINE, track)
        progress = min(1.0, self.distance / FINISH_DISTANCE)
        pygame.draw.rect(self.screen, LIME, (track.x, track.y, int(track.width * progress), track.height))
        pygame.draw.line(self.screen, PAPER, (track.right, track.y - 3), (track.right, track.y + 5), 2)

    def draw_overlay(self, scene: pygame.Rect) -> None:
        if self.state == "racing":
            return
        shade = pygame.Surface(scene.size, pygame.SRCALPHA)
        shade.fill((17, 22, 17, 168))
        self.screen.blit(shade, scene.topleft)
        center_x, center_y = scene.center
        self.draw_text(
            f"APEX MOTOR CLUB  /  STAGE {self.stage_index + 1:02d} OF {len(STAGES):02d}",
            center_x,
            center_y - 67,
            LIME,
            self.fonts["tiny"],
            "center",
        )
        self.draw_text(self.message, center_x, center_y - 43, PAPER, self.fonts["display"], "midtop")
        detail = self.message_detail
        if self.state in ("ready", "paused"):
            detail += "  Press SPACE to continue."
        self.draw_text(detail, center_x, center_y + 3, (211, 210, 198), self.fonts["small"], "midtop")
        if self.state in ("ready", "paused", "stage_clear", "finished", "wrecked"):
            button = self.overlay_action_rect(scene)
            pygame.draw.rect(self.screen, LIME, button, border_radius=2)
            if self.state == "ready":
                label = "START RACE"
            elif self.state == "paused":
                label = "RESUME RACE"
            elif self.state == "stage_clear":
                label = "NEXT STAGE"
            else:
                label = "RACE AGAIN"
            self.draw_text(label, button.centerx, button.centery, BACKGROUND, self.fonts["mono"], "center")

    def draw_footer(self, width: int, height: int) -> None:
        margin = max(24, int(width * 0.045))
        y = height - 31
        pygame.draw.line(self.screen, LINE, (margin, y - 12), (width - margin, y - 12), 1)
        self.draw_text("NO BRAKES. NO BACKSEAT.", margin, y, MUTED, self.fonts["tiny"])
        self.draw_text(
            "BUILT FOR THE LONG WAY ROUND",
            width - margin,
            y,
            MUTED,
            self.fonts["tiny"],
            "topright",
        )

    def draw(self) -> None:
        width, height = self.screen.get_size()
        scene, sidebar = self.layout()
        self.screen.fill(BACKGROUND)
        self.draw_header(width)
        self.draw_title(scene)
        self.draw_scene(scene)
        self.draw_progress(scene)
        self.draw_sidebar(sidebar)
        self.draw_overlay(scene)
        if self.state == "racing":
            self.draw_touch_controls(scene)
        self.draw_footer(width, height)
        pygame.display.flip()

    async def run(self) -> None:
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.04)
            self.handle_events()
            self.update(dt)
            self.draw()
            await asyncio.sleep(0)


if __name__ == "__main__":
    asyncio.run(ApexCircuit().run())