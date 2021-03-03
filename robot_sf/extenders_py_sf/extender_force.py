# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 14:30:55 2020

@author: enric
"""

# required if current directory is not found

import sys 
import os

csfp = os.path.abspath(os.path.dirname(__file__))
if csfp not in sys.path:
    sys.path.insert(0, csfp)


#%%
from ..utils.utilities import change_direction

from pysocialforce import forces
from pysocialforce.utils import stateutils

import numpy as np

#%%

def normalize(vecs):
    """Normalize nx2 array along the second axis
    input: [n,2] ndarray
    output: (normalized vectors, norm factors)
    """
    
    #with CodeTimer('new'):
    norm_factors = np.linalg.norm(vecs, axis = 1)
    normalized = vecs/(norm_factors[:,np.newaxis]+1e-8)
    
    return normalized, norm_factors



#%%

class DesiredForce(forces.Force):
    """Calculates the force between this agent and the next assigned waypoint.
    If the waypoint has been reached, the next waypoint in the list will be
    selected.
    :return: the calculated force
    """

    def __init__(self, 
                 obstacle_avoidance= False, 
                 angles =np.pi*np.array([-1,-0.5,-0.25,0.25,0.5,1]), 
                 p0 = np.empty((0,2)),
                 p1 = np.empty((0,2)),
                 view_distance = 15,
                 forgetting_factor = .8):
        super().__init__()
        self.obstacle_avoidance = obstacle_avoidance
        if self.obstacle_avoidance:
            self.angles = angles
            self.p0 = p0
            self.p1 = p1
            self.view_distance = view_distance
            self.forgetting_factor = forgetting_factor

    def _get_force(self):
        relexation_time = self.config("relaxation_time", 0.5)
        goal_threshold = self.config("goal_threshold", 0.1)
        pos = self.peds.pos()
        vel = self.peds.vel()
        goal = self.peds.goal()
        
        direction, dist = normalize(goal - pos)
        ### in the following, direction is changed if obstacle is detected

        #####
        if self.obstacle_avoidance:
            direction,peds_collision_indices =  change_direction(self.p0,
                                                                 self.p1,
                                                                 self.peds.state[:,:2],   # current positions
                                                                 self.peds.state[:,4:6],  # current destinations
                                                                 self.view_distance, 
                                                                 self.angles, 
                                                                 direction,
                                                                 self.peds.desired_directions()) # current desired directions
        ##############################
        
        force = np.zeros((self.peds.size(), 2))
        force[dist > goal_threshold] = (
            direction * self.peds.max_speeds.reshape((-1, 1)) - vel.reshape((-1, 2))
        )[dist > goal_threshold, :]
        force[dist <= goal_threshold] = -1.0 * vel[dist <= goal_threshold]
        force /= relexation_time

        if self.obstacle_avoidance:
        # in case of correction of direction, some "memory" has to be used on the direction of the pedestrians in order to reduce "chattering"
            forces_intensities = np.linalg.norm(force,axis=-1)
            previous_directions = vel / np.tile(np.linalg.norm(vel,axis=-1),(2,1)).T
            previous_directions = np.nan_to_num(previous_directions)
            #print(previous_directions)
            previous_forces = previous_directions*np.tile(forces_intensities,(2,1)).T
            force[peds_collision_indices] = self.forgetting_factor*force[peds_collision_indices] + (1-self.forgetting_factor)*previous_forces[peds_collision_indices] 
        
        return force * self.factor




class GroupRepulsiveForce(forces.Force):
    """Group repulsive force"""

    def _get_force(self):
        threshold = self.config("threshold", 0.5)
        forces = np.zeros((self.peds.size(), 2))
        if self.peds.has_group():
            for group in self.peds.groups:
                size = len(group)
                member_pos = self.peds.pos()[group, :]
                diff = stateutils.each_diff(member_pos)  # others - self
                _, norms = normalize(diff)
                diff[norms > threshold, :] = 0
                # forces[group, :] += np.sum(diff, axis=0)
                try: #try except has been added (only difference)
                    forces[group, :] += np.sum(diff.reshape((size, -1, 2)), axis=1)
                except Exception:
                    stophere=1  # this problem was introduced due to the existance of empty groups

        return forces * self.factor
