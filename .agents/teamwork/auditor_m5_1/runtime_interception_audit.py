import sys
import os
import traceback
import inspect
from pathlib import Path

# Tracking structures
call_log = []

def poison_handler(source_name, func_name, *args, **kwargs):
    stack = traceback.format_stack()
    # Filter out our own wrapper
    caller_frame = stack[-2] if len(stack) >= 2 else "unknown"
    msg = f"POISON INTERCEPTION: {source_name}.{func_name}() called from:\n{''.join(stack[-4:-1])}"
    call_log.append({
        "source": source_name,
        "func": func_name,
        "caller": caller_frame,
        "stack": stack,
        "message": msg
    })
    print(f"\n[!!! INTEGRITY ALERT !!!] {msg}\n", file=sys.stderr)
    raise RuntimeError(f"Integrity Violation: Intercepted prohibited call to {source_name}.{func_name}()")

# 1. Poison standard library random
import random
print("Applying poison monkeypatching to 'random' module...")
random_funcs = [
    "random", "uniform", "triangular", "randint", "choice", "randrange",
    "sample", "shuffle", "choices", "normalvariate", "lognormvariate",
    "expovariate", "vonmisesvariate", "gammavariate", "gauss", "betavariate",
    "paretovariate", "weibullvariate", "seed", "getstate", "setstate"
]
for fn in random_funcs:
    if hasattr(random, fn):
        setattr(random, fn, (lambda name=fn: lambda *a, **k: poison_handler("random", name, *a, **k))())

# 2. Poison numpy.random
import numpy as np
import numpy.random
print("Applying poison monkeypatching to 'numpy.random'...")
np_random_funcs = [
    "rand", "randn", "randint", "random_integers", "random_sample", "random",
    "ranf", "sample", "choice", "bytes", "permutation", "shuffle", "beta",
    "binomial", "chisquare", "dirichlet", "exponential", "f", "gamma",
    "geometric", "gumbel", "hypergeometric", "laplace", "logistic", "lognormal",
    "logseries", "multinomial", "multivariate_normal", "negative_binomial",
    "noncentral_chisquare", "noncentral_f", "normal", "pareto", "poisson",
    "power", "rayleigh", "standard_cauchy", "standard_exponential",
    "standard_gamma", "standard_normal", "standard_t", "triangular", "uniform",
    "vonmises", "wald", "weibull", "zipf", "seed", "get_state", "set_state"
]
for fn in np_random_funcs:
    if hasattr(np.random, fn):
        setattr(np.random, fn, (lambda name=fn: lambda *a, **k: poison_handler("numpy.random", name, *a, **k))())

orig_default_rng = np.random.default_rng
def poisoned_default_rng(*args, **kwargs):
    poison_handler("numpy.random", "default_rng", *args, **kwargs)
np.random.default_rng = poisoned_default_rng

# Also patch Generator and RandomState methods
if hasattr(np.random, "Generator"):
    for attr in dir(np.random.Generator):
        if not attr.startswith("_"):
            try:
                setattr(np.random.Generator, attr, (lambda name=attr: lambda self, *a, **k: poison_handler("np.random.Generator", name, *a, **k))())
            except (TypeError, AttributeError):
                pass

if hasattr(np.random, "RandomState"):
    for attr in dir(np.random.RandomState):
        if not attr.startswith("_"):
            try:
                setattr(np.random.RandomState, attr, (lambda name=attr: lambda self, *a, **k: poison_handler("np.random.RandomState", name, *a, **k))())
            except (TypeError, AttributeError):
                pass

# 3. Poison torch RNG
import torch
print("Applying poison monkeypatching to 'torch'...")
torch_rng_funcs = [
    "rand", "randn", "randint", "randperm", "bernoulli", "multinomial",
    "normal", "poisson", "manual_seed", "initial_seed"
]
for fn in torch_rng_funcs:
    if hasattr(torch, fn):
        setattr(torch, fn, (lambda name=fn: lambda *a, **k: poison_handler("torch", name, *a, **k))())

print("All RNG poison interceptors successfully primed.")

# NOW RUN WORKLOADS
test_dir = Path("/Users/pmsanch1/code/romanepsf/.agents/teamwork/auditor_m5_1")
output_pdf = test_dir / "audit_intercept_report.pdf"
results_dir = Path("/Users/pmsanch1/code/romanepsf/output/run_all")

print("\n--- Phase 2A: Executing Full Publication Report Generation under Poisoning ---")
from romanepsf.report import generate_publication_pdf_report
from romanepsf.config import load_config

cfg = load_config()
try:
    generate_publication_pdf_report(
        results_dir=results_dir,
        output_pdf=output_pdf,
        cfg=cfg,
        dpi=150
    )
    print("Report generation completed successfully under RNG poison!")
except Exception as e:
    print(f"Exception during report generation: {e}")
    traceback.print_exc()

print("\n--- Phase 2B: Executing Model Validation under Poisoning ---")
from romanepsf.validation import evaluate_epsf_validation
from astropy.io import fits

model_fits = Path("/Users/pmsanch1/code/romanepsf/output/run_all/roman_epsf_composite.fits")
val_out_dir = test_dir / "val_output"
val_out_dir.mkdir(parents=True, exist_ok=True)

try:
    with fits.open(model_fits) as hdul:
        epsf_model = hdul[0].data

    val_res = evaluate_epsf_validation(
        epsf_model=epsf_model,
        asdf_path=None,
        cfg=cfg.validation,
        output_dir=val_out_dir,
        save_residual_fits=True
    )
    print(f"Model validation completed successfully under RNG poison! Status: {val_res.overall_status}")
except Exception as e:
    print(f"Exception during validation: {e}")
    traceback.print_exc()

print("\n--- Phase 2 Summary: Call Interception Audit ---")
print(f"Total prohibited calls intercepted: {len(call_log)}")
if len(call_log) > 0:
    for entry in call_log:
        print(f"INTERCEPTED: {entry['source']}.{entry['func']} called from:\n{entry['caller']}")
    sys.exit(1)
else:
    print("CLEAN: ZERO prohibited RNG calls intercepted during report generation and model validation.")
    sys.exit(0)
