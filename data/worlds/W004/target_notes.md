# W004 target observation (synthetic simulation)
Domain analogy: biological quantity simulation; state z is nonnegative and normalized.
Nominal candidate-rate k=0.5182; observation noise sigma=0.040.
Four candidate mechanisms use this same nominal rate; none is labelled true:
- EXP_DECAY: z0*exp(-k*t)
- HYPERBOLIC_DECAY: z0/(1+k*z0*t)
- STRETCHED_EXP: z0*exp(-(k*t)^2)
- BI_EXP: z0*(0.75 exp(-1.8*k*t)+0.25 exp(-0.25*k*t))
Initial observations:
- T01: x0=1.00, t=0.08, measured_state=0.99868
- T02: x0=1.00, t=0.18, measured_state=0.92652
Choose exactly one experiment ID from the public menu to discriminate at least two candidates.
