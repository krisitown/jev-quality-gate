# Public routing compatibility convention

New HTTP method support should remain additive for applications using the router. Preserve existing route sets and the behavior of established routing interfaces; where a new capability cannot be added to a broad interface without breaking external implementations, expose it through a compatible opt-in surface.
