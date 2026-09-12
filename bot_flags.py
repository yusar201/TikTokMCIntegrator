"""Global flags for different testing/logging modes."""

# Pure connection test: log all events/actions, but NEVER execute anything
LOG_ONLY_MODE = False

# Current debug mode: enables SuperFan probe logging, but still executes all actions
DEBUG_MODE = False

def reset_flags():
    """Reset to defaults."""
    global LOG_ONLY_MODE, DEBUG_MODE
    LOG_ONLY_MODE = False
    DEBUG_MODE = False
