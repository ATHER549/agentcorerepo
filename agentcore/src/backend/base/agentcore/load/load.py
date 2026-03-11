import json
from io import StringIO
from pathlib import Path

from aiofile import async_open
from dotenv import dotenv_values
from loguru import logger

from agentcore.graph_langgraph import LangGraphAdapter, RunOutputs
from agentcore.load.utils import replace_tweaks_with_env
from agentcore.logging.logger import configure
from agentcore.processing.process import process_tweaks, run_graph
from agentcore.utils.async_helpers import run_until_complete
from agentcore.utils.util import update_settings


async def aload_agent_from_json(
    agent: Path | str | dict,
    *,
    tweaks: dict | None = None,
    log_level: str | None = None,
    log_file: str | None = None,
    log_rotation: str | None = None,
    env_file: str | None = None,
    cache: str | None = None,
    disable_logs: bool | None = True,
) -> LangGraphAdapter:
    """Load a agent graph from a JSON file or a JSON object.

    Args:
        agent (Union[Path, str, dict]): The agent to load. It can be a file path (str or Path object)
            or a JSON object (dict).
        tweaks (Optional[dict]): Optional tweaks to apply to the loaded agent graph.
        log_level (Optional[str]): Optional log level to configure for the agent processing.
        log_file (Optional[str]): Optional log file to configure for the agent processing.
        log_rotation (Optional[str]): Optional log rotation(Time/Size) to configure for the agent processing.
        env_file (Optional[str]): Optional .env file to override environment variables.
        cache (Optional[str]): Optional cache path to update the agent settings.
        disable_logs (Optional[bool], default=True): Optional flag to disable logs during agent processing.
            If log_level or log_file are set, disable_logs is not used.

    Returns:
        LangGraphAdapter: The loaded agent graph.

    Raises:
        TypeError: If the input is neither a file path (str or Path object) nor a JSON object (dict).

    """
    # If input is a file path, load JSON from the file
    log_file_path = Path(log_file) if log_file else None
    configure(
        log_level=log_level, log_file=log_file_path, disable=disable_logs, async_file=True, log_rotation=log_rotation
    )

    # override env variables with .env file
    if env_file and tweaks is not None:
        async with async_open(Path(env_file), encoding="utf-8") as f:
            content = await f.read()
            env_vars = dotenv_values(stream=StringIO(content))
        tweaks = replace_tweaks_with_env(tweaks=tweaks, env_vars=env_vars)

    # Update settings with cache and components path
    await update_settings(cache=cache)

    if isinstance(agent, str | Path):
        async with async_open(Path(agent), encoding="utf-8") as f:
            content = await f.read()
            agent_graph = json.loads(content)
    # If input is a dictionary, assume it's a JSON object
    elif isinstance(agent, dict):
        agent_graph = agent
    else:
        msg = "Input must be either a file path (str) or a JSON object (dict)"
        raise TypeError(msg)

    graph_data = agent_graph["data"]
    if tweaks is not None:
        graph_data = process_tweaks(graph_data, tweaks)

    return LangGraphAdapter.from_payload(graph_data)


def load_agent_from_json(
    agent: Path | str | dict,
    *,
    tweaks: dict | None = None,
    log_level: str | None = None,
    log_file: str | None = None,
    log_rotation: str | None = None,
    env_file: str | None = None,
    cache: str | None = None,
    disable_logs: bool | None = True,
) -> LangGraphAdapter:
    """Load a agent graph from a JSON file or a JSON object.

    Args:
        agent (Union[Path, str, dict]): The agent to load. It can be a file path (str or Path object)
            or a JSON object (dict).
        tweaks (Optional[dict]): Optional tweaks to apply to the loaded agent graph.
        log_level (Optional[str]): Optional log level to configure for the agent processing.
        log_file (Optional[str]): Optional log file to configure for the agent processing.
        log_rotation (Optional[str]): Optional log rotation(Time/Size) to configure for the agent processing.
        env_file (Optional[str]): Optional .env file to override environment variables.
        cache (Optional[str]): Optional cache path to update the agent settings.
        disable_logs (Optional[bool], default=True): Optional flag to disable logs during agent processing.
            If log_level or log_file are set, disable_logs is not used.

    Returns:
        LangGraphAdapter: The loaded agent graph.

    Raises:
        TypeError: If the input is neither a file path (str or Path object) nor a JSON object (dict).

    """
    return run_until_complete(
        aload_agent_from_json(
            agent,
            tweaks=tweaks,
            log_level=log_level,
            log_file=log_file,
            log_rotation=log_rotation,
            env_file=env_file,
            cache=cache,
            disable_logs=disable_logs,
        )
    )


async def arun_agent_from_json(
    agent: Path | str | dict,
    input_value: str,
    *,
    session_id: str | None = None,
    tweaks: dict | None = None,
    input_type: str = "chat",
    output_type: str = "chat",
    output_component: str | None = None,
    log_level: str | None = None,
    log_file: str | None = None,
    log_rotation: str | None = None,
    env_file: str | None = None,
    cache: str | None = None,
    disable_logs: bool | None = True,
    fallback_to_env_vars: bool = False,
) -> list[RunOutputs]:
    """Run a agent from a JSON file or dictionary.

    Args:
        agent (Union[Path, str, dict]): The path to the JSON file or the JSON dictionary representing the agent.
        input_value (str): The input value to be processed by the agent.
        session_id (str | None, optional): The session ID to be used for the agent. Defaults to None.
        tweaks (Optional[dict], optional): Optional tweaks to be applied to the agent. Defaults to None.
        input_type (str, optional): The type of the input value. Defaults to "chat".
        output_type (str, optional): The type of the output value. Defaults to "chat".
        output_component (Optional[str], optional): The specific component to output. Defaults to None.
        log_level (Optional[str], optional): The log level to use. Defaults to None.
        log_file (Optional[str], optional): The log file to write logs to. Defaults to None.
        log_rotation (Optional[str], optional): The log rotation to use. Defaults to None.
        env_file (Optional[str], optional): The environment file to load. Defaults to None.
        cache (Optional[str], optional): The cache directory to use. Defaults to None.
        disable_logs (Optional[bool], optional): Whether to disable logs. Defaults to True.
        fallback_to_env_vars (bool, optional): Whether Global Variables should fallback to environment variables if
            not found. Defaults to False.

    Returns:
        List[RunOutputs]: A list of RunOutputs objects representing the results of running the agent.
    """
    if tweaks is None:
        tweaks = {}
    tweaks["stream"] = False
    graph = await aload_agent_from_json(
        agent=agent,
        tweaks=tweaks,
        log_level=log_level,
        log_file=log_file,
        log_rotation=log_rotation,
        env_file=env_file,
        cache=cache,
        disable_logs=disable_logs,
    )
    result = await run_graph(
        graph=graph,
        session_id=session_id,
        input_value=input_value,
        input_type=input_type,
        output_type=output_type,
        output_component=output_component,
        fallback_to_env_vars=fallback_to_env_vars,
    )
    await logger.complete()
    return result


def run_agent_from_json(
    agent: Path | str | dict,
    input_value: str,
    *,
    session_id: str | None = None,
    tweaks: dict | None = None,
    input_type: str = "chat",
    output_type: str = "chat",
    output_component: str | None = None,
    log_level: str | None = None,
    log_file: str | None = None,
    log_rotation: str | None = None,
    env_file: str | None = None,
    cache: str | None = None,
    disable_logs: bool | None = True,
    fallback_to_env_vars: bool = False,
) -> list[RunOutputs]:
    """Run a agent from a JSON file or dictionary.

    Note:
        This function is a synchronous wrapper around `arun_agent_from_json`.
        It creates an event loop if one does not exist and runs the agent.

    Args:
        agent (Union[Path, str, dict]): The path to the JSON file or the JSON dictionary representing the agent.
        input_value (str): The input value to be processed by the agent.
        session_id (str | None, optional): The session ID to be used for the agent. Defaults to None.
        tweaks (Optional[dict], optional): Optional tweaks to be applied to the agent. Defaults to None.
        input_type (str, optional): The type of the input value. Defaults to "chat".
        output_type (str, optional): The type of the output value. Defaults to "chat".
        output_component (Optional[str], optional): The specific component to output. Defaults to None.
        log_level (Optional[str], optional): The log level to use. Defaults to None.
        log_file (Optional[str], optional): The log file to write logs to. Defaults to None.
        log_rotation (Optional[str], optional): The log rotation to use. Defaults to None.
        env_file (Optional[str], optional): The environment file to load. Defaults to None.
        cache (Optional[str], optional): The cache directory to use. Defaults to None.
        disable_logs (Optional[bool], optional): Whether to disable logs. Defaults to True.
        fallback_to_env_vars (bool, optional): Whether Global Variables should fallback to environment variables if
            not found. Defaults to False.

    Returns:
        List[RunOutputs]: A list of RunOutputs objects representing the results of running the agent.
    """
    return run_until_complete(
        arun_agent_from_json(
            agent,
            input_value,
            session_id=session_id,
            tweaks=tweaks,
            input_type=input_type,
            output_type=output_type,
            output_component=output_component,
            log_level=log_level,
            log_file=log_file,
            log_rotation=log_rotation,
            env_file=env_file,
            cache=cache,
            disable_logs=disable_logs,
            fallback_to_env_vars=fallback_to_env_vars,
        )
    )
