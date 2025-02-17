import torch
import numpy as np
import time
import traceback
import logging
from copy import deepcopy


class NoValidResultsError(Exception):
    pass


class UnsupportedError(Exception):
    pass


# Logger
logger = logging.getLogger(__name__)

algorithm_defaults = {'n_steps': 30,
                      'executor': None,
                      'n_initial_samples': 5,
                      'custom_model': None,
                      'output_path': None,
                      'verbose': True,
                      'restart_data_file': None,
                      'initial_x': None,
                      'use_gpu': False,
                      'eval_args': None}


def get_bounds(vocs, **tkwargs):
    # get initial bounds
    return torch.vstack(
        [torch.tensor(ele, **tkwargs) for _, ele in vocs['variables'].items()]).T


def get_corrected_outputs(vocs, train_y, train_c):
    """
    scale and invert outputs depending on maximization/minimization, etc.
    """

    objectives = vocs['objectives']
    objective_names = list(objectives.keys())

    constraints = vocs['constraints']
    constraint_names = list(constraints.keys())

    # need to multiply -1 for each axis that we are using 'MINIMIZE' for an objective
    # need to multiply -1 for each axis that we are using 'GREATER_THAN' for a constraint
    corrected_train_y = train_y.clone()
    corrected_train_c = train_c.clone()

    # negate objective measurements that want to be minimized
    for j, name in zip(range(len(objective_names)), objective_names):
        if vocs['objectives'][name] == 'MINIMIZE':
            corrected_train_y[:, j] = -train_y[:, j]

        # elif vocs['objectives'][name] == 'MAXIMIZE' or vocs['objectives'][name] == 'None':
        #    pass
        else:
            pass
            # logger.warning(f'Objective goal {vocs["objectives"][name]} not found, defaulting to MAXIMIZE')

    # negate constraints that use 'GREATER_THAN'
    for k, name in zip(range(len(constraint_names)), constraint_names):
        if vocs['constraints'][name][0] == 'GREATER_THAN':
            corrected_train_c[:, k] = (vocs['constraints'][name][1] - train_c[:, k])

        elif vocs['constraints'][name][0] == 'LESS_THAN':
            corrected_train_c[:, k] = -(vocs['constraints'][name][1] - train_c[:, k])
        else:
            logger.warning(
                f'Constraint goal {vocs["constraints"][name]} not found, defaulting to LESS_THAN')

    return corrected_train_y, corrected_train_c


def parse_vocs(vocs):
    # parse VOCS
    variables = vocs['variables']
    vocs['variable_names'] = list(variables.keys())

    objectives = vocs['objectives']
    vocs['objective_names'] = list(objectives.keys())
    assert len(vocs['objective_names']) == 1

    constraints = vocs['constraints']
    vocs['constraint_names'] = list(constraints.keys())
    return vocs


def sampler_evaluate(inputs, evaluate_f, *eval_args, verbose=False):
    """
    Wrapper to catch any exceptions


    inputs: possible inputs to evaluate_f (a single positional argument)

    evaluate_f: a function that takes a dict with keys, and returns some output

    """
    outputs = None
    result = {}

    try:
        outputs = evaluate_f(inputs, *eval_args)
        err = False

    except Exception as ex:
        outputs = {'Exception': str(ex),
                   'Traceback': traceback.print_tb(ex.__traceback__)}
        err = True
        if verbose:
            print(outputs)

    finally:
        result['inputs'] = inputs
        result['outputs'] = outputs
        result['error'] = err

    return result


def get_results(futures):
    # check the status of all futures
    results = []
    done = False
    ii = 1
    n_samples = len(futures)

    while True:
        if len(futures) == 0:
            break
        else:
            # get the first element of futures - if done delete the element
            fut = futures[0]
            if fut.done():
                results.append(fut.result())
                del futures[0]

        # Slow down polling. Needed for MPI to work well.
        time.sleep(0.001)

    return results


def collect_results(futures, vocs, **tkwargs):
    """
        Collect successful measurement results into torch tensors to add to training data
    """

    train_x = []
    train_y = []
    train_c = []

    inputs = []
    outputs = []

    at_least_one_point = False
    results = get_results(futures)

    for result in results:
        if not result['error']:
            train_x += [[result['inputs'][ele] for ele in vocs['variables'].keys()]]
            train_y += [[result['outputs'][ele] for ele in vocs['objectives'].keys()]]
            train_c += [[result['outputs'][ele] for ele in vocs['constraints'].keys()]]

            inputs += [result['inputs']]
            outputs += [result['outputs']]

            at_least_one_point = True

    if not at_least_one_point:
        raise NoValidResultsError('No valid results')

    train_x = torch.tensor(train_x, **tkwargs)
    train_y = torch.tensor(train_y, **tkwargs)
    train_c = torch.tensor(train_c, **tkwargs)

    return train_x, train_y, train_c, inputs, outputs
