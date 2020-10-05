#TODO: Change this to plotting for SODE

import sys,os
sys.path.insert(0,'../../../../')
from glennopt.helpers import Parameter, mutation_parameters, de_mutation_type
from glennopt.nsga3 import NSGA3,mutation_parameters, de_mutation_type
from glennopt.doe import generate_reference_points


# Generate the DOE
current_dir = os.getcwd()
sode = NSGA3(eval_script = "Evaluation/evaluation.py", eval_folder="Evaluation",num_populations=10,pop_size=20,optimization_folder=current_dir)

eval_parameters = []
eval_parameters.append(Parameter(name="x1",min_value=-10,max_value=10))
eval_parameters.append(Parameter(name="x2",min_value=-10,max_value=10))
eval_parameters.append(Parameter(name="x3",min_value=-10,max_value=10))
sode.add_eval_parameters(eval_params = eval_parameters)

objectives = []
objectives.append(Parameter(name='objective1'))
objectives.append(Parameter(name='objective2'))
sode.add_objectives(objectives=objectives)

# No performance Parameters
performance_parameters = []
performance_parameters.append(Parameter(name='p1'))
performance_parameters.append(Parameter(name='p2'))
performance_parameters.append(Parameter(name='p3'))
# ns.start_doe(doe_size=40)
# ns.optimize_from_population(pop_start=-1,n_generations=10)
sode.read_calculation_folder()
sode.plot_best_objective(objective_index=0)


