# DV005 target observation (synthetic development world)
Domain analogy: chemical simulation; state z is nonnegative and normalized.
Nominal candidate-rate k=0.5640; observation noise sigma=0.035.
Candidate mechanisms use this same nominal rate; none is labelled true:
- EXP_DECAY: z0*exp(-k*t)
- HYPERBOLIC_DECAY: z0/(1+k*z0*t)
- STRETCHED_EXP: z0*exp(-(k*t)^2)
- BI_EXP: z0*(0.75 exp(-1.8*k*t)+0.25 exp(-0.25*k*t))
Initial observations:
- T01: x0=0.58, t=0.12, measured_state=0.554793
- T02: x0=0.58, t=0.21, measured_state=0.516788
