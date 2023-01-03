from math import pi
from robot_sf.robot import DifferentialDriveMotion, DifferentialDriveState, RobotSettings


def norm_angle(angle: float) -> float:
    while angle < 0:
        angle += 2*pi
    while angle >= 2*pi:
        angle -= 2*pi
    return angle


def test_can_drive_right_curve():
    motion = DifferentialDriveMotion(RobotSettings(1, 1, 1, 1))
    pose_before, vel_before, wheel_speeds = ((0, 0), 0), (1, 0), (1, 1)
    state = DifferentialDriveState(pose_before, vel_before, wheel_speeds, wheel_speeds)
    right_curve_action = (1, -0.5)
    motion.move(state, right_curve_action, 1.0)
    pos_after, orient_after = state.pose
    assert pos_after[0] > 0 and pos_after[1] < 0    # position in 4th quadrant
    assert 1.5*pi < norm_angle(orient_after) < 2*pi # orientation in 4th quadrant


def test_can_drive_left_curve():
    motion = DifferentialDriveMotion(RobotSettings(1, 1, 1, 1))
    pose_before, vel_before, wheel_speeds = ((0, 0), 0), (1, 0), (1, 1)
    state = DifferentialDriveState(pose_before, vel_before, wheel_speeds, wheel_speeds)
    left_curve_action = (1, 0.5)
    motion.move(state, left_curve_action, 1.0)
    pos_after, orient_after = state.pose
    assert pos_after[0] > 0 and pos_after[1] > 0 # position in 1st quadrant
    assert 0 < norm_angle(orient_after) < 0.5*pi # orientation in 1st quadrant
