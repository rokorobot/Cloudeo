"""Read-only Mission Control views over the V2 control store.

The adapter maps control-layer records (cloudeo.control) onto UI-facing view
models. It never writes, never infers values the control store does not hold,
and fails closed on any domain state it does not know how to present.
"""
