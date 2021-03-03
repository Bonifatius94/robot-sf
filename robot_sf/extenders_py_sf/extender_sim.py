# -*- coding: utf-8 -*-
"""
Created on Sat Dec  5 12:56:00 2020

@author: Matteo Caruso, Enrico Regolin
"""

# required if current directory is not found
#%%Module loading list

import sys 
import os
import toml
import json
import copy
from natsort import natsorted
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)


import numpy as np
import random

import pysocialforce as psf
from pysocialforce import forces
from pysocialforce.utils import stateutils

#src.extenders_py_sf.
from .extender_scene import PedState
from .extender_force import DesiredForce, GroupRepulsiveForce

from ..utils.utilities import fill_state, fun_reduce_index #check_peds_validity
from ..utils.poly import Polygon


#%%Simulator Class Definition
# extension of Class "Simulator"
class ExtdSimulator(psf.Simulator):
    def __init__(self,config_file=None, path_to_config = None):
        
        self.tmp = None
        
        self.box_size = None   #Implemented in load config
        self.peds_sparsity = None    #average min m^2 per person #Implemented in load config
        
        self.obstacles_lolol = None #Implemented in load config
        self.obstacle_avoidance_params = None
        
        #print(obstacle_avoidance_params)
        
        self.ped_generation_action_pool = dict()
        self.ped_generation_action_pool['actions'] = None  #Implemented in load config
        self.ped_generation_action_pool['probabilities'] = None  #Implemented in load config
        
        self.group_action_pool = dict()
        self.group_action_pool['actions'] = None   #Implemented in load config
        self.group_action_pool['probabilities'] = None   #Implemented in load config
        
        
        self.stopping_action_pool = dict()
        self.stopping_action_pool['actions'] = None  #Implemented in load config
        self.stopping_action_pool['probabilities'] = None  #Implemented in load config
        
        
        
       #----------------------------------------------------------------------
        #                       FLAGS
        #----------------------------------------------------------------------
         #Flag needed for check if dynamic grouping is allowed
        self.update_peds = None   #Implemented in load config
        
        self.__dynamic_grouping = None  #Implemented in load config
        
        self.__enable_max_steps_stop = None   #Implemented in load config
        
        self.__enable_topology_on_stopped = None   #Implemented in load config
        
        self.__enable_rendezvous_centroid = None   #Implemented in load config
        
        self.__topology_operations_on_unfreezing = None   #Implemented in load config
        
        self.__backup_config_data = None   #Implemented in load config
        
          #---------------------------------------------------------------------
        
        self.robot = dict()
        self.robot['radius'] = []
        self.robot['x'] = []
        self.robot['y'] = []
        self.robot['orient'] = []
        
        
        
        """Parameters for the addition of new agents"""
        self.new_peds_params = dict()
        
        
    
        
        state, groups, obstacles = self.loadConfig(path_to_filename=path_to_config)
        
        self.tmp = obstacles
        self.groups_vect_idxs = []
        
        
        #obs_filtered = []
        
        
        obs_filtered = [sublist for sublist in obstacles if not (sublist[0]==sublist[1] and sublist[2]==sublist[3])]
        
        
        super().__init__(state, groups, obs_filtered, config_file)
        
       
        # initiate agents (overwrite PedState Class)
        self.peds = PedState(state, groups, self.config)
        # construct forces (overwrite DesiredForce Class)
        self.forces = self.make_forces(self.config)
        
        
        # new state with current positions of "active" pedestrians are stored
        #self.current_positions = self.get_pedestrians_positions()
        #self.current_groups = self.get_pedestrians_groups()
        self.active_peds_update()
        
        
        
        
        
        
        
        
        #print(self.box_size)
        #print(self.peds_sparsity)
        
        
        self.av_max_people = round((2*self.box_size)**2 / self.peds_sparsity)
            
        self.max_population_for_new_group = int(self.av_max_people - round((self.new_peds_params['max_grp_size']+2)/2) )
        self.max_population_for_new_individual = self.max_population_for_new_group - (1+self.new_peds_params['max_single_peds'])
        
        
        
        """ Memory for pedestrians and groups target direction """
        #Initialize check for stopped group of pedestrians status
        self._stopped_groups = np.zeros((len(self.peds.groups),), dtype = bool)
        self._last_known_group_target = np.zeros((len(self.peds.groups),2))
        self._timer_stopped_group = np.zeros((len(self.peds.groups),), dtype=int)
        
        
        #Initialize check for stopped pedestrians status
        self._stopped_peds = np.zeros((self.peds.size(),), dtype = bool)
        self._last_known_ped_target = np.zeros((self.peds.size(),2))
        self._timer_stopped_peds = np.zeros((self.peds.size(),), dtype=int)
        
        
    # make_forces overrides existing function: accounts for obstacle avoidance
    def make_forces(self, force_configs): 
        """Construct forces"""
        if self.obstacle_avoidance_params == None:
            forceDes = forces.DesiredForce()
        else:
            forceDes = DesiredForce(obstacle_avoidance= True,
                                           angles = self.obstacle_avoidance_params[0],
                                           p0 = self.obstacle_avoidance_params[1],
                                           p1 = self.obstacle_avoidance_params[2],
                                           view_distance = self.obstacle_avoidance_params[3],
                                           forgetting_factor = self.obstacle_avoidance_params[4])
 
        force_list = [
            forceDes,                               ####################  changed
            forces.SocialForce(),
            forces.ObstacleForce(),
            #forces.PedRepulsiveForce(),
            # forces.SpaceRepulsiveForce(),
        ]
        group_forces = [
            forces.GroupCoherenceForceAlt(),
            GroupRepulsiveForce(),                  ####################  changed
            forces.GroupGazeForceAlt(),
        ]
        if self.scene_config("enable_group"):
            force_list += group_forces

        # initiate forces
        for force in force_list:
            force.init(self, force_configs)

        return force_list
    
    # overwrite function to account for pedestrians update
    def step_once(self):
        """step once"""            
        if self.update_peds:
            self.update_peds_on_scene()
            # only now perform step...
        forces = self.compute_forces()    
        self.peds.step(forces)
        
        self.__updateStoppingTime()
        
        if self.__enable_max_steps_stop:
            self.__unfreezeExceedingLimits()
        
        
        
        
    
    # function to get positions of currently active pedestrians only (for graphical rendering and for Lidar implementation)
    def get_pedestrians_positions(self):
        # get peds states
        peds_pos = self.get_states()[0][-1,:,:] #states_full is full history, we only want last instance
        return peds_pos[(peds_pos[:,:2]!=[0,0]).any(axis = 1),:][:,:2]


        # function to get groupings of currently active pedestrians only (for graphical rendering)
    def get_pedestrians_groups(self):
        # get peds states
        return self.get_states()[1][-1]  #states_full is full history, we only want last instance
        

    # update positions of currently active pedestrians
    def active_peds_update(self, new_positions = None, new_groups = None):
        
        if (new_positions is not None) :
            self.current_positions = new_positions
            self.current_groups = new_groups
        else:            
            self.current_positions = self.get_pedestrians_positions()
            self.current_groups = self.get_pedestrians_groups()
        
        # define vector with all groups belongings (for plotting reasons)
        groups_vect = np.zeros(self.current_positions.shape[0],dtype = int)
        for j in range(len(groups_vect)):
            for num,group in enumerate(self.current_groups, start=1):
                if j in group:
                    groups_vect[j] = num
                    break
        self.groups_vect_idxs = groups_vect


    def updateRobotCoord(self,coordinates):
        self.robot['x'] = coordinates[0]
        self.robot['y'] = coordinates[1]
        self.robot['orient'] = coordinates[2]


    def addRobot(self, action_radius, coordinates):
        self.robot['radius'] = action_radius
        self.updateRobotCoord(coordinates)


    # new function (update pedestrians on scene)
    def update_peds_on_scene(self):
        
        box_size = self.box_size
                
        # mask of pedestrians to drop because they reached their target outside of the square
        #Row of booleans indicating which pedestrian is out of bound (True) and which is still valid (False)
        drop_out_of_bounds = np.any(np.absolute(self.peds.state[:,:2])>box_size*1.2, axis = 1)
        
        #Find row indices of pedestrians out of bounds: (Needed to update groups)
        index_drop_out_of_bounds = np.where(np.any(np.absolute(self.peds.state[:,:2])>box_size*1.2, axis = 1))
        
        drop_zeroes = (self.peds.state[:,:2]==[0,0]).all(axis = 1) #Da capire ancora
        
        #Find row indices of pedestrians in [0,0] to be removed
        index_drop_zeroes = np.where(np.any(self.peds.state[:,:2]==[0,0],axis=1))
        #print(index_drop_zeroes)
        #drop agents which went out of the square (and respective groups)
        
        #Initialize mask all to true
        mask = np.ones(drop_out_of_bounds.shape, dtype = bool)
        
        #Set to False pedestrians out of bounds and zeros
        mask[drop_out_of_bounds] = False
        mask[drop_zeroes]= False
        
        #Create new pedestrians by applying the mask
        new_state = self.peds.state[mask,:]
        new_groups = self.peds.groups
        ped_to_drop = index_drop_out_of_bounds[0].tolist() + index_drop_zeroes[0].tolist()

        #Remove indexes of removed pedestrians from groups
        #self.removePedestriansFromGroups(ped_to_drop)
        index_drop = np.where(~mask)[0]
        
        mask2 = np.ones(self._stopped_peds.shape, dtype = bool)
        mask2[index_drop] = False
        
        
        #Clean pedestrians memory
        self._stopped_peds = self._stopped_peds[mask2]
        self._timer_stopped_peds = self._timer_stopped_peds[mask2]
        self._last_known_ped_target = self._last_known_ped_target[mask2]
        
        #print(self._stopped_peds.shape)

        for i in -np.sort(-index_drop):
            for num,group in enumerate(new_groups):
                group = np.array(group)
                if i in group: # if the index removed is in the group, remove it from there
                    new_groups[num] = group[~(group==i)].tolist()
            new_groups = fun_reduce_index(new_groups, i)
            

        # IMPORTANT!!before adding new pedestrians, the vector of initial speeds also has to be cleaned
        self.peds.initial_speeds = self.peds.initial_speeds[mask]
        #self.peds.state = new_state
        #self.peds.groups = self.peds.groups
        
        self.peds.update(new_state, new_groups)

        #ACTIONS
        self.__generationActionSelector()
        self.__groupActionSelector()
        self.__stopActionSelector()
        
        #self.peds.update(self.peds.state, self.peds.groups)
        #self.active_peds_update(self.peds.state[:,:2], self.peds.groups)
        self.active_peds_update()
        # re-initialize forces
        self.forces = self.make_forces(self.config)
            

    def getNotGroupedPedestrianIndexes(self): #(TESTED !!)
        """This method returns a list of pedestrian indexes which doesn't belong
        to any group"""
        idx = []
        for i in range(self.peds.size()):
            if self.peds.which_group(i) == -1:
                idx.append(i)
        
        return idx
    
    
    def removePedestriansFromGroups(self,pedestrian_indexes): #(TESTED!)
        """ This method removes pedestrians indexes from existing groups if
        belonging to any"""
        
        if not pedestrian_indexes:
            return False
        
        else:
            for index in pedestrian_indexes:
                #Check if pedestrian index belongs to any group
                if self.peds.which_group(index) != -1:
                    #Remove pedestrian from group
                    group_idx = self.peds.which_group(index)
                    self.peds.groups[group_idx].remove(index)
            return True
    
    
    def addStandaloneToExistingGroup(self, pedestrian_idx = None, destination_group = None): #(TESTED!)
        """This method adds a standalone pedestrian to an existig group inheriting
        also the group target"""
        
        square_dim = self.box_size + 1
        idx_standalone = self.getNotGroupedPedestrianIndexes()
        
        
        if not self.__enable_topology_on_stopped:
            idx_non_stopped = []
            for index in idx_standalone:
                if not self._stopped_peds[index]:
                    idx_non_stopped.append(index)
            
            idx_standalone = idx_non_stopped
        
            
        #Set max pedestrian grouping
        if not idx_standalone:
            return False
            
        if pedestrian_idx is None:
            #Select a random index from not grouped pedestrians
            
            #Select max standalone grouping
            max_ped_to_add = min(len(idx_standalone), self.new_peds_params['max_standalone_grouping'])
            
            #Choose randomm standalone pedestrian
            selected_ped = random.sample(idx_standalone, max_ped_to_add)
            
        else:
            #Check if input pedestrian is valid
            if isinstance(pedestrian_idx, int):
                pedestrian_idx = [pedestrian_idx]
                
            try:
                for ped_idx in pedestrian_idx:
                    if ped_idx not in idx_standalone:
                        #Invalid pedestrian index
                        return False
                    
                selected_ped = pedestrian_idx
                    
                if (len(selected_ped) > self.new_peds_params['max_standalone_grouping']):
                    selected_ped = random.sample(selected_ped, self.new_peds_params['max_standalone_grouping'])
                
                
            except:
                return False
            
        #Get valid group if topology deactivated
        valid_group = []
        
        if not self.__enable_topology_on_stopped:
            for i in range(len(self.peds.groups)):
                if not self._stopped_groups[i]:
                    valid_group.append(i)
        else:
            valid_group = np.arange(len(self.peds.groups)).tolist()
        
        
        
        
        
        
        if destination_group is None:
            #Select random destination group
            destination_group = random.choice(valid_group)
        
        else:
            
            if destination_group not in valid_group:
                return False
                
            
        if isinstance(selected_ped, int):
            selected_ped = [selected_ped]
        
        
        
        #Now perform assignements
        old_groups = self.peds.groups
        group = old_groups[destination_group] + selected_ped
        
        new_group = old_groups.copy()
        new_group[destination_group] = group
        
        
        #Now get group destination
        if not old_groups[destination_group]:
            #Needs to be generated group destination
            
            destination_a = random.choice([0,1,2,3])
            destination_b = random.randint(-square_dim,square_dim)*np.ones((len(selected_ped),))
            
            target_state = fill_state(destination_a, destination_b, False, self.box_size)
            
            self._stopped_groups[destination_group] = False
            self._timer_stopped_group[destination_group] = 0
            
            
            
        else:
            target_state = np.zeros((len(selected_ped),2))
            
                        
            ped_old_idx = old_groups[destination_group][0]
            target_state[:,0] = self.peds.state[ped_old_idx,4]
            target_state[:,1] = self.peds.state[ped_old_idx,5]
            
        
        self._last_known_ped_target[selected_ped, :] = [0, 0]
        self._timer_stopped_peds[selected_ped] = 0
            
        self._stopped_peds[selected_ped] = False
        
        
        #Now apply mask and update pedestrian states
        ped_state = self.peds.state
        ped_state[selected_ped,4:6] = target_state
        
        self.peds.update(ped_state, new_group)
         
        
            
        return True
            
            
            
        
    
    
    def groupStandalones(self): #(TESTED!)
        """This method takes few standalones pedestrians in the map and group
        them in order to form a new group"""
        
        #Immediately brake if there is no space for new groups and dynamic 
        #grouping is not allowed
        
        if not self.__dynamic_grouping:
            if not [] in self.peds.groups:
                return False
                
        
        square_dim = self.box_size + 1
        
        #Get indexes of all standalone pedestrians
        idx_standalone = self.getNotGroupedPedestrianIndexes()
        
        
        #Reduce valid pedestrian indices if topology deactivated
        if not self.__enable_topology_on_stopped:
            idx_non_stopped = []
            for index in idx_standalone:
                if not self._stopped_peds[index]:
                    idx_non_stopped.append(index)
            
            idx_standalone = idx_non_stopped
        
        if not idx_standalone or len(idx_standalone) == 1:
            return False
        
        
        
        #Compute new group size
        new_group_max_size = min(len(idx_standalone), self.new_peds_params['max_standalone_grouping'])
        new_group_size = random.randint(2, new_group_max_size )
        
        #Select standalones to be grouped
        chosen_ped_idx = random.sample(idx_standalone, new_group_size)
        
        if isinstance(chosen_ped_idx, int):
            chosen_ped_idx = [chosen_ped_idx] #Non ha senso se min group size è >= 2
        
        
        #Create new group from selected standalone pedestrian indexes
        groups = self.peds.groups
        if [] in groups:
            tmp_grp = groups.index([])
            groups[tmp_grp] = chosen_ped_idx
            self._stopped_groups[tmp_grp] = False
            self._last_known_group_target[tmp_grp] = [0, 0]
            self._timer_stopped_group[tmp_grp] = 0
            
        else:
            groups.append(chosen_ped_idx)
            self._stopped_groups = np.hstack((self._stopped_groups, False))
            self._last_known_group_target = np.concatenate((self._last_known_group_target, [[0, 0]]))
            self._timer_stopped_group = np.hstack((self._timer_stopped_group, 0))
            
        
        #Reset pedestrians memory
        self._stopped_peds[chosen_ped_idx] = False
        self._last_known_ped_target[chosen_ped_idx, :] = [0, 0]
        self._timer_stopped_peds[chosen_ped_idx] = 0
        
        
        #Now it is needed to update new group target
        group_destination_a = random.choice([0,1,2,3]) #0:left, 1:bottom, 2:right, 3:top
        group_destination_b = random.randint(-square_dim,square_dim)*np.ones((new_group_size,))
        
        #Now generate pedestrian target states
        target_states = fill_state(group_destination_a, group_destination_b, False, self.box_size)
        
        #Get current pedestrian states
        ped_state = self.peds.state
        
        #Update pedestrian states with new target
        ped_state[chosen_ped_idx, 4:6] = target_states
        
        
        
        self.peds.update(ped_state, groups)
        
        return True
    
    
    def group_split(self, group_index = None): #(TESTED!)
        "This method split an existing group and create a standalone group"
        
        square_dim  = self.box_size + 1
        
        #populate group valid indexes
        valid_indexes = []
        
        for n,sublist in enumerate(self.peds.groups):
            if sublist and len(sublist) >= 2:
                valid_indexes.append(n)
                
        
        #Immediately brake if there is no space for new groups and dynamic 
        #grouping is not allowed
        
        if not self.__dynamic_grouping:
            if not [] in self.peds.groups:
                return False
            
        
        if not self.__enable_topology_on_stopped:
            idx_non_stopped_groups = []
            for i in range(len(self._stopped_groups)):
                if not self._stopped_peds[i]:
                    idx_non_stopped_groups.append(i)
            
            valid_indexes = [item for item in valid_indexes if item in idx_non_stopped_groups]
            
        if not valid_indexes:
            return False
        
        if group_index is None:
            #Choose from valid index list
            group_index = random.choice(valid_indexes)
            
        else:
            
            if group_index not in valid_indexes:
                return False
            

        #Define max number of pedestrians to be removed
        max_ped_num = random.randint(1,len(self.peds.groups[group_index]))
                
        #Select pedestrians index from group to be removed and form a new group
        new_group_idx = random.sample(self.peds.groups[group_index], max_ped_num)
                
        old_groups = self.peds.groups.copy()
                
        #Start removing indexes from old array
        tmp = []
                
        for idx in old_groups[group_index]:
            if idx not in new_group_idx:
                tmp.append(idx)
                
        old_groups[group_index] = tmp
                
        #Start populating new group list of list with the new group
                
        if [] in old_groups:
            tmp_groups = old_groups.index([])
            old_groups[tmp_groups] = new_group_idx
            #Reset memory
            self._stopped_groups[tmp_groups] = False
            self._last_known_group_target[tmp_groups] = [0, 0]
            self._timer_stopped_group[tmp_groups] = 0
            
        else:
            old_groups.append(new_group_idx)
            self._stopped_groups = np.hstack((self._stopped_groups, False))
            self._last_known_group_target = np.concatenate((self._last_known_group_target, [[0, 0]]))
            self._timer_stopped_group = np.hstack((self._timer_stopped_group, 0))
            
        
        #Continue (Set target new group -> update)
                
        destination_a = random.choice([0,1,2,3])
        destination_b = random.randint(-square_dim,square_dim)*np.ones((len(new_group_idx),))
                
        #Now generate pedestrian target states
        target_states = fill_state(destination_a, destination_b, False, self.box_size)

        #Get pedestrian states:
        old_ped_state = self.peds.state
        old_ped_state[new_group_idx, 4:6] = target_states
                
        #Update states
        self.peds.update(old_ped_state, old_groups)
        
        return True
                

        
        
    def group_merge(self, group_1_index_origin = None, group_2_index_destination = None): #(TESTED!)
        "This method merge two existing groups into a single one"
        old_groups = self.peds.groups
        len_old_groups = len(self.peds.groups)
        
        #--------------------------------------
        if group_1_index_origin is not None:
            if not isinstance(group_1_index_origin, int) or group_1_index_origin < 0 or group_1_index_origin >= len_old_groups:
                return False
        
        if group_2_index_destination is not None:
            if not isinstance(group_2_index_destination, int) or group_2_index_destination < 0 or group_2_index_destination >= len_old_groups:
                return False
            
        if group_1_index_origin is not None and group_2_index_destination is not None and group_1_index_origin == group_2_index_destination:
            return False
        
        #--------------------------------------
        #There must be at least two valid group indices
        valid_indexes = []
        for n,sub_list in enumerate(old_groups):
            if sub_list:
                valid_indexes.append(n)
                
                
        if not self.__enable_topology_on_stopped:
            idx_non_stopped_groups = []
            for i in range(len(self._stopped_groups)):
                if not self._stopped_peds[i]:
                    idx_non_stopped_groups.append(i)
            
            valid_indexes = [item for item in valid_indexes if item in idx_non_stopped_groups]
            
                    
        if len(valid_indexes) <= 1:
            return False
        
        if group_1_index_origin is not None and (group_2_index_destination == None):
            if group_1_index_origin not in valid_indexes:
                return False
            
            tmp = valid_indexes.copy()
            tmp.remove(group_1_index_origin)
            
            group_2_index_destination = random.choice(tmp)
        
        if (group_1_index_origin == None) and group_2_index_destination is not None:
            if group_2_index_destination not in valid_indexes:
                return False
            
            tmp = valid_indexes.copy()
            tmp.remove(group_2_index_destination)
            
            group_1_index_origin = random.choice(tmp)
            
        
        if group_1_index_origin is not None and group_2_index_destination is not None:
            if group_1_index_origin not in valid_indexes or group_2_index_destination not in valid_indexes:
                return False
            
        
        #---------------------------------------------------------------------
        if (group_1_index_origin == None) and (group_2_index_destination == None):
            group_1_index_origin = random.choice(valid_indexes)
            tmp = valid_indexes.copy()
            
            tmp.remove(group_1_index_origin)
            group_2_index_destination = random.choice(tmp)
            
        #---------------------------------------------------------------------
        
        #Now it's time to move pedestrians from group 1 to group 2
        new_group = old_groups.copy()
        new_group[group_2_index_destination] = old_groups[group_2_index_destination] + old_groups[group_1_index_origin]
        new_group[group_1_index_origin] = []
        
        
        
        #Reset group memory
        self._stopped_groups[group_1_index_origin] = False
        self._last_known_group_target[group_1_index_origin] = [0, 0]
        self._timer_stopped_group[group_1_index_origin] = 0
        
        
        
        target_ped_state = np.zeros((len(old_groups[group_1_index_origin]), 2))
        
        old_ped = old_groups[group_1_index_origin]
        old_ped_target_idx = old_groups[group_2_index_destination][0]
        target_ped_state[:,0] = self.peds.state[old_ped_target_idx, 4]
        target_ped_state[:,1] = self.peds.state[old_ped_target_idx, 5]
        
        new_ped_state = self.peds.state
        new_ped_state[old_ped,4:6] = target_ped_state
        
        self.peds.update(new_ped_state, new_group)
        
        return True
        
        
        
    def group_stop(self, group_index = None):
        "This method select a group and stop it in the scene"
        #Check if input group index is valid
        
        if group_index is not None:
            if not isinstance(group_index, int) or group_index < 0 or group_index >= len(self.peds.groups):
                return False
        
        #Create valid list of stoppable groups
        valid_indexes = []
        for n,sub_list in enumerate(self.peds.groups):
            if sub_list and not self._stopped_groups[n]:
                valid_indexes.append(n)
        
        if not valid_indexes:
            return False
        
        
        
        if group_index is None:
            #Generate random index from valid indexes list
            group_index = random.choice(valid_indexes)
        
        
        if group_index not in valid_indexes:
            return False
        
        #Go on
        #Set group_stopped flag to true
        self._stopped_groups[group_index] = True
        
        
        
        #Get item of the first pedestrian of the group
        tmp_ped_idx = self.peds.groups[group_index][0]
        
        
        #Update last_known group direction
        self._last_known_group_target[group_index, :] = self.peds.state[tmp_ped_idx,4:6]
        #Now it is needed to set original target in the memory
        
        #Set new group pedestrian target
        
        if self.__enable_rendezvous_centroid:
            new_target = self.peds.computeCentroidGroup(group_index)
        
        else:
            new_target = self.peds.state[tmp_ped_idx,:2]
            
        
        
        new_state = self.peds.state
        mask = self.peds.groups[group_index]
        new_state[mask, 4:6] = new_target
        #new_state[mask, 2:4] = [0,0]
        
        self.peds.update(new_state, self.peds.groups)
        
        
        
        
        
        
    def unfreeze_group(self, group_index = None):
        """This method will unfreeze a stopped group returning to the original
        target direction"""
        if group_index is not None:
            if not isinstance(group_index, int) or group_index < 0 or group_index >= len(self.peds.groups):
                return False
            
        
        #Create a list of valid index group which can be unfreezed
        valid_indexes = []
        for i in range(len(self._stopped_groups)):
            if self._stopped_groups[i]:
                valid_indexes.append(i)
                
        if not valid_indexes:
            return False
        
        if group_index is None:
            group_index = random.choice(valid_indexes)
            
            
        #Unflag the list of stopped groups
        self._stopped_groups[group_index] = False
        
        #Set target of current group as the last known target
        tmp_ped_indexes = self.peds.groups[group_index]
        
        self.peds.state[tmp_ped_indexes,4:6] = self._last_known_group_target[group_index, :]
        
        #Reset last known target
        self._last_known_group_target[group_index] = [0, 0]
        
        #Reset timer
        self._timer_stopped_group[group_index] = 0
        
        
        if not self.__enable_topology_on_stopped:
            self.peds.update(self.peds.state, self.peds.groups)
            return True
        
        #Compute probability of splitting group or merge or do nothing
        
        
        
        
        action_chosen = random.choices(['split','merge','none'], [5,5,90])
        
        if action_chosen[0] == 'split':
            #Try to split current group
            success = self.group_split(group_index)
            
            if not success:
                tmp = ['merge','none']
                action = random.choices(tmp,[10,90])
                
                if action == 'merge':
                    
                    success = self.group_merge(group_1_index_origin=group_index)
                    
        elif action_chosen[0] == 'merge':
            #try to merge current group
            #print("MERGING")
            #print(group_index)
            success = self.group_merge(group_1_index_origin=group_index)
            
            if not success:
                tmp = ['split','none']
                action = random.choices(tmp, [10,90])
                
                if action == 'split':
                    success = self.group_split(group_index)
        
        else:
            #Do nothing
            action = 'none'
        
        #Update groups
        self.peds.update(self.peds.state, self.peds.groups)
        
        
        return True
        
            
        
        
    def pedestrian_stop(self, ped_index = None):
        """"This method select a pedestrian and stop it in the scene"""
        #Get pedestrian index and set destination of stopped pedestrian equals to the current position
        valid_ped_idx = self.getNotGroupedPedestrianIndexes()
        
        #Get list of stopped pedestrians
        stopped_idx = np.where(self._stopped_peds)[0].tolist()
        
        #Remove from valid ped indexes list the index of pedestrians already stopped
        new_valid_index = [item for item in valid_ped_idx if item not in stopped_idx]
        
        if not new_valid_index:
            return False
        
        #Check if pedestrian index input is valid
        if ped_index is not None:
            if isinstance(ped_index, int):
                if ped_index not in new_valid_index:
                    return False
                else:
                    ped_index = [ped_index]
                    
            elif isinstance(ped_index, list):
                for sublist in ped_index:
                    if sublist not in new_valid_index:
                        return False
                    
            else:
                
                return False
            
        else:
        #Here implement random stopping
            num_ped_to_stop = min(len(new_valid_index), self.new_peds_params['max_stopping_pedestrians'])
            
            #Choose pedestrians index to stop
            ped_index = random.sample(new_valid_index, num_ped_to_stop) #Output is a list
            
        
        """Now that the list of pedestrians we want to stop is created we need to
        update the last known target and initialize the clock"""
        
        #Update stopped flag
        self._stopped_peds[ped_index] = True
        
        #Last known target update
        self._last_known_ped_target[ped_index,:] = self.peds.state[ped_index, 4:6]
        
        #Current target update
        self.peds.state[ped_index, 4:6] = self.peds.state[ped_index, :2]
        
        return True
    
    def unfreezePedestrian(self, ped_index = None):
        """This method unfreeze the pedestrians indicated by input index"""
        
        #Get index of pedestrians which can be unfrozen
        valid_ped_idx = np.where(self._stopped_peds)[0].tolist()
        
        if not valid_ped_idx:
            return False
        
        #Check for valid input
        if ped_index is not None:
            if isinstance(ped_index, int):
                if ped_index not in valid_ped_idx:
                    return False
                else:
                    ped_index = [ped_index]
            
                
            elif isinstance(ped_index, list):
                for index in ped_index:
                    if index not in valid_ped_idx:
                        return False
                    
            else:
                
                return False
        else:
            #Select random index from list of indices of pedestrians which can be 
            #Unfrozen
            
            num_max = min(len(valid_ped_idx), self.new_peds_params['max_unfreezing_pedestrians'])
            
            ped_index = random.sample(valid_ped_idx, num_max)
            
            
        """Now that the the list of pedestrians index is create we need to update 
        the memory variables"""
        
        self._stopped_peds[ped_index] = False
        self._timer_stopped_peds[ped_index] = 0
        self.peds.state[ped_index, 4:6] = self._last_known_ped_target[ped_index, :]
        self._last_known_ped_target[ped_index, :] = [0, 0]
        
        
        if not self.__enable_topology_on_stopped:
            return True
        
        
        """ Vedere se implementare le actions"""    
        
        
        #print("TO DO!!")
        return True
        
    
    def add_new_group(self): #(TESTED!)
        """This method generate pedestrian states for new group"""
        
        #Immediately brake if there is no space for new groups and dynamic 
        #grouping is not allowed
        
        if not self.__dynamic_grouping:
            if not [] in self.peds.groups:
                return False

        square_dim = self.box_size + 1
        speed_variance_red = 10
    
        #Initialize new random group size:
        new_grp_size = random.randint(1, self.new_peds_params['max_grp_size'])
    
        #Compute side of origin for new pedestrians group
        group_origin_a = random.randint(0,3) #0:left, 1:bottom, 2:right, 3:top
    
        #Compute random group width
        group_width = (self.new_peds_params['group_width_max'] - self.new_peds_params['group_width_min'])*\
            random.random() + self.new_peds_params['group_width_min']

        #Generate group pedestrian position
        group_origin_b = random.randint(-square_dim, square_dim) + group_width*np.random.random_sample(new_grp_size) - group_width/2
    
        #Choose random destination and delete the origin side
        group_destination_a = random.choice(np.delete(np.array([0, 1, 2, 3]), group_origin_a))
        group_destination_b = random.randint(-square_dim,square_dim)*np.ones((new_grp_size,))

        #Based on group origin and group destination compute the new states of the 
        #new added pedestrians
    
        origin_states      = fill_state(group_origin_a, group_origin_b, True , self.box_size)
        destination_states = fill_state(group_destination_a, group_destination_b, False, self.box_size)
    
        #Initialize full state matrix
        new_group_states = np.concatenate( (origin_states, np.zeros(origin_states.shape) , destination_states, self.peds.default_tau*np.ones((origin_states.shape[0],1)) ) , axis = 1)
        # Compute new group desired direction
        new_group_directions = stateutils.desired_directions(new_group_states)[0]
        # Compute new group speed
        random_speeds = np.repeat((self.new_peds_params['average_speed'] + np.random.randn(new_group_directions.shape[0])/speed_variance_red)[np.newaxis,:],2,axis=0).T
        #Fill last state
        new_group_states[:,2:4] = np.multiply(new_group_directions, random_speeds)
        # new group indices
        new_group_states = np.concatenate((self.peds.state,new_group_states),axis = 0)
        new_group = self.peds.size() + np.arange(new_grp_size)

        self._stopped_peds = np.concatenate((self._stopped_peds, np.zeros((new_grp_size,), dtype = bool)))
        self._timer_stopped_peds = np.hstack((self._timer_stopped_peds, np.zeros((new_grp_size,))))
        self._last_known_ped_target = np.concatenate((self._last_known_ped_target, np.zeros((new_grp_size, 2))))
                
        
        groups = self.peds.groups
        if [] in groups:
            grp_index_free = groups.index([])
            groups[grp_index_free] = new_group.tolist()
            
            self._stopped_groups[grp_index_free] = False
            self._last_known_group_target[grp_index_free,:] = [0, 0]
            self._timer_stopped_group[grp_index_free] = 0
            
            
        else:
            groups.append(new_group.tolist())
            self._stopped_groups = np.hstack((self._stopped_groups, False))
            self._last_known_group_target = np.concatenate((self._last_known_group_target, [[0, 0]]), axis = 0)
            self._timer_stopped_group = np.hstack((self._timer_stopped_group, False))
        

        #Now update new pedestrians in the global pedestrians state
        self.peds.update(new_group_states, groups)
        
        return True


    
    def add_new_individuals(self): #(TESTED!)
        square_dim = self.box_size +1
        speed_variance_red = 10
    
        #Generate random integer representing the new pedestrians to be added
        new_pedestrians = random.randint(1,self.new_peds_params['max_single_peds'])
    
        #Initialize empty pedestrian state matrix for the new pedestrians added
        new_pedestrians_states = np.zeros((new_pedestrians, 7))
    
    
        for i in range(new_pedestrians):
            # randomly generate origin and destination of new pedestrian
            origin_a = random.randint(0,3) #0:left, 1:bottom, 2:right, 3:top
            origin_b = 2*square_dim*random.random() - square_dim
            
            destination_a = random.choice(np.delete(np.array([0, 1, 2, 3]), origin_a))
            destination_b = 2*square_dim*random.random() - square_dim
            
            # fill i-th row of the list of new pedestrian states
            new_pedestrians_states[i,:2] = fill_state(origin_a, origin_b, True, self.box_size)
            new_pedestrians_states[i,4:6] = fill_state(destination_a, destination_b, False, self.box_size)
            new_pedestrians_states[i,-1] = self.peds.default_tau
            # add new pedestrian state to list of other pedestrians
    
        #speeds update
        new_peds_directions = stateutils.desired_directions(new_pedestrians_states)[0]
        #randomize initial speeds
        random_speeds = np.repeat((self.new_peds_params['average_speed'] + np.random.randn(new_peds_directions.shape[0])/speed_variance_red)[np.newaxis,:],2,axis=0).T
        new_pedestrians_states[:,2:4] = np.multiply(new_peds_directions, random_speeds)
        
        new_pedestrians_states = np.concatenate((self.peds.state, new_pedestrians_states), axis = 0)
        
        
        #Update stopped peds array with the new pedestrians
        self._stopped_peds = np.concatenate((self._stopped_peds, np.zeros((new_pedestrians,), dtype = bool)))
        self._last_known_ped_target = np.concatenate((self._last_known_ped_target, np.zeros((new_pedestrians, 2))))
        self._timer_stopped_peds = np.hstack((self._timer_stopped_peds, new_pedestrians*[False]))
        
        self.peds.update(new_pedestrians_states, self.peds.groups)
        
        
        return True
            
    
    def _updateGroupsInfo(self):
        """ This method helps on keeping stored groups informations, needed for 
        example in group stopping"""
        
        print("TO DO!")
        
        
    def allowDynamicGrouping(self, flag):
        if not isinstance(flag, bool):
            return False
        else:
            self.__dynamic_grouping = flag
        
    
    def allowMaxStepsStop(self, flag):
        if not isinstance(flag, bool):
            return False
        else:
            self.__enable_max_steps_stop = flag
            
    def sortGroups(self):
        for i in range(len(self.peds.groups)):
            self.peds.groups[i].sort()
        
    def loadConfig(self, path_to_filename = None):
        if path_to_filename is None:
            try:
                dirname = os.path.dirname(__file__)
                parent = os.path.split(dirname)[0]
                filename = os.path.join(parent, "utils", "config", "map_config.toml")
                data = toml.load(filename)
                
            except:
                raise ValueError("Cannot load valid config toml file")
        
        else:
            if not isinstance(path_to_filename, str):
                raise ValueError("invalid input filename")
                
            else:
                try:
                    
                    data = toml.load(path_to_filename)
                
                except:
                    raise ValueError("Cannot load valid config toml file at specified path:" + path_to_filename)
        
        #Start populating class structures and attributes if no errors occured
        
        self.__backup_config_data = data
        

        maps_config_path = os.path.join ( os.path.dirname(os.path.dirname(os.path.realpath(__file__))) , 'utils', 'maps')
        path_to_map = None
        
        #Check if default map flag is activated
        if data['simulator']['flags']['default_map']:
            self.box_size = data['simulator']['default']['box_size']
            state = np.array(data['simulator']['default']['states'])
            
            obstacle = []
            obstacles_lolol = []
            
            for key in data['simulator']['default']['obstacles'].keys():
                obstacle += data['simulator']['default']['obstacles'][key]
                obstacles_lolol.append(data['simulator']['default']['obstacles'][key])
            
            groups = data['simulator']['default']['groups']
            
        else:
            #Check if map number is specified
            if not data['simulator']['flags']['random_map']:
                n = data['simulator']['custom']['map_number']
                try:
                    #keys = 
                    map_name    = natsorted(list(data['map_files'].values()))[n]
                
                except:
                    map_name = natsorted(list(data['map_files'].values()))[0]
                    raise Warning('Invalid map number: Using map 0')
                    
            else:
                
                map_name = random.choice(list(data['map_files'].values()))
                
            path_to_map = os.path.join(maps_config_path, map_name)
            
            #Here load the json file
            #----------------------------------------------------------------
            with open(path_to_map, 'r') as f:
                map_structure = json.load(f)
                
            self.box_size = max((map_structure['x_margin'][1]), (map_structure['y_margin'][1]))
            #print(path_to_map)
            #Start creating obstacles, peds ecc...
            obstacle = []
            obstacles_lolol = []
            
            for key in map_structure['Obstacles'].keys():
                
                tmp = map_structure['Obstacles'][key]['Edges'].copy()
                
                valid_edges = []
                for n, sub_list in enumerate(tmp):
                    #if not sub_list[0]==sub_list[1] and not sub_list[2]==sub_list[3]:
                    valid_edges.append(sub_list)
                

                
                obstacle += valid_edges
                obstacles_lolol.append(valid_edges)
                
                
            if not data['simulator']['flags']['random_initial_population']:
                state = np.array(data['simulator']['default']['states'])
                groups = data['simulator']['default']['groups']
                
                grouped_peds = []
                
                for group in groups:
                    grouped_peds += group
                n_peds = len(state)
                
                
            else:
                n_peds = data['simulator']['custom']['random_population']['max_initial_peds']
                index_list = np.arange(n_peds).tolist() #Available index to group
                
                #initialize state matrix
                state = np.zeros((n_peds, 6))
                groups = []
                                   
                
                #Initialize groups
                grouped_peds = []
                available_peds = index_list.copy()
                
                                
                for i in range(data['simulator']['custom']['random_population']['max_initial_groups']):
                    max_n = min(len(available_peds), data['simulator']['custom']['random_population']['max_peds_per_group'])
                    
                    group = random.sample(available_peds, max_n)
                    groups.append(group)
                    grouped_peds += group
                    
                    available_peds = [ped for ped in available_peds if ped not in group]
                    
                    
                    #generate group target for grouped peds
                    if group:
                        group_destination_a = random.choice([0,1,2,3])
                        group_destination_b = random.randint(-(self.box_size +1),self.box_size +1)*np.ones((len(group),))
                        
                        #Initial speed
                        dot_x_0 = 0.5 #Module
                        
                        #random angle
                        angle = random.uniform(-np.pi, np.pi)
                        dot_x_x = dot_x_0*np.cos(angle)
                        dot_x_y = dot_x_0*np.sin(angle)
        
                    #Based on group origin and group destination compute the new states of the 
                    #new added pedestrians
                        destination_states = fill_state(group_destination_a, group_destination_b, False, self.box_size)
                        state[group, 4:6] = destination_states
                        state[group, 2:4] = [dot_x_x, dot_x_y]
                
                #Check for state validity
                obs_recreated = Polygon()
            for i in range(n_peds):
                #Check if initial position is valid
                state[i, :2] = np.random.uniform(-self.box_size, self.box_size, (1,2))
                
                
                while True:
                        
                    for iter_num, ob in enumerate(map_structure['Obstacles'].keys()):
                            #Compute safety radius for each obstacle

                        obs_recreated.load(map_structure['Obstacles'][ob]['Vertex'])
                        
                        vert = np.array(map_structure['Obstacles'][ob]['Vertex'])
                        radius = max(np.linalg.norm(vert - obs_recreated.centre, axis = 1)) +1
                        
                        
                     
                        if np.linalg.norm(state[i, :2] - obs_recreated.centre) < radius:
                            #Generate new point, break and restart the for loop check
                                
                            state[i, :2] = np.random.uniform(-self.box_size, self.box_size, (1,2))
                            break
                        
                        #Break the endless loop and let i-index increase
                    if iter_num == len(map_structure['Obstacles'].keys())-1:
                        
                        break
                
                #Generate target
                if data['simulator']['flags']['random_initial_population']:
                    #print("Generate target")
                    if i not in grouped_peds:
                        destination_a = random.choice([0,1,2,3])
                        destination_b = random.randint(-(self.box_size +1),self.box_size +1)
                        
                        destination_state = fill_state(destination_a, destination_b, False, self.box_size)
                        state[i, 4:6] = destination_state
                        
                        dot_x_0 = 0.5
                        angle = random.uniform(-np.pi, np.pi)
                        
                        dot_x_x = dot_x_0*np.cos(angle)
                        dot_x_y = dot_x_0*np.sin(angle)
                        
                        state[i,2:4] = [dot_x_x, dot_x_y]
                        
                
                
                
            
            
                        

                            
                
                
                
        
        #---------------------------------------------------------------------
        #here load the parameters which are in common
        self.peds_sparsity = data['simulator']['custom']['ped_sparsity']
        self.update_peds = data['simulator']['flags']['update_peds']
        self.ped_generation_action_pool['actions'] = data['simulator']['generation']['actions']
        self.ped_generation_action_pool['probabilities'] = data['simulator']['generation']['probabilities']
            
        self.group_action_pool['actions'] = data['simulator']['group_actions']['actions']
        self.group_action_pool['probabilities'] = data['simulator']['group_actions']['probabilities']
        
        
        self.stopping_action_pool['actions'] = data['simulator']['stopping']['actions']
        self.stopping_action_pool['probabilities'] = data['simulator']['stopping']['probabilities']
        
        
        
        self.__dynamic_grouping = data['simulator']['flags']['allow_dynamic_grouping']
        
        self.__enable_max_steps_stop = data['simulator']['flags']['allow_max_steps_stop']
        
        self.__enable_topology_on_stopped = data['simulator']['flags']['topology_operations_on_stopped']
        
        self.__enable_rendezvous_centroid = data['simulator']['flags']['rendezvous_centroid']
        
        self.__topology_operations_on_unfreezing = data['simulator']['flags']['topology_operations_on_unfreezing']
        
        
        
        self.obstacles_lolol = obstacles_lolol #list of lists of lists of obstacles (required for dynamic animation)
        
        
        
        self.new_peds_params['max_single_peds'] = data['simulator']['generation']['parameters']['max_single_peds']
        self.new_peds_params['max_grp_size'] = data['simulator']['generation']['parameters']['max_group_size']
        self.new_peds_params['group_width_max'] = data['simulator']['generation']['parameters']['max_group_size']
        self.new_peds_params['group_width_min'] = data['simulator']['generation']['parameters']['group_width_min']
        self.new_peds_params['average_speed'] = data['simulator']['generation']['parameters']['average_speed']
        self.new_peds_params['max_standalone_grouping'] = data['simulator']['group_actions']['parameters']['max_standalone_grouping']
        self.new_peds_params['max_group_splitting'] = 5
        
        #self.new_peds_params['min_nsteps_ped_stopped'] = 10
        #self.new_peds_params['min_nsteps_group_stopped'] = 10
        self.new_peds_params['max_nsteps_ped_stopped'] = data['simulator']['stopping']['parameters']['max_nsteps_ped_stopped']
        self.new_peds_params['max_nteps_group_stopped'] = data['simulator']['stopping']['parameters']['max_nsteps_group_stopped']
        self.new_peds_params['max_stopping_pedestrians'] = data['simulator']['stopping']['parameters']['max_stopping_pedestrians']
        self.new_peds_params['max_unfreezing_pedestrians'] = data['simulator']['stopping']['parameters']['max_unfreezing_pedestrians']
        
            ############# obstacle avoidance: (no obstacle_avoidance_params means no obstacles avoidance)
        # angles to evaluate
        angles_neg = np.array([-1,-.8,-.6,-.5,-.4,-.3,-.25,-.2,-.15,-.1,-.05])
        #angles_neg = np.array([-1,-.8,-.6,-.5,-.4,-.2])
        angles_pos = np.sort(-angles_neg)
        angles = np.multiply(np.pi,np.concatenate((angles_neg,angles_pos)))
        
        #obstacles points to get the segments (commented part refers to in-function implementation)
        p0 = np.empty((0,2))
        p1 = np.empty((0,2))
        ##get obstacles on the scenes in p0,p1 format (do be moved to class attributes)
        for obi in obstacle:
            p0 = np.append(p0,np.array([obi[0],obi[2]])[np.newaxis,:],axis = 0)
            p1 = np.append(p1,np.array([obi[1],obi[3]])[np.newaxis,:],axis = 0)
        
        # obstacle_avoidance_params
        view_distance = 15
        forgetting_factor = 0.8
        obstacle_avoidance_params = [  angles, p0, p1, view_distance, forgetting_factor ]
        
        
        self.obstacle_avoidance_params = obstacle_avoidance_params
        self.obstacles_lolol = obstacles_lolol
        
        return state, groups, obstacle
    
    def __updateStoppingTime(self):
        #Get index of stopped peds
        stopped_ped_index = np.where(self._stopped_peds)[0].tolist()
        #print(stopped_ped_index)
        #print(self._timer_stopped_peds)
        #Get index of stopped groups
        stopped_groups_index = np.where(self._stopped_groups)[0].tolist()
        #print(stopped_groups_index)
        #print(self._timer_stopped_group)
        #Udate stopped step time
        
        self._timer_stopped_group[stopped_groups_index] += 1
        self._timer_stopped_peds[stopped_ped_index] += 1
        
    def __unfreezeExceedingLimits(self):
        ped_idx = np.where(self._timer_stopped_peds > self.new_peds_params['max_nsteps_ped_stopped'])[0].tolist()
        group_idx = np.where(self._timer_stopped_group > self.new_peds_params['max_nsteps_ped_stopped'])[0].tolist()
        
        self.unfreezePedestrian(ped_idx)
        
        for group in group_idx:
            self.unfreeze_group(group)
        
        
    def __generationActionSelector(self):
        ped_generations_action = copy.deepcopy(self.ped_generation_action_pool)
        while True:
            #Action selection:
            action = random.choices(ped_generations_action['actions'], ped_generations_action['probabilities'])[0]
            #print(action)
            
            if action == 'standalone_individual':
                if self.peds.size() < self.max_population_for_new_individual:
                    success = self.add_new_individuals()
                    if success:
                        break
                    else:
                        #select new action
                        index_action = ped_generations_action['actions'].index(action)
                        del ped_generations_action['actions'][index_action]
                        val = ped_generations_action['probabilities'][index_action]/len(ped_generations_action['actions'])
                        
                        del ped_generations_action['probabilities'][index_action]
                        
                        for i in range(len(ped_generations_action['probabilities'])):
                            ped_generations_action['probabilities'][i] += val
                        
                        
                else:
                    #select new action
                    index_action = ped_generations_action['actions'].index(action)
                    del ped_generations_action['actions'][index_action]
                    val = ped_generations_action['probabilities'][index_action]/len(ped_generations_action['actions'])
                        
                    del ped_generations_action['probabilities'][index_action]
                        
                    for i in range(len(ped_generations_action['probabilities'])):
                        ped_generations_action['probabilities'][i] += val
                        
                        
            elif action == 'group':
                if self.peds.size() < self.max_population_for_new_group:
                    success = self.add_new_group()
                    
                    if success:
                        break
                    
                    else:
                        #select new action
                        index_action = ped_generations_action['actions'].index(action)
                        del ped_generations_action['actions'][index_action]
                        val = ped_generations_action['probabilities'][index_action]/len(ped_generations_action['actions'])
                        
                        del ped_generations_action['probabilities'][index_action]
                        
                        for i in range(len(ped_generations_action['probabilities'])):
                            ped_generations_action['probabilities'][i] += val
                
                
                else:
                    #Select new action
                        index_action = ped_generations_action['actions'].index(action)
                        del ped_generations_action['actions'][index_action]
                        val = ped_generations_action['probabilities'][index_action]/len(ped_generations_action['actions'])
                        
                        del ped_generations_action['probabilities'][index_action]
                        
                        for i in range(len(ped_generations_action['probabilities'])):
                            ped_generations_action['probabilities'][i] += val
            
            elif action == 'both':
                if self.peds.size() < self.max_population_for_new_individual:
                    success = self.add_new_individuals()
                
                if self.peds.size() < self.max_population_for_new_group:
                    success = self.add_new_group()
                    
                break
            
            
            else:
                break
            
            
    
    
    def __groupActionSelector(self):
        topology_actions = copy.deepcopy(self.group_action_pool)
        
        while True:
            action = random.choices(topology_actions['actions'], topology_actions['probabilities'])[0]
            #print(action)
            
            if action == 'split':
                success = self.group_split()
                if success:
                    break
                else:
                    #Select new action
                    index_action = topology_actions['actions'].index(action)
                    del topology_actions['actions'][index_action]
                    val = topology_actions['probabilities'][index_action]/len(topology_actions['actions'])
                        
                    del topology_actions['probabilities'][index_action]
                        
                    for i in range(len(topology_actions['probabilities'])):
                        topology_actions['probabilities'][i] += val
            
            elif action == 'merge':
                success = self.group_merge()
                if success:
                    break
                else:
                    #Select new action
                    index_action = topology_actions['actions'].index(action)
                    del topology_actions['actions'][index_action]
                    val = topology_actions['probabilities'][index_action]/len(topology_actions['actions'])
                        
                    del topology_actions['probabilities'][index_action]
                        
                    for i in range(len(topology_actions['probabilities'])):
                        topology_actions['probabilities'][i] += val
                        
    
            elif action == 'group_standalone':
                success = self.groupStandalones()
                if success:
                    break
                else:
                    #Select new action
                    index_action = topology_actions['actions'].index(action)
                    del topology_actions['actions'][index_action]
                    val = topology_actions['probabilities'][index_action]/len(topology_actions['actions'])
                        
                    del topology_actions['probabilities'][index_action]
                        
                    for i in range(len(topology_actions['probabilities'])):
                        topology_actions['probabilities'][i] += val
                        
                        
            elif action == 'toExisting':
                success = self.addStandaloneToExistingGroup()
                if success:
                    break
                else:
                    #Select new action
                    index_action = topology_actions['actions'].index(action)
                    del topology_actions['actions'][index_action]
                    val = topology_actions['probabilities'][index_action]/len(topology_actions['actions'])
                    
                    del topology_actions['probabilities'][index_action]
                    
                    for i in range(len(topology_actions['probabilities'])):
                        topology_actions['probabilities'][i] += val
                        
                        
            else:
                break
                

    

    def __stopActionSelector(self):
        #self.stopping_action_pool['actions'] = ['stop_pedestrian','stop_group','move_pedestrian','move_group','none']
        stop_actions = copy.deepcopy(self.stopping_action_pool)
        
        while True:
            action = random.choices(stop_actions['actions'], stop_actions['probabilities'])[0]
            #print(action)
            if action == 'stop_pedestrian':
                success = self.pedestrian_stop()
                if success:
                    break
                else:
                    #Select new action
                    index_action = stop_actions['actions'].index(action)
                    del stop_actions['actions'][index_action]
                    val = stop_actions['probabilities'][index_action]/len(stop_actions['actions'])
                    
                    del stop_actions['probabilities'][index_action]
                    
                    for i in range(len(stop_actions['probabilities'])):
                        stop_actions['probabilities'][i] += val
                        
                        
            elif action == 'stop_group':
                success = self.group_stop()
                if success:
                    break
                else:
                    #Select new action
                    index_action = stop_actions['actions'].index(action)
                    del stop_actions['actions'][index_action]
                    val = stop_actions['probabilities'][index_action]/len(stop_actions['actions'])
                    
                    del stop_actions['probabilities'][index_action]
                    
                    for i in range(len(stop_actions['probabilities'])):
                        stop_actions['probabilities'][i] += val
                        
                        
            elif action == 'move_pedestrian':
                success = self.unfreezePedestrian()
                if success:
                    break
                else:
                    #Select new action
                    index_action = stop_actions['actions'].index(action)
                    del stop_actions['actions'][index_action]
                    val = stop_actions['probabilities'][index_action]/len(stop_actions['actions'])
                    
                    del stop_actions['probabilities'][index_action]
                    
                    for i in range(len(stop_actions['probabilities'])):
                        stop_actions['probabilities'][i] += val
                        
                        
            elif action == 'move_group':
                success = self.unfreeze_group()
                if success:
                    break
                else:
                    #Select new action
                    index_action = stop_actions['actions'].index(action)
                    del stop_actions['actions'][index_action]
                    val = stop_actions['probabilities'][index_action]/len(stop_actions['actions'])
                    
                    del stop_actions['probabilities'][index_action]
                    
                    for i in range(len(stop_actions['probabilities'])):
                        stop_actions['probabilities'][i] += val
                        
                        
                        
            else:
                break
