from math import sin, cos
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np
from gym import spaces


Vec2D = Tuple[float, float]
PolarVec2D = Tuple[float, float]
RobotPose = Tuple[Vec2D, float]
WheelSpeedState = Tuple[float, float] # tuple of (left, right) speeds


@dataclass
class DifferentialDriveSettings:
    radius: float = 1.0
    max_linear_speed: float = 2.0
    max_angular_speed: float = 0.5
    wheel_radius: float = 0.05
    interaxis_length: float = 0.3

    def __post_init__(self):
        if self.radius <= 0:
            raise ValueError("Robot's radius mustn't be negative or zero! Needs to model a corps!")
        if self.wheel_radius <= 0:
            raise ValueError("Robot's wheel radius mustn't be negative or zero! Needs to model a corps!")
        if self.max_linear_speed <= 0 or self.max_angular_speed <= 0:
            raise ValueError("Robot's max. linear / angular speed mustn't be negative or zero!")
        if self.interaxis_length <= 0:
            raise ValueError("Robot's interaxis length mustn't be negative or zero!")


@dataclass
class DifferentialDriveState:
    pose: RobotPose
    velocity: PolarVec2D = field(default=(0, 0))
    last_wheel_speeds: WheelSpeedState = field(default=(0, 0))
    wheel_speeds: WheelSpeedState = field(default=(0, 0))


DifferentialDriveAction = Tuple[float, float] # (linear velocity, angular velocity)


@dataclass
class DifferentialDriveMotion:
    config: DifferentialDriveSettings

    def move(self, state: DifferentialDriveState, action: PolarVec2D, d_t: float):
        robot_vel = self._robot_velocity(state.velocity, action)
        new_wheel_speeds = self._resulting_wheel_speeds(robot_vel)
        distance = self._covered_distance(state.wheel_speeds, new_wheel_speeds, d_t)
        new_orient = self._new_orientation(state.pose[1], state.wheel_speeds, new_wheel_speeds, d_t)
        state.pose = self._compute_odometry(state.pose, (distance, new_orient))
        state.last_wheel_speeds = state.wheel_speeds
        state.wheel_speeds = new_wheel_speeds
        state.velocity = robot_vel

    def _robot_velocity(self, velocity: PolarVec2D, action: PolarVec2D) -> PolarVec2D:
        dot_x = velocity[0] + action[0]
        dot_orient = velocity[1] + action[1]
        dot_x = np.clip(dot_x, 0, self.config.max_linear_speed)
        angular_max = self.config.max_angular_speed
        dot_orient = np.clip(dot_orient, -angular_max, angular_max)
        return dot_x, dot_orient

    def _resulting_wheel_speeds(self, movement: PolarVec2D) -> WheelSpeedState:
        dot_x, dot_orient = movement
        diff = self.config.interaxis_length * dot_orient / 2
        new_left_wheel_speed = (dot_x - diff) / self.config.wheel_radius
        new_right_wheel_speed = (dot_x + diff) / self.config.wheel_radius
        return new_left_wheel_speed, new_right_wheel_speed

    def _covered_distance(
            self, last_wheel_speeds: WheelSpeedState,
            new_wheel_speeds: WheelSpeedState, d_t: float) -> float:
        last_wheel_speed_left, last_wheel_speed_right = last_wheel_speeds
        wheel_speed_left, wheel_speed_right = new_wheel_speeds

        velocity = ((last_wheel_speed_left + wheel_speed_left) / 2 \
            + (last_wheel_speed_right + wheel_speed_right) / 2)
        distance_covered = self.config.wheel_radius / 2 * velocity * d_t
        return distance_covered

    def _new_orientation(
            self, robot_orient: float, last_wheel_speeds: WheelSpeedState,
            wheel_speeds: WheelSpeedState, d_t: float) -> float:
        last_wheel_speed_left, last_wheel_speed_right = last_wheel_speeds
        wheel_speed_left, wheel_speed_right = wheel_speeds

        right_left_diff = (last_wheel_speed_right + wheel_speed_right) / 2 \
            - (last_wheel_speed_left + wheel_speed_left) / 2
        diff = self.config.wheel_radius / self.config.interaxis_length * right_left_diff * d_t
        new_orient = robot_orient + diff
        return new_orient

    def _compute_odometry(self, old_pose: RobotPose, movement: PolarVec2D) -> RobotPose:
        distance_covered, new_orient = movement
        (robot_x, robot_y), old_orient = old_pose
        rel_rotation = (old_orient + new_orient) / 2
        new_x = robot_x + distance_covered * cos(rel_rotation)
        new_y = robot_y + distance_covered * sin(rel_rotation)
        return (new_x, new_y), new_orient


@dataclass
class DifferentialDriveRobot():
    """Representing a robot with differential driving behavior"""

    config: DifferentialDriveSettings
    state: DifferentialDriveState = field(default=DifferentialDriveState(((0, 0), 0)))
    movement: DifferentialDriveMotion = field(init=False)

    def __post_init__(self):
        self.movement = DifferentialDriveMotion(self.config)

    @property
    def observation_space(self) -> spaces.Box:
        high = np.array([self.config.max_linear_speed, self.config.max_angular_speed], dtype=np.float32)
        low = np.array([0.0, -self.config.max_angular_speed], dtype=np.float32)
        return spaces.Box(low=low, high=high, dtype=np.float32)

    @property
    def action_space(self) -> spaces.Box:
        high = np.array([self.config.max_linear_speed, self.config.max_angular_speed], dtype=np.float32)
        low = np.array([0.0, -self.config.max_angular_speed], dtype=np.float32)
        return spaces.Box(low=low, high=high, dtype=np.float32)

    @property
    def pos(self) -> Vec2D:
        return self.state.pose[0]

    @property
    def pose(self) -> RobotPose:
        return self.state.pose

    @property
    def current_speed(self) -> PolarVec2D:
        return self.state.velocity

    def apply_action(self, action: DifferentialDriveAction, d_t: float):
        self.movement.move(self.state, action, d_t)

    def reset_state(self, new_pose: RobotPose):
        self.state = DifferentialDriveState(new_pose)

    def parse_action(self, action: np.ndarray) -> DifferentialDriveAction:
        return (action[0], action[1])
