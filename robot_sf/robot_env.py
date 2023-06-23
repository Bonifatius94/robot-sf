from __future__ import annotations
from math import atan2, dist
from dataclasses import dataclass, field
from typing import Tuple, Union, Callable, Dict, List
from copy import deepcopy

import numpy as np
from gym import Env, spaces

from robot_sf.sim_config import EnvSettings
from robot_sf.occupancy import ContinuousOccupancy
from robot_sf.range_sensor import lidar_ray_scan
from robot_sf.sim_view import \
    SimulationView, VisualizableAction, VisualizableSimState
from robot_sf.simulator import Simulator

from robot_sf.robot.differential_drive import DifferentialDriveAction
from robot_sf.robot.bicycle_drive import BicycleAction


Vec2D = Tuple[float, float]
PolarVec2D = Tuple[float, float]
RobotPose = Tuple[Vec2D, float]

OBS_DRIVE_STATE = "drive_state"
OBS_RAYS = "rays"


def simple_reward(meta: dict) -> float:
    step_discount = 0.1 / meta["max_sim_steps"]
    reward = -step_discount
    if meta["is_pedestrian_collision"] or meta["is_obstacle_collision"]:
        reward -= 2
    if meta["is_robot_at_goal"]:
        reward += 1
    return reward


def is_terminal(meta: dict) -> bool:
    return meta["is_timesteps_exceeded"] or meta["is_pedestrian_collision"] or \
        meta["is_obstacle_collision"] or meta["is_robot_at_goal"]


def build_norm_observation_space(
        timesteps: int, num_rays: int, max_scan_dist: float,
        robot_obs: spaces.Box, max_target_dist: float) -> Tuple[spaces.Dict, spaces.Dict]:
    max_drive_state = np.array([
        robot_obs.high.tolist() + [max_target_dist, np.pi, np.pi]
        for t in range(timesteps)], dtype=np.float32)
    min_drive_state = np.array([
        robot_obs.low.tolist() + [0.0, -np.pi, -np.pi]
        for t in range(timesteps)], dtype=np.float32)
    max_lidar_state = np.full((timesteps, num_rays), max_scan_dist)
    min_lidar_state = np.zeros((timesteps, num_rays))

    orig_box_drive_state = spaces.Box(low=min_drive_state, high=max_drive_state, dtype=np.float32)
    orig_box_lidar_state = spaces.Box(low=min_lidar_state, high=max_lidar_state, dtype=np.float32)
    orig_obs_space = spaces.Dict({ OBS_DRIVE_STATE: orig_box_drive_state, OBS_RAYS: orig_box_lidar_state })

    box_drive_state = spaces.Box(
        low=min_drive_state / max_drive_state,
        high=max_drive_state / max_drive_state,
        dtype=np.float32)
    box_lidar_state = spaces.Box(
        low=min_lidar_state / max_lidar_state,
        high=max_lidar_state / max_lidar_state,
        dtype=np.float32)
    norm_obs_space = spaces.Dict({ OBS_DRIVE_STATE: box_drive_state, OBS_RAYS: box_lidar_state })

    return norm_obs_space, orig_obs_space


def angle(p_1: Vec2D, p_2: Vec2D, p_3: Vec2D) -> float:
    v1_x, v1_y = p_2[0] - p_1[0], p_2[1] - p_1[1]
    v2_x, v2_y = p_3[0] - p_2[0], p_3[1] - p_2[1]
    o_1, o_2 = atan2(v1_y, v1_x), atan2(v2_y, v2_x)
    angle_raw = o_2 - o_1
    angle_norm = (angle_raw + np.pi) % (2 * np.pi) - np.pi
    return angle_norm


def rel_pos(pose: RobotPose, target_coords: Vec2D) -> PolarVec2D:
    t_x, t_y = target_coords
    (r_x, r_y), orient = pose
    distance = dist(target_coords, (r_x, r_y))

    angle = atan2(t_y - r_y, t_x - r_x) - orient
    angle = (angle + np.pi) % (2 * np.pi) - np.pi
    return distance, angle


def target_sensor_obs(
        robot_pose: RobotPose,
        goal_pos: Vec2D,
        next_goal_pos: Union[Vec2D, None]) -> Tuple[float, float, float]:
    robot_pos, _ = robot_pose
    target_distance, target_angle = rel_pos(robot_pose, goal_pos)
    next_target_angle = 0.0 if next_goal_pos is None else angle(robot_pos, goal_pos, next_goal_pos)
    return target_distance, target_angle, next_target_angle


@dataclass
class SensorFusion:
    lidar_sensor: Callable[[], np.ndarray]
    robot_speed_sensor: Callable[[], PolarVec2D]
    target_sensor: Callable[[], Tuple[float, float, float]]
    unnormed_obs_space: spaces.Dict
    drive_state_cache: List[np.ndarray] = field(init=False, default_factory=list)
    lidar_state_cache: List[np.ndarray] = field(init=False, default_factory=list)
    cache_steps: int = field(init=False)

    def __post_init__(self):
        self.cache_steps = self.unnormed_obs_space[OBS_RAYS].shape[0]

    def next_obs(self) -> Dict[str, np.ndarray]:
        lidar_state = self.lidar_sensor()
        # TODO: append beginning at the end for conv feature extractor

        speed_x, speed_rot = self.robot_speed_sensor()
        target_distance, target_angle, next_target_angle = self.target_sensor()
        drive_state = np.array([speed_x, speed_rot, target_distance, target_angle, next_target_angle])

        # info: populate cache with same states -> no movement
        if len(self.drive_state_cache) == 0:
            for _ in range(self.cache_steps):
                self.drive_state_cache.append(drive_state)
                self.lidar_state_cache.append(lidar_state)

        self.drive_state_cache.append(drive_state)
        self.lidar_state_cache.append(lidar_state)
        self.drive_state_cache.pop(0)
        self.lidar_state_cache.pop(0)

        stacked_drive_state = np.array(self.drive_state_cache, dtype=np.float32)
        stacked_lidar_state = np.array(self.lidar_state_cache, dtype=np.float32)

        max_drive = self.unnormed_obs_space[OBS_DRIVE_STATE].high
        max_lidar = self.unnormed_obs_space[OBS_RAYS].high
        return { OBS_DRIVE_STATE: stacked_drive_state / max_drive,
                 OBS_RAYS: stacked_lidar_state / max_lidar }


def collect_metadata(env) -> dict:
    # TODO: add RobotEnv type hint
    return {
        "step": env.episode * env.max_sim_steps,
        "episode": env.episode,
        "step_of_episode": env.timestep,
        "is_pedestrian_collision": env.occupancy.is_pedestrian_collision,
        "is_obstacle_collision": env.occupancy.is_obstacle_collision,
        "is_robot_at_goal": env.sim_env.robot_nav.reached_waypoint,
        "is_route_complete": env.sim_env.robot_nav.reached_destination,
        "is_timesteps_exceeded": env.timestep > env.max_sim_steps,
        "max_sim_steps": env.max_sim_steps
    }


class RobotEnv(Env):
    """Representing an OpenAI Gym environment for training
    a self-driving robot with reinforcement learning"""

    def __init__(
            self, env_config: EnvSettings = EnvSettings(),
            metadata_collector: Callable[[RobotEnv], dict] = collect_metadata,
            reward_func: Callable[[dict], float] = simple_reward,
            term_func: Callable[[dict], bool] = is_terminal,
            debug: bool = False):
        self.reward_func = reward_func
        self.term_func = term_func
        self.metadata_collector = metadata_collector
        sim_config = env_config.sim_config
        lidar_config = env_config.lidar_config
        robot_config = env_config.robot_config
        map_def = env_config.map_pool.choose_random_map()

        self.env_type = 'RobotEnv'
        self.max_sim_steps = sim_config.max_sim_steps
        robot = env_config.robot_factory()

        self.action_space = robot.action_space
        self.observation_space, orig_obs_space = build_norm_observation_space(
            sim_config.stack_steps, lidar_config.num_rays, lidar_config.max_scan_dist,
            robot.observation_space, map_def.max_target_dist)

        goal_proximity = robot_config.radius + sim_config.goal_radius
        self.sim_env = Simulator(sim_config, map_def, robot, goal_proximity)

        self.occupancy = ContinuousOccupancy(
            map_def.width, map_def.height, lambda: robot.pos, lambda: self.sim_env.goal_pos,
            lambda: self.sim_env.pysf_sim.env.obstacles_raw[:, :4], lambda: self.sim_env.ped_positions,
            robot_config.radius, sim_config.ped_radius, sim_config.goal_radius)

        ray_sensor = lambda: lidar_ray_scan(robot.pose, self.occupancy, lidar_config)
        target_sensor = lambda: target_sensor_obs(
            robot.pose, self.sim_env.goal_pos, self.sim_env.next_goal_pos)
        self.sensor_fusion = SensorFusion(
            ray_sensor, lambda: robot.current_speed, target_sensor, orig_obs_space)

        self.episode = 0
        self.timestep = 0
        self.last_action: Union[DifferentialDriveAction, BicycleAction, None] = None
        if debug:
            self.sim_ui = SimulationView(
                robot_radius=robot_config.radius,
                ped_radius=sim_config.ped_radius,
                goal_radius=sim_config.goal_radius)
            self.sim_ui.show()

    def step(self, action: np.ndarray):
        action_parsed = self.sim_env.robot.parse_action(action)
        self.sim_env.step_once(action_parsed)
        self.last_action = action_parsed
        obs = self.sensor_fusion.next_obs()

        meta = self.metadata_collector(self)
        masked_meta = { "step": meta["step"], "meta": meta } # info: SB3 crashes otherwise
        self.timestep += 1
        return obs, self.reward_func(meta), self.term_func(meta), masked_meta

    def reset(self):
        self.episode += 1
        self.timestep = 0
        self.last_action = None
        self.sim_env.reset_state()
        return self.sensor_fusion.next_obs()

    def render(self, mode='human'):
        if not self.sim_ui:
            raise RuntimeError('Debug mode is not activated! Consider setting debug=True!')

        action = None if not self.last_action else VisualizableAction(
            self.sim_env.robot.pose, self.last_action, self.sim_env.goal_pos)

        state = VisualizableSimState(
            self.timestep, action, self.sim_env.robot.pose,
            deepcopy(self.occupancy.pedestrian_coords),
            deepcopy(self.occupancy.obstacle_coords))

        self.sim_ui.render(state)

    def exit(self):
        if self.sim_ui:
            self.sim_ui.exit()
