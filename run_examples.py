# !/usr/bin/env python3
#
# Adapted from botorch: M. Balandat, B. Karrer, D. R. Jiang,
# S. Daulton, B. Letham, A. G. Wilson, and E. Bakshy. BoTorch: A Framework for
# Efficient Monte-Carlo Bayesian Optimization. Advances in Neural Information
# Processing Systems 33, 2020. https://github.com/pytorch/botorch

import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path
from subprocess import CalledProcessError
from typing import Dict, Optional

import nbformat
from nbconvert import PythonExporter


IGNORE = {
    "cnsga_tnk.ipynb",
    "cnsga2_tnk.ipynb",  # requires pymoo, not in package dependencies or conda
}

SUB_DIRS = ['cnsga', 'mobo', 'bayes_exp', 'multi_fidelity']


def parse_ipynb(file: Path) -> str:
    with open(file, "r", encoding="utf-8") as nb_file:
        nb_str = nb_file.read()
    nb = nbformat.reads(nb_str, nbformat.NO_CONVERT)
    exporter = PythonExporter()
    script, _ = exporter.from_notebook_node(nb)

    if 'pinfo' in script:
        raise ValueError('`pinfo` command (`?`) in notebook freezes execution, '
                         'cannot proceed, please remove')

    return script


def run_script(script: str, env: Dict[str, str] = None) -> None:
    # need to keep the file around & close it so subprocess does not run into I/O issues
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf_name = tf.name
        with open(tf_name, "w", encoding="utf-8") as tmp_script:
            tmp_script.write(script)
    if env is not None:
        env = {**os.environ, **env}
    run_out = subprocess.run(
        ["ipython", tf_name], capture_output=True, text=True, env=env
    )
    os.remove(tf_name)
    return run_out


def run_tutorial(tutorial: Path, smoke_test: bool = False) -> Optional[str]:
    script = parse_ipynb(tutorial)
    tic = time.time()
    print(f"Running tutorial {tutorial.name}.")
    run_out = run_script(script, env={"SMOKE_TEST": "true"})
    try:
        run_out.check_returncode()
    except CalledProcessError:
        return "\n".join(
            [
                f"Encountered error running tutorial {tutorial.name}:",
                "stdout:",
                run_out.stdout,
                "stderr:",
                run_out.stderr,
            ]
        )
    runtime = time.time() - tic
    print(f"Running tutorial {tutorial.name} took {runtime:.2f} seconds.")


def run_tutorials(
    repo_dir: str,
    include_ignored: bool = False,
    smoke_test: bool = False,
) -> None:
    print(f"Running tutorials in {'smoke test' if smoke_test else 'standard'} mode.")
    if not smoke_test:
        print("This may take a long time...")
    tutorial_base = Path(repo_dir).joinpath("examples")
    num_runs = 0
    num_errors = 0

    for sub_dir in SUB_DIRS:
        tutorial_dir = Path(tutorial_base).joinpath(sub_dir)
        print(f'In directory {sub_dir}')
        for tutorial in tutorial_dir.iterdir():
            if not tutorial.is_file or tutorial.suffix != ".ipynb":
                continue
            if not include_ignored and tutorial.name in IGNORE:
                print(f"Ignoring tutorial {tutorial.name}.")
                continue
            num_runs += 1
            error = run_tutorial(tutorial, smoke_test=smoke_test)
            if error is not None:
                num_errors += 1
                print(error)

    if num_errors > 0:
        raise RuntimeError(
            f"Running {num_runs} tutorials resulted in {num_errors} errors."
        )


if __name__ == "__main__":
    ########################
    #WARNING!!!!!!!! - calling pinfo magic command crashes
    # evaluation for some reason
    ########################

    parser = argparse.ArgumentParser(description="Run the tutorials.")
    parser.add_argument(
        "-p", "--path", metavar="path", required=True, help="botorch repo directory."
    )
    parser.add_argument(
        "-s", "--smoke", action="store_true", help="Run in smoke test mode."
    )
    parser.add_argument(
        "--include-ignored",
        action="store_true",
        help="Run all tutorials (incl. ignored).",
    )
    args = parser.parse_args()
    run_tutorials(
        repo_dir=args.path,
        include_ignored=args.include_ignored,
        smoke_test=args.smoke,
    )