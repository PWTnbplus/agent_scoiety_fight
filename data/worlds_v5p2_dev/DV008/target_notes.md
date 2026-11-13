# DV008 target observation (synthetic development world)
Domain analogy: ecological population; state z is nonnegative and normalized.
Nominal candidate-rate k=0.4070; observation noise sigma=0.030.
Candidate mechanisms use this same nominal rate; none is labelled true:
- EXP_DECAY: z0*exp(-k*t)
- HYPERBOLIC_DECAY: z0/(1+k*z0*t)
- STRETCHED_EXP: z0*exp(-(k*t)^2)
- BI_EXP: z0*(0.75 exp(-1.8*k*t)+0.25 exp(-0.25*k*t))
Initial observations:
- T01: x0=0.72, t=0.12, measured_state=0.656370
- T02: x0=0.72, t=0.18, measured_state=0.648449
