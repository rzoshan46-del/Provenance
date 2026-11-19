"""Router package initializer.
Ensures that the package is recognized as a module for imports.
Exports the individual router modules for convenient import.
"""

# Export routers as package attributes
from . import auth, users, projects, health

__all__ = ["auth", "users", "projects", "health"]
