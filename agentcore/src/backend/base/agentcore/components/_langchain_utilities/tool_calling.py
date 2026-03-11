import logging

from langchain_classic.agents import create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from agentcore.base.agents.agent import LCToolsAgentNode
from agentcore.inputs.inputs import (
    DataInput,
    HandleInput,
    MessageTextInput,
)
from agentcore.schema.data import Data

logger = logging.getLogger(__name__)


class ToolCallingAgentNode(LCToolsAgentNode):
    display_name: str = "Tool Calling Agent"
    description: str = "An agent designed to utilize various tools seamlessly within workflows."
    icon = "LangChain"
    name = "ToolCallingAgent"

    inputs = [
        *LCToolsAgentNode._base_inputs,
        HandleInput(
            name="llm",
            display_name="Language Model",
            input_types=["LanguageModel"],
            required=True,
            info="Language model that the agent utilizes to perform tasks effectively.",
        ),
        MessageTextInput(
            name="system_prompt",
            display_name="System Prompt",
            info="System prompt to guide the agent's behavior.",
            value="You are a helpful assistant that can use tools to answer questions and perform tasks.",
        ),
        DataInput(
            name="chat_history",
            display_name="Chat Memory",
            is_list=True,
            advanced=True,
            info="This input stores the chat history, allowing the agent to remember previous conversations.",
        ),
    ]

    def get_chat_history_data(self) -> list[Data] | None:
        return self.chat_history

    def create_agent_runnable(self):
        # Check if we have actual tools to use
        tools = self.tools
        has_tools = bool(tools and len(tools) > 0)
        tool_names = [getattr(t, "name", str(t)) for t in (tools or [])]
        logger.info(
            "[create_agent_runnable] has_tools=%s tools=%s llm_type=%s",
            has_tools,
            tool_names,
            type(self.llm).__name__,
        )

        if has_tools:
            # Use tool-calling agent when tools are available
            messages = [
                ("system", "{system_prompt}"),
                ("placeholder", "{chat_history}"),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
            prompt = ChatPromptTemplate.from_messages(messages)
            self.validate_tool_names()
            try:
                return create_tool_calling_agent(self.llm, self.tools, prompt)
            except (NotImplementedError, ValueError) as e:
                message = f"{self.display_name} does not support tool calling. Please try using a compatible model."
                raise type(e)(message) from e
        else:
            # No tools - create a simple chain that doesn't bind tools to the LLM
            # This prevents the "Tool choice is none, but model called a tool" error
            from langchain_classic.agents.output_parsers.tools import ToolsAgentOutputParser
            from langchain_core.agents import AgentFinish
            from langchain_core.runnables import RunnableLambda
            
            messages = [
                ("system", "{system_prompt}"),
                ("placeholder", "{chat_history}"),
                ("human", "{input}"),
            ]
            prompt = ChatPromptTemplate.from_messages(messages)
            
            # Create a simple chain that returns an AgentFinish directly
            def wrap_as_agent_finish(response):
                """Wrap LLM response as AgentFinish for compatibility with AgentExecutor."""
                if hasattr(response, 'content'):
                    content = response.content
                else:
                    content = str(response)
                return AgentFinish(
                    return_values={"output": content},
                    log=content,
                )
            
            # Simple chain: prompt | llm | wrap as AgentFinish
            # Pass through agent_scratchpad but don't use it (for compatibility)
            chain = (
                RunnablePassthrough.assign(agent_scratchpad=lambda x: [])
                | prompt 
                | self.llm 
                | RunnableLambda(wrap_as_agent_finish)
            )
            return chain
