# Frozen MVP protocol

The experiment uses four synthetic worlds: W001/W002 have hidden `EXP_DECAY`
law and W003/W004 have hidden `HYPERBOLIC_DECAY` law. Each world has four
candidate mechanisms and the Cartesian product of two initial states and four
measurement times, producing exactly eight legal actions.

The public target evidence is fixed across conditions. A receives a matched
unrelated source note; B receives a related source note; C and D use the same
stage-1 law artifact, with D blocked in the router; S_COLLAB3 uses source and
target analysts plus a synthesis designer; S_COMPETE3 uses two independent
proposers plus an evidence judge.

The independent evaluator computes expected information gain from the target
initial evidence only, with equal model prior and Gaussian measurement noise.
The evaluator never runs in prompt construction.

All model calls and outputs are hashed and logged. Invalid JSON, illegal action
IDs, missing fields, and provider failures remain visible and receive zero
question score.
