# RS006 target observations (V5-P15 public protocol)
All times use seconds. Target initial state x0, nominal candidate-rate k, and independent Gaussian observation scale are public metadata.
Target x0=1.00000; target candidate-rate k=0.49760; target noise sigma=0.02500.
Candidate equations (each candidate remains unlabeled):
- EXP_DECAY: z0*exp(-k*t)
- HYPERBOLIC_DECAY: z0/(1+k*z0*t)
- STRETCHED_EXP: z0*exp(-(k*t)^2)
- BI_EXP: z0*(0.75*exp(-1.8*k*t)+0.25*exp(-0.25*k*t))
Initial target observations:
- T01: target_state=0.949263, target_time=0.08 s, target_x0=1.0000
- T02: target_state=0.933375, target_time=0.18 s, target_x0=1.0000
- T03: target_state=0.871599, target_time=0.35 s, target_x0=1.0000
Choose exactly one experiment ID from the public menu.
