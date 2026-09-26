import warnings
import flpit  # The NEW location

# Enforce a loud, clear deprecation alert
warnings.warn(
    "The top-level 'flp' namespace is deprecated and has been moved to 'flpit'. "
    "Please update your imports to 'from flpit import flp, FlpIt, FlpList'"
    "This legacy entry point will throw a hard ImportError in a future version.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = getattr(flpit.flp, "__all__", []) + getattr(flpit, "__all__", [])
mods = [flpit, flpit.flp]

def __getattr__(name: str):
    for mod in mods:
        if hasattr(mod, name):
            return getattr(mod, name)

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
