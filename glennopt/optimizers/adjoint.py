"""
    adjoint - gradient based optimization 
"""
import os, shutil
import copy, random
from typing import Dict, List, Tuple
from scipy.optimize import minimize, Bounds, least_squares
import numpy as np
from tqdm import trange

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.optim import LBFGS, AdamW
from torch.utils.data import Dataset
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, MinMaxScaler

from ..helpers import MultiLayerLinear 
from ..helpers import diversity, distance, set_eval_parameters
from ..helpers import non_dominated_sorting, find_intercepts, uniform_reference_points, sort_and_select_population
from ..helpers import compute_mse, transform_data
from ..base import Parameter, Individual, Optimizer
from .nsga3 import find_intercepts
individual_list = List[Individual]

@torch.no_grad()
def adjoint_objective_func(x0:np.ndarray,model:nn.Module,reference_points:List[np.ndarray],intercepts:np.ndarray,dist_index:int,best_point:np.ndarray, labels_scaler:List[MinMaxScaler], features_scaler:List[MinMaxScaler]):
    """Objective function of adjoint using neural networks. The goal is to use this function to find values of x0 that minimize the distance to the reference point

    Args:
        x0 (np.ndarray): [description]
        model (nn.Module): [description]
        reference_points (List[np.ndarray]): [description]
        intercepts (np.ndarray)
    """
    x0_2 = copy.deepcopy(x0)
    for l in range(len(features_scaler)):
        x0_2[l] = features_scaler[l].transform(x0_2[l].reshape(-1,1))

    x0_2 = torch.as_tensor(x0_2,dtype=torch.float32)
    fitnesses = model(x0_2)
    fitnesses = fitnesses.detach().numpy()    
    for f in range(len(labels_scaler)):        
        fitnesses[f] = labels_scaler[f].inverse_transform(fitnesses[f].reshape(-1,1)*reference_points[dist_index][f])

    return np.sum(fitnesses[f])

def calculate_distance(fitnesses:np.ndarray, reference_points:List[Tuple[float]], best_point:np.ndarray, intercepts:np.ndarray):
    """Associates individuals to reference points and calculates niche number. Corresponds to Algorithm 3 of Deb & Jain (2014).

    Args:
        fitnesses (np.ndarray): These are a list of unnormalized objective values from all individuals.
        reference_points (List[Tuple[float]]): List of tuples representing the ideal normalized pareto front/surface. Example for 2 objectives [ [0,1], [0.25, 0.75],[0.5, 0.5], [0.75, 0.25], [1, 0] ]
        best_point (np.ndarray): Array representing the best individual's objective. Example for 2 objectives [7.28, -4.07]
        intercepts (np.ndarray): [description]

    Returns:
        [type]: [description]
    """
    # Normalize by ideal point and intercepts
    fn = (fitnesses - best_point) / (intercepts - best_point)

    # Create distance matrix
    fn = np.repeat(np.expand_dims(fn, axis=1), len(reference_points), axis=1)
    norm = np.linalg.norm(reference_points, axis=1)

    distances = np.sum(fn * reference_points, axis=2) / norm.reshape(1, -1)
    distances = distances[:, :, np.newaxis] * reference_points[np.newaxis, :, :] / norm[np.newaxis, :, np.newaxis]
    distances = np.linalg.norm(distances - fn, axis=2)

    # Retrieve min distance niche index
    # niches = np.argmin(distances, axis=1)
    # distances = distances[range(niches.shape[0]), niches]

    return distances

class Adjoint(Optimizer):
    def __init__(self,eval_command:str = "python evaluation.py", eval_folder:str = "Evaluation", optimization_folder:str=None,single_folder_eval:bool=False, overwrite_input_file:bool=False, linear_network:List[int]=[16,16,16,16],epochs:int=200, train_test_split:float=0.8,pareto_resolution:int=32):
        """The objective of adjoint is to find the minimum of the jacobian of the evaluation parameters.

        Args:
            eval_command (str, optional): [description]. Defaults to "python evaluation.py".
            eval_folder (str, optional): [description]. Defaults to "Evaluation".
            optimization_folder (str, optional): Folder where the optimization and doe work should be stored in. Defaults to None.
            single_folder_eval (bool, optional): Evaluate within a single folder and not make a bunch of folders . Defaults to False.
            overwrite_input_file (bool, optional): whether or not to overwrite the input file with new data when restarting a simulation. Defaults to False.
            linear_network (list, optional): Size of MultiLinear network. Defaults to [128,256,256].
            epochs (int, optional): Number of epochs to train neural network for 
            train_test_split (float, optional): Number of datapoints to be assigned to train and test
            pareto_resolution (int, optional)
        """
        super().__init__(name="adjoint",eval_command=eval_command,eval_folder=eval_folder, opt_folder=optimization_folder,single_folder_eval=single_folder_eval,overwrite_input_file=overwrite_input_file)
        
        self.individuals = None
        self.linear_network = linear_network
        self.epochs = epochs
        self.train_test_split = train_test_split
        self.pareto_resolution = pareto_resolution
        self.model = None
        self.optimizer = None

        self.label_scalers = None
        self.feature_scalers = None
        self.labels_str = None
        self.features_str = None


    def train(self,individuals:List[Individual],retrain:bool=False):
        """Trains the neural network to predict the output given an input 
    
        Optimizer (LBFGS): 
            https://johaupt.github.io/python/pytorch/neural%20network/optimization/pytorch_lbfgs.html 

        Args:
            individuals (List[Individual]): [description]
            retrain (bool, Optional): (True) retrains the existing model on new data. (False) create a new model

        Returns:
            Tuple[float float]: Train Loss and test loss 
        """
        # * Normalizing the Data
        if retrain: # If we simply train it with more data then there's no reason create new normalization scalers
            normalized_individuals, label_scalers, feature_scalers, labels_str, features_str = transform_data(individuals,self.label_scalers,self.feature_scalers)
        else:
            normalized_individuals, label_scalers, feature_scalers, labels_str, features_str = transform_data(individuals)
        self.label_scalers = label_scalers
        self.feature_scalers = feature_scalers
        self.labels_str = labels_str
        self.features_str = features_str

        labels = torch.as_tensor(np.array([ind.objectives for ind in normalized_individuals]),dtype=torch.float32)
        features = torch.as_tensor(np.array([ind.eval_parameters for ind in normalized_individuals]),dtype=torch.float32)
        
        # Transform
        data = list(zip(features,labels))
        test_size = int(len(data)*(1-self.train_test_split))
        train_size = int(len(data) - test_size)
        train_dataset, test_dataset = train_test_split(data,test_size=test_size,train_size=train_size,shuffle=True)
        train_dl = DataLoader(train_dataset,batch_size=128,shuffle=True)
        test_dl = DataLoader(test_dataset,batch_size=128,shuffle=False)
        # * Defining the Model        
        n_inputs = features.shape[1]
        n_outputs = labels.shape[1]

        if self.model is None or retrain == False:
            self.model = MultiLayerLinear(n_inputs,n_outputs,h_sizes=self.linear_network)
            # self.optimizer = LBFGS(self.model.parameters(), lr=0.0001,history_size=100, max_eval=int(20*1.25), max_iter=20)
            self.optimizer = AdamW(self.model.parameters())

        criterion = nn.MSELoss()
        
        for epoch in range(self.epochs):
            train_running_loss = 0 
            n_train = 0
            self.model.train()
            for i, (x, y) in enumerate(train_dl):
                batch_size = x.shape[0]
                self.optimizer.zero_grad()
                y_pred = self.model(x)
                loss = criterion(y_pred, y)
                loss.backward() # Zero gradients, backward pass, and update weights
                self.optimizer.step()
                # calculate the loss again for monitoring
                train_running_loss += loss.item()
                n_train += batch_size
            
            test_loss = 0
            n_test = 0
            self.model.eval()
            for j, (x,y) in enumerate(test_dl):
                batch_size = x.shape[0]
                y_pred = self.model(x)
                test_loss += criterion(y_pred, y).item()
                n_test += batch_size
            train_running_loss /= n_train
            test_loss /= n_test
        return train_running_loss, test_loss


    def optimize_from_population(self,pop_start:int,n_generations:int):
        """Reads the values of a population, this can be a DOE or a previous evaluation
            Starts the optimization 

            Inputs:
                pop_start (-1 for DOE), reads the population folder and starts at pop_start+1
                n_generations - number of generations to run for
        """
        # * Read in all the results of the DOE, this should be done by a single thread
        # Check restart file, if not read the population
        self.load_history_file()
        ref_points = uniform_reference_points(len(self.objectives), p=self.pareto_resolution, scaling=None)

        all_individuals = list() 

        newIndividuals = self.read_calculation_folder() # Use all individuals, there's no restart file
        newIndividuals = [item for sublist in newIndividuals for item in sublist]  # Flattens the list of lists
        lb = [ep.min_value for ep in self.eval_parameters]
        ub = [ep.max_value for ep in self.eval_parameters]
        bounds = Bounds(lb,ub)
        if (len(newIndividuals)<self.pareto_resolution):
            raise Exception("Number of individuals in the restart file is less than the population size."
                + " lower the population size or increase the DOE count(if restarting from a DOE)")

        # Do this before going into the train loop. This part of the code should happen after a new population is evaluated 
        individuals,best_point, worst_point, extreme_points = sort_and_select_population(individuals=newIndividuals,reference_points=ref_points, pop_size=self.pareto_resolution)
        
        all_individuals.extend(copy.deepcopy(newIndividuals))
        newIndividuals=individuals
        for pop in range(pop_start+1,pop_start+n_generations):  # Population Loop 
            ''' 
                Train a Neural network on Individuals. Initially this is all the individuals
            '''
            train_loss, test_loss = self.train(copy.deepcopy(all_individuals), False)   

            label_scalers = [self.label_scalers[l] for l in self.labels_str]
            feature_scalers = [self.feature_scalers[l] for l in self.features_str]
            '''
                Run parts of NSGA3 code to find intercepts 
            '''
            pareto_fronts = non_dominated_sorting(individuals,self.pareto_resolution)
            fitnesses = np.array([ind.objectives for f in pareto_fronts for ind in f])
            fitnesses *= -1            

            front_worst = np.max(fitnesses[:sum(len(f) for f in pareto_fronts),:],axis=0)
            intercepts = find_intercepts(extreme_points,best_point,worst_point,front_worst)

            '''
                Calculate new evaluation points using scipy minimization BFGS method
                Broyden Fletcher Goldfarb Shanno algorithm
                https://en.wikipedia.org/wiki/Broyden%E2%80%93Fletcher%E2%80%93Goldfarb%E2%80%93Shanno_algorithm
            '''
            features = np.array([ind.eval_parameters for ind in individuals])       # Normalized Features
            newIndividuals.clear()
            # adjoint_objective_func(res.x,self.model,ref_points,intercepts,o, best_point,label_scalers,feature_scalers)
            for o in range(self.pareto_resolution):
                x0 = features[random.randrange(0,len(features))]
                # least_squares(adjoint_objective_func,x0,jac=)
                res = minimize(adjoint_objective_func,x0,bounds=bounds,method="Powell",args=(self.model,ref_points,intercepts,o, best_point,label_scalers,feature_scalers))
                adjoint_objective_func(res.x,self.model,ref_points,intercepts,o, best_point,label_scalers,feature_scalers)                
                newIndividuals.append(
                    Individual(eval_parameters=set_eval_parameters(self.eval_parameters,copy.deepcopy(res.x)),
                        objectives=copy.deepcopy(self.objectives),performance_parameters=copy.deepcopy(self.performance_parameters))
                        )
            # newIndividuals = inverse_transform_data(self.label_scalers,self.feature_scalers,newIndividuals)
            # Evaluate
            self.evaluate_population(newIndividuals,pop)
            newIndividuals = self.read_population(pop)
            mse = compute_mse(individuals,newIndividuals)
            print(f"POP {pop} mse {mse:03e}")

            # Sort and select
            pop_diversity = diversity(newIndividuals)       # Calculate diversity 
            pop_dist = distance(individuals,newIndividuals) # Calculate population distance between past and future
            all_individuals.extend(copy.deepcopy(newIndividuals))
            newIndividuals.extend(individuals)
            # TODO: Save the model and optimizer
            # Sort and select 2x the amount of individuals for training 
            individuals,best_point, worst_point, extreme_points = sort_and_select_population(individuals=newIndividuals,reference_points=ref_points, pop_size=self.pareto_resolution)

            self.append_restart_file(newIndividuals)        # Keep the last designs
            self.append_history_file(pop,individuals[0],pop_diversity,pop_dist,train_loss,test_loss,mse)
    
            if self.single_folder_eval:
                # Delete the population folder
                population_folder = os.path.join(self.optimization_folder,self.__check_population_folder__(pop))
                if os.path.isdir(population_folder):
                    shutil.rmtree(population_folder)            

    def add_eval_parameters(self,eval_params:List[Parameter]):
        """Add evaluation parameters. This is part of the initialization    

        Args:
            eval_params (List[Parameter]): Add in a list of evaluation parameters 

        """
        self.eval_parameters = eval_params # Sets base class variable

    def add_objectives(self,objectives:List[Parameter]):
        """Add the objectives 

        Args:
            objectives (List[Parameter]): [description]
        """
        self.objectives = objectives # Sets base class variable

    def add_performance_parameters(self,performance_params:List[Parameter] = None):
        """Add performance parameters 

        Args:
            performance_params (List[Parameter], optional): [description]. Defaults to None.
        """
        self.performance_parameters = performance_params # Sets base class variable
    
    def start_doe(self,doe_individuals:List[Individual]=None,doe_size:int=128):
        """Starts a design of experiments. This generates the parameters for the individuals to be evaluated and executes each case. If the DOE has already started and there is an output file for an individual then the individual won't be evaluated    

        Args:
            doe_individuals (List[Individual], optional): List of individuals. Defaults to None.
            doe_size (int, optional): [description]. Defaults to 128.
        """
        if doe_individuals is None:
            doe_individuals = []
            for i in trange(doe_size):
                parameters = copy.deepcopy(self.eval_parameters)
                for eval_param in parameters:
                    eval_param.value = np.random.uniform(eval_param.min_value,eval_param.max_value,1)[0]
                doe_individuals.append(Individual(eval_parameters=parameters,objectives=self.objectives, performance_parameters = self.performance_parameters))
     
        # * Begin the evaluation
        self.evaluate_population(individuals=doe_individuals,population_number=-1)
        # * Read the DOE
        individuals = self.read_population(population_number=-1)
        self.append_restart_file(individuals)
        
        if self.single_folder_eval: 
            # Delete the population folder
            population_folder = os.path.join(self.optimization_folder,self.__check_population_folder__(-1))
            if os.path.isdir(population_folder):
                shutil.rmtree(population_folder)


