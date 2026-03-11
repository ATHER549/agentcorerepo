from pydantic_settings import BaseSettings


class FeatureFlags(BaseSettings):
    mvp_components: bool = False

    class Config:
        env_prefix = "AGENTCORE_FEATURE_"


FEATURE_FLAGS = FeatureFlags()
