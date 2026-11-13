# IV003 target observations (V5-P11 public protocol)
All times use seconds. Target initial state x0 and nominal candidate-rate k are public metadata; sigma is the independent Gaussian observation scale.
Target x0=1.00000; target candidate-rate k=0.42568; target noise sigma=0.02500.
Candidate equations (none is labelled as true):
- EXP_DECAY: z0*exp(-k*t)
- HYPERBOLIC_DECAY: z0/(1+k*z0*t)
- STRETCHED_EXP: z0*exp(-(k*t)^2)
- BI_EXP: z0*(0.75*exp(-1.8*k*t)+0.25*exp(-0.25*k*t))
Initial target observations:
- T01: target_state=0.964396, target_time=0.08 s, target_x0=1.0000
- T02: target_state=0.950750, target_time=0.18 s, target_x0=1.0000
Choose exactly one experiment ID from the public menu.
