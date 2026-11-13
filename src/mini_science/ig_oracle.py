from __future__ import annotations

import math
from typing import Iterable

from .simulators import MODELS, predict


def _logsumexp(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        raise ValueError("empty logsumexp")
    pivot = max(values)
    return pivot + math.log(sum(math.exp(value - pivot) for value in values))


def entropy(probabilities: Iterable[float]) -> float:
    return -sum(p * math.log(p) for p in probabilities if p > 0)


def gaussian_density(y: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((y - mu) / sigma) ** 2) / (sigma * math.sqrt(2.0 * math.pi))


def target_posterior(observations: list[dict], k: float, sigma: float, models: tuple[str, ...] = MODELS) -> list[float]:
    if sigma <= 0 or not models:
        raise ValueError("sigma and models must be valid")
    logweights: list[float] = []
    for model in models:
        score = -math.log(len(models))
        for observation in observations:
            mu = predict(model, float(observation["x0"]), float(observation["t"]), k)
            score -= ((float(observation["observed_x"]) - mu) ** 2) / (2.0 * sigma**2)
        logweights.append(score)
    normalizer = _logsumexp(logweights)
    posterior = [math.exp(value - normalizer) for value in logweights]
    if not math.isclose(sum(posterior), 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise ArithmeticError("posterior did not normalize")
    return posterior


def expected_information_gain(priors: list[float], means: list[float], sigma: float, n_grid: int = 1001) -> float:
    if len(priors) != len(means) or not priors:
        raise ValueError("priors and means must have identical non-empty sizes")
    if any(p < 0 for p in priors) or not math.isclose(sum(priors), 1.0, rel_tol=0.0, abs_tol=1e-7):
        raise ValueError("priors must be a probability vector")
    if sigma <= 0 or n_grid < 100:
        raise ValueError("invalid sigma or integration grid")
    if max(means) - min(means) < 1e-12:
        return 0.0
    left = min(means) - 7.0 * sigma
    right = max(means) + 7.0 * sigma
    width = (right - left) / n_grid
    expected_entropy = 0.0
    mass = 0.0
    for index in range(n_grid):
        y = left + (index + 0.5) * width
        likelihoods = [gaussian_density(y, mean, sigma) for mean in means]
        joint = [prior * likelihood for prior, likelihood in zip(priors, likelihoods)]
        predictive = sum(joint)
        if predictive <= 0:
            continue
        posterior = [value / predictive for value in joint]
        mass += predictive * width
        expected_entropy += predictive * entropy(posterior) * width
    if mass <= 0:
        raise ArithmeticError("integration has zero predictive mass")
    ig = entropy(priors) - expected_entropy / mass
    if ig < -1e-6:
        raise ArithmeticError(f"materially negative IG: {ig}")
    return max(0.0, ig)


def oracle_scores(
    observations: list[dict],
    menu: list[dict],
    k: float,
    sigma: float,
    models: tuple[str, ...] = MODELS,
    n_grid: int = 1001,
) -> dict:
    priors = target_posterior(observations, k, sigma, models)
    ig_map: dict[str, float] = {}
    for experiment in menu:
        experiment_id = str(experiment["experiment_id"])
        means = [predict(model, float(experiment["x0"]), float(experiment["measure_t"]), k) for model in models]
        ig_map[experiment_id] = expected_information_gain(priors, means, sigma, n_grid=n_grid)
    ig_star = max(ig_map.values())
    if ig_star <= 1e-7:
        raise ValueError("INVALID_WORLD: all candidate experiments have zero IG")
    scores = {key: max(0.0, min(100.0, 100.0 * value / ig_star)) for key, value in ig_map.items()}
    return {
        "posterior_target_only": dict(zip(models, priors)),
        "ig_nats": ig_map,
        "top1_score": scores,
        "ig_star": ig_star,
        "best_experiment_ids": [key for key, value in ig_map.items() if math.isclose(value, ig_star, rel_tol=1e-10, abs_tol=1e-10)],
        "integration_grid": n_grid,
    }


def conditional_oracle_scores(
    target_observations: list[dict],
    source_observations: list[dict],
    menu: list[dict],
    k: float,
    sigma: float,
    models: tuple[str, ...] = MODELS,
    n_grid: int = 1001,
) -> dict:
    """Score the independent conditional metric IG(q | K_target, K_source).

    This is deliberately a separate interface from :func:`oracle_scores`.
    The frozen V5P4 primary action score continues to use target-only
    information; callers must opt into this conditional research-question
    metric explicitly.
    """
    result = oracle_scores(target_observations + source_observations, menu, k, sigma, models=models, n_grid=n_grid)
    result["metric"] = "IG(q|K_target,K_source)"
    result["target_observation_count"] = len(target_observations)
    result["source_observation_count"] = len(source_observations)
    return result
