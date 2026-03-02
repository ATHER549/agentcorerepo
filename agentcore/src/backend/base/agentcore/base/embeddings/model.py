from agentcore.custom.custom_node.node import Node
from agentcore.field_typing import Embeddings
from agentcore.io import Output


class LCEmbeddingsModel(Node):
    trace_type = "embedding"

    outputs = [
        Output(display_name="Embedding Model", name="embeddings", method="build_embeddings"),
    ]

    def _validate_outputs(self) -> None:
        required_output_methods = ["build_embeddings"]
        output_names = [output.name for output in self.outputs]
        for method_name in required_output_methods:
            if method_name not in output_names:
                msg = f"Output with name '{method_name}' must be defined."
                raise ValueError(msg)
            if not hasattr(self, method_name):
                msg = f"Method '{method_name}' must be defined."
                raise ValueError(msg)

    def build_embeddings(self) -> Embeddings:
        msg = "You must implement the build_embeddings method in your class."
        raise NotImplementedError(msg)
