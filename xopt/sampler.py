from xopt.tools import full_path, new_date_filename, random_settings, DummyExecutor, NpEncoder
from xopt import __version__
from deap.base import Toolbox
import json
import time
import os, sys

sampler_logo = f"""

███████╗ █████╗ ███╗   ███╗██████╗ ██╗     ███████╗██████╗ 
██╔════╝██╔══██╗████╗ ████║██╔══██╗██║     ██╔════╝██╔══██╗
███████╗███████║██╔████╔██║██████╔╝██║     █████╗  ██████╔╝
╚════██║██╔══██║██║╚██╔╝██║██╔═══╝ ██║     ██╔══╝  ██╔══██╗
███████║██║  ██║██║ ╚═╝ ██║██║     ███████╗███████╗██║  ██║
╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝  ╚═╝
                                                           

Xopt Random Sampler
Version {__version__}
"""


def sampler_evaluate(inputs, evaluate_f=None, verbose=False):
    """
    Wrapper to catch any exceptions
    
    
    inputs: possible inputs to evaluate_f (a single positional argument)
    
    evaluate_f: a function that takes a dict with keys, and returns some output
    
    """
    result = {}

    try:
        outputs = evaluate_f(inputs)
        err = False

    except Exception as ex:
        outputs = {'Exception': str(ex)}
        err = True
        if verbose:
            print(outputs)

    finally:
        result['inputs'] = inputs
        result['outputs'] = outputs
        result['error'] = err

    return result


def random_sampler(vocs, evaluate_f,
                   executor=None,
                   output_path=None,
                   chunk_size=10,
                   max_samples=100,
                   verbose=False):
    """
    
    Makes random samples based on vocs
    
    """

    toolbox = Toolbox()
    toolbox.register('evaluate', sampler_evaluate, evaluate_f=evaluate_f, verbose=verbose)

    # Verbose print helper
    def vprint(*a, **k):
        if verbose:
            print(*a, **k)
            sys.stdout.flush()

    # Logo
    vprint(sampler_logo)

    if not executor:
        executor = DummyExecutor()
        vprint('No executor given. Running in serial mode.')

        # Setup saving to file
    if output_path:
        path = full_path(output_path)
        assert os.path.exists(path), f'output_path does not exist {path}'

        def save(data):
            file = new_date_filename(prefix='sampler-', path=path)
            with open(file, 'w') as f:
                json.dump(data, f, ensure_ascii=True, cls=NpEncoder)  # , indent=4)
            vprint('Samples written to:\n', file)

    else:
        # Dummy save
        def save(data):
            pass

            #  Initial batch
    futures = [executor.submit(toolbox.evaluate, random_settings(vocs)) for _ in range(chunk_size)]

    # Continuous loop
    ii = 0
    t0 = time.time()
    done = False
    results = []
    all_results = []
    while not done:

        if ii > max_samples:
            done = True

        # Check the status of all futures
        for ix in range(len(futures)):

            # Examine a future
            fut = futures[ix]

            if not fut.done():
                continue

            # Future is done.
            results.append(fut.result())
            all_results.append(fut.result())
            vprint('.', end='')
            ii += 1

            # Submit new job, keep in futures list
            future = executor.submit(toolbox.evaluate, random_settings(vocs))
            futures[ix] = future

            # output
            if ii % chunk_size == 0:
                t1 = time.time()
                dt = t1 - t0
                t0 = t1
                vprint(f'{chunk_size} samples completed in {dt / 60:0.5f} minutes')

                data = {'vocs': vocs}
                # Reshape data
                for k in ['inputs', 'outputs', 'error']:
                    data[k] = [r[k] for r in results]
                save(data)
                results = []

        # Slow down polling. Needed for MPI to work well. 
        time.sleep(0.001)

        # Cancel remaining jobs
    for future in futures:
        future.cancel()

    data = {'vocs': vocs}
    # Reshape data
    for k in ['inputs', 'outputs', 'error']:
        data[k] = [r[k] for r in all_results]
    return data
