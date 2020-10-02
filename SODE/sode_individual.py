import sys
sys.path.insert(0,'../')
from glennopt.base_classes import Individual
from glennopt.helpers import Parameter
from typing import TypeVar,List
T = TypeVar('T', bound='Parameter')
parameter_list = List[T]


class SODE_Individual(Individual):
    '''
    This class represents each individual or "evaluation". In each evaluation there are a set of parameters for objectives as well as additional parameters that are kept track. 
    '''
    def __init__(self,eval_parameters:parameter_list,objectives:parameter_list = None,performance_parameters:parameter_list = None):
        '''
            Initializes an individual 
            An individual evaluation contains the "evaluation parameters", "objectives", "performance_parameters"

        '''       
        super().__init__(eval_parameters=eval_parameters, objectives=objectives, performance_parameters=performance_parameters) 
        self.Position = 0