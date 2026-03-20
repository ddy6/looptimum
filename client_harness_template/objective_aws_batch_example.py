#!/usr/bin/env python3
"""Example objective adapter for the optional AWS Batch executor path."""

from __future__ import annotations

import os
from typing import Any

from aws_config import load_aws_batch_config
from aws_executor import evaluate_via_batch
from aws_models import CanonicalEvalRequest


def evaluate(params: dict[str, Any]) -> dict[str, Any]:
    """Submit one trial to AWS Batch using the local AWS config sidecar."""
    raw_trial_id = os.environ.get("LOOPTIMUM_TRIAL_ID")
    if raw_trial_id is None:
        raise RuntimeError("LOOPTIMUM_TRIAL_ID is required for AWS Batch objective example")

    request = CanonicalEvalRequest(
        trial_id=int(raw_trial_id),
        params=dict(params),
    )
    config = load_aws_batch_config()
    return dict(evaluate_via_batch(request, config=config))
