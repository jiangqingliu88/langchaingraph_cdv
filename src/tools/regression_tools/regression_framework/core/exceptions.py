# src/regression_framework/core/exceptions.py
class RegressionError(Exception):
    """Base exception for regression framework."""
    pass

class ConfigError(RegressionError):
    """Configuration error."""
    pass

class ExecutionError(RegressionError):
    """Execution error."""
    pass

class LSFError(RegressionError):
    """LSF related error."""
    pass