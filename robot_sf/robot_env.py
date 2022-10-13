from math import dist
from typing import Tuple, List

import numpy as np
from gym import Env, spaces

from robot_sf.map import BinaryOccupancyGrid
from robot_sf.range_sensor import LidarScanner
from robot_sf.vector import RobotPose, Vec2D, PolarVec2D
from robot_sf.robot import DifferentialDriveRobot, LidarScannerSettings, RobotSettings
from robot_sf.extenders_py_sf.extender_sim import ExtdSimulator


def initialize_lidar(
        robot_map: BinaryOccupancyGrid,
        visualization_angle_portion: float,
        lidar_range: int,
        lidar_n_rays: int,
        scan_noise: List[float]):
    lidar_settings = LidarScannerSettings(
        lidar_range, visualization_angle_portion, lidar_n_rays, scan_noise)
    lidar_sensor = LidarScanner(lidar_settings, robot_map)
    return lidar_sensor


def initialize_robot(
        robot_map: BinaryOccupancyGrid,
        lidar_sensor: LidarScanner,
        spawn_pos: RobotPose,
        robot_collision_radius,
        wheel_max_linear_speed: float,
        wheel_max_angular_speed: float):

    # initialize robot with map
    robot_settings = RobotSettings(
        wheel_max_linear_speed, wheel_max_angular_speed, robot_collision_radius)

    robot = DifferentialDriveRobot(spawn_pos, robot_settings, lidar_sensor, robot_map)
    return robot


def initialize_simulator(peds_sparsity, difficulty, dt, peds_speed_mult) -> ExtdSimulator:
    sim_env = ExtdSimulator(difficulty=difficulty)
    sim_env.set_ped_sparsity(peds_sparsity)
    sim_env.peds.step_width = dt
    sim_env.peds.max_speed_multiplier = peds_speed_mult
    return sim_env


def initialize_map(sim_env: ExtdSimulator) -> BinaryOccupancyGrid:
    # initialize map
    map_height = 2 * sim_env.box_size
    map_width = 2 * sim_env.box_size
    map_resolution = 10 # grid cell granularity rel. to 1 map unit
    robot_map = BinaryOccupancyGrid(map_height, map_width, map_resolution, sim_env.box_size,
        lambda: sim_env.env.obstacles, lambda: sim_env.current_positions)
    return robot_map


class RobotEnv(Env):
    """Representing an OpenAI Gym environment wrapper for
    training a robot with reinforcement leanring"""

    # TODO: transform this into cohesive data structures
    def __init__(self, lidar_n_rays: int=272,
                 collision_distance: float=0.7, visualization_angle_portion: float=0.5, lidar_range: int=10,
                 v_linear_max: float=1, v_angular_max: float=1, rewards: List[float]=None, max_v_x_delta: float=.5, 
                 initial_margin: float=.3, max_v_rot_delta: float=.5, dt: float=None, normalize_obs_state: bool=True,
                 sim_length: int=200, difficulty: int=0, scan_noise: List[float]=None, peds_speed_mult: float=1.3):

        # TODO: get rid of most of these instance variables
        #       -> encapsulate statefulness inside a "state" object
        scan_noise = scan_noise if scan_noise else [0.005, 0.002]

        # info: this gets initialized by env.reset()
        self.robot: DifferentialDriveRobot = None
        self.target_coords: np.ndarray = None

        self.lidar_range = lidar_range
        self.closest_obstacle = self.lidar_range

        self.sim_length = sim_length  # maximum simulation length (in seconds)
        self.env_type = 'RobotEnv'
        self.rewards = rewards if rewards else [1, 100, 40]
        self.normalize_obs_state = normalize_obs_state

        self.linear_max =  v_linear_max
        self.angular_max = v_angular_max

        # TODO: don't initialize the entire simulator just for retrieving some settings
        sim_env_test = ExtdSimulator()
        self.target_distance_max = np.sqrt(2) * (sim_env_test.box_size * 2)
        self.dt = sim_env_test.peds.step_width if dt is None else dt

        action_low  = np.array([-max_v_x_delta, -max_v_rot_delta])
        action_high = np.array([ max_v_x_delta,  max_v_rot_delta])
        self.action_space = spaces.Box(low=action_low, high=action_high, dtype=np.float64)

        state_max = np.concatenate((
                self.lidar_range * np.ones((lidar_n_rays,)),
                np.array([self.linear_max, self.angular_max, self.target_distance_max, np.pi])
            ), axis=0)
        state_min = np.concatenate((
                np.zeros((lidar_n_rays,)),
                np.array([0, -self.angular_max, 0, -np.pi])
            ), axis=0)
        self.observation_space = spaces.Box(low=state_min, high=state_max, dtype=np.float64)

        self.map_boundaries_factory = lambda robot_map: \
            robot_map.position_bounds(initial_margin)

        sparsity_levels = [500, 200, 100, 50, 20]
        self.sim_env = initialize_simulator(
            sparsity_levels[difficulty], difficulty, self.dt, peds_speed_mult)

        # TODO: generate a couple of maps on environment startup and pick randomly from them
        self.robot_map = initialize_map(self.sim_env)
        lidar_sensor = initialize_lidar(
            self.robot_map,
            visualization_angle_portion,
            self.lidar_range,
            lidar_n_rays,
            scan_noise)

        self.robot_factory = lambda robot_map, robot_pose: initialize_robot(
            robot_map,
            lidar_sensor,
            robot_pose,
            collision_distance,
            self.linear_max,
            self.angular_max)

    def render(self, mode='human'):
        # TODO: visualize the game state with something like e.g. pygame
        # rendering: use the map's occupancy grid and display it as bitmap
        pass

    def step(self, action_np: np.ndarray):
        coords_with_direction = self.robot.pose.coords_with_orient
        self.sim_env.move_robot(coords_with_direction)
        self.sim_env.step(1)
        self.robot_map.update_moving_objects()

        dist_before = dist(self.robot.pos.as_list, self.target_coords)
        action = PolarVec2D(action_np[0], action_np[1])
        movement, saturate_input = self.robot.apply_action(action, self.dt)
        dot_x, dot_orient = movement.dist, movement.orient
        dist_after = dist(self.robot.pos.as_list, self.target_coords)

        # scan for collisions with LiDAR sensor, generate new observation
        ranges = self.robot.get_scan()
        norm_ranges, rob_state = self._get_obs(ranges)
        self.rotation_counter += np.abs(dot_orient * self.dt)

        # determine the reward and whether the episode is done
        reward, done = self._reward(dist_before, dist_after, dot_x, norm_ranges, saturate_input)
        return (norm_ranges, rob_state), reward, done, None

    def _reward(self, dist_0, dist_1, dot_x, ranges, saturate_input) -> Tuple[float, bool]:
        # TODO: figure out why the reward is sometimes NaN

        # if pedestrian / obstacle is hit or time expired
        if self.robot.is_pedestrians_collision(.8) or \
                self.robot.is_obstacle_collision(self.robot.config.rob_collision_radius) or \
                self.robot.is_out_of_bounds(margin = 0.01) or self.duration > self.sim_length:
            final_distance_bonus = np.clip((self.distance_init - dist_1) / self.target_distance_max , -1, 1)
            reward = -self.rewards[1] * (1 - final_distance_bonus)
            done = True

        # if target is reached
        elif self.robot.is_target_reached(self.target_coords, tolerance=1):
            cum_rotations = (self.rotation_counter / (2 * np.pi))
            rotations_penalty = self.rewards[2] * cum_rotations / (1e-5 + self.duration)

            # reward is proportional to distance covered / speed in getting to target
            reward = np.maximum(self.rewards[1] / 2, self.rewards[1] - rotations_penalty)
            done = True

        else:
            self.duration += self.dt
            reward = self.rewards[0] * ((dist_0 - dist_1) / (self.linear_max * self.dt) \
                - int(saturate_input) + (1 - min(ranges)) * (dot_x / self.linear_max) * int(dist_0 > dist_1))
            done = False

        return reward, done

    def reset(self):
        self.duration = 0
        self.rotation_counter = 0

        self.target_coords, robot_pose = \
            self._pick_robot_spawn_and_target_pos(self.robot_map)
        self.robot = self.robot_factory(self.robot_map, robot_pose)

        # initialize Scan to get dimension of state (depends on ray cast)
        dist_to_goal, _ = robot_pose.target_rel_position(self.target_coords)
        self.distance_init = dist_to_goal
        ranges = self.robot.get_scan()
        return self._get_obs(ranges)

    def _pick_robot_spawn_and_target_pos(
            self, robot_map: BinaryOccupancyGrid) -> Tuple[np.ndarray, RobotPose]:
        low_bound, high_bound = self.map_boundaries_factory(robot_map)
        count = 0
        min_distance = (high_bound[0] - low_bound[0]) / 20 # TODO: why divide by 20?????
        while True:
            target_coords = np.random.uniform(
                low=np.array(low_bound)[:2], high=np.array(high_bound)[:2], size=2)
            # ensure that the target is not occupied by obstacles
            dists = np.linalg.norm(robot_map.obstacle_coordinates - target_coords)
            if np.amin(dists) > min_distance:
                break
            count +=1
            # TODO: rather exhaustively check if the map is ok on environment creation
            if count >= 100:
                raise ValueError('suitable initial coordinates not found')

        check_out_of_bounds = lambda coords: not robot_map.check_if_valid_world_coordinates(coords, margin=0.2).any()
        robot_coords = np.random.uniform(low=low_bound, high=high_bound, size=3)
        robot_pose = RobotPose(Vec2D(robot_coords[0], robot_coords[1]), robot_coords[2])

        # if initial condition is too close (1.5m) to obstacle,
        # pedestrians or target, generate new initial condition
        while robot_map.is_collision(robot_pose.pos, 1.5) or check_out_of_bounds(robot_pose.coords) or \
                robot_pose.target_rel_position(target_coords)[0] < (high_bound[0] - low_bound[0]) / 2:
            robot_coords = np.random.uniform(low=low_bound, high=high_bound, size=3)
            robot_pose = RobotPose(Vec2D(robot_coords[0], robot_coords[1]), robot_coords[2])

        return target_coords, robot_pose

    def _get_obs(self, ranges_np: np.ndarray):
        speed_x = self.robot.state.current_speed.dist
        speed_rot = self.robot.state.current_speed.orient

        target_distance, target_angle = self.robot.state.current_pose.target_rel_position(self.target_coords)
        self.closest_obstacle = np.amin(ranges_np)

        if self.normalize_obs_state:
            ranges_np /= self.lidar_range
            speed_x /= self.linear_max
            speed_rot = speed_rot / self.angular_max
            target_distance /= self.target_distance_max
            target_angle = target_angle / np.pi

        return ranges_np, np.array([speed_x, speed_rot, target_distance, target_angle])
