"""Runtime integration above the pure control layer (ADR-030).

Orchestration acquires trusted runtime observations and converts them into
cloudeo.control inputs; cloudeo.control evaluates them. Policy stays in
cloudeo.control, and broker, Git, bridge, and kernel behavior stays in its
owning package. The dependency is one way: orchestration imports control,
never the reverse.

Nothing is re-exported here, so importing one module never pulls in another
module's optional dependencies (kernel_outcome needs the 'longhorizon' extra;
baseline does not).
"""
