# Reactive state mutation convention

Reactive state updates should publish a coherent state to observers. A no-op should not be reported as a change, and mutations to a nested object that no longer belongs to a state tree should not notify that former parent. Array operations should retain their native result and mutation behavior while keeping observers consistent with the completed operation.
