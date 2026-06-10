"""
Exposition du registre de configurations.

Usage dans create_app() :
    from config import config_registry
    app.config.from_object(config_registry[env])
"""
from .settings import (
    DevelopmentConfig,
    ProductionConfig,
    TestingConfig,
    StagingConfig,
)

config_registry: dict = {
    "development": DevelopmentConfig,
    "testing":     TestingConfig,
    "staging":     StagingConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}

__all__ = [
    "config_registry",
    "DevelopmentConfig",
    "ProductionConfig",
    "TestingConfig",
    "StagingConfig",
]
