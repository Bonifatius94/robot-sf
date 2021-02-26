# -*- coding: utf-8 -*-
"""
Created on Wed Aug 26 11:23:20 2020

@author: Enrico Regolin
"""

import math, random
import numpy as np
from pysocialforce.utils import stateutils
import matplotlib.pyplot as plt


#####################################
# functions used to change directions

# check vectorization of these functions
def line_segment(p0, p1):
    A = p0[:,1] - p1[:,1]
    B = p1[:,0] - p0[:,0]
    C = p0[:,0]*p1[:,1] - p1[:,0]*p0[:,1]
    return np.array([A, B, -C]).T


# check vectorization of these functions
def lines_intersection(L1, L2, p0_L1, p1_L1, p0_L2, p1_L2):
    x_min_L1 = np.tile(np.minimum(p0_L1[:,0],p1_L1[:,0])[:,np.newaxis],(1,L2.shape[0]))
    x_max_L1 = np.tile(np.maximum(p0_L1[:,0],p1_L1[:,0])[:,np.newaxis],(1,L2.shape[0]))

    y_min_L1 = np.tile(np.minimum(p0_L1[:,1],p1_L1[:,1])[:,np.newaxis],(1,L2.shape[0]))
    y_max_L1 = np.tile(np.maximum(p0_L1[:,1],p1_L1[:,1])[:,np.newaxis],(1,L2.shape[0]))


    x_min_L2 = np.tile(np.minimum(p0_L2[:,0],p1_L2[:,0])[np.newaxis,:],(L1.shape[0],1))
    x_max_L2 = np.tile(np.maximum(p0_L2[:,0],p1_L2[:,0])[np.newaxis,:],(L1.shape[0],1))

    y_min_L2 = np.tile(np.minimum(p0_L2[:,1],p1_L2[:,1])[np.newaxis,:],(L1.shape[0],1))
    y_max_L2 = np.tile(np.maximum(p0_L2[:,1],p1_L2[:,1])[np.newaxis,:],(L1.shape[0],1))
    
    D  = L1[:,0][:,np.newaxis] * L2[:,1][np.newaxis,:] - L1[:,1][:,np.newaxis] * L2[:,0][np.newaxis,:]
    Dx = L1[:,2][:,np.newaxis] * L2[:,1][np.newaxis,:] - L1[:,1][:,np.newaxis] * L2[:,2][np.newaxis,:]
    Dy = L1[:,0][:,np.newaxis] * L2[:,2][np.newaxis,:] - L1[:,2][:,np.newaxis] * L2[:,0][np.newaxis,:]
    #if (D!=0).all():
    with np.errstate(divide='ignore', invalid='ignore'): # np.errstate(invalid='ignore'):
        x = Dx / D
        y = Dy / D
        nan_mask = np.logical_or.reduce(( (x<x_min_L1), (x>x_max_L1), (y<y_min_L1) , (y>y_max_L1) , (x<x_min_L2) , (x>x_max_L2) , (y<y_min_L2) , (y>y_max_L2)   ))
    
    x[nan_mask] = np.NAN
    y[nan_mask] = np.NAN
    
    return x,y


def rotate_segment(origin, point, angle):
    """
    Rotate a point counterclockwise by a given array of angles around a given origin.
    The angle should be given in radians.
    """
    ox, oy = origin
    px, py = point

    qx = ox + np.cos(angle) * (px - ox) - np.sin(angle) * (py - oy)
    qy = oy + np.sin(angle) * (px - ox) + np.cos(angle) * (py - oy)
    return qx, qy


###############################################################################################################


def change_direction(p0,p1,current_positions,destinations,view_distance, angles, direction, desired_directions):

    #1. find pedestrians who are headed towards an obstacle (within horizon defined by view_distance)
    L_directions = line_segment(current_positions, destinations)
    L_obstacles  = line_segment(p0, p1)
    
    R = lines_intersection(L_directions, L_obstacles, current_positions, destinations, p0, p1)
    intersections_coordinates = np.stack((R[0],R[1]))
                
    distances = intersections_coordinates -  (np.repeat(current_positions.T[:,:,None], intersections_coordinates.shape[2], axis=2))
    with np.errstate(invalid='ignore'):
        peds_collision_indices = (np.sqrt((distances**2).sum(axis = 0)) < view_distance).any(axis = 1)
    
    #2. only for these, evaluate trajectories which deviate from original directions, by changing angles (within predefined angular and distance ranges)
    #3. select obstacle-free direction with least angular deviation, or (if not available) angle with most distant obstacle  
    
    collision_states = current_positions[peds_collision_indices]
    close_targets = collision_states + view_distance * desired_directions[peds_collision_indices]
    
    if collision_states.shape[0]==1:
        # generate array of possible destinations, based on angles considered
        wide_scope = rotate_segment(collision_states.reshape(2), close_targets.reshape(2), angles)
        wide_scope__ = np.stack((wide_scope[0],wide_scope[1]),axis = 1)  # vectorize it
        
        # get all intersections of new array with existing objects
        L_eval_dirs = line_segment(collision_states.reshape(1,2), wide_scope__)
        R = lines_intersection(L_eval_dirs, L_obstacles, collision_states.reshape(1,2), wide_scope__, p0, p1)
        intersections_coordinates = np.stack((R[0],R[1]))
        
        ### calculate distances from intersections
        dist_0 = intersections_coordinates[0]-collision_states.reshape(2)[0]
        dist_1 = intersections_coordinates[1]-collision_states.reshape(2)[1]
        my_dist = np.sqrt((np.stack((dist_0,dist_1))**2).sum(axis = 0))
        my_dist = np.minimum(view_distance,my_dist)
        
        ### choose angles without intersections
        idxs_nan = np.where(np.isnan(my_dist).all(axis = 1))[0]  #generated as tuple
        idx_used =  np.argmin(np.absolute(idxs_nan - len(angles)/2))
        
        ped_idx = np.where(peds_collision_indices)[0] # indices of directions to be changed
        
        #generate new destinations
        new_goal = rotate_segment(collision_states.reshape(2), destinations[ped_idx][0,:], angles[idx_used] )
        new_direction = ([new_goal[0], new_goal[1] ]- collision_states.reshape(2))/np.linalg.norm(new_goal - collision_states)
        direction[ped_idx] = new_direction
       
        ### same as above, iteratively
    elif collision_states.shape[0]>1:
        for i in range(collision_states.shape[0]): 
            wide_scope = rotate_segment(collision_states[i].reshape(2), close_targets[i].reshape(2), angles)
            wide_scope__ = np.stack((wide_scope[0],wide_scope[1]),axis = 1)
    
            L_eval_dirs = line_segment(collision_states[i][np.newaxis,:], wide_scope__)
            R = lines_intersection(L_eval_dirs, L_obstacles, collision_states[i][np.newaxis,:], wide_scope__, p0, p1)
            intersections_coordinates = np.stack((R[0],R[1]))
            dist_0 = intersections_coordinates[0]-collision_states[i][0]
            dist_1 = intersections_coordinates[1]-collision_states[i][1]
            my_dist = np.sqrt((np.stack((dist_0,dist_1))**2).sum(axis = 0))
            my_dist = np.minimum(view_distance,my_dist)
            
            idxs_nan = np.where(np.isnan(my_dist).all(axis = 1))[0]  #generated as tuple
            idx_used =  np.argmin(np.absolute(idxs_nan - len(angles)/2))
            
            ped_idx = np.where(peds_collision_indices)[0][i]
            
            new_goal = rotate_segment(collision_states[i].reshape(2), destinations[ped_idx], angles[idx_used] )
            new_direction = (new_goal - collision_states[i])/np.linalg.norm(new_goal - collision_states[i])
            direction[ped_idx] = new_direction
    ##########
    return direction, peds_collision_indices


###################################################################################
###################################################################################
# functions for simulator.py


def fill_state(coordinate_a, coordinate_b, origin,box_size):
    if origin:
        distance = box_size *1.1
    else:
        distance = box_size *1.6
        
    if isinstance(coordinate_b,np.ndarray):
        dim = len(coordinate_b)
        mydict = {
            0: np.concatenate( (-distance*np.ones([dim,1]),coordinate_b[:, np.newaxis]) , axis = 1  ) ,
            1: np.concatenate( (coordinate_b[:, np.newaxis] , -distance*np.ones([dim,1]) ), axis = 1 ),
            2: np.concatenate( (distance*np.ones([dim,1]),coordinate_b[:, np.newaxis] ), axis = 1 ) ,
            3: np.concatenate( (coordinate_b[:, np.newaxis] , distance*np.ones([dim,1]) ), axis = 1 )
        }
    else:
        mydict = {
            0: np.array([-distance ,coordinate_b]) ,
            1: np.array([coordinate_b , -distance] ),
            2: np.array([distance, coordinate_b]) ,
            3: np.array([coordinate_b , distance] )
        }
    return mydict[coordinate_a]


# function used to correctly update groups indices after states are removed
def fun_reduce_index(list_of_lists, num):
    for idx_out,a_list in enumerate(list_of_lists):
        for idx,item in enumerate(a_list):
            if item>num:
                a_list[idx] = item-1
        list_of_lists[idx_out] = a_list        
    return list_of_lists



def add_new_group(box_size, max_grp_size, n_pedestrians_actual, group_width_max, group_width_min, tau, average_speed, speed_variance_red):
    # generate states of new group
    square_dim = box_size +1
    
    #Initialize new random new group size
    new_grp_size = np.random.randint(2,max_grp_size)
    
    group_origin_a = np.random.randint(0,4) #0:left, 1:bottom, 2:right, 3:top
    group_width = (group_width_max-group_width_min)*np.random.random_sample()+ group_width_min
    
    #Generate pedestrians group position
    group_origin_b = np.random.randint(-square_dim,square_dim) + group_width*np.random.random_sample(new_grp_size)-group_width/2
    
    #Choose random destination and delete the origin
    group_destination_a = np.random.choice(np.delete(np.array([0, 1, 2, 3]), group_origin_a))
    group_destination_b = np.random.randint(-square_dim,square_dim)*np.ones((new_grp_size,))                                        
    
    
    origin_states      = fill_state(group_origin_a, group_origin_b, True , box_size)
    destination_states = fill_state(group_destination_a, group_destination_b, False,box_size)
    
    
    new_group_states = np.concatenate( (origin_states, np.zeros(origin_states.shape) , destination_states, tau*np.ones((origin_states.shape[0],1)) ) , axis = 1)
    # define initial speeds of group
    new_group_directions = stateutils.desired_directions(new_group_states)[0]
    random_speeds = np.repeat((average_speed+np.random.randn(new_group_directions.shape[0])/speed_variance_red)[np.newaxis,:],2,axis=0).T
    new_group_states[:,2:4] = np.multiply(new_group_directions, random_speeds)
    # new group indices
    new_group = n_pedestrians_actual+np.arange(new_grp_size)
    
    return new_group_states, new_group


def add_new_individuals(box_size, max_single_peds, tau, average_speed = 0.5,speed_variance_red = 10 ):
    square_dim = box_size +1
    
    #Generate random integer representing the new pedestrians to be added
    new_pedestrians = np.random.randint(1,max_single_peds)
    
    #Initialize empty pedestrian state matrix for the new pedestrians added
    new_pedestrians_states = np.zeros((new_pedestrians, 7))
    
    
    for i in range(new_pedestrians):
        # randomly generate origin and destination of new pedestrian
        origin_a = np.random.randint(0,4) #0:left, 1:bottom, 2:right, 3:top
        origin_b = 2*square_dim*np.random.random_sample() - square_dim
        destination_a = np.random.choice(np.delete(np.array([0, 1, 2, 3]), origin_a))
        destination_b = 2*square_dim*np.random.random_sample() - square_dim
        # fill i-th row of the list of new pedestrian states
        new_pedestrians_states[i,:2]=fill_state(origin_a, origin_b, True,box_size)
        new_pedestrians_states[i,4:6]=fill_state(destination_a, destination_b, False,box_size)
        new_pedestrians_states[i,-1] = tau
        # add new pedestrian state to list of other pedestrians
    
    #speeds update
    new_peds_directions = stateutils.desired_directions(new_pedestrians_states)[0]
    #randomize initial speeds
    random_speeds = np.repeat((average_speed+np.random.randn(new_peds_directions.shape[0])/speed_variance_red)[np.newaxis,:],2,axis=0).T
    new_pedestrians_states[:,2:4] = np.multiply(new_peds_directions, random_speeds)
                
    return new_pedestrians_states



###################################################################################
###################################################################################
# clear py_cache folders after execution as main

import shutil
import os

# clear pycache from tree
def clear_pycache(path):

    for directories, subfolder, files in os.walk(path):
        if os.path.isdir(directories):
            if directories[::-1][:11][::-1] == '__pycache__':
                            shutil.rmtree(directories)
                            

            
            
        
