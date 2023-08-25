from time import sleep
from math import sin, cos
from typing import Tuple, Union, List
from dataclasses import dataclass, field
from threading import Thread
from signal import signal, SIGINT

import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"

import pygame
import numpy as np

from robot_sf.robot.differential_drive import DifferentialDriveAction
from robot_sf.robot.bicycle_drive import BicycleAction
from robot_sf.nav.map_config import Obstacle

Vec2D = Tuple[float, float]
RobotPose = Tuple[Vec2D, float]
RobotAction = Tuple[float, float]
RgbColor = Tuple[int, int, int]


BACKGROUND_COLOR = (255, 255, 255)
BACKGROUND_COLOR_TRANSP = (255, 255, 255, 128)
OBSTACLE_COLOR = (20, 30, 20, 128)
PED_COLOR = (255, 50, 50)
ROBOT_COLOR = (0, 0, 200)
COLLISION_COLOR = (200, 0, 0)
ROBOT_ACTION_COLOR = (65, 105, 225)
PED_ACTION_COLOR = (255, 50, 50)
ROBOT_GOAL_COLOR = (0, 204, 102)
ROBOT_LIDAR_COLOR = (238, 160, 238, 128)
TEXT_COLOR = (0, 0, 0)


@dataclass
class VisualizableAction:
    robot_pose: RobotPose
    robot_action: Union[DifferentialDriveAction, BicycleAction]
    robot_goal: Vec2D


@dataclass
class VisualizableSimState:
    """Representing a collection of properties to display
    the simulator's state at a discrete timestep."""
    timestep: int
    action: Union[VisualizableAction, None]
    robot_pose: RobotPose
    pedestrian_positions: np.ndarray
    ray_vecs: np.ndarray
    ped_actions: np.ndarray
    # obstacles: List[Obstacle]


@dataclass
class SimulationView:
    width: float=1200
    height: float=800
    scaling: float=15
    robot_radius: float=1.0
    ped_radius: float=0.4
    goal_radius: float=1.0
    obstacles: List[Obstacle] = field(default_factory=list)
    size_changed: bool = field(init=False, default=False)
    is_exit_requested: bool = field(init=False, default=False)
    is_abortion_requested: bool = field(init=False, default=False)
    screen: pygame.surface.Surface = field(init=False)
    font: pygame.font.Font = field(init=False)

    @property
    def timestep_text_pos(self) -> Vec2D:
        return (self.width - 100, 10)

    def __post_init__(self):
        pygame.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode(
            (self.width, self.height), pygame.RESIZABLE)
        pygame.display.set_caption('RobotSF Simulation')
        self.font = pygame.font.SysFont('Consolas', 14)
        self.surface_obstacles = self.preprocess_obstacles()
        self.clear()

    def preprocess_obstacles(self) -> pygame.Surface:
        obst_vertices = [o.vertices_np * self.scaling for o in self.obstacles]
        min_x, max_x, min_y, max_y = np.inf, -np.inf, np.inf, -np.inf
        for vertices in obst_vertices:
            min_x, max_x = min(np.min(vertices[:, 0]), min_x), max(np.max(vertices[:, 0]), max_x)
            min_y, max_y = min(np.min(vertices[:, 1]), min_y), max(np.max(vertices[:, 1]), max_y)
        width, height = max_x - min_x, max_y - min_y
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        surface.fill(BACKGROUND_COLOR_TRANSP)
        for vertices in obst_vertices:
            pygame.draw.polygon(surface, OBSTACLE_COLOR, [(x, y) for x, y in vertices])
        return surface

    def show(self):
        self.ui_events_thread = Thread(target=self._process_event_queue)
        self.ui_events_thread.start()

        def handle_sigint(signum, frame):
            self.is_exit_requested = True
            self.is_abortion_requested = True

        signal(SIGINT, handle_sigint)

    def exit(self):
        self.is_exit_requested = True
        self.ui_events_thread.join()

    def _process_event_queue(self):
        while not self.is_exit_requested:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.is_exit_requested = True
                    self.is_abortion_requested = True
                elif e.type == pygame.VIDEORESIZE:
                    self.size_changed = True
                    self.width, self.height = e.w, e.h
            sleep(0.01)

    def clear(self):
        self.screen.fill(BACKGROUND_COLOR)
        self._augment_timestep(0)
        pygame.display.update()

    def render(self, state: VisualizableSimState):
        sleep(0.01) # limit UI update rate to 100 fps

        # info: event handling needs to be processed
        #       in the main thread to access UI resources
        if self.is_exit_requested:
            pygame.quit()
            self.ui_events_thread.join()
            if self.is_abortion_requested:
                exit()
        if self.size_changed:
            self._resize_window()
            self.size_changed = False

        state, offset = self._zoom_camera(state)
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_obstacles(offset)
        self._augment_lidar(state.ray_vecs)
        self._augment_ped_actions(state.ped_actions)
        if state.action:
            self._augment_robot_action(state.action)
            self._augment_goal_position(state.action.robot_goal)
        self._draw_pedestrians(state.pedestrian_positions)
        self._draw_robot(state.robot_pose)
        self._augment_timestep(state.timestep)
        pygame.display.update()

    def _resize_window(self):
        old_surface = self.screen
        self.screen = pygame.display.set_mode(
            (self.width, self.height), pygame.RESIZABLE)
        self.screen.blit(old_surface, (0, 0))

    def _zoom_camera(self, state: VisualizableSimState) \
            -> Tuple[VisualizableSimState, Tuple[float, float]]:
        r_x, r_y = state.robot_pose[0]
        x_offset = r_x * self.scaling - self.width / 2
        y_offset = r_y * self.scaling - self.height / 2
        state.pedestrian_positions *= self.scaling
        state.pedestrian_positions -= [x_offset, y_offset]
        state.ped_actions *= self.scaling
        state.ped_actions -= [x_offset, y_offset]
        state.ray_vecs *= self.scaling
        state.ray_vecs -= [x_offset, y_offset]
        state.robot_pose = ((
            state.robot_pose[0][0] * self.scaling - x_offset,
            state.robot_pose[0][1] * self.scaling - y_offset),
            state.robot_pose[1])
        if state.action:
            state.action.robot_pose = ((
                state.action.robot_pose[0][0] * self.scaling - x_offset,
                state.action.robot_pose[0][1] * self.scaling - y_offset),
                state.action.robot_pose[1])
            state.action.robot_goal = (
                state.action.robot_goal[0] * self.scaling - x_offset,
                state.action.robot_goal[1] * self.scaling - y_offset)
        return state, (x_offset, y_offset)

    def _draw_robot(self, pose: RobotPose):
        # TODO: display robot with an image instead of a circle
        pygame.draw.circle(self.screen, ROBOT_COLOR, pose[0], self.robot_radius * self.scaling)

    def _draw_pedestrians(self, ped_pos: np.ndarray):
        # TODO: display pedestrians with an image instead of a circle
        for ped_x, ped_y in ped_pos:
            pygame.draw.circle(self.screen, PED_COLOR, (ped_x, ped_y), self.ped_radius * self.scaling)

    def _draw_obstacles(self, offset: Tuple[float, float]):
        offset = offset[0] * -1, offset[1] * -1
        self.screen.blit(self.surface_obstacles, offset)

    def _augment_goal_position(self, robot_goal: Vec2D):
        # TODO: display pedestrians with an image instead of a circle
        pygame.draw.circle(self.screen, ROBOT_GOAL_COLOR, robot_goal, self.goal_radius * self.scaling)

    def _augment_lidar(self, ray_vecs: np.ndarray):
        for p1, p2 in ray_vecs:
            pygame.draw.line(self.screen, ROBOT_LIDAR_COLOR, p1, p2)

    def _augment_robot_action(self, action: VisualizableAction):
        r_x, r_y = action.robot_pose[0]
        vec_length, vec_orient = action.robot_action[0] * self.scaling * 3, action.robot_pose[1]

        def from_polar(length: float, orient: float) -> Vec2D:
            return cos(orient) * length, sin(orient) * length

        def add_vec(v_1: Vec2D, v_2: Vec2D) -> Vec2D:
            return v_1[0] + v_2[0], v_1[1] + v_2[1]

        vec_x, vec_y = add_vec((r_x, r_y), from_polar(vec_length, vec_orient))
        pygame.draw.line(self.screen, ROBOT_ACTION_COLOR, (r_x, r_y), (vec_x, vec_y), width=3)

    def _augment_ped_actions(self, ped_actions: np.ndarray):
        for p1, p2 in ped_actions:
            pygame.draw.line(self.screen, PED_ACTION_COLOR, p1, p2, width=3)

    def _augment_timestep(self, timestep: int):
        # TODO: show map name as well
        text = f'step: {timestep}'
        text_surface = self.font.render(text, False, TEXT_COLOR)
        self.screen.blit(text_surface, self.timestep_text_pos)
