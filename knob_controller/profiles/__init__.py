"""Profile subsystem package boundary.

Per-application profile behavior is currently provided by the unprivileged
`knob-controller-agent.py` process. v0.9 establishes this package boundary so
that the agent can migrate here without changing the hardware daemon API.
"""
