from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback
from robot_sf.robot_env import RobotEnv


def training():
    n_envs = 64
    env = make_vec_env(lambda: RobotEnv(), n_envs=n_envs, vec_env_cls=SubprocVecEnv)
    model = PPO("MlpPolicy", env, tensorboard_log="./logs/ppo_logs/")
    save_model = CheckpointCallback(1_000_000 // n_envs, "./model/backup", "ppo_model")
    model.learn(total_timesteps=50_000_000, progress_bar=True, callback=save_model)
    model.save("./model/ppo_model")


if __name__ == '__main__':
    training()