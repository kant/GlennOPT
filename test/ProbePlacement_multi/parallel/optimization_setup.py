"""
    Simple, non parallel optimization set up example. 
"""
import sys,os
sys.path.insert(0,'../../../')
from glennopt.helpers import Parameter
from glennopt.nsga3 import de_mutation_type, mutation_parameters, NSGA3
import numpy as np

eval_parameters = list()

# Define evaluation parameters 
nProbes = 10
minSpacing = 3
probeSpacing = 360/nProbes
tLo     = np.zeros(nProbes)
tHi     = np.zeros(nProbes)
for i in range(nProbes):
    tLo[i] = probeSpacing*i
    if i != nProbes-1:
        tHi[i] = probeSpacing*(i+1) - minSpacing
    else:
        tHi[-1] = probeSpacing*(i+1)    
    eval_parameters.append(Parameter(name="x"+str(i+1),min_value=tLo[i],max_value=tHi[i]))
constraints = (tLo,tHi)

# Generate the DOE
current_dir = os.getcwd()
pop_size = 48
ns = NSGA3(eval_script = "Evaluation/evaluation.py", eval_folder="Evaluation",pop_size=pop_size,optimization_folder=current_dir)

ns.add_eval_parameters(eval_params = eval_parameters)

objectives = list()
objectives.append(Parameter(name='objective1'))
objectives.append(Parameter(name='objective2'))
ns.add_objectives(objectives=objectives)

perf_parameters = list()
perf_parameters.append(Parameter(name='PearsonR',min_value=None,max_value=None))
perf_parameters.append(Parameter(name='RMS_Error',min_value=None,max_value=None))
ns.add_performance_parameters(perf_parameters)
# Serial Execution but with a shorter execution timeout.
ns.parallel_settings.concurrent_executions = 8
ns.parallel_settings.cores_per_execution: 1
ns.parallel_settings.execution_timeout = 0.2 # minutes

# params = mutation_parameters
ns.mutation_params.mutation_type = de_mutation_type.de_rand_1_bin
ns.mutation_params.F = 0.6
ns.mutation_params.C = 0.7
ns.start_doe(doe_size=128)
ns.optimize_from_population(pop_start=-1,n_generations=150)