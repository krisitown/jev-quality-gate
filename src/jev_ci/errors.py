class JevCIError(Exception):
    """A safe, user-facing configuration or execution error."""


class ConfigError(JevCIError):
    pass


class ComparisonError(JevCIError):
    pass


class InferenceError(JevCIError):
    pass


class ContextLimitError(InferenceError):
    """The evaluator cannot fit this request in its native context budget."""


class ProviderError(JevCIError):
    pass


class TraceError(JevCIError):
    pass
